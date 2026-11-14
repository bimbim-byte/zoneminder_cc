"""Ganti zm_cookie_login dengan skema yang TERBUKTI bekerja di ZM 1.36.

Temuan uji (bukti di dalam container ZoneMinder):
  POST /zm/index.php  {username, password, action=login}
  -> menulis "Login successful for user ..." di auth.php:372 dan sesi jadi sah.
  Skema state-secret (secret__user[username] dst.) -> HTTP 403, sesi TIDAK sah
  walaupun cookie ZMSESSID baru ikut dikirim.

Jadi bentuk field yang benar adalah yang lama. Yang salah pada kode lama
bukan bentuknya, melainkan (a) dipakai saat autentikasi web mati dan
(b) diulang terus walaupun password ditolak.
"""
from pathlib import Path

TARGET = Path("html_dashboard/app.py")

OLD = '''def zm_cookie_login(session, user: str, password: str, timeout: float = 10):
    """Login web ZoneMinder memakai skema state-secret v1.36.'''

MARKER_END = '''    return False, "ZoneMinder menolak login web (tidak ada cookie sesi yang diberikan)."
'''

NEW = '''def zm_cookie_login(session, user: str, password: str, timeout: float = 10):
    """Login web ZoneMinder memakai form kredensial standar.

    Bentuk field di sini SUDAH DIUJI langsung terhadap ZoneMinder 1.36
    (lihat scripts/diagnose_zm_auth.php):

        POST /zm/index.php  {username, password, action=login}

    Hasil uji: auth.php:372 menulis "Login successful for user ..." dan sesi
    menjadi sah. Skema lain (field ber-prefix state-secret) dibalas HTTP 403
    dan sesinya TIDAK sah walaupun cookie ZMSESSID baru ikut dikirim - karena
    itu keberhasilan diperiksa dari isi halaman, bukan dari ada-tidaknya cookie.

    Mengembalikan (berhasil, pesan).
    """
    payload = {
        "username": user,
        "password": password,
        "action": "login",
    }

    try:
        res = session.post(
            f"{ZM_HOST}/zm/index.php",
            data=payload,
            timeout=timeout,
            verify=False,
            allow_redirects=True,
        )
    except Exception as exc:
        return False, f"Tidak dapat menghubungi halaman login ZoneMinder: {exc}"

    if res.status_code >= 500:
        return False, f"Halaman login ZoneMinder bermasalah (HTTP {res.status_code})."

    # Halaman login yang ditolak tetap dibalas HTTP 200, jadi keberhasilan
    # diperiksa dari isi halaman: form login muncul kembali berarti gagal.
    body = res.text or ""
    if "Invalid username or password" in body:
        return False, "ZoneMinder menolak username/password (Invalid username or password)."

    if 'name="username"' in body and "logout" not in body.lower():
        return False, "ZoneMinder menampilkan form login kembali - kredensial ditolak."

    return True, "Login web ZoneMinder berhasil."
'''


def main() -> int:
    raw = TARGET.read_bytes()
    crlf = b"\r\n" in raw
    text = raw.decode("utf-8").replace("\r\n", "\n")

    if "form kredensial standar" in text:
        print("SKIP: patch sudah terpasang")
        return 0

    start = text.find(OLD)
    if start < 0:
        print("FAIL: awal blok zm_cookie_login tidak ditemukan")
        return 1
    end = text.find(MARKER_END, start)
    if end < 0:
        print("FAIL: akhir blok zm_cookie_login tidak ditemukan")
        return 1
    end += len(MARKER_END)

    text = text[:start] + NEW + text[end:]
    out = text.replace("\n", "\r\n") if crlf else text
    TARGET.write_bytes(out.encode("utf-8"))
    print("OK: zm_cookie_login diperbaiki")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
