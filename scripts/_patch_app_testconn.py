"""Patch sekali pakai: ganti logika validasi kredensial di zm_connection_test.

Jalankan dari root repo:
    docker run --rm -v "$PWD":/w -w /w python:3.12-alpine python scripts/_patch_app_testconn.py
"""
from pathlib import Path

TARGET = Path("html_dashboard/app.py")

OLD = '''    result["zm_version"] = data.get("version")
    token = data.get("access_token")

    # ZM hanya mengembalikan access_token bila autentikasi diaktifkan. Saat
    # ZM_OPT_USE_AUTH=0, API memang terbuka dan token bernilai null — ini
    # bukan kegagalan, karena dashboard memakai cookie sesi ZM.
    if token:
        result["authenticated"] = True
        result["message"] = f"Kredensial valid. ZoneMinder v{result['zm_version'] or '?'}."
        return result

    try:
        probe = requests.get(
            f"{ZM_BASE_URL}/monitors.json", params={"limit": 1}, timeout=10, verify=False
        )
    except Exception as exc:
        result["message"] = f"Login OK tetapi API tidak dapat dijangkau: {exc}"
        return result

    if probe.status_code == 200:
        result["authenticated"] = True
        result["message"] = (
            f"Terhubung. ZoneMinder v{result['zm_version'] or '?'} berjalan dengan "
            "autentikasi internal NONAKTIF (ZM_OPT_USE_AUTH=0), sehingga login "
            "mengembalikan token kosong dan dashboard memakai cookie sesi ZM."
        )
    elif probe.status_code in (401, 403):
        result["message"] = (
            f"Login ditolak (HTTP {probe.status_code}). Periksa username/password ZM."
        )
    else:
        result["message"] = f"API ZoneMinder mengembalikan HTTP {probe.status_code}."
    return result
'''

NEW = """    result["zm_version"] = data.get("version")
    token = data.get("access_token")

    # PENTING: access_token VALID (bukan None) hanya ada saat
    # API_OPT_USE_AUTH=1, dan saat itu token memang membuktikan password benar.
    if token:
        result["authenticated"] = True
        result["message"] = f"Kredensial valid. ZoneMinder v{result['zm_version'] or '?'}."
        return result

    # Di sini token kosong, dan itu BUKAN bukti password benar: saat
    # API_OPT_USE_AUTH=0, ZoneMinder mengembalikan access_token=null TANPA
    # memeriksa kredensial sama sekali. Versi lama kode ini lalu memanggil
    # /monitors.json tanpa token; karena API memang terbuka, hasilnya 200 dan
    # password salah pun dilaporkan "authenticated: true". Operator dikira
    # sudah benar, lalu bingung saat error muncul belakangan sebagai
    # "Unable to authenticate user from auth hash" di log ZoneMinder.
    #
    # Jadi jalur API tidak dapat dipakai memvalidasi kredensial. Satu-satunya
    # validator sebenarnya adalah login web (ZM_ENABLE_AUTH_ADMIN=1).
    if zm_web_auth_enabled():
        probe_session = requests.Session()
        probe_session.verify = False
        ok, message = zm_cookie_login(probe_session, creds["user"], creds["pass"])
        result["authenticated"] = ok
        result["detail"] = message
        if ok:
            result["message"] = (
                f"Kredensial valid (login web ZoneMinder diverifikasi). "
                f"ZoneMinder v{result['zm_version'] or '?'}."
            )
        else:
            result["message"] = (
                "Password ZoneMinder DITOLAK oleh login web. Periksa ZM_USER/ZM_PASS "
                "di .env. Catatan: nilai ini adalah password akun WEB ZoneMinder "
                "(Options > Users), bukan password database MySQL."
            )
        return result

    result["authenticated"] = False
    result["message"] = (
        f"ZoneMinder terjangkau (v{result['zm_version'] or '?'}), tetapi kredensial "
        "TIDAK dapat diverifikasi: API_OPT_USE_AUTH=0 dan ZM_ENABLE_AUTH_ADMIN=0. "
        "Set ZM_ENABLE_AUTH_ADMIN=1 di .env agar dashboard benar-benar menguji "
        "password, atau verifikasi manual di ZoneMinder > Options > Users."
    )
    return result
"""


def main() -> int:
    raw = TARGET.read_bytes()
    crlf = b"\r\n" in raw
    text = raw.decode("utf-8").replace("\r\n", "\n")

    if "zm_cookie_login(probe_session" in text:
        print("SKIP: patch sudah terpasang")
        return 0
    if OLD not in text:
        print("FAIL: blok lama tidak ditemukan - file berubah, periksa manual")
        return 1

    text = text.replace(OLD, NEW, 1)
    out = text.replace("\n", "\r\n") if crlf else text
    TARGET.write_bytes(out.encode("utf-8"))
    print("OK: zm_connection_test dipatch")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
