"""Ganti blok inline di app.py dengan import dari modul rtsp_path.

Dijalankan SEKALI saat refactor (idempoten: berhenti bila blok sudah diganti).
Argumen: path app.py (default html_dashboard/app.py).

Kenapa lewat skrip: blok yang diganti ~230 baris; menggantinya dengan
replace_text akan rawan salah tempel, sedangkan penanda awal/akhirnya unik.
"""

import pathlib
import sys

TARGET = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "html_dashboard/app.py")
START_MARK = 'ZM_FFMPEG_TIMEOUT_US = "5000000"'
END_MARK = '    return {"Monitor[AnalysisFPSLimit]": str(fps)}'

REPLACEMENT = '''from rtsp_path import (  # noqa: E402  (setelah konstanta, bukan di blok import atas)
    ANALYSIS_FPS_DEFAULT,
    ZM_FFMPEG_OPTIONS,
    _monitor_fps_payload as _rtsp_fps_payload,
    normalize_analysis_fps,
    normalize_rtsp_path,
)

# Batas laju analisa motion + normalisasi path RTSP kini hidup di modul
# terpisah (rtsp_path.py) supaya bisa diuji tanpa menyeret Flask. Lihat
# _verify_rtsp_path.py untuk uji perilakunya.
ZM_FFMPEG_TIMEOUT_US = "5000000"


def _monitor_fps_payload(analysis_fps=None):
    """Field FPS yang dikirim saat membuat/menyimpan monitor.

    Hanya AnalysisFPSLimit yang diisi; MaxFPS sengaja tidak dikirim agar
    capture tidak dipotong. Implementasi ada di rtsp_path.py.
    """
    return _rtsp_fps_payload(analysis_fps)'''

lines = TARGET.read_text(encoding="utf-8").splitlines(keepends=True)

starts = [i for i, line in enumerate(lines) if line.startswith(START_MARK)]
if not starts:
    print("LEWATI: penanda awal tidak ditemukan (mungkin sudah diganti).")
    sys.exit(0)

start = starts[0]
ends = [i for i, line in enumerate(lines) if line.startswith(END_MARK)]
if not ends:
    print("GAGAL: penanda akhir tidak ditemukan.")
    sys.exit(1)
end = ends[0]

if start >= end:
    print("GAGAL: penanda akhir mendahului penanda awal.")
    sys.exit(1)

before = lines[:start]
after = lines[end + 1:]

# Buang judul section "NORMALISASI PATH RTSP" (komentar panjang) yang kini
# hidup di rtsp_path.py, supaya tidak ada dokumentasi ganda yang bisa
# berbeda isi.
while before and before[-1].lstrip().startswith("#"):
    before.pop()

TARGET.write_text("".join(before + [REPLACEMENT + "\n"] + after), encoding="utf-8")
print("DIGANTI: baris %d-%d" % (start + 1, end + 1))
