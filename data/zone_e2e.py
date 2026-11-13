"""Uji end-to-end logika zone terhadap ZoneMinder yang benar-benar berjalan.

Dijalankan DI DALAM container camera-dashboard. Skrip ini hanya menyentuh
monitor uji yang dibuatnya sendiri, dan menghapusnya kembali di akhir —
kamera produksi tidak pernah disentuh.
"""
import json
import sys

sys.path.insert(0, "/app")

import app as dash  # noqa: E402

TEST_NAME = "ZZ_ZONE_E2E_TEST"

FAILURES = []
CHECKS = []


def check(label, condition, detail=""):
    CHECKS.append((label, bool(condition), detail))
    if not condition:
        FAILURES.append(label + " :: " + str(detail))
    print("  [" + ("PASS" if condition else "FAIL") + "] " + label
          + (" -- " + str(detail) if detail else ""))


def zm_send(method, path, data=None):
    """Request mentah ke ZoneMinder dengan token yang benar."""
    session, token = dash.zm_authenticated_session()
    url = dash.ZM_BASE_URL + "/" + path
    params = {"token": token} if token else {}
    return session.request(method, url, params=params, data=data, timeout=15)


def cleanup_test_monitors():
    """Hapus semua monitor bernama TEST_NAME beserta zone-nya."""
    data = dash.zm_api_get("monitors.json")
    if not isinstance(data, dict):
        return 0
    removed = 0
    for item in data.get("monitors", []):
        m = item.get("Monitor", item)
        if isinstance(m, dict) and m.get("Name") == TEST_NAME:
            zm_send("DELETE", "monitors/" + str(m.get("Id")) + ".json")
            removed += 1
    return removed


