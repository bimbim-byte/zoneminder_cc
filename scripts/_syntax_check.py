#!/usr/bin/env python3
"""Pemeriksaan sintaks cepat sebelum rebuild Docker.

Memeriksa tanpa mengubah apa pun:
  1. Python  : semua berkas .py dapat dikompilasi (compileall).
  2. HTML    : halaman dashboard tidak kosong, tag inti seimbang, dan tidak
               memuat placeholder Jinja yang tidak akan dirender Flask.
  3. JS      : berkas app_shell.js tidak kosong dan kurungnya seimbang
               (atau lolos `node --check` bila node tersedia).

Jalankan dari root repo:  python3 scripts/_syntax_check.py
"""

from __future__ import annotations

import json
import pathlib
import py_compile
import re
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
DASH = REPO / "html_dashboard"

PAGES = [
    "index.html",
    "zoneminder.html",
    "add_camera.html",
    "burst.html",
    "log_display.html",
    "settings.html",
    "login.html",
]

# login.html dirender Flask, jadi boleh berisi placeholder Jinja.
JINJA_ALLOWED = {"login.html"}

HTML_TAGS = ("html", "head", "body", "script", "style")

failures: list[str] = []


def ok(msg: str) -> None:
    print(f"  [ OK ]   {msg}")


def bad(msg: str) -> None:
    print(f"  [GAGAL]  {msg}")
    failures.append(msg)


# --------------------------------------------------------------------------- 1
def check_python() -> None:
    print("\n[1/3] Python")
    files = [
        p
        for p in REPO.rglob("*.py")
        if "__pycache__" not in p.parts and ".git" not in p.parts
    ]
    if not files:
        bad("tidak ada berkas .py ditemukan")
        return

    errors = []
    for path in sorted(files):
        try:
            py_compile.compile(str(path), doraise=True, cfile=str(REPO / "_pyc_tmp.pyc"))
        except py_compile.PyCompileError as exc:
            errors.append(f"{path.relative_to(REPO)}: {exc.msg.strip()}")
        except Exception as exc:  # pragma: no cover
            errors.append(f"{path.relative_to(REPO)}: {exc}")

    tmp = REPO / "_pyc_tmp.pyc"
    if tmp.exists():
        tmp.unlink()

    if errors:
        for err in errors:
            bad(err)
    else:
        ok(f"semua berkas .py dapat dikompilasi ({len(files)} berkas)")


# --------------------------------------------------------------------------- 2
def check_html() -> None:
    print("\n[2/3] HTML dashboard (keseimbangan tag)")

    for name in PAGES:
        path = DASH / name
        if not path.is_file():
            bad(f"{name}: berkas tidak ada")
            continue

        text = path.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            bad(f"{name}: berkas KOSONG")
            continue

        problems = []
        for tag in HTML_TAGS:
            opens = len(re.findall(rf"<{tag}[\s>]", text, re.I))
            closes = len(re.findall(rf"</{tag}>", text, re.I))
            if opens != closes:
                problems.append(f"<{tag}> buka={opens} tutup={closes}")

        if name not in JINJA_ALLOWED and ("{{" in text or "{%" in text):
            problems.append("berisi placeholder Jinja yang tidak akan dirender")

        if problems:
            bad(f"{name}: " + "; ".join(problems))
        else:
            ok(f"{name} ({len(text)} byte)")

    # app_shell.js wajib dirujuk minimal oleh halaman pengaturan.
    settings = (DASH / "settings.html").read_text(encoding="utf-8", errors="replace")
    if "app_shell.js" not in settings:
        bad("settings.html tidak memuat app_shell.js (header bersama hilang)")


# --------------------------------------------------------------------------- 3
def check_js() -> None:
    print("\n[3/3] JavaScript")
    targets = [DASH / "app_shell.js"]

    node = shutil.which("node")
    for path in targets:
        if not path.is_file() or not path.read_text(encoding="utf-8", errors="replace").strip():
            bad(f"{path.name}: kosong atau tidak ada")
            continue

        text = path.read_text(encoding="utf-8")

        if node:
            proc = subprocess.run(
                [node, "--check", str(path)], capture_output=True, text=True
            )
            if proc.returncode == 0:
                ok(f"{path.name} lolos {pathlib.Path(node).name} --check")
            else:
                bad(f"{path.name}: {(proc.stderr or proc.stdout).strip()[:200]}")
            continue

        unbalanced = []
        for open_ch, close_ch in (("{", "}"), ("(", ")"), ("[", "]")):
            if text.count(open_ch) != text.count(close_ch):
                unbalanced.append(
                    f"'{open_ch}{close_ch}' ({text.count(open_ch)} vs {text.count(close_ch)})"
                )
        if unbalanced:
            bad(f"{path.name}: kurung tidak seimbang -> " + ", ".join(unbalanced))
        else:
            ok(f"{path.name} seimbang (node tidak tersedia untuk cek penuh)")


# --------------------------------------------------------------------------- 4
def check_compose_env_vars() -> None:
    """Pastikan setiap variabel ${...} di compose punya pasangan di .env.example."""
    print("\n[4/4] Konsistensi variabel docker-compose")
    raw = (REPO / "docker-compose.yml").read_text(encoding="utf-8")
    compose = "\n".join(l for l in raw.splitlines() if not l.lstrip().startswith("#"))
    example_path = REPO / ".env.example"

    used = set(re.findall(r"\$\{([A-Z_][A-Z0-9_]*)", compose))
    if not used:
        bad("tidak ada variabel ditemukan di docker-compose.yml")
        return

    if not example_path.is_file():
        bad(".env.example tidak ditemukan")
        return

    documented = set(
        re.findall(r"^\s*([A-Z_][A-Z0-9_]*)=", example_path.read_text(encoding="utf-8"), re.M)
    )
    missing = sorted(used - documented)
    if missing:
        bad(".env.example belum memuat: " + ", ".join(missing))
    else:
        ok(f".env.example memuat seluruh {len(used)} variabel yang dipakai compose")


if __name__ == "__main__":
    print("=" * 56)
    print(" Pemeriksaan Sintaks & Konsistensi")
    print("=" * 56)
    check_python()
    check_html()
    check_js()
    check_compose_env_vars()

    print("\n" + "=" * 56)
    if failures:
        print(f" HASIL: {len(failures)} masalah ditemukan.")
    else:
        print(" HASIL: BERSIH.")
    print("=" * 56)
    sys.exit(1 if failures else 0)
