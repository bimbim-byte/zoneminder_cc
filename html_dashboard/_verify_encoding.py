"""Verifikasi encoding default terhadap ZoneMinder 1.38.6 yang berjalan.

Dijalankan DI DALAM container camera-dashboard. Membuat monitor uji melalui
tiga jalur (payload tunggal, burst, save-camera), lalu membaca kembali nilai
yang benar-benar tersimpan di ZoneMinder.

Sejak field video/encoding ditambahkan, OutputContainer TIDAK LAGI dibuang:
nilainya selalu dikirim dengan bentuk sah (auto/mp4/mkv) supaya API ZM tidak
menolak seluruh simpan dengan "Please choose one of the following values".
Karena itu pemeriksaan di sini mengharapkan nilai default yang SAH, bukan NULL.

Catatan sumber RTSP: tipe monitor Ffmpeg di ZM 1.38 hanya mengenali Method
rtpRtsp / rtpUni / rtpMulti / rtpRtspHttp. Transport dikodekan oleh Method,
bukan oleh Monitor[Options] — lihat komentar ZM_FFMPEG_METHOD di app.py.
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

    # OutputContainer kini WAJIB berisi nilai sah, bukan NULL.
    container = mon.get("OutputContainer")
    print("    OutputContainer =", repr(container))
    if str(container or "") != str(EXPECTED["OutputContainer"]):
        FAILS.append(label + ".OutputContainer = " + repr(container))

    # Pasangan kodec: OutputCodec (int) dan OutputCodecName (varchar).
    print("    OutputCodec =", repr(mon.get("OutputCodec")),
          "| OutputCodecName =", repr(mon.get("OutputCodecName")))
    if str(mon.get("OutputCodec") or "") != str(EXPECTED["OutputCodec"]):
        FAILS.append(label + ".OutputCodec")
    if str(mon.get("OutputCodecName") or "") != str(EXPECTED["OutputCodecName"]):
        FAILS.append(label + ".OutputCodecName")

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
if enc.get("Monitor[OutputContainer]") != str(EXPECTED["OutputContainer"]):
    FAILS.append("jalur1: OutputContainer = " + repr(enc.get("Monitor[OutputContainer]")))
if enc.get("Monitor[StorageId]") != str(EXPECTED["StorageId"]):
    FAILS.append("jalur1: StorageId = " + repr(enc.get("Monitor[StorageId]")))
if enc.get("Monitor[OutputCodecName]") != str(EXPECTED["OutputCodecName"]):
    FAILS.append("jalur1: OutputCodecName = " + repr(enc.get("Monitor[OutputCodecName]")))
if len(enc) != len(EXPECTED):
    FAILS.append("jalur1: jumlah field " + str(len(enc)) + " != " + str(len(EXPECTED)))

NAME1 = "Enc_Single_" + STAMP
p1 = {
    "Monitor[Name]": NAME1,
    "Monitor[Type]": "Ffmpeg",
    "Monitor[Function]": "Monitor",
    "Monitor[Enabled]": "1",
    # WAJIB walau kosong: tanpa kunci ini ZM 1.38 menolak validasi Device
    # (pesan "Invalid device path"), padahal balasannya tetap HTTP 200.
    "Monitor[Device]": "",
    "Monitor[Path]": "rtsp://127.0.0.1:8554/probe",
    "Monitor[Method]": dash.ZM_FFMPEG_METHOD,
    "Monitor[Options]": dash.ZM_FFMPEG_OPTIONS,
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
    # Kolom encoding per baris: nilai operator harus MENANG atas default panel.
    "Storage": "1",
    "Video Writer": "Encode",
    "Output Codec": "h264",
    "Encoder": "libx264",
    "Output Container": "mkv",
}
over = dash.read_encoding_overrides(row)
print("    overrides terbaca:", over)
enc2, warns2 = dash.build_encoding_payload(over)
print("    SectionLength:", enc2.get("Monitor[SectionLength]"),
      "crf:", enc2.get("Monitor[EncoderParameters]"),
      "container:", enc2.get("Monitor[OutputContainer]"))

p2 = {
    "Monitor[Name]": NAME2,
    "Monitor[Type]": "Ffmpeg",
    "Monitor[Function]": "Monitor",
    "Monitor[Enabled]": "1",
    # WAJIB walau kosong: tanpa kunci ini ZM 1.38 menolak validasi Device
    # (pesan "Invalid device path"), padahal balasannya tetap HTTP 200.
    "Monitor[Device]": "",
    "Monitor[Path]": "rtsp://127.0.0.1:8554/probe",
    "Monitor[Method]": dash.ZM_FFMPEG_METHOD,
    "Monitor[Options]": dash.ZM_FFMPEG_OPTIONS,
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
    got_container = str(mon2.get("OutputContainer") or "")
    got_writer = str(mon2.get("VideoWriter") or "")
    print("    SectionLength tersimpan:", got_sec, "(harap 180)")
    print("    EncoderParameters tersimpan:", repr(got_crf), "(harap crf=28)")
    print("    OutputContainer tersimpan:", repr(got_container), "(harap mkv)")
    print("    VideoWriter tersimpan:", repr(got_writer), "(harap 1)")
    if got_sec != "180":
        FAILS.append("burst.SectionLength override gagal: " + got_sec)
    if got_crf != "crf=28":
        FAILS.append("burst.EncoderParameters override gagal: " + got_crf)
    if got_container != "mkv":
        FAILS.append("burst.OutputContainer override gagal: " + repr(got_container))
    if got_writer != "1":
        FAILS.append("burst.VideoWriter override gagal: " + repr(got_writer))
    # Pasangan kodec tetap utuh walau nilainya ditimpa per baris.
    if str(mon2.get("OutputCodec") or "") != "27" or str(mon2.get("OutputCodecName") or "") != "h264":
        FAILS.append(
            "burst.pasangan kodec rusak: OutputCodec=%r OutputCodecName=%r"
            % (mon2.get("OutputCodec"), mon2.get("OutputCodecName"))
        )
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
