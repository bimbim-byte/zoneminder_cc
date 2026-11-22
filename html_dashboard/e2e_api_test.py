"""Uji end-to-end jalur API dashboard terhadap ZoneMinder 1.38.6 yang HIDUP.

Dijalankan DI DALAM container camera-dashboard:
    docker exec camera-dashboard python /app/e2e_api_test.py

Yang diuji (lewat endpoint dashboard, bukan curl langsung):
  1. Tambah kamera + zone otomatis -> kamera & zone benar-benar ada di ZM.
  2. Edit kamera                   -> perubahan benar-benar tersimpan.
  3. Hapus kamera uji              -> bersih kembali.

Setiap langkah memverifikasi STATE di ZoneMinder, bukan sekadar pesan sukses.
"""
import json
import os
import sys

import requests

ZM = os.environ.get("ZM_HOST", "http://zoneminder:80")

sys.path.insert(0, "/app")
import app as dash  # noqa: E402

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
    r = requests.get(ZM + "/zm/api/" + path, params={"token": t}, timeout=15)
    try:
        return r.json()
    except Exception:
        return {}


def zm_post(path, data):
    t = dash.get_zm_token()
    r = requests.post(ZM + "/zm/api/" + path, params={"token": t}, data=data, timeout=15)
    try:
        return r.json()
    except Exception:
        return {}


def zm_delete(path):
    t = dash.get_zm_token()
    r = requests.delete(ZM + "/zm/api/" + path, params={"token": t}, timeout=15)
    try:
        return r.json()
    except Exception:
        return {}


def find_monitor(name):
    """Cari monitor AKTIF berdasarkan nama.

    ZoneMinder memakai soft-delete: monitor lama tetap muncul di
    monitors.json dengan Deleted=true. Tanpa menyaringnya, pembacaan bisa
    mengenai baris sisa run sebelumnya dan membuat pengujian nilai gagal.
    Bila ada beberapa baris, pakai Id terbesar (paling baru).
    """
    data = zm_get("monitors.json")
    found = None
    for item in data.get("monitors", []) or []:
        m = item.get("Monitor", item)
        if str(m.get("Name")) != name:
            continue
        if str(m.get("Deleted", "0")).lower() in ("1", "true"):
            continue
        if found is None or int(m.get("Id", 0)) > int(found.get("Id", 0)):
            found = m
    return found


print("=" * 66)
print("E2E: jalur API dashboard -> ZoneMinder 1.38.6")
print("=" * 66)

NAME = "E2E_TESTCAM"
PATH = "rtsp://operator:0p3r@t0r@10.121.10.145:554/Streaming/Channels/101"

# Bersihkan SEMUA sisa percobaan sebelumnya (ZM soft-delete, jadi baris lama
# tetap terbaca API). Tanpa ini, run kedua menemukan monitor lama dan
# pengujian "FPS default 8" gagal karena membaca nilai run sebelumnya.
for m in list(zm_get("monitors.json").get("monitors", []) or []):
    mm = m.get("Monitor", m)
    if str(mm.get("Name")) == NAME:
        zm_delete("monitors/" + str(mm.get("Id")) + ".json")

print("")
print("[1] Tambah kamera + zone otomatis")
c = client()
r = c.post("/api/zones/save-camera", json={
    "name": NAME,
    "path": PATH,
    "width": "1280",
    "height": "720",
    "function": "Monitor",
    "analysisFps": 8,
    "zoneMode": "medium",
    "createZone": True,
})
print("     HTTP " + str(r.status_code))
body = r.get_json() or {}
print("     status=" + str(body.get("status")) + " monitor_id=" + str(body.get("monitor_id")))
print("     zone=" + json.dumps(body.get("zone", {}))[:170])

if r.status_code == 200 and body.get("status") == "success":
    ok("endpoint melaporkan sukses")
else:
    bad("endpoint gagal: " + str(body.get("message")))

