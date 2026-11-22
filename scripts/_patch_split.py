"""Ganti fungsi _split_rtsp_userinfo di rtsp_path.py (satu kali).

Dijalankan di dalam container:
    docker exec -i camera-dashboard python - /app/rtsp_path.py < scripts/_patch_split.py
"""

import pathlib
import sys

TARGET = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "html_dashboard/rtsp_path.py")

NEW_FUNC = '''def _split_rtsp_userinfo(url):
    """Pisahkan URL menjadi (skema, userinfo, sisa).

    userinfo = None bila URL tidak membawa kredensial.

    PEMISAH YANG DIPAKAI ADALAH "@" PERTAMA setelah "://", bukan yang terakhir.
    Ini sempat salah: pada URL rusak
    "rtsp://operator:0p3r@t0r@10.121.10.145:554/..." pemisah TERAKHIR membuat
    password justru ikut masuk ke bagian host, sehingga kerusakan tidak
    terdeteksi sama sekali (diuji: keluar tanpa peringatan). Dengan pemisah
    pertama hasilnya:
        userinfo = "operator:0p3r@t0r"      (mengandung "@" -> belum encoded)
        sisa     = "10.121.10.145:554/..."  (host valid)
    dan justru bentuk itulah yang bisa diperbaiki.

    Catatan: RFC 3986/ffmpeg memakai "@" TERAKHIR sebagai pemisah userinfo dan
    host. Perbedaan ini disengaja - di sini kita sedang membaca input yang
    kemungkinan rusak, jadi yang dibutuhkan adalah titik sisip yang salah,
    bukan penafsiran yang menghasilkan host palsu.
    """
    scheme, sep, after = url.partition("://")
    if not sep or "@" not in after:
        return url, None, ""
    userinfo, _, rest = after.partition("@")
    if not userinfo or not rest:
        return url, None, ""
    return scheme + "://", userinfo, rest
'''

text = TARGET.read_text(encoding="utf-8")
marker = "def _split_rtsp_userinfo(url):"
if marker not in text:
    print("GAGAL: fungsi tidak ditemukan")
    sys.exit(1)
if "@\" PERTAMA setelah" in text:
    print("LEWATI: sudah diperbaiki")
    sys.exit(0)

start = text.index(marker)
end = text.index("def normalize_rtsp_path(", start)
TARGET.write_text(text[:start] + NEW_FUNC + "\n\n" + text[end:], encoding="utf-8")
print("DIGANTI: _split_rtsp_userinfo")
