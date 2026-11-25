"""E2E dua jalur produksi untuk 3 preset baru: burst-add (Excel) dan save-camera.

Dijalankan di container:
    docker exec camera-dashboard python3 /app/_e2e_paths.py

Burst-add diuji lewat HTTP ke aplikasi Flask sungguhan (bukan memanggil fungsi
internal), karena di situlah kolom Excel "Zone Preset" dan preset panel dibaca.
Monitor uji berawalan __e2e dan dihapus di akhir.
"""
import json
import sys

import app

W, H = 1280, 720
AREA = (W - 1) * (H - 1)

CASES = [
    ("Fast, ultra sensitivity", "AlarmedPixels", 16, (3, 0), 0, 0, (0, 0), (0, 0), 0),
    ("Best, balanced high sensitivity", "Blobs", 18, (5, 0), 4, 4, (4, 0), (3, 0), 1),
    ("Ultra, high sensitivity", "Blobs", 15, (2, 85), 3, 3, (2, 85), (1, 0), 1),
]

FAIL = []


def check(cond, label, detail=""):
    print(("   [OK]   " if cond else "   [FAIL] ") + label + (" " + detail if detail else ""))
    if not cond:
        FAIL.append(label + " " + detail)


def px(pct):
    return int(pct * AREA / 100)


def fresh():
    app.MONITOR_CACHE["data"] = None
    app.MONITOR_CACHE["ts"] = 0
    return app.get_all_monitors_cached() or []


def purge():
    for m in fresh():
        if str(m.get("name", "")).startswith("__e2e"):
            app.zm_delete("monitors/%s.json" % m.get("id"))


def client():
    app.app.config["TESTING"] = True
    c = app.app.test_client()
    with c.session_transaction() as sess:
        sess["user"] = "admin"
        sess["username"] = "admin"
        sess["logged_in"] = True
    return c


def find_id(name):
    for m in fresh():
        if m.get("name") == name:
            return m.get("id")
    return None


def verify_zone(mid, method, minpt, alarm, fx, fy, filt, blob, minblobs):
    zones = app.get_monitor_zones(mid) or []
    check(len(zones) == 1, "tepat 1 zone", "dapat %d" % len(zones))
    if not zones:
        return
    z = zones[0]

    def eq(field, expected, label=None):
        got = z.get(field)
        ok = str(got) == str(expected)
        check(ok, label or field, "%s%s" % (got, "" if ok else " (harap %s)" % expected))

    eq("CheckMethod", method)
    eq("MinPixelThreshold", minpt)
    eq("MaxPixelThreshold", 0)
    eq("MinAlarmPixels", px(alarm[0]), "MinAlarmPixels %d%%" % alarm[0])
    eq("MaxAlarmPixels", px(alarm[1]), "MaxAlarmPixels %d%%" % alarm[1])
    eq("FilterX", fx)
    eq("FilterY", fy)
    eq("MinFilterPixels", px(filt[0]), "MinFilterPixels %d%%" % filt[0])
    eq("MaxFilterPixels", px(filt[1]), "MaxFilterPixels %d%%" % filt[1])
    eq("MinBlobPixels", px(blob[0]), "MinBlobPixels %d%%" % blob[0])
    eq("MaxBlobPixels", px(blob[1]), "MaxBlobPixels %d%%" % blob[1])
    eq("MinBlobs", minblobs)
    eq("MaxBlobs", 0)
    eq("Area", AREA)
    eq("Units", "Percent")
    eq("AlarmRGB", 16711680)


def main():
    purge()
    c = client()

    print("\n########## JALUR 1: burst-add (impor Excel / per-baris) ##########")
    for preset, method, minpt, alarm, fx, fy, filt, blob, minblobs in CASES:
        print("\n=== %s ===" % preset)
        name = "__e2e_burst_" + preset.split(",")[0].strip().lower()
        body = {
            "createZone": True,
            "zonePreset": preset,
            "monitors": [{
                "Name": name,
                "Path": "rtsp://probe:probe@127.0.0.1:554/probe",
                "Capturing": "None", "Analysing": "None", "Recording": "None",
                "Width": str(W), "Height": str(H),
                "Zone Preset": preset,
            }],
        }
        res = c.post("/api/zoneminder/burst-add", json=body)
        print("HTTP", res.status_code)
        data = res.get_json() or {}
        row = (data.get("details") or [{}])[0]
        print("row:", json.dumps({k: row.get(k) for k in
                                  ("name", "status", "zone", "zone_preset", "zone_reason")}))
        check(res.status_code == 200, "HTTP 200", str(res.status_code))
        check(row.get("status") == "success", "monitor sukses", str(row.get("status")))
        check(row.get("zone") == "created", "zone dibuat", str(row.get("zone")))
        mid = find_id(name)
        if mid:
            verify_zone(mid, method, minpt, alarm, fx, fy, filt, blob, minblobs)
        else:
            FAIL.append(preset + " monitor burst tidak ditemukan")

    purge()

    print("\n########## JALUR 2: save-camera (Kelola Kamera) ##########")
    for preset, method, minpt, alarm, fx, fy, filt, blob, minblobs in CASES:
        print("\n=== %s ===" % preset)
        name = "__e2e_save_" + preset.split(",")[0].strip().lower()
        body = {
            "name": name,
            "path": "rtsp://probe:probe@127.0.0.1:554/probe",
            "function": "Monitor",
            "width": str(W), "height": str(H),
            "createZone": True,
            "zonePreset": preset,
        }
        res = c.post("/api/zones/save-camera", json=body)
        print("HTTP", res.status_code)
        data = res.get_json() or {}
        zinfo = data.get("zone")
        print("zone:", json.dumps(zinfo if isinstance(zinfo, dict)
                                  else {k: data.get(k) for k in ("status", "message")}))
        check(res.status_code == 200, "HTTP 200", str(res.status_code))
        mid = find_id(name)
        if mid:
            verify_zone(mid, method, minpt, alarm, fx, fy, filt, blob, minblobs)
        else:
            FAIL.append(preset + " monitor save-camera tidak ditemukan")

    purge()
    print("\n================ RINGKASAN ================")
    print("monitor tersisa:", [(m.get("id"), m.get("name")) for m in fresh()])
    if FAIL:
        print("GAGAL:", len(FAIL))
        for f in FAIL:
            print("  -", f)
        return 1
    print("KEDUA JALUR COCOK SPESIFIKASI")
    return 0


if __name__ == "__main__":
    sys.exit(main())