mon = find_monitor(NAME)
if mon:
    ok("monitor ADA di ZoneMinder (Id=" + str(mon.get("Id")) + ")")
else:
    bad("monitor TIDAK ADA di ZoneMinder")

if mon:
    fps = mon.get("AnalysisFPSLimit")
    if str(fps) in ("8", "8.0", "8.00"):
        ok("AnalysisFPSLimit=" + str(fps))
    else:
        bad("AnalysisFPSLimit=" + str(fps) + " (harus 8)")

    if mon.get("Method") == "rtpRtsp":
        ok("Method=rtpRtsp")
    else:
        bad("Method=" + str(mon.get("Method")) + " (harus rtpRtsp)")

    stored = str(mon.get("Path", ""))
    if stored.count("@") == 1:
        ok("Path bersih: " + stored)
    else:
        bad("Path masih korup (" + str(stored.count("@")) + " '@'): " + stored)

    mid = mon.get("Id")
    zlist = zm_get("zones.json")
    zones = zlist.get("zones", []) if isinstance(zlist, dict) else []
    mine = [z.get("Zone", z) for z in zones
            if str(z.get("Zone", z).get("MonitorId")) == str(mid)]
    if mine:
        ok("zone terdeteksi: " + str(len(mine)) + " buah (Coords=" + str(mine[0].get("Coords")) + ")")
    else:
        bad("TIDAK ADA zone untuk monitor ini -> Modect tidak akan pernah alarm")

    print("")
    print("[2] Edit kamera (Function -> Modect, FPS -> 5)")
    r = c.post("/api/zones/save-camera", json={
        "id": str(mid),
        "name": NAME,
        "path": PATH,
        "width": "1280",
        "height": "720",
        "function": "Modect",
        "analysisFps": 5,
        "createZone": False,
    })
    print("     HTTP " + str(r.status_code) + " body=" + str(r.get_json())[:140])
    if r.status_code == 200:
        ok("endpoint edit melaporkan sukses")
    else:
        bad("edit gagal: " + str((r.get_json() or {}).get("message")))

    mon2 = find_monitor(NAME)
    if mon2 and mon2.get("Function") == "Modect":
        ok("Function berubah menjadi Modect di ZoneMinder")
    else:
        bad("Function tidak berubah: " + str(mon2.get("Function") if mon2 else "monitor hilang"))

    if mon2 and str(mon2.get("AnalysisFPSLimit")) in ("5", "5.0", "5.00"):
        ok("AnalysisFPSLimit berubah menjadi 5")
    else:
        bad("AnalysisFPSLimit tidak berubah: " + str(mon2.get("AnalysisFPSLimit") if mon2 else "-"))

    print("")
    print("[3] Hapus kamera uji")
    # ZM melakukan SOFT DELETE (Deleted=1), jadi monitor memang masih bisa
    # terbaca API. Yang menentukan adalah baris di database: pastikan
    # monitor benar-benar dihapus, bukan sekadar dikosongkan.
    zm_delete("monitors/" + str(mid) + ".json")
    row = dash.zm_api_get("monitors/" + str(mid) + ".json")
    m = dash._unwrap_zm(row, "monitor", "Monitor") if isinstance(row, dict) else None
    if not m:
        ok("monitor uji sudah tidak ada (hard delete)")
    elif str(m.get("Deleted")) in ("1", "True", "true"):
        ok("monitor uji dihapus (Deleted=1, soft delete sesuai perilaku ZM)")
    else:
        bad("monitor uji MASIH ADA dan belum ditandai hapus: " + str(m.get("Deleted")))

print("")
print("=" * 66)
print("LULUS: " + str(PASS) + "   GAGAL: " + str(FAIL))
print("SEMUA PEMERIKSAAN E2E LULUS" if FAIL == 0 else "ADA YANG GAGAL")
sys.exit(0 if FAIL == 0 else 1)
