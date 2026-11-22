"""Uji end-to-end payload /api/zoneminder/save-camera untuk URL nyata.

Dijalankan DI DALAM container dashboard:
    docker exec camera-dashboard python /app/_e2e_rtsp_payload.py

Yang diuji bukan cuma normalizer, tapi APA YANG DIKIRIM ke ZoneMinder:
Path harus bersih dan AnalysisFPSLimit harus 8. Request HTTP ke ZoneMinder
dipalsukan (monkeypatch zm_post) supaya tidak ada kamera nyata yang dibuat.
"""

import sys

import app as A
from rtsp_path import normalize_rtsp_path

FAILED = []
CAPTURED = {}


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + label)
    if not ok:
        print("        got : %r" % (got,))
        print("        want: %r" % (want,))
        FAILED.append(label)


def fake_zm_post_monitor(target, payload, *a, **kw):
    """Tiruan zm_post_monitor: kembalikan (ok, pesan, body)."""
    if not (target == "monitors.json" or target.startswith("monitors/")):
        return True, "Saved", {}
    CAPTURED["target"] = target
    CAPTURED["payload"] = dict(payload)
    return True, "Saved", {}


A.zm_post_monitor = fake_zm_post_monitor
A.find_monitor_id_by_name = lambda name: "99"
A.build_encoding_payload = lambda *a, **kw: ({}, [])
# Cegah harness menyentuh ZoneMinder sungguhan.
A.ensure_zone_for_monitor = lambda *a, **kw: {"created": False, "skipped": True, "reason": "uji"}

RAW = "rtsp://operator:0p3r@t0r@10.121.10.145:554/Streaming/Channels/101"

print("=== 1. Normalizer pada URL operator ===")
path, warns = normalize_rtsp_path(RAW)
print("  input : %s" % RAW)
print("  output: %s" % path)
print("  warn  : %s" % warns)
check("password tetap utuh (ffmpeg akan decode %40 jadi @)", path,
      "rtsp://operator:0p3r%40t0r@10.121.10.145:554/Streaming/Channels/101")

print("\n=== 2. Payload POST /save-camera (kamera baru) ===")
client = A.app.test_client()
with client.session_transaction() as sess:
    sess["user"] = "e2e"

body = {"name": "CAM_E2E_RTSP", "path": RAW, "function": "Modect"}
res = client.post("/api/zones/save-camera", json=body)

print("  HTTP %s" % res.status_code)
payload = CAPTURED.get("payload", {})
for key in sorted(payload):
    print("    %-28s = %r" % (key, payload[key]))

check("HTTP 200 dari endpoint", res.status_code, 200)
check("target API", CAPTURED.get("target"), "monitors.json")
check("Path bersih (tanpa dua '@')", payload.get("Monitor[Path]"),
      "rtsp://operator:0p3r%40t0r@10.121.10.145:554/Streaming/Channels/101")
check("AnalysisFPSLimit default 8", payload.get("Monitor[AnalysisFPSLimit]"), "8")
check("MaxFPS tidak dikirim", "Monitor[MaxFPS]" in payload, False)
check("Method rtpRtsp (bukan warisan 1.36)", payload.get("Monitor[Method]"), "rtpRtsp")
check("Options tanpa rtsp_transport",
      "rtsp_transport" in (payload.get("Monitor[Options]") or ""), False)

print("\n=== 3. Payload saat MENGEDIT kamera lama yang path-nya rusak ===")
CAPTURED.clear()
res2 = client.post("/api/zones/save-camera",
                   json={"id": "7", "name": "CAM_E2E_RTSP", "path": RAW,
                         "function": "Modect"})
payload2 = CAPTURED.get("payload", {})
check("target API saat edit", CAPTURED.get("target"), "monitors/7.json")
check("Path diperbaiki juga saat edit", payload2.get("Monitor[Path]"),
      "rtsp://operator:0p3r%40t0r@10.121.10.145:554/Streaming/Channels/101")
check("AnalysisFPSLimit tetap 8", payload2.get("Monitor[AnalysisFPSLimit]"), "8")

print("\n=== 4. Kredensial lewat field terpisah (URL tanpa kredensial) ===")
CAPTURED.clear()
res3 = client.post("/api/zones/save-camera",
                   json={"name": "CAM_E2E_PLAIN",
                         "path": "rtsp://10.121.10.145:554/Streaming/Channels/101",
                         "username": "operator", "password": "0p3r@t0r",
                         "analysisFps": "6", "function": "Modect"})
payload3 = CAPTURED.get("payload", {})
check("Path digabung dengan encoding", payload3.get("Monitor[Path]"),
      "rtsp://operator:0p3r%40t0r@10.121.10.145:554/Streaming/Channels/101")
check("AnalysisFPSLimit mengikuti input", payload3.get("Monitor[AnalysisFPSLimit]"), "6")

print()
if FAILED:
    print("GAGAL: %d pemeriksaan tidak sesuai:" % len(FAILED))
    for name in FAILED:
        print("  - " + name)
    sys.exit(1)
print("SEMUA PEMERIKSAAN E2E LULUS")
