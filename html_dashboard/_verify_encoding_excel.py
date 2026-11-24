"""Uji ujung-ke-ujung jalur Excel/Burst terhadap ZoneMinder yang berjalan.

Menirukan persis apa yang dikirim burst.html setelah berkas Excel dibaca:
satu objek Monitor per baris, dengan kolom encoding ikut sebagai field datar
(Storage, Video Writer, Output Codec, Encoder, Encoder Parameters,
Output Container). Lalu menegaskan nilai yang benar-benar tersimpan di
database ZoneMinder.

Yang diperiksa:
  1. Kolom encoding per baris MENANG atas default panel.
  2. Baris tanpa kolom encoding mewarisi default (bukan dikosongkan).
  3. VideoWriter bukan Encode -> kodec & encoder dikunci 'auto' (0/'auto'),
     karena ZM tidak memakainya.
  4. OutputContainer selalu bernilai sah (auto/mp4/mkv), tidak pernah NULL.
  5. Peringatan preflight encoding dilaporkan, bukan menggagalkan simpan.
"""
import sys
import time

sys.path.insert(0, "/app")

import app as d  # noqa: E402

STAMP = str(int(time.time()))
FAILS = []


def client():
    c = d.app.test_client()
    with c.session_transaction() as s:
        s["user"] = "admin"
        s["issued_at"] = time.time()
        s.permanent = True
    return c


def db_row(name):
    """Baris monitor langsung dari ZM API, dibaca dengan kunci yang benar."""
    mid = d.find_monitor_id_by_name(name)
    if not mid:
        return None, None
    raw = d.zm_api_get("monitors/" + str(mid) + ".json")
    return mid, (d._unwrap_zm(raw, "monitor", "Monitor") or {})


c = client()

# Baris ini meniru hasil pembacaan Excel. Kolom encoding ditulis seperti di
# template (dengan spasi) supaya variasi nama kolom ikut teruji.
rows = [
    {
        "Name": "XL_A_" + STAMP,
        "Path": "rtsp://127.0.0.1:8554/a",
        "Width": "1920",
        "Height": "1080",
        "ZoneMode": "medium",
        "Storage": 1,
        "Video Writer": "Encode",
        "Output Codec": "h264",
        "Encoder": "libx264",
        "Encoder Parameters": "crf=23",
        "Output Container": "mp4",
        "SectionLength": "300",
    },
    {
        "Name": "XL_B_" + STAMP,
        "Path": "rtsp://127.0.0.1:8554/b",
        "Width": "1280",
        "Height": "720",
        "ZoneMode": "light",
        "Storage": 1,
        "Video Writer": "Encode",
        "Output Codec": "h265",
        "Encoder": "libx265",
        "Encoder Parameters": "crf=28",
        "Output Container": "mkv",
        "SectionLength": "90",
    },
    {
        # Tanpa kolom encoding sama sekali -> harus mewarisi default.
        "Name": "XL_C_" + STAMP,
        "Path": "rtsp://127.0.0.1:8554/c",
        "Width": "1280",
        "Height": "720",
    },
    {
        # VideoWriter Disabled -> kodec & encoder tidak dipakai ZM.
        "Name": "XL_D_" + STAMP,
        "Path": "rtsp://127.0.0.1:8554/d",
        "Width": "1280",
        "Height": "720",
        "Storage": 1,
        "Video Writer": "Disabled",
        "Output Codec": "h264",
        "Encoder": "libx264",
        "Encoder Parameters": "crf=23",
        "Output Container": "mp4",
    },
]

body = {
    "monitors": [{"Monitor": r} for r in rows],
    "zoneMode": "light",
    "createZone": False,
    "overwriteZone": False,
}
res = c.post("/api/zoneminder/burst-add", json=body)
data = res.get_json()
print("HTTP", res.status_code, "| total", data.get("total"),
      "| sukses", data.get("success_count"), "| gagal", data.get("fail_count"))
if data.get("fail_count"):
    FAILS.append("ada baris gagal: " + str(data.get("details")))

EXPECT = {
    "XL_A_" + STAMP: {
        "Encoder": "libx264",
        "EncoderParameters": "crf=23",
        "SectionLength": "300",
        "VideoWriter": "1",
        "OutputCodec": "27",
        "OutputCodecName": "h264",
        "OutputContainer": "mp4",
    },
    "XL_B_" + STAMP: {
        "Encoder": "libx265",
        "EncoderParameters": "crf=28",
        "SectionLength": "90",
        "VideoWriter": "1",
        "OutputCodec": "173",
        "OutputCodecName": "hevc",
        "OutputContainer": "mkv",
    },
    # Tanpa kolom encoding: seluruh nilai default 1.38.6.
    "XL_C_" + STAMP: {
        "Encoder": d.MONITOR_ENCODING_DEFAULTS["Encoder"],
        "EncoderParameters": d.MONITOR_ENCODING_DEFAULTS["EncoderParameters"],
        "SectionLength": d.MONITOR_ENCODING_DEFAULTS["SectionLength"],
        "VideoWriter": d.MONITOR_ENCODING_DEFAULTS["VideoWriter"],
        "OutputCodec": d.MONITOR_ENCODING_DEFAULTS["OutputCodec"],
        "OutputCodecName": d.MONITOR_ENCODING_DEFAULTS["OutputCodecName"],
        "OutputContainer": d.MONITOR_ENCODING_DEFAULTS["OutputContainer"],
    },
    # VideoWriter Disabled: kodec/encoder 'auto', container tetap sah.
    "XL_D_" + STAMP: {
        "Encoder": "auto",
        "EncoderParameters": "crf=23",
        "VideoWriter": "0",
        "OutputCodec": "0",
        "OutputCodecName": "auto",
        "OutputContainer": "mp4",
    },
}

print()
for name, want in EXPECT.items():
    mid, mon = db_row(name)
    if not mon:
        FAILS.append(name + ": monitor tidak terbentuk")
        continue
    print(name, "-> id", mid)
    for field, expect in want.items():
        got = mon.get(field)
        got_s = "" if got is None else str(got)
        ok = got_s == str(expect)
        print(("  OK   " if ok else "  FAIL ") + field + " = " + repr(got_s)
              + ("" if ok else " (harap " + repr(str(expect)) + ")"))
        if not ok:
            FAILS.append(name + "." + field)

    container = mon.get("OutputContainer")
    print("  OutputContainer =", repr(container))
    if container in (None, ""):
        FAILS.append(name + ".OutputContainer kosong/NULL")

    # Kolom non-encoding tidak boleh rusak.
    for field in ("Name", "Path", "Width", "Height"):
        print("  " + field + " =", repr(mon.get(field)))

# Peringatan preflight harus muncul untuk baris SectionLength=90 (< pre+post 50+50).
details = data.get("details") or []
print()
if len(details) > 1:
    warns = details[1].get("encoding_warnings")
    print("encoding_warnings baris kedua:", warns)
    if not warns:
        FAILS.append("peringatan preflight tidak muncul untuk SectionLength=90")
else:
    FAILS.append("detail baris kedua tidak ada")

print()
print("--- bersihkan ---")
for name in EXPECT:
    mid = d.find_monitor_id_by_name(name)
    if mid:
        print(" hapus", name, d.zm_delete("monitors/" + str(mid) + ".json"))

print()
if FAILS:
    print("GAGAL:")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("JALUR EXCEL LULUS - penimpaan per baris, pewarisan default, dan "
      "pasangan kodec benar")
