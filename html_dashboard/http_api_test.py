"""Uji endpoint dashboard lewat HTTP sungguhan (bukan Flask test client).

Dijalankan di dalam container camera-dashboard:
    docker exec camera-dashboard python /app/http_api_test.py

Menguji hal yang tidak terlihat pada uji test-client:
  1. Route benar-benar terdaftar dan dijangkau lewat waitress.
  2. Endpoint terlindungi sesi (tidak terbuka tanpa login).
"""
import sys

import requests

BASE = "http://127.0.0.1:8080"
PASS, FAIL = 0, 0


def ok(m):
    global PASS
    PASS += 1
    print("  [OK]   " + m)


def bad(m):
    global FAIL
    FAIL += 1
    print("  [FAIL] " + m)


s = requests.Session()

print("=" * 66)
print("Uji HTTP nyata: endpoint dashboard")
print("=" * 66)

print("")
print("[1] Tanpa login harus ditolak")
r = s.post(BASE + "/api/zones/save-camera", json={"name": "X", "path": "rtsp://a/b"})
print("     HTTP " + str(r.status_code) + " " + str(r.text)[:100])
if r.status_code in (401, 403):
    ok("endpoint terlindungi (HTTP " + str(r.status_code) + ")")
else:
    bad("endpoint TIDAK terlindungi: HTTP " + str(r.status_code))

print("")
print("[2] Halaman login dapat diakses")
r = s.get(BASE + "/login")
if r.status_code == 200:
    ok("GET /login -> 200")
else:
    bad("GET /login -> " + str(r.status_code))

print("")
print("[3] Halaman terproteksi mengarahkan ke login jika belum ada sesi")
for path in ("/", "/status", "/zoneminder.html", "/settings"):
    r = s.get(BASE + path, allow_redirects=False)
    if r.status_code in (302, 401):
        ok("GET " + path + " -> " + str(r.status_code) + " (terproteksi)")
    else:
        bad("GET " + path + " -> " + str(r.status_code) + " (seharusnya redirect)")

print("")
print("[4] Health probe")
r = s.get(BASE + "/healthz")
if r.status_code == 200 and r.json().get("ok"):
    ok("GET /healthz -> 200 OK")
else:
    bad("GET /healthz -> " + str(r.status_code))

print("")
print("=" * 66)
print("LULUS: " + str(PASS) + "   GAGAL: " + str(FAIL))
sys.exit(0 if FAIL == 0 else 1)
