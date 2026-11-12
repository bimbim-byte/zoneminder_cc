"""Menambal scripts/_syntax_check.py agar mengabaikan baris komentar.

Alasan: blok komentar di docker-compose.yml menyebut nama variabel lama
(ZONEMINDER_PORT / DASHBOARD_PORT) untuk menjelaskan kenapa variabel itu
dihapus. Penyebutan di komentar bukan substitusi aktif, jadi tidak boleh
dianggap sebagai variabel yang wajib ada di .env.example.

Jalankan dari root repo: python3 html_dashboard/_patch_checker.py
"""

import pathlib

REPO = pathlib.Path(__file__).resolve().parent.parent
TARGET = REPO / "scripts" / "_syntax_check.py"

OLD = '    compose = (REPO / "docker-compose.yml").read_text(encoding="utf-8")\n'

NEW = (
    '    raw = (REPO / "docker-compose.yml").read_text(encoding="utf-8")\n'
    "\n"
    "    # Abaikan baris komentar: dokumentasi sering menyebut nama variabel\n"
    "    # lama (mis. ZONEMINDER_PORT) untuk menjelaskan kenapa ia dihapus.\n"
    "    compose = \"\\n\".join(\n"
    "        line for line in raw.splitlines() if not line.lstrip().startswith(\"#\")\n"
    "    )\n"
)


def main() -> int:
    if not TARGET.is_file():
        print("[GAGAL] tidak menemukan", TARGET)
        return 1

    text = TARGET.read_text(encoding="utf-8")
    if 'if not line.lstrip().startswith("#")' in text:
        print("[i] Sudah ditambal sebelumnya.")
        return 0

    if OLD not in text:
        print("[GAGAL] pola baris compose tidak ditemukan:")
        for i, line in enumerate(text.splitlines(), 1):
            if "docker-compose.yml" in line:
                print(f"  {i}: {line!r}")
        return 1

    TARGET.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")
    print("[OK] scripts/_syntax_check.py ditambal (komentar diabaikan).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
