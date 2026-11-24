"""Probe: nilai enum encoding mana yang DITERIMA API ZM 1.38.6."""
import sys

sys.path.insert(0, "/app")
import app as dash  # noqa: E402

BASE = dict(
    name="PROBE_ENUM",
    path="rtsp://10.0.0.1/probe",
    width="1280",
    height="720",
)


def run(label, overrides):
    payload = dash.build_zm138_full_payload(**BASE)
    payload.update({"Monitor[%s]" % k: str(v) for k, v in overrides.items()})
    ok, msg, body = dash.zm_post_monitor("monitors.json", payload)
    mid = ""
    if ok:
        mid = dash.find_monitor_id_by_name("PROBE_ENUM")
        if mid:
            row = dash._unwrap_zm(
                dash.zm_api_get("monitors/%s.json" % mid), "monitor", "Monitor"
            ) or {}
            got = {k: row.get(k) for k in
                   ("StorageId", "VideoWriter", "OutputCodec", "OutputCodecName",
                    "Encoder", "EncoderParameters", "OutputContainer")}
        else:
            got = {"error": "monitor tidak ditemukan"}
    else:
        got = {"error": msg}
    print("%-6s ok=%s msg=%s" % (label, ok, str(msg)[:120]))
    print("       ->", got)
    if mid:
        dash.zm_delete("monitors/%s.json" % mid)


print("[A] OutputContainer=webm + VideoWriter=1 + hevc")
run("A", {"OutputContainer": "webm", "VideoWriter": "1",
           "OutputCodec": "173", "OutputCodecName": "hevc",
           "Encoder": "hevc_qsv", "EncoderParameters": "crf=51",
           "StorageId": "1"})

print("")
print("[B] OutputContainer=mp4 + VideoWriter=1 + hevc")
run("B", {"OutputContainer": "mp4", "VideoWriter": "1",
           "OutputCodec": "173", "OutputCodecName": "hevc",
           "Encoder": "hevc_qsv", "EncoderParameters": "crf=51",
           "StorageId": "1"})

print("")
print("[C] VideoWriter=2 (Camera Passthrough), codec auto")
run("C", {"OutputContainer": "mp4", "VideoWriter": "2",
           "OutputCodec": "0", "OutputCodecName": "auto",
           "Encoder": "auto", "EncoderParameters": "crf=23",
           "StorageId": "1"})

print("")
print("[D] OutputContainer=auto")
run("D", {"OutputContainer": "auto", "VideoWriter": "1",
           "Encoder": "libx264", "EncoderParameters": "crf=23",
           "StorageId": "1"})
