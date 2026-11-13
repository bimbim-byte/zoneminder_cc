"""Pemeriksa sintaks & keseimbangan blok JS untuk halaman dashboard.

Dipanggil di dalam container camera-dashboard. Tidak menyentuh jaringan atau
data produksi: hanya membaca berkas HTML dan melaporkan keseimbangan
kurung/kurawal pada setiap blok <script> inline. Ketidakseimbangan di sini
adalah penyebab paling umum halaman "diam" tanpa error yang terlihat.

BATASAN YANG DISENGAJA — BACA SEBELUM "MEMPERBAIKI" LAPORAN:
    Penghitung kurung ini adalah perkiraan kasar, BUKAN parser JavaScript.
    Ia menghasilkan LAPORAN PALSU pada konstruksi yang sah, dan itu sudah
    terverifikasi:

      - Template literal bersarang: Di dalam `${...}` ia menganggap backtick
        pembuka sebagai penutup string, lalu sisa berkas terbaca sebagai kode.
      - Regex literal yang memuat kurung atau kutip: `/\\d+\\.\\s*/`,
        `/'/g`, `/"&/g` — isi regex dihitung sebagai kurung kode.

    Pada keadaan ini skrip melaporkan "tidak seimbang" padahal parser V8
    menerima berkasnya. Pembuktiannya:

        docker run --rm \\
          -v "<repo>/data:/data:ro" \\
          -v "<repo>/html_dashboard:/app:ro" \\
          node:20-alpine node /data/zone_js_check.js \\
          /app/add_camera.html /app/burst.html /app/zoneminder.html

    Skrip data/zone_js_check.js memakai `vm.Script` (parser V8 sungguhan).
    Ia adalah sumber kebenaran; skrip ini hanya deteksi dini yang murah dan
    cepat, berguna ketika Node tidak tersedia (image dashboard hanya berisi
    Python).

    Jadi: JANGAN menambah backtick, kurung, atau escaped-quote hanya untuk
    membuat skrip ini diam. Yang berubah hanyalah pesan palsunya, sementara
    kode yang benar ikut dirusak. Bila skrip ini melapor RUSAK sementara
    zone_js_check.js melapor OK, percayai zone_js_check.js.
"""
import re
import sys
import xml.etree.ElementTree as ET

PAGES = ["/app/add_camera.html", "/app/burst.html", "/app/zoneminder.html"]

SCRIPT_RE = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S)
OPEN_CLOSE = [("{", "}"), ("(", ")"), ("[", "]")]


def strip_js_strings_and_comments(js):
    """Buang string literal, template literal, dan komentar.

    Tanpa langkah ini, tanda kurung di dalam teks (mis. pesan alert berisi
    "(zone dilewati)") dihitung sebagai kurung kode dan menghasilkan
    peringatan palsu.

    Catatan: `${...}` di dalam template literal TIDAK ditangani secara
    khusus — lihat batasan di docstring modul.
    """
    out = []
    i = 0
    n = len(js)
    while i < n:
        ch = js[i]
        nxt = js[i + 1] if i + 1 < n else ""

        if ch == "/" and nxt == "/":
            while i < n and js[i] != "\n":
                i += 1
            continue
        if ch == "/" and nxt == "*":
            i += 2
            while i < n - 1 and not (js[i] == "*" and js[i + 1] == "/"):
                i += 1
            i += 2
            continue
        if ch in "\"'`":
            quote = ch
            i += 1
            while i < n:
                if js[i] == "\\":
                    i += 2
                    continue
                if js[i] == quote:
                    i += 1
                    break
                i += 1
            out.append("S")  # penanda string, tidak dihitung sebagai kurung
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def check_page(path):
    try:
        html = open(path, encoding="utf-8").read()
    except OSError as exc:
        return [f"GAGAL MEMBACA: {exc}"], 0

    problems = []
    blocks = SCRIPT_RE.findall(html)
    for idx, js in enumerate(blocks, 1):
        clean = strip_js_strings_and_comments(js)
        for opener, closer in OPEN_CLOSE:
            diff = clean.count(opener) - clean.count(closer)
            if diff != 0:
                problems.append(
                    f"blok script #{idx}: '{opener}{closer}' tidak seimbang "
                    f"(selisih {diff:+d})"
                )
    return problems, len(blocks)


def main():
    total_problems = 0
    for page in PAGES:
        problems, blocks = check_page(page)
        status = "OK" if not problems else "PERLU DIPERIKSA (bisa jadi laporan palsu)"
        print(f"[{status}] {page} — {blocks} blok script inline")
        for p in problems:
            total_problems += 1
            print(f"        - {p}")

    if total_problems:
        print(
            f"\nHASIL: {total_problems} ketidakseimbangan kurung terdeteksi."
            "\nCATATAN: penghitung ini bukan parser JS. Template literal "
            "bersarang `${...}` dan regex literal yang memuat kurung/kutip "
            "menghasilkan laporan palsu. Jalankan pemeriksaan sebenarnya:"
            "\n    node /data/zone_js_check.js "
            "/app/add_camera.html /app/burst.html /app/zoneminder.html"
            "\n(lihat docstring modul untuk perintah docker lengkapnya)"
        )
        return 2
    print("\nHASIL: semua blok script seimbang.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
