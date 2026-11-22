#!/usr/bin/env python3
"""Parity test API ZoneMinder setelah migrasi 1.36.32 -> 1.38.6.

Dijalankan DI DALAM container cctv_checker_service, karena hanya container itu
yang memegang ZM_USER / ZM_PASS / ZM_HOST sebagai environment:

    docker cp scripts/_api_parity.py cctv_checker_service:/tmp/api_parity.py
    docker exec cctv_checker_service python3 /tmp/api_parity.py

Kontrak yang diuji = yang benar-benar dipakai stack ini:
  - GET  /zm/api/host/getVersion.json     (cctv_checker: wait_for_zoneminder)
  - POST /zm/api/host/login.json          (cctv_checker + dashboard)
  - GET  /zm/api/monitors.json?token=...  (cctv_checker + dashboard)
  - POST /zm/api/monitors/{id}.json       (auto-switch Function None/Monitor)

Uji POST memakai NILAI FUNCTION YANG SEDANG DIPAKAI (idempotent), jadi tidak
mengubah perilaku monitor apa pun.
"""
import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request

ZM = os.environ.get("ZM_HOST", "http://zoneminder:80").rstrip("/")
USER = os.environ.get("ZM_USER", "")
PASS = os.environ.get("ZM_PASS", "")

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def req(path, data=None, token=None):
    url = ZM + path
    if token:
        url += ("&" if "?" in url else "?") + "token=" + urllib.parse.quote(str(token))
    body = urllib.parse.urlencode(data).encode() if data else None
    r = urllib.request.Request(url, data=body)
    try:
        with urllib.request.urlopen(r, timeout=20, context=CTX) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return -1, repr(e)


print("== 1. GET /zm/api/host/getVersion.json (tanpa token) ==")
st, raw = req("/zm/api/host/getVersion.json")
print("   status:", st, "| body_len:", len(raw))

print("== 2. POST /zm/api/host/login.json ==")
st, raw = req("/zm/api/host/login.json", {"user": USER, "pass": PASS})
token = None
try:
    token = json.loads(raw).get("access_token")
except Exception:  # noqa: BLE001
    pass
print("   status:", st, "| token_present:", bool(token))

print("== 3. GET /zm/api/monitors.json?token=... ==")
st, raw = req("/zm/api/monitors.json", token=token)
print("   status:", st, "| body_len:", len(raw))
mons = []
try:
    mons = json.loads(raw).get("monitors", [])
    print("   monitor_count:", len(mons))
    if mons:
        first = mons[0]["Monitor"]
        print("   monitor_keys:", ",".join(sorted(first.keys()))[:400])
        sample = {k: first.get(k) for k in ("Id", "Name", "Function", "Enabled")}
        print("   sample:", json.dumps(sample))
except Exception as e:  # noqa: BLE001
    print("   parse_error:", e, "| raw:", raw[:200])

print("== 4. POST /zm/api/monitors/{id}.json (idempotent) ==")
for m in mons:
    mon = m.get("Monitor", {})
    mid, fn = mon.get("Id"), mon.get("Function")
    st, raw = req("/zm/api/monitors/%s.json" % mid, {"Monitor[Function]": fn}, token=token)
    print("   monitor", mid, "Function", fn, "-> status:", st, "| body:", raw[:160].replace("\n", " "))

print("== 5. Re-read monitors.json (pastikan tidak ada drift state) ==")
st, raw = req("/zm/api/monitors.json", token=token)
try:
    for m in json.loads(raw).get("monitors", []):
        mon = m.get("Monitor", {})
        print("   monitor", mon.get("Id"), mon.get("Name"), "Function=", mon.get("Function"),
              "Enabled=", mon.get("Enabled"))
except Exception as e:  # noqa: BLE001
    print("   parse_error:", e)
