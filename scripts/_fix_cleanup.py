"""Buang sisa kode skema state-secret yang tidak terbukti, dan rapikan
zm_login_mode yang menyesatkan.
"""
from pathlib import Path

TARGET = Path("html_dashboard/app.py")

OLD_BLOCK_START = "# Skema login web ZoneMinder v1.36 (WAJIB dipahami sebelum mengubah apa pun)"

OLD_TAIL = '''def zm_web_auth_enabled() -> bool:
    """True bila autentikasi web ZoneMinder (ZM_ENABLE_AUTH_ADMIN) menyala."""
    return os.environ.get("ZM_ENABLE_AUTH_ADMIN", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
'''

NEW_BLOCK = '''# Skema autentikasi web ZoneMinder v1.36 (WAJIB dipahami sebelum mengubah)
# ------------------------------------------------------------------------------
# ZoneMinder memakai DUA kredensial berbeda yang mudah tertukar:
#
#   1. PASSWORD API (API_OPT_USE_AUTH=1)
#      Divalidasi pada POST /zm/api/host/login.json. Bila DIMATIKAN, endpoint
#      itu mengembalikan access_token null TANPA memeriksa password sama
#      sekali. Artinya di instalasi default, memanggilnya berulang kali selalu
#      "berhasil" - tidak menghasilkan satu baris log pun, dan tidak bisa
#      dipakai memvalidasi kredensial.
#
#   2. PASSWORD WEB / LOGIN (ZM_OPT_USE_AUTH=1)
#      Divalidasi pada POST /zm/index.php {username, password, action=login}.
#      Saat GAGAL, ZoneMinder menulis ke /var/log/zm/web_php.log:
#         ERR Login denied for user "admin"                 auth.php:322
#      Saat BERHASIL:
#         INF Login successful for user "admin"             auth.php:372
#
# Di samping itu ada mekanisme `auth hash` (ZM_AUTH_RELAY=hashed) untuk URL
# internal ZM (stream, gambar event, cron). Hash = md5 dari
# secret+user+password_di_database+IP+jam+hari+bulan+tahun. Bila hash yang
# dikirim tidak cocok, ZM menulis:
#         ERR Unable to authenticate user from auth hash '<md5>'    auth.php:217
# Error itu muncul saat nilai pembentuk hash berubah (pergantian jam, password
# user berubah, atau IP klien berubah) - bukan karena satu permintaan salah.
# Yang bisa dilakukan aplikasi: jangan memicu jalur itu berulang kali.
ZM_CSRF_FIELD = "__csrf_magic"


def zm_web_auth_enabled() -> bool:
    """True bila autentikasi web ZoneMinder (ZM_ENABLE_AUTH_ADMIN) menyala.

    Nilai ini menentukan apakah dashboard boleh mengirim form login ke
    /zm/index.php. Saat autentikasi web mati, mengirim form tetap menulis
    "Login denied" ke log ZoneMinder - jadi pengiriman WAJIB dilewati.
    """
    return os.environ.get("ZM_ENABLE_AUTH_ADMIN", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def zm_login_mode() -> str:
    """Mode autentikasi ZM yang dipakai dashboard."""
    return "cookie" if zm_web_auth_enabled() else "token"
'''


def main() -> int:
    raw = TARGET.read_bytes()
    crlf = b"\r\n" in raw
    text = raw.decode("utf-8").replace("\r\n", "\n")

    if "Dua kredensial berbeda" in text or "auth hash` (ZM_AUTH_RELAY=hashed)" in text:
        print("SKIP: patch sudah terpasang")
        return 0

    start = text.find(OLD_BLOCK_START)
    if start < 0:
        print("FAIL: awal blok skema tidak ditemukan")
        return 1
    # mundur ke awal baris komentar pembuka
    line_start = text.rfind("\n# ", 0, start)
    if line_start > 0:
        start = line_start + 1

    end = text.find(OLD_TAIL, start)
    if end < 0:
        print("FAIL: akhir blok skema tidak ditemukan")
        return 1
    end += len(OLD_TAIL)

    text = text[:start] + NEW_BLOCK + text[end:]

    if "def _zm_login_secret()" in text:
        s2 = text.find("def _zm_login_secret()")
        e2 = text.find("def zm_cookie_login", s2)
        if s2 > 0 and e2 > s2:
            text = text[:s2] + text[e2:]

    out = text.replace("\n", "\r\n") if crlf else text
    TARGET.write_bytes(out.encode("utf-8"))
    print("OK: sisa kode state-secret dibersihkan")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
