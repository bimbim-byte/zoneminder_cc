"""Verifikasi tiga jalur registrasi kamera memuat seluruh input wajib.

Dijalankan di container:
    docker exec camera-dashboard python3 /app/_verify_three_paths.py

Diperiksa untuk setiap jalur (single add, burst add, Excel import):
  1. UI menyediakan Capturing, Analysing, Recording, Path, Username, Password,
     Width, Height, MaxFPS, AnalysisFPSLimit, Decoder.
  2. Decoder memuat 9 pilihan (termasuk hevc_qsv).
  3. Pilihan pembuatan zone tetap ada (createZone / zoneMode).
  4. Backend meneruskan nilai triad ke payload Monitor[Capturing] dst.
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


DECODERS = ["Auto", "h264", "h264_cuvid", "h264_vaapi", "h264_qsv",
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
check(all(d in src for d in DECODERS), "9 pilihan decoder lengkap (incl. hevc_qsv)")
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
check(all(d in src for d in DECODERS), "9 pilihan decoder lengkap (incl. hevc_qsv)")
check("createZone" in src and "zoneMode" in src, "pilihan pembuatan zone ada")
check("XLSX.utils.sheet_to_json" in src, "impor Excel/CSV aktif")

print("[3] Backend meneruskan triad + field wajib")
app_src = read("app.py")
for token in ["build_zm138_full_payload", "capturing=", "analysing=", "recording=",
              "max_fps=", "analysis_fps_limit=", "decoder=", "width=", "height="]:
    check(token in app_src, "app.py memakai argumen %s" % token)
check(app_src.count("ensure_zone_for_monitor") >= 3,
      "zone creation dipanggil di ketiga jalur")

print("")
if FAILED:
    print("GAGAL: %d pemeriksaan" % len(FAILED))
    sys.exit(1)
print("SEMUA PEMERIKSAAN TIGA JALUR LULUS")