def main():
    print("=" * 78)
    print("UJI END-TO-END ZONE DETEKSI -- 5 MODE")
    print("=" * 78)

    print("\n[0] Prasyarat: koneksi ZoneMinder")
    token = dash.zm_login_session()
    check("Autentikasi ZoneMinder berhasil", token is not None,
          "token=" + ("ada" if token else "KOSONG"))
    if token is None:
        print("\nTidak dapat melanjutkan tanpa autentikasi ZM.")
        return 1

    print("\n[1] Bersihkan sisa monitor uji (bila ada)")
    print("  monitor uji lama dihapus: " + str(cleanup_test_monitors()))

    print("\n[2] Payload kelima mode")
    variants = {}
    for key, spec in dash.ZONE_MODES.items():
        p = dash.build_zone_payload(key, 1920, 1080)
        variants[key] = p
        print("  %-9s CheckMethod=%-15s MinPixelThreshold=%3s MinAlarmPixels=%3s MinBlobPixels=%3s"
              % (key, p["Zone[CheckMethod]"], p["Zone[MinPixelThreshold]"],
                 p["Zone[MinAlarmPixels]"], p.get("Zone[MinBlobPixels]", "-")))

    check("5 mode terdefinisi", len(variants) == 5, str(len(variants)) + " mode")
    check("Koordinat layar penuh memakai W-1/H-1",
          variants["medium"]["Zone[Coords]"] == "0 0 1919 0 1919 1079 0 1079",
          variants["medium"]["Zone[Coords]"])
    check("NumCoords = 4 untuk poligon layar penuh",
          variants["medium"]["Zone[NumCoords]"] == "4")
    check("Area = W*H", variants["medium"]["Zone[Area]"] == str(1920 * 1080),
          variants["medium"]["Zone[Area]"])
    check("AlarmRGB = 16711680 (merah penuh)",
          variants["medium"]["Zone[AlarmRGB]"] == "16711680")
    check("Semua mode memakai Units=Percent",
          all(p["Zone[Units]"] == "Percent" for p in variants.values()))
    check("Paling Ringan memakai AlarmedPixels (paling hemat CPU)",
          variants["lightest"]["Zone[CheckMethod]"] == "AlarmedPixels")
    check("Paling Berat memakai Blobs (paling akurat)",
          variants["heaviest"]["Zone[CheckMethod]"] == "Blobs")
    check("Mode berbeda menghasilkan parameter berbeda",
          len(set(json.dumps(p, sort_keys=True) for p in variants.values())) == 5)
    check("Field NULL tidak dikirim sebagai string None",
          not any("None" in str(v) for p in variants.values() for v in p.values()))

    print("\n[3] Daftarkan monitor uji ke ZoneMinder")
    cleanup_test_monitors()
    res = zm_send("POST", "monitors.json", {
        "Monitor[Name]": TEST_NAME,
        "Monitor[Type]": "Ffmpeg",
        "Monitor[Function]": "Modect",
        "Monitor[Enabled]": "1",
        "Monitor[Path]": "rtsp://127.0.0.1:9/none",
        "Monitor[Method]": "rtsp",
        "Monitor[Options]": "rtsp_transport=tcp",
        "Monitor[Width]": "1920",
        "Monitor[Height]": "1080",
        "Monitor[Colours]": "4",
        "Monitor[TargetColorspace]": "4",
        "Monitor[ServerId]": "0",
    })
    check("Monitor uji dibuat", res.status_code in (200, 201),
          "HTTP " + str(res.status_code))

    monitors = dash.zm_api_get("monitors.json")
    mon_id = None
    for item in (monitors or {}).get("monitors", []):
        m = item.get("Monitor", item)
        if isinstance(m, dict) and m.get("Name") == TEST_NAME:
            mon_id = str(m.get("Id"))
    check("ID monitor uji ditemukan", mon_id is not None, "id=" + str(mon_id))
    if not mon_id:
        cleanup_test_monitors()
        return 1

    zones_before = dash.get_monitor_zones(mon_id)
    check("Monitor baru belum punya zone (masalah aslinya)",
          zones_before == [], "zones=" + str(zones_before))

    print("\n[4] Buat zone dengan mode medium")
    r1 = dash.ensure_zone_for_monitor(mon_id, mode_key="medium")
    print("  hasil: " + json.dumps(r1, ensure_ascii=False))
    check("Zone berhasil dibuat", r1.get("created") is True, r1.get("reason", ""))

    zones_after = dash.get_monitor_zones(mon_id)
    check("Zone terbaca kembali dari ZoneMinder",
          isinstance(zones_after, list) and len(zones_after) == 1,
          "jumlah=" + str(len(zones_after) if zones_after else zones_after))

    if zones_after:
        z = zones_after[0]
        print("  zone tersimpan: name=%s type=%s units=%s check=%s coords=%s"
              % (z.get("Name"), z.get("Type"), z.get("Units"),
                 z.get("CheckMethod"), z.get("Coords")))
        check("Nama zone = All", str(z.get("Name")) == "All")
        check("Type = Active (zone benar-benar dievaluasi)",
              str(z.get("Type")) == "Active")
        check("CheckMethod = Blobs sesuai mode medium",
              str(z.get("CheckMethod")) == "Blobs")
        check("MinPixelThreshold = 25 sesuai mode medium",
              str(z.get("MinPixelThreshold")) == "25",
              "nilai=" + str(z.get("MinPixelThreshold")))
        check("Koordinat menutupi seluruh frame 1920x1080",
              str(z.get("Coords")) == "0 0 1919 0 1919 1079 0 1079",
              "coords=" + str(z.get("Coords")))

    print("\n[5] Idempotensi: panggil ulang TANPA overwrite")
    r2 = dash.ensure_zone_for_monitor(mon_id, mode_key="medium")
    print("  hasil: " + json.dumps(r2, ensure_ascii=False))
    check("Panggilan kedua dilewati (tidak menimpa)",
          r2.get("skipped") is True and r2.get("created") is False)
    zones_dup = dash.get_monitor_zones(mon_id)
    check("Tidak ada zone duplikat",
          isinstance(zones_dup, list) and len(zones_dup) == 1,
          "jumlah=" + str(len(zones_dup) if zones_dup else zones_dup))

    print("\n[6] Ganti mode dengan overwrite=True -> zone lama diganti")
    r3 = dash.ensure_zone_for_monitor(mon_id, mode_key="lightest", overwrite=True)
    print("  hasil: " + json.dumps(r3, ensure_ascii=False))
    zones_new = dash.get_monitor_zones(mon_id)
    check("Tetap hanya 1 zone setelah ganti mode",
          isinstance(zones_new, list) and len(zones_new) == 1,
          "jumlah=" + str(len(zones_new) if zones_new else zones_new))
    if zones_new:
        check("CheckMethod berubah ke AlarmedPixels",
              str(zones_new[0].get("CheckMethod")) == "AlarmedPixels",
              "nilai=" + str(zones_new[0].get("CheckMethod")))
        check("MinPixelThreshold berubah ke 60",
              str(zones_new[0].get("MinPixelThreshold")) == "60",
              "nilai=" + str(zones_new[0].get("MinPixelThreshold")))

    print("\n[7] Perlindungan konfigurasi manual pengguna")
    # Endpoint bersarang /monitors/{id}/zones.json membalas 404 pada
    # ZoneMinder 1.36 (diperiksa langsung), jadi zone manual dibuat
    # lewat /zones.json dengan MonitorId di dalam body. Status code
    # WAJIB diperiksa: tanpa itu kegagalan pembuatan zone manual tidak
    # terlihat dan pemeriksaan berikutnya gagal tanpa sebab yang jelas.
    manual_res = zm_send("POST", "zones.json", {
        "Zone[MonitorId]": mon_id,
        "Zone[Name]": "Area_Pintu_Manual",
        "Zone[Type]": "Active",
        "Zone[Units]": "Pixels",
        "Zone[NumCoords]": "4",
        "Zone[Coords]": "10 10 200 10 200 200 10 200",
        "Zone[Area]": "36100",
        "Zone[AlarmRGB]": "255",
        "Zone[CheckMethod]": "Blobs",
        "Zone[MinPixelThreshold]": "25",
    })
    zones_manual = dash.get_monitor_zones(mon_id)
    check("POST zone manual diterima ZoneMinder",
          manual_res.status_code in (200, 201),
          "HTTP " + str(manual_res.status_code) + " " + manual_res.text[:120])

    check("Zone manual berhasil ditambahkan",
          isinstance(zones_manual, list) and len(zones_manual) == 2,
          "jumlah=" + str(len(zones_manual) if zones_manual else zones_manual))

    r4 = dash.ensure_zone_for_monitor(mon_id, mode_key="heavy")
    check("Dianggap sudah punya zone -> dilewati",
          r4.get("skipped") is True, r4.get("reason", ""))

    dash.ensure_zone_for_monitor(mon_id, mode_key="heaviest", overwrite=True)
    zones_mixed = dash.get_monitor_zones(mon_id) or []
    names = sorted(str(z.get("Name")) for z in zones_mixed)
    print("  zone setelah overwrite: " + str(names))
    check("Zone manual Area_Pintu_Manual TETAP ADA (tidak dihapus)",
          "Area_Pintu_Manual" in names, "names=" + str(names))
    check("Jumlah zone tetap 2 (1 manual + 1 dashboard)",
          len(zones_mixed) == 2, "jumlah=" + str(len(zones_mixed)))
    auto_zone = None
    for z in zones_mixed:
        if str(z.get("Name")) == "All":
            auto_zone = z
    check("Zone dashboard memakai mode heaviest (MinPixelThreshold=20)",
          auto_zone is not None and str(auto_zone.get("MinPixelThreshold")) == "20",
          "nilai=" + str(auto_zone.get("MinPixelThreshold") if auto_zone else "tidak ada"))

    print("\n[8] Mode tidak valid ditolak, bukan gagal diam-diam")
    check("normalize_zone_mode(None) -> default",
          dash.normalize_zone_mode(None) == dash.ZONE_MODE_DEFAULT)
    check("normalize_zone_mode('Paling Berat') -> heaviest",
          dash.normalize_zone_mode("Paling Berat") == "heaviest")
    check("normalize_zone_mode('ngawur') -> None",
          dash.normalize_zone_mode("ngawur") is None)
    r6 = dash.ensure_zone_for_monitor(mon_id, mode_key="ngawur")
    check("Mode ngawur dilaporkan sebagai kesalahan",
          r6.get("skipped") is True and "tidak dikenali" in r6.get("reason", ""),
          r6.get("reason", ""))

    print("\n[9] Bersihkan monitor uji")
    removed = cleanup_test_monitors()
    check("Monitor uji terhapus", removed >= 1, "dihapus=" + str(removed))
    dash.MONITOR_CACHE["ts"] = 0
    remaining = [m for m in dash.get_all_monitors_cached() if m["name"] == TEST_NAME]
    check("Tidak ada monitor uji yang tertinggal", len(remaining) == 0)

    print("\n" + "=" * 78)
    passed = sum(1 for _, ok, _ in CHECKS if ok)
    print("HASIL: %d/%d pemeriksaan lulus" % (passed, len(CHECKS)))
    if FAILURES:
        print("\n%d KEGAGALAN:" % len(FAILURES))
        for f in FAILURES:
            print("  - " + f)
        return 1
    print("SEMUA PEMERIKSAAN LULUS -- fitur zone 5 mode terverifikasi.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
