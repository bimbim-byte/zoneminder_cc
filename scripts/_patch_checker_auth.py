"""Patch: hentikan banjir error auth ZoneMinder dari cctv_checker.

Root cause:
  wait_for_zoneminder() memanggil GET {ZM_HOST}/zm/ tanpa kredensial. Pada
  instalasi dengan autentikasi web menyala, setiap permintaan tidak sah
  menulis ke /var/log/zoneminder/web_php.log:
      ERR Unable to authenticate user from auth hash '<md5>'  auth.php:217
"""
from pathlib import Path

TARGET = Path("cctv_checker/main.py")

OLD_WAIT = '''def wait_for_zoneminder():
    """Menunggu web server ZoneMinder siap menerima request."""
    print("[CHECKER] Menunggu service ZoneMinder siap...", flush=True)
    for _ in range(30):
        try:
            res = zm_session.get(f"{ZM_HOST}/zm/", timeout=3)
            if res.status_code == 200:
                print("[CHECKER] Service ZoneMinder terhubung dan siap!", flush=True)
                return True
        except Exception:
            pass
        time.sleep(2)
    print("[CHECKER] Melanjutkan inisialisasi...", flush=True)
    return False
'''

NEW_WAIT = '''def wait_for_zoneminder():
    """Menunggu ZoneMinder siap TANPA menyentuh halaman berautentikasi.

    PENTING - jangan kembalikan ini menjadi GET {ZM_HOST}/zm/.
    Halaman /zm/ adalah halaman berautentikasi. Setiap permintaan tanpa sesi
    yang sah membuat ZoneMinder menulis baris error berikut ke
    /var/log/zoneminder/web_php.log:
        ERR Unable to authenticate user from auth hash '<md5>'  auth.php:217
    Versi lama fungsi ini memanggilnya sampai 30 kali per start container,
    sehingga log ZoneMinder penuh error auth yang sebenarnya tidak berbahaya
    tetapi membuat operator mengira ada masalah kredensial.

    Tujuan fungsi ini hanya memastikan web server ZM sudah menerima koneksi,
    jadi cukup pakai endpoint API host (tanpa kredensial, tanpa sesi). Bila
    endpoint itu membalas HTTP apa pun, artinya web server sudah hidup.
    """
    print("[CHECKER] Menunggu service ZoneMinder siap...", flush=True)
    probe_url = f"{ZM_HOST}/zm/api/host/getVersion.json"
    for _ in range(30):
        try:
            res = zm_session.get(probe_url, timeout=3, verify=False)
            if res.status_code:
                print(
                    f"[CHECKER] Service ZoneMinder terhubung (HTTP {res.status_code}).",
                    flush=True,
                )
                return True
        except Exception:
            pass
        time.sleep(2)
    print("[CHECKER] Melanjutkan inisialisasi...", flush=True)
    return False
'''

OLD_LOGIN = '''def zm_login():
    """Autentikasi ke ZoneMinder API jika AUTH aktif."""
    global access_token
    login_url = f"{ZM_HOST}/zm/api/host/login.json"
    payload = {"user": ZM_USER, "pass": ZM_PASS}
    try:
        res = zm_session.post(login_url, data=payload, verify=False, timeout=8)
        if res.status_code == 200:
            data = res.json()
            access_token = data.get("access_token")
            if access_token:
                print(f"[ZM API] Login berhasil! Token diperoleh.", flush=True)
            else:
                print(f"[ZM API] ZoneMinder berjalan (auth token opsional).", flush=True)
            return True
        else:
            print(f"[ZM API] Login status: {res.status_code}", flush=True)
            return False
    except Exception as e:
        print(f"[ZM API ERROR] Gagal koneksi login ZM: {e}", flush=True)
        return False
'''

NEW_LOGIN = '''def zm_login(force=False):
    """Autentikasi ke ZoneMinder API jika AUTH aktif.

    Hasil login di-cache (ZM_LOGIN_FAILED) supaya kredensial yang ditolak
    tidak dikirim berulang kali. Checker berjalan tiap interval, jadi tanpa
    cache satu password salah menghasilkan banjir error di log ZoneMinder.
    """
    global access_token, ZM_LOGIN_FAILED
    if ZM_LOGIN_FAILED and not force:
        return False
    login_url = f"{ZM_HOST}/zm/api/host/login.json"
    payload = {"user": ZM_USER, "pass": ZM_PASS}
    try:
        res = zm_session.post(login_url, data=payload, verify=False, timeout=8)
        if res.status_code == 200:
            data = res.json()
            access_token = data.get("access_token")
            ZM_LOGIN_FAILED = False
            if access_token:
                print("[ZM API] Login berhasil! Token diperoleh.", flush=True)
            else:
                # access_token null = API_OPT_USE_AUTH=0; API terbuka sehingga
                # tidak ada kredensial yang bisa divalidasi dari jalur ini.
                print("[ZM API] ZoneMinder berjalan (auth token opsional).", flush=True)
            return True
        print(f"[ZM API] Login status: {res.status_code}", flush=True)
        ZM_LOGIN_FAILED = True
        return False
    except Exception as e:
        print(f"[ZM API ERROR] Gagal koneksi login ZM: {e}", flush=True)
        return False
'''

OLD_STATE = "zm_session = requests.Session()\naccess_token = None"
NEW_STATE = (
    "zm_session = requests.Session()\n"
    "zm_session.verify = False\n"
    "access_token = None\n"
    "# Penanda login terakhir gagal. Mencegah percobaan login berulang yang\n"
    "# membanjiri log ZoneMinder dengan error autentikasi.\n"
    "ZM_LOGIN_FAILED = False"
)


def main() -> int:
    raw = TARGET.read_bytes()
    crlf = b"\r\n" in raw
    text = raw.decode("utf-8").replace("\r\n", "\n")

    if "ZM_LOGIN_FAILED" in text:
        print("SKIP: patch sudah terpasang")
        return 0

    for label, old in (("wait", OLD_WAIT), ("login", OLD_LOGIN), ("state", OLD_STATE)):
        if old not in text:
            print("FAIL: blok %s tidak ditemukan" % label)
            return 1

    text = text.replace(OLD_WAIT, NEW_WAIT, 1)
    text = text.replace(OLD_LOGIN, NEW_LOGIN, 1)
    text = text.replace(OLD_STATE, NEW_STATE, 1)

    out = text.replace("\n", "\r\n") if crlf else text
    TARGET.write_bytes(out.encode("utf-8"))
    print("OK: cctv_checker dipatch")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
