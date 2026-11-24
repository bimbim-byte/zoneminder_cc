"""Verifikasi tiga jalur registrasi kamera memuat seluruh input wajib.

Dijalankan di container:
    docker exec camera-dashboard python3 /app/_verify_three_paths.py

Diperiksa untuk setiap jalur (single add, burst add, Excel import):
  1. UI menyediakan Capturing, Analysing, Recording, Path, Username, Password,
     Width, Height, MaxFPS, AnalysisFPSLimit, Decoder.
  2. Decoder mencakup 9 pilihan inti (incl. hevc_qsv).
  3. Pilihan pembuatan zone tetap ada (createZone / zoneMode).
  4. Backend meneruskan nilai triad ke payload Monitor[Capturing] dst.

Catatan: daftar decoder tidak lagi hardcode di halaman tambah. Sejak portal
memakai app_shell.js, daftar dipusatkan di sana (ZM_DECODERS) dan halaman
mengisinya lewat fillDecoderOptions(). Karena itu pemeriksaan decoder pada
jalur single add mengacu ke modul bersama tersebut.
"""
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
FAILED = []


def check(cond, msg):
    print(("  [OK]   " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAILED.append(msg)


def read(name):
    with open(os.path.join(BASE, name), encoding="utf-8") as f:
        return f.read()


DECODERS = ["auto", "h264", "h264_cuvid", "h264_vaapi", "h264_qsv",
            "hevc", "hevc_cuvid", "hevc_vaapi", "hevc_qsv"]

print("[1] Jalur tambah kamera satuan (add_camera.html)")
src = read("add_camera.html")
for token, label in [
    ("camCapturing", "Capturing"),
    ("camAnalysing", "Analysing"),
    ("camRecording", "Recording"),
    ("rtspUrl", "Path Source"),
    ("camUser", "Username"),
    ("camPass", "Password"),
    ("resolution", "Resolusi"),
    ("maxFps", "MaxFPS"),
    ("analysisFps", "AnalysisFPSLimit"),
    ("camDecoder", "Decoder"),
]:
    check(token in src, "kontrol %s ada" % label)

shell = read("app_shell.js")
check(all(d in shell for d in DECODERS),
      "9 pilihan decoder inti ada di app_shell.js (ZM_DECODERS)")
check("fillDecoderOptions" in src,
      "add_camera.html mengisi decoder dari daftar bersama")
check("createZone" in src and "zoneMode" in src, "pilihan pembuatan zone ada")

print("[2] Jalur burst add + impor Excel (burst.html)")
src = read("burst.html")
for token, label in [
    ("Capturing", "Capturing"),
    ("Analysing", "Analysing"),
    ("Recording", "Recording"),
    ("Source Path", "Path Source"),
    ("Username", "Username"),
    ("Password", "Password"),
    ("Width", "Resolusi Width"),
    ("Height", "Resolusi Height"),
    ("Max FPS", "MaxFPS"),
    ("Analysis FPS", "AnalysisFPSLimit"),
    ("Decoder", "Decoder"),
]:
    check(token in src, "kontrol %s ada" % label)
check(all(d in src for d in ["h264_qsv", "hevc_qsv", "hevc_vaapi"]),
      "pilihan decoder burst mencakup varian qsv/vaapi")
check("createZone" in src and "zoneMode" in src, "pilihan pembuatan zone ada")
check("XLSX.utils.sheet_to_json" in src, "impor Excel/CSV aktif")

print("[3] Field event & analisis ZM 1.38.6 di ketiga jalur")
EVENT_UI = ["Section Length", "Minimum Section Length", "Event Close Mode",
            "Frame Skip", "Analysis Update Delay", "FPS Report Interval",
            "Importance", "Startup Delay"]
for name in ("add_camera.html", "burst.html"):
    body = read(name)
    missing = [f for f in EVENT_UI if f not in body and f.lower() not in body.lower()]
    check(not missing, "%s memuat 8 field event/analisis" % name)

print("[4] Backend meneruskan triad + field wajib")
app_src = read("app.py")
for token in ["build_zm138_full_payload", "capturing=", "analysing=", "recording=",
              "max_fps=", "analysis_fps_limit=", "decoder=", "width=", "height="]:
    check(token in app_src, "app.py memakai argumen %s" % token)
for token in ["section_length=", "min_section_length=", "event_close_mode=",
              "frame_skip=", "analysis_update_delay=", "fps_report_interval=",
              "importance=", "startup_delay="]:
    check(token in app_src, "app.py meneruskan %s" % token)
check(app_src.count("ensure_zone_for_monitor") >= 3,
      "zone creation dipanggil di ketiga jalur")

print("")
if FAILED:
    print("GAGAL: %d pemeriksaan" % len(FAILED))
    sys.exit(1)
print("[5] Field encoding video (Storage/VideoWriter/Codec/Encoder/Container)")
ENC_UI = ["storageId", "videoWriter", "outputCodec", "encoder",
          "encoderParameters", "outputContainer"]
add_src = read("add_camera.html")
missing = [f for f in ENC_UI if ('id="%s"' % f) not in add_src]
check(not missing, "add_camera.html memuat 6 kontrol encoding (%s)" % (missing or "lengkap"))
check('data-encoding-section' in add_src and 'data-encoding-block="encode"' in add_src,
      "kontrol model encoding hanya tampil saat VideoWriter=Encode")
check("readEncodingControls" in add_src, "add_camera.html mengirim field encoding saat submit")

burst_src = read("burst.html")
for token in ["defaultStorageId", "defaultVideoWriter", "defaultOutputCodec",
              "defaultOutputContainer", "defaultEncoder",
              "defaultEncoderParameters"]:
    check(token in burst_src, "burst.html punya kontrol %s" % token)
check("ENCODING_DEFAULTS" in burst_src and "readEncodingDefaults" in burst_src,
      "burst.html memakai default encoding panel")
for col in ['"Storage"', '"Video Writer"', '"Output Codec"', '"Encoder"',
            '"Encoder Parameters"', '"Output Container"']:
    check(col in burst_src, "kolom Excel %s dibaca" % col)
check("encodingSummary" in burst_src, "tabel pratinjau menampilkan ringkasan encoding")
check("ENCODING_TEMPLATE_COLUMNS" in burst_src, "template Excel memuat kolom encoding")

shell = read("app_shell.js")
for token in ["ZM_VIDEO_WRITERS", "ZM_OUTPUT_CODECS", "ZM_OUTPUT_CONTAINERS",
              "ZM_ENCODERS", "fillEncodingControls", "readEncodingControls",
              "toggleEncodingBlock", "loadStorageAreas"]:
    check(token in shell, "app_shell.js menyediakan %s" % token)

app_src2 = read("app.py")
check("def read_encoding_fields" in app_src2, "app.py punya pembaca field encoding")
check(app_src2.count("**read_encoding_fields(") == 3,
      "ketiga jalur memakai pembaca field encoding")
check('"/api/zm/storageareas"' in app_src2, "endpoint daftar storage area ada")
check('zm_api_get("storage.json")' in app_src2, "storage.json (bukan storages.json) dipakai")
check("normalize_output_container" in app_src2, "'webm' dipetakan ke container sah")

print("")
if FAILED:
    print("GAGAL: %d pemeriksaan" % len(FAILED))
    sys.exit(1)
print("SEMUA PEMERIKSAAN TIGA JALUR LULUS")
