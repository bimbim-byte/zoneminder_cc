"""Daftarkan ulang CAM_SQ_01 dan CAM_SQ_02 lewat API dashboard (jalur operator).

Dijalankan DI DALAM container camera-dashboard:
    docker exec -e CAM_PASS=... camera-dashboard python /app/scripts/recreate_cameras.py

Kenapa file ini ada:
    Tabel Monitors sempat kosong (dua monitor hilang). Alih-alih INSERT manual
    ke database — yang akan melewati validasi CakePHP dan berisiko mengulang
    bug lama (Method='rtsp', Options='rtsp_transport=tcp') — skrip ini memakai
    endpoint /api/zones/save-camera yang SUDAH diperbaiki, sehingga hasilnya
    persis sama dengan menambah kamera dari halaman dashboard.

Sumber kebenaran URL: backups/zm_pre_138.sql (baris Monitors sebelum migrasi).
Kredensial dibaca dari env supaya tidak tertulis di skrip.
"""
import os
import sys

import requests

sys.path.insert(0, "/app")
import app as dash  # noqa: E402

ZM = os.environ.get("ZM_HOST", "http://zoneminder:80")

CAM_USER = os.environ.get("CAM_USER", "operator")
CAM_PASS = os.environ.get("CAM_PASS", "")

# Host:port/channel dari backup, urut sesuai Id lama (1 dan 2).
CAMERAS = [
    {"name": "CAM_SQ_01", "host": "10.121.10.145:554", "channel": "Streaming/Channels/101"},
    {"name": "CAM_SQ_02", "host": "10.121.10.148:554", "channel": "Streaming/Channels/101"},
]

PASS, FAIL = 0, 0


def ok(msg):
    global PASS
    PASS += 1
    print("  [OK]   " + msg)


def bad(msg):
    global FAIL
    FAIL += 1
    print("  [FAIL] " + msg)


def client():
    c = dash.app.test_client()
    with c.session_transaction() as sess:
        sess["user"] = "tester"
    return c


def zm_get(path):
    t = dash.get_zm_token()
    r = requests.get(ZM + "/zm/api/" + path, params={"token": t}, timeout=20)
    try:
        return r.json()
    except Exception:
        return {}


def all_monitors():
    data = zm_get("monitors.json")
    out = {}
    for item in data.get("monitors", []) or []:
        m = item.get("Monitor", item)
        if m.get("Name"):
            out[str(m.get("Name"))] = m
    return out


def main():
    if not CAM_PASS:
        print("GAGAL: CAM_PASS kosong. Isi lewat -e CAM_PASS=... pada docker exec.")
        return 2

    print("=" * 70)
    print("Daftarkan ulang kamera lewat /api/zones/save-camera")
    print("=" * 70)

    c = client()
    existing = all_monitors()
    print("\nMonitor yang ada sekarang: %s\n" % (sorted(existing) or "(kosong)"))

    for cam in CAMERAS:
        url = "rtsp://%s/%s" % (cam["host"], cam["channel"])
        print("[%s] %s" % (cam["name"], url))

        body = {
            "name": cam["name"],
            "path": url,
            "username": CAM_USER,
            "password": CAM_PASS,
            "width": "1280",
            "height": "720",
            "function": "Monitor",
            "analysisFps": 8,
            "zoneMode": "medium",
            "createZone": True,
            "overwriteZone": False,
        }
        # Bila monitor sudah ada, kirim sebagai EDIT supaya tidak duplikat.
        if cam["name"] in existing:
            body["id"] = str(existing[cam["name"]].get("Id"))
            print("    (sudah ada -> mode EDIT)")

        r = c.post("/api/zones/save-camera", json=body)
        print("    HTTP %s: %s" % (r.status_code, r.text[:300]))

        if r.status_code != 200:
            bad("%s: simpan gagal" % cam["name"])
            continue
        ok("%s: dashboard menerima penyimpanan" % cam["name"])

    print("\n" + "=" * 70)
    print("Verifikasi state di ZoneMinder")
    print("=" * 70)
    final = all_monitors()
    for cam in CAMERAS:
        m = final.get(cam["name"])
        if not m:
            bad("%s: TIDAK ADA di ZoneMinder" % cam["name"])
            continue
        print("\n  %s (Id=%s)" % (cam["name"], m.get("Id")))
        checks = [
            ("Method", str(m.get("Method")), "rtpRtsp"),
            ("Options", str(m.get("Options")), "timeout=5000000"),
            ("Type", str(m.get("Type")), "Ffmpeg"),
            ("Width", str(m.get("Width")), "1280"),
            ("Height", str(m.get("Height")), "720"),
        ]
        for label, got, want in checks:
            if got == want:
                ok("%s = %s" % (label, got))
            else:
                bad("%s = %r (harus %r)" % (label, got, want))

        fps = str(m.get("AnalysisFPSLimit"))
        if fps in ("8", "8.0", "8.00"):
            ok("AnalysisFPSLimit = %s" % fps)
        else:
            bad("AnalysisFPSLimit = %r (harus 8)" % fps)

        path = str(m.get("Path") or "")
        raw_at = path.count("@")
        if raw_at == 1:
            ok("Path punya tepat 1 '@'")
        else:
            bad("Path punya %d '@' -> kredensial ambigu: %s" % (raw_at, path))

        if "rtsp_transport" in str(m.get("Options") or ""):
            bad("Options memuat rtsp_transport")
        else:
            ok("Options bersih dari rtsp_transport")

    print("\n" + "=" * 70)
    print("LULUS: %d   GAGAL: %d" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
