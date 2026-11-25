"""E2E ketiga preset baru terhadap ZoneMinder 1.38.6 hidup.

Dijalankan di container:
    docker exec camera-dashboard python3 /app/_e2e_new_presets.py

CATATAN AREA — penting untuk memahami angka yang diharapkan:
    Polygon layar penuh untuk monitor 1280x720 berkoordinat 0..1279 dan 0..719,
    sehingga luasnya (1280-1)*(720-1) = 1279*719 = 919601 piksel, BUKAN
    921600. Angka 919601 inilah yang tersimpan di kolom Area dan menjadi basis
    konversi persen -> piksel. Zone produksi yang sudah ada juga memakai angka
    ini, jadi perilaku di sini konsisten dengan instance.

Field luas disimpan ZM dalam PIXEL: int(pct * 919601 / 100).
"""
import sys

import app

W, H = 1280, 720
AREA = (W - 1) * (H - 1)   # 919601

# preset: CheckMethod, MinPT, MaxPT, (alarm min%, alarm max%),
#         FilterX, FilterY, (filter min%, filter max%),
#         (blob min%, blob max%), MinBlobs, MaxBlobs
SPECS = [
    ("Fast, ultra sensitivity", "AlarmedPixels", 16, 0, (3, 0), 0, 0, (0, 0), (0, 0), 0, 0),
    ("Best, balanced high sensitivity", "Blobs", 18, 0, (5, 0), 4, 4, (4, 0), (3, 0), 1, 0),
    ("Ultra, high sensitivity", "Blobs", 15, 0, (2, 85), 3, 3, (2, 85), (1, 0), 1, 0),
]

FAIL = []


def check(cond, label, detail=""):
    print(("   [OK]   " if cond else "   [FAIL] ") + label + (" " + detail if detail else ""))
    if not cond:
        FAIL.append(label + " " + detail)


def px(pct):
    return int(pct * AREA / 100)


def fresh_monitors():
    app.MONITOR_CACHE["data"] = None
    app.MONITOR_CACHE["ts"] = 0
    return app.get_all_monitors_cached() or []


def make_monitor(name):
    payload = app.build_zm138_full_payload(
        name=name,
        path="rtsp://probe:probe@127.0.0.1:554/probe",
        width=str(W),
        height=str(H),
        capturing="None",
        analysing="None",
        recording="None",
        function="None",
    )
    ok, msg, _ = app.zm_post_monitor("monitors.json", payload)
    if not ok:
        print("POST monitor gagal:", msg)
        return None
    for m in fresh_monitors():
        if m.get("name") == name:
            return m.get("id")
    return None


def run_one(preset, method, minpt, maxpt, alarm, fx, fy, filt, blob, minblobs, maxblobs):
    print("\n=== %s ===" % preset)
    name = "__e2e_" + preset.split(",")[0].strip().lower()
    for m in fresh_monitors():
        if str(m.get("name", "")).startswith("__e2e_"):
            app.zm_delete("monitors/%s.json" % m.get("id"))

    mid = make_monitor(name)
    print("monitor uji:", mid)
    if not mid:
        FAIL.append(preset + " monitor")
        return
    try:
        result = app.ensure_zone_with_preset(mid, preset, overwrite=False,
                                             width=W, height=H)
        print("ensure_zone:", {k: result.get(k) for k in
                               ("created", "skipped", "preset", "zone_id", "reason")})

        zones = app.get_monitor_zones(mid) or []
        check(len(zones) == 1, "tepat 1 zone", "dapat %d" % len(zones))
        if not zones:
            return
        z = zones[0]

        def eq(field, expected, label=None, pretty=None):
            got = z.get(field)
            ok = str(got) == str(expected)
            check(ok, label or field,
                  "%s%s" % (got, "" if ok else " (harap %s%s)" % (
                      expected, "" if pretty is None else " = %s" % pretty)))

        check(str(z.get("Name")) == "All", "Name", str(z.get("Name")))
        check(str(z.get("Type")) == "Active", "Type", str(z.get("Type")))
        check(str(z.get("Units")) == "Percent", "Units", str(z.get("Units")))
        eq("CheckMethod", method)
        eq("MinPixelThreshold", minpt)
        eq("MaxPixelThreshold", maxpt)
        eq("MinAlarmPixels", px(alarm[0]), "MinAlarmPixels", "%d%%" % alarm[0])
        eq("MaxAlarmPixels", px(alarm[1]), "MaxAlarmPixels", "%d%%" % alarm[1])
        eq("FilterX", fx)
        eq("FilterY", fy)
        eq("MinFilterPixels", px(filt[0]), "MinFilterPixels", "%d%%" % filt[0])
        eq("MaxFilterPixels", px(filt[1]), "MaxFilterPixels", "%d%%" % filt[1])
        eq("MinBlobPixels", px(blob[0]), "MinBlobPixels", "%d%%" % blob[0])
        eq("MaxBlobPixels", px(blob[1]), "MaxBlobPixels", "%d%%" % blob[1])
        eq("MinBlobs", minblobs)
        eq("MaxBlobs", maxblobs)
        eq("Area", AREA)
        eq("AlarmRGB", 16711680)
        eq("OverloadFrames", 0)
        eq("ExtendAlarmFrames", 0)
        eq("Coords", "0,0 %d,0 %d,%d 0,%d" % (W - 1, W - 1, H - 1, H - 1))
    finally:
        for zz in app.get_monitor_zones(mid) or []:
            app.zm_delete("zones/%s.json" % zz.get("Id"))
        app.zm_delete("monitors/%s.json" % mid)
        print("cleanup monitor", mid)


def main():
    for spec in SPECS:
        run_one(*spec)

    print("\n================ RINGKASAN ================")
    left = [m for m in fresh_monitors() if str(m.get("name", "")).startswith("__e2e_")]
    print("monitor uji tersisa:", [(m.get("id"), m.get("name")) for m in left])
    print("monitor produksi:", [(m.get("id"), m.get("name")) for m in fresh_monitors()])
    if FAIL:
        print("GAGAL:", len(FAIL))
        for f in FAIL:
            print("  -", f)
        return 1
    print("SEMUA FIELD COCOK SPESIFIKASI")
    return 0


if __name__ == "__main__":
    sys.exit(main())
