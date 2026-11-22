"""Uji jalur burst-add massal terhadap ZoneMinder 1.38.6.

    docker exec camera-dashboard python /app/burst_api_test.py

Burst memakai kode berbeda dari save-camera, jadi jalur ini wajib diuji
terpisah: satu bug di sini berarti SEMUA kamera dalam daftar gagal sekaligus.
"""
import json
import sys

import requests

ZM = "http://zoneminder:80"

sys.path.insert(0, "/app")
import app as dash  # noqa: E402

PASS, FAIL = 0, 0


def ok(m):
    global PASS
    PASS += 1
    print("  [OK]   " + m)


def bad(m):
    global FAIL
    FAIL += 1
    print("  [FAIL] " + m)


def zm_get(path):
    t = dash.get_zm_token()
    r = requests.get(ZM + "/zm/api/" + path, params={"token": t}, timeout=15)
    try:
        return r.json()
    except Exception:
        return {}


def zm_delete(path):
    t = dash.get_zm_token()
    requests.delete(ZM + "/zm/api/" + path, params={"token": t}, timeout=15)


def monitors_named(name):
    out = []
    for item in zm_get("monitors.json").get("monitors", []) or []:
        m = item.get("Monitor", item)
        if str(m.get("Name")) == name:
            out.append(m)
    return out


NAMES = ["BURST_TEST_1", "BURST_TEST_2"]

for n in NAMES:
    for m in monitors_named(n):
        zm_delete("monitors/" + str(m.get("Id")) + ".json")

print("=" * 66)
print("Uji burst-add: dua kamera sekaligus")
print("=" * 66)

c = dash.app.test_client()
with c.session_transaction() as sess:
    sess["user"] = "tester"

r = c.post("/api/zoneminder/burst-add", json={
    "monitors": [
        {"Name": NAMES[0], "Path": "rtsp://10.121.10.145:554/Streaming/Channels/101"},
        {"Name": NAMES[1], "Path": "rtsp://10.121.10.148:554/Streaming/Channels/101"},
    ],
    "zoneMode": "light",
    "createZone": True,
})

print("")
print("HTTP " + str(r.status_code))
body = r.get_json() or {}
print("status=" + str(body.get("status")))
print("success_count=" + str(body.get("success_count")) + " fail_count=" + str(body.get("fail_count")))
for item in (body.get("results") or [])[:4]:
    print("  - " + json.dumps(item)[:150])

print("")
if body.get("success_count") == 2:
    ok("kedua kamera dilaporkan sukses")
else:
    bad("success_count=" + str(body.get("success_count")) + " (harus 2)")

for n in NAMES:
    got = monitors_named(n)
    if got:
        m = got[0]
        ok(n + " ADA di ZoneMinder (Id=" + str(m.get("Id")) + ", Method=" + str(m.get("Method")) + ")")
        zl = zm_get("zones.json").get("zones", []) or []
        mine = [z for z in zl if str(z.get("Zone", z).get("MonitorId")) == str(m.get("Id"))]
        if mine:
            ok(n + " punya zone deteksi (" + str(len(mine)) + ")")
        else:
            bad(n + " TIDAK punya zone -> Modect tidak akan alarm")
    else:
        bad(n + " TIDAK ADA di ZoneMinder")

print("")
print("[bersihkan]")
for n in NAMES:
    for m in monitors_named(n):
        zm_delete("monitors/" + str(m.get("Id")) + ".json")
    if not monitors_named(n):
        ok(n + " dihapus")

print("")
print("=" * 66)
print("LULUS: " + str(PASS) + "   GAGAL: " + str(FAIL))
print("SEMUA PEMERIKSAAN BURST LULUS" if FAIL == 0 else "ADA YANG GAGAL")
sys.exit(0 if FAIL == 0 else 1)
