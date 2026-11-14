"""Patch: ganti login cookie ZoneMinder di zm_authenticated_session."""
from pathlib import Path

TARGET = Path("html_dashboard/app.py")

OLD = '''        # Tanpa token (mis. kredensial terisi tetapi autentikasi ZM dimatikan),
        # login cookie tetap dicoba agar instalasi lama tetap berjalan.
        if not ZM_SESSION.cookies.get_dict():
            try:
                ZM_SESSION.post(
                    f"{ZM_HOST}/zm/index.php",
                    data={
                        "username": zm_credentials.user,
                        "password": zm_credentials.password,
                        "action": "login",
                    },
                    timeout=10,
                )
            except Exception as e:
                log.error("Login cookie ZoneMinder gagal: %s", e)
        ZM_SESSION_AUTHED = bool(ZM_SESSION.cookies.get_dict())
        return ZM_SESSION, None
'''

NEW = '''        # --- Jalur cookie sesi (butuh ZM_ENABLE_AUTH_ADMIN=1 di ZoneMinder) ---
        #
        # JANGAN mengirim form login saat autentikasi web ZM mati. Setiap POST
        # ke /zm/index.php yang berakhir di jalur "permintaan tidak sah"
        # menulis baris ini ke /var/log/zoneminder/web_php.log:
        #     ERR Unable to authenticate user from auth hash '<md5>'  auth.php:217
        # Versi lama kode ini mengirim form dengan field username/password
        # polos (bukan skema state-secret v1.36), sehingga SELALU ditolak dan
        # SELALU menulis error di atas - berulang tiap interval pengecekan.
        #
        # Aturan sekarang:
        #   1. Login hanya dicoba bila ZM_ENABLE_AUTH_ADMIN=1.
        #   2. Hasil percobaan di-cache (ZM_LOGIN_RESULT). Password salah tidak
        #      pernah dikirim ulang, sehingga log ZM tidak dibanjiri error.
        #   3. Kredensial baru (disimpan dari halaman Pengaturan) mereset cache.
        global ZM_LOGIN_RESULT

        if not zm_web_auth_enabled():
            ZM_SESSION_AUTHED = False
            return ZM_SESSION, None

        if ZM_SESSION.cookies.get_dict():
            ZM_SESSION_AUTHED = True
            return ZM_SESSION, None

        if ZM_LOGIN_RESULT[0] is False:
            # Sudah gagal sebelumnya dengan kredensial yang sama - jangan ulangi.
            ZM_SESSION_AUTHED = False
            return ZM_SESSION, None

        ok, message = zm_cookie_login(
            ZM_SESSION, zm_credentials.user, zm_credentials.password
        )
        ZM_LOGIN_RESULT = (ok, message, time.time())
        if not ok:
            log.warning(
                "Login web ZoneMinder GAGAL: %s Percobaan ulang otomatis "
                "DIHENTIKAN agar log ZoneMinder tidak dipenuhi error. Perbaiki "
                "ZM_USER/ZM_PASS di halaman Pengaturan atau file .env, lalu "
                "simpan ulang kredensial untuk mencoba lagi.",
                message,
            )
        ZM_SESSION_AUTHED = ok
        return ZM_SESSION, None
'''

OLD_STATE = "ZM_SESSION = requests.Session()\nZM_SESSION.verify = False\nZM_SESSION_AUTHED = False"
NEW_STATE = (
    "ZM_SESSION = requests.Session()\n"
    "ZM_SESSION.verify = False\n"
    "ZM_SESSION_AUTHED = False\n"
    "# Hasil percobaan login web terakhir: (berhasil, pesan, waktu).\n"
    "# Dipakai agar password salah TIDAK dikirim berulang kali - setiap\n"
    "# pengiriman yang ditolak menulis error auth ke log ZoneMinder.\n"
    "ZM_LOGIN_RESULT = (None, \"\", 0)"
)

OLD_INVALIDATE = '''    global ZM_TOKEN, ZM_SESSION_AUTHED
    ZM_TOKEN = None
    ZM_SESSION_AUTHED = False
    try:
        ZM_SESSION.cookies.clear()
    except Exception:
        pass'''

NEW_INVALIDATE = '''    global ZM_TOKEN, ZM_SESSION_AUTHED, ZM_LOGIN_RESULT
    ZM_TOKEN = None
    ZM_SESSION_AUTHED = False
    # Kredensial baru disimpan: izinkan satu percobaan login lagi.
    ZM_LOGIN_RESULT = (None, "", 0)
    try:
        ZM_SESSION.cookies.clear()
    except Exception:
        pass'''


def main() -> int:
    raw = TARGET.read_bytes()
    crlf = b"\r\n" in raw
    text = raw.decode("utf-8").replace("\r\n", "\n")

    if "ZM_LOGIN_RESULT" in text:
        print("SKIP: patch sudah terpasang")
        return 0

    for label, old in (("session", OLD), ("state", OLD_STATE), ("invalidate", OLD_INVALIDATE)):
        if old not in text:
            print("FAIL: blok %s tidak ditemukan" % label)
            return 1

    text = text.replace(OLD, NEW, 1)
    text = text.replace(OLD_STATE, NEW_STATE, 1)
    text = text.replace(OLD_INVALIDATE, NEW_INVALIDATE, 1)

    out = text.replace("\n", "\r\n") if crlf else text
    TARGET.write_bytes(out.encode("utf-8"))
    print("OK: login cookie ZoneMinder dipatch")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
