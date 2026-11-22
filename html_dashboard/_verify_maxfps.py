"""Bukti bahwa jalur TAMBAH kamera sekarang mengisi MaxFPS (batas capture).

Dijalankan DI DALAM container camera-dashboard:
    docker exec camera-dashboard python /app/_verify_maxfps.py

Kenapa file ini ada:
    Sebelumnya Monitor[MaxFPS] sengaja TIDAK dikirim. Akibatnya kolom MaxFPS
    NULL dan zmc menelan stream secepat laju asli kamera (terukur 14.98 dan
    25.10 fps pada kamera 25 fps, padahal target 10 fps untuk 60 kamera).

    Uji ini membuat satu monitor uji lewat endpoint dashboard yang SAMA dengan
    tombol "Tambah Kamera", memeriksa nilai yang benar-benar tersimpan di
    ZoneMinder, lalu menghapusnya kembali.
"""
import sys

import requests

sys.path.insert(0, "/app")
import app as dash  # noqa: E402

ZM = dash.ZM_HOST
TEST_NAME = "ZZ_MAXFPS_TEST"

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


def find(name):
    for item in zm_get("monitors.json").get("monitors", []) or []:
        m = item.get("Monitor", item)
        if str(m.get("Name")) == name:
            return m
    return None


def cleanup(mid):
    if not mid:
        return
    t = dash.get_zm_token()
    requests.delete(ZM + "/zm/api/monitors/%s.json" % mid,
                    params={"token": t}, timeout=20)


def main():
    print("=" * 66)
    print("Bukti: tambah kamera mengirim MaxFPS (batas capture)")
    print("=" * 66)

    stale = find(TEST_NAME)
    if stale:
        cleanup(stale.get("Id"))
        print("(membersihkan sisa uji sebelumnya)")

    c = client()
    body = {
        "name": TEST_NAME,
        "path": "rtsp://127.0.0.1:9/none",
        "analysisFps": 8,
        "createZone": False,
    }
    r = c.post("/api/zones/save-camera", json=body)
    print("\nHTTP %s: %s\n" % (r.status_code, r.text[:200]))

    m = find(TEST_NAME)
    if not m:
        bad("monitor uji tidak tercipta")
        return 1

    mid = m.get("Id")
    try:
        for field, want in (("MaxFPS", "10.00"), ("AlarmMaxFPS", "10.00"),
                            ("AnalysisFPSLimit", "8.00")):
            got = str(m.get(field))
            if got in (want, want.rstrip("0").rstrip(".")):
                ok("%s = %s (tersimpan di ZM)" % (field, got))
            else:
                bad("%s = %r (harus %r)" % (field, got, want))
    finally:
        cleanup(mid)
        left = find(TEST_NAME)
        # ZoneMinder melakukan SOFT delete: baris TETAP ada dengan Deleted=1.
        # Jadi yang diperiksa adalah flag Deleted, bukan hilangnya baris.
        if not left:
            ok("monitor uji sudah tidak terdaftar")
        elif str(left.get("Deleted")) in ("1", "True", "true"):
            ok("monitor uji ditandai Deleted=1 (soft delete ZM)")
        else:
            bad("monitor uji masih aktif (Id=%s)" % left.get("Id"))

    print("\n" + "=" * 66)
    print("LULUS: %d   GAGAL: %d" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
