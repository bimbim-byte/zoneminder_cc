"""Menyatukan header navigasi pada halaman dashboard (dijalankan sekali).

Jalankan dari root repo:
    python3 scripts/_apply_headers.py

Yang dilakukan pada add_camera.html, burst.html, dan log_display.html:
  * blok <header> lama diganti placeholder <header id="dashHeader"></header>;
  * aksi penting (tombol "Daftarkan Semua", Refresh, Pause) dipindah ke toolbar
    halaman sendiri agar tidak hilang;
  * skrip app_shell.js dimuat sebelum </body>.

Setiap penggantian diverifikasi: bila pola tidak cocok persis, berkas tidak
diubah dan alasannya dilaporkan (tidak ada penulisan setengah jalan).
"""

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
DASH = REPO / "html_dashboard"

HEADER_RE = re.compile(r"[ \t]*<header>.*?</header>\n", re.S)

PLAN = {
    "add_camera.html": """  <!-- Header navigasi bersama: tautan ZoneMinder ditonjolkan + tombol logout -->
  <header id="dashHeader"></header>
""",
    "burst.html": """  <!-- Header navigasi bersama: tautan ZoneMinder ditonjolkan + tombol logout -->
  <header id="dashHeader"></header>
  <div class="page-toolbar">
    <span class="toolbar-info" id="summaryCounter">Total: 0 Kamera</span>
    <button id="btnSubmitAll" class="btn btn-success" disabled onclick="executeBurstAdd()">
      &#9889; Daftarkan Semua ke ZoneMinder
    </button>
  </div>
""",
    "log_display.html": """  <!-- Header navigasi bersama: tautan ZoneMinder ditonjolkan + tombol logout -->
  <header id="dashHeader"></header>
  <div class="page-toolbar">
    <span class="toolbar-info" id="logCountHeader">0 Entri Log</span>
    <button id="toggleRefreshBtn" class="btn btn-outline btn-small" onclick="toggleAutoRefresh()">
      &#9208; Pause Auto-Refresh
    </button>
    <button class="btn btn-primary btn-small" onclick="fetchLogsFromFile()">
      &#128260; Refresh
    </button>
  </div>
""",
}

TOOLBAR_CSS = """    /* Toolbar aksi halaman, berada di bawah header bersama. */
    .page-toolbar {
      display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
      padding: 9px 24px; background: #fff;
      border-bottom: 1px solid var(--border); flex-shrink: 0;
    }
    .page-toolbar .toolbar-info {
      font-size: 12.5px; color: var(--muted); font-weight: 600;
    }
    .page-toolbar .btn { height: 30px; font-size: 12px; padding: 0 12px; }

"""


def replace_header(path: pathlib.Path, replacement: str):
    text = path.read_text(encoding="utf-8")
    match = HEADER_RE.search(text)
    if not match:
        return False, "blok <header> tidak ditemukan"
    new_text = text[: match.start()] + replacement + text[match.end():]
    if new_text == text:
        return False, "tidak ada perubahan"
    path.write_text(new_text, encoding="utf-8")
    return True, "header diganti"


def add_toolbar_css(path: pathlib.Path):
    text = path.read_text(encoding="utf-8")
    if ".page-toolbar" in text:
        return True, "CSS toolbar sudah ada"
    if 'class="page-toolbar"' not in text and 'class="toolbar-info"' not in text:
        return True, "toolbar tidak dipakai, CSS dilewati"
    idx = text.find("</style>")
    if idx == -1:
        return False, "</style> tidak ditemukan"
    path.write_text(text[:idx] + TOOLBAR_CSS + text[idx:], encoding="utf-8")
    return True, "CSS toolbar disisipkan"


def ensure_shell_script(path: pathlib.Path):
    text = path.read_text(encoding="utf-8")
    if "app_shell.js" in text:
        return True, "app_shell.js sudah dimuat"
    idx = text.rfind("</body>")
    if idx == -1:
        return False, "</body> tidak ditemukan"
    loader = '  <script src="app_shell.js"></script>\n'
    path.write_text(text[:idx] + loader + text[idx:], encoding="utf-8")
    return True, "app_shell.js disisipkan"


def main() -> int:
    failures = []
    for name, replacement in PLAN.items():
        path = DASH / name
        if not path.is_file():
            failures.append(f"{name}: berkas tidak ada")
            continue

        ok, msg = replace_header(path, replacement)
        print(f"{name:20s} header : {'OK' if ok else 'LEWAT'} - {msg}")
        if not ok:
            failures.append(f"{name}: {msg}")
            continue

        for label, fn in (("css", add_toolbar_css), ("script", ensure_shell_script)):
            ok2, msg2 = fn(path)
            print(f"{'':20s} {label:7s}: {'OK' if ok2 else 'LEWAT'} - {msg2}")
            if not ok2:
                failures.append(f"{name}: {msg2}")

    print()
    if failures:
        print("MASALAH:")
        for f in failures:
            print("  -", f)
        return 1
    print("Semua header berhasil disatukan.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
