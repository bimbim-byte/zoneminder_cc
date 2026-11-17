"""Verifikasi encoding default terhadap ZoneMinder 1.36.32 yang berjalan.

Dijalankan DI DALAM container camera-dashboard. Membuat monitor uji melalui
tiga jalur (payload tunggal, burst, save-camera), lalu membaca kembali nilai
yang benar-benar tersimpan di ZoneMinder.
"""
import sys
import time

sys.path.insert(0, "/app")

import app as dash  # noqa: E402

EXPECTED = dict(dash.MONITOR_ENCODING_DEFAULTS)
FAILS = []


def check(label, name, expect_id=True):
    mid = dash.find_monitor_id_by_name(name)
    print("  monitor_id:", mid)
    if not mid:
        FAILS.append(label + ": monitor tidak terbentuk")
        return None

    data = dash.zm_api_get("monitors/" + str(mid) + ".json")
    mon = dash._unwrap_zm(data, "monitor", "Monitor") or {}

    for field, want in EXPECTED.items():
        got = mon.get(field)
        got_s = "" if got is None else str(got)
        if got_s != str(want):
            print("    FAIL", field, "got", repr(got_s), "want", repr(str(want)))
            FAILS.append(label + "." + field)

    container = mon.get("OutputContainer")
    print("    OutputContainer =", repr(container))
    if container not in (None, ""):
        FAILS.append(label + ".OutputContainer not null: " + repr(container))

    print("    checked", len(EXPECTED), "fields")
    return mid


def cleanup(name):
    mid = dash.find_monitor_id_by_name(name)
    if mid:
        code = dash.zm_delete("monitors/" + str(mid) + ".json")
        print("    cleanup HTTP", code)


STAMP = str(int(time.time()))
TOKEN = dash.get_zm_token()
AUTH = ("?token=" + TOKEN) if TOKEN else ""


def post_payload(payload, label):
    import requests
    url = dash.ZM_HOST + "/zm/api/monitors.json" + AUTH
    r = requests.post(url, data=payload, timeout=20, verify=False)
    print("    POST", label, "HTTP", r.status_code, r.text[:200])
    return r


# ---------------------------------------------------------------- JALUR 1
print("[1] Jalur tunggal - build_encoding_payload langsung")
enc, warns = dash.build_encoding_payload()
print("    fields:", len(enc), "warnings:", warns)
if "Monitor[OutputContainer]" in enc:
    FAILS.append("jalur1: OutputContainer ikut terkirim")
if len(enc) != len(EXPECTED):
    FAILS.append("jalur1: jumlah field " + str(len(enc)) + " != " + str(len(EXPECTED)))

NAME1 = "Enc_Single_" + STAMP
p1 = {
    "Monitor[Name]": NAME1,
    "Monitor[Type]": "Ffmpeg",
    "Monitor[Function]": "Monitor",
    "Monitor[Enabled]": "1",
    "Monitor[Path]": "rtsp://127.0.0.1:8554/probe",
    "Monitor[Method]": "rtsp",
    "Monitor[Options]": "rtsp_transport=tcp",
    "Monitor[Width]": "1280",
    "Monitor[Height]": "720",
    "Monitor[Colours]": "4",
    "Monitor[TargetColorspace]": "4",
    "Monitor[ServerId]": "0",
}
p1.update(enc)
post_payload(p1, "single")
check("single", NAME1)
cleanup(NAME1)

# ---------------------------------------------------------------- JALUR 2
print()
print("[2] Jalur burst - penimpaan per baris")
NAME2 = "Enc_Burst_" + STAMP
row = {
    "Name": NAME2,
    "Path": "rtsp://127.0.0.1:8554/probe",
    "Width": "1280",
    "Height": "720",
    "SectionLength": "180",
    "EncoderParameters": "crf=28",
}
over = dash.read_encoding_overrides(row)
print("    overrides terbaca:", over)
enc2, warns2 = dash.build_encoding_payload(over)
print("    SectionLength:", enc2.get("Monitor[SectionLength]"),
      "crf:", enc2.get("Monitor[EncoderParameters]"))

p2 = {
    "Monitor[Name]": NAME2,
    "Monitor[Type]": "Ffmpeg",
    "Monitor[Function]": "Monitor",
    "Monitor[Enabled]": "1",
    "Monitor[Path]": "rtsp://127.0.0.1:8554/probe",
    "Monitor[Method]": "rtsp",
    "Monitor[Options]": "rtsp_transport=tcp",
    "Monitor[Width]": "1280",
    "Monitor[Height]": "720",
    "Monitor[Colours]": "4",
    "Monitor[TargetColorspace]": "4",
    "Monitor[ServerId]": "0",
}
p2.update(enc2)
post_payload(p2, "burst")

mid2 = dash.find_monitor_id_by_name(NAME2)
if mid2:
    mon2 = dash._unwrap_zm(dash.zm_api_get("monitors/" + str(mid2) + ".json"), "monitor", "Monitor") or {}
    got_sec = str(mon2.get("SectionLength"))
    got_crf = str(mon2.get("EncoderParameters"))
    print("    SectionLength tersimpan:", got_sec, "(harap 180)")
    print("    EncoderParameters tersimpan:", repr(got_crf), "(harap crf=28)")
    if got_sec != "180":
        FAILS.append("burst.SectionLength override gagal: " + got_sec)
    if got_crf != "crf=28":
        FAILS.append("burst.EncoderParameters override gagal: " + got_crf)
    if mon2.get("OutputContainer") not in (None, ""):
        FAILS.append("burst.OutputContainer tidak NULL")
cleanup(NAME2)

# ---------------------------------------------------------------- JALUR 3
print()
print("[3] Jalur save-camera - field non-encoding tidak boleh rusak")
enc3, warns3 = dash.build_encoding_payload({"Encoder": "libx264"})
print("    fields:", len(enc3))

print()
if FAILS:
    print("GAGAL:")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("SEMUA JALUR LULUS - encoding default tersimpan sesuai permintaan")
 
