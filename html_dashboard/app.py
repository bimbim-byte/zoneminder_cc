import json
import logging
import os
import re
import threading
from datetime import datetime, timedelta

import requests
from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    stream_with_context,
    url_for,
)

import auth as dash_auth
import token_crypto

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("dashboard")

app = Flask(__name__, static_folder=".", template_folder=".")

# ==============================================================================
# KONFIGURASI ENVIRONMENT
# ==============================================================================
ZM_HOST = os.environ.get("ZM_HOST", "http://zoneminder:80")
ZM_BASE_URL = os.environ.get("ZM_BASE_URL", f"{ZM_HOST}/zm/api")

MQTT_LOG_FILE = os.environ.get("MQTT_LOG_FILE", "/app/data/mqtt_logs.json")
CHECKER_CONFIG_FILE = os.environ.get("CHECKER_CONFIG_FILE", "/app/data/checker_config.json")

DASH_SECRET_KEY = os.environ.get("DASH_SECRET_KEY", "")
if not DASH_SECRET_KEY:
    # Tanpa kunci tetap, setiap restart akan membuat kunci acak baru:
    # semua sesi login dan brankas kredensial menjadi tidak dapat dibuka.
    log.warning(
        "DASH_SECRET_KEY kosong. Memakai kunci acak sementara — sesi login dan "
        "brankas kredensial TIDAK akan bertahan setelah restart. Isi di .env."
    )
    DASH_SECRET_KEY = os.urandom(32).hex()

DASH_USERS_FILE = os.environ.get("DASH_USERS_FILE", "/app/data/dashboard_users.json")
ZM_CREDENTIALS_FILE = os.environ.get("ZM_CREDENTIALS_FILE", "/app/data/zm_credentials.enc")

# Cookie sesi: HttpOnly mencegah pembacaan oleh JavaScript, SameSite=Lax
# mencegah pengiriman lintas situs (CSRF), Secure hanya saat HTTPS dipakai.
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "true").lower()
    in ("1", "true", "yes", "on"),
    PERMANENT_SESSION_LIFETIME=dash_auth.SESSION_TTL_SECONDS,
    MAX_CONTENT_LENGTH=32 * 1024 * 1024,
)

dashboard_auth = dash_auth.DashboardAuth(DASH_USERS_FILE)
zm_credentials = dash_auth.ZMCredentials(ZM_CREDENTIALS_FILE, DASH_SECRET_KEY)

if not token_crypto.crypto_available():
    log.warning(
        "Library 'cryptography' tidak tersedia — kredensial ZM akan jatuh ke "
        "environment dan TIDAK tersimpan terenkripsi."
    )

# Cache token auth ZM di memori. Direset saat kredensial berubah.
ZM_TOKEN = None


# ==============================================================================
# HELPER AUTH ZONEMINDER
# ==============================================================================
def zm_login_params():
    """Kredensial ZM efektif (brankas -> environment)."""
    return {"user": zm_credentials.user, "pass": zm_credentials.password}


def invalidate_zm_session():
    """Buang token & cookie ZM yang lama setelah kredensial berganti."""
    global ZM_TOKEN, ZM_SESSION_AUTHED, ZM_LOGIN_RESULT
    ZM_TOKEN = None
    ZM_SESSION_AUTHED = False
    # Kredensial baru disimpan: izinkan satu percobaan login lagi.
    ZM_LOGIN_RESULT = (None, "", 0)
    try:
        ZM_SESSION.cookies.clear()
    except Exception:
        pass


def get_zm_token():
    """Mengambil Access Token dari ZoneMinder API.

    PENTING (perilaku ZoneMinder v1.36 yang mudah menjebak):
    /zm/api/host/login.json mengembalikan access_token, tetapi TIDAK memasang
    cookie sesi apa pun pada responsnya. Artinya token itu satu-satunya bukti
    autentikasi untuk panggilan API berikutnya. Bila token tidak ikut dikirim
    (mis. karena nilainya None), ZM membalas HTTP 401 "Not Authenticated".

    Karena itu fungsi ini selalu mengembalikan token yang benar-benar baru
    diambil, bukan sekadar nilai cache global.
    """
    global ZM_TOKEN
    creds = zm_login_params()
    login_url = f"{ZM_HOST}/zm/api/host/login.json"
    try:
        res = requests.post(login_url, data=creds, timeout=8, verify=False)
        if res.status_code == 200:
            ZM_TOKEN = res.json().get("access_token") or None
            return ZM_TOKEN
        log.warning("Login ZoneMinder ditolak: HTTP %s", res.status_code)
        ZM_TOKEN = None
    except Exception as e:
        log.error("Auth ZoneMinder gagal: %s", e)
        ZM_TOKEN = None
    return ZM_TOKEN


_login_lock = threading.Lock()


def zm_authenticated_session():
    """Session requests yang PASTI terautentikasi ke ZoneMinder.

    Dua jalur autentikasi disiapkan sekaligus karena keduanya bergantung pada
    konfigurasi server:

      1. Cookie ZMSESSID — hasil login lewat /zm/index.php. Dipakai untuk
         endpoint non-API (mis. stream nph-zms).
      2. Access token — dikirim sebagai query string pada endpoint /api/*.
         Ini jalur utama: lihat catatan di get_zm_token().

    Mengembalikan (session, token). Token bisa None bila ZM menolak kredensial;
    pemanggil harus memperlakukan itu sebagai kegagalan autentikasi, bukan
    sebagai kondisi normal.
    """
    global ZM_SESSION_AUTHED
    with _login_lock:
        token = get_zm_token()
        if token:
            return ZM_SESSION, token

        # --- Jalur cookie sesi (butuh ZM_ENABLE_AUTH_ADMIN=1 di ZoneMinder) ---
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


def zm_connection_test(user=None, password=None):
    """Uji kredensial ZM tanpa menyimpannya. Dipakai oleh tombol Test Connection."""
    creds = {
        "user": user if user is not None else zm_credentials.user,
        "pass": password if password is not None else zm_credentials.password,
    }
    result = {"reachable": False, "authenticated": False, "zm_version": None, "message": ""}
    try:
        res = requests.post(
            f"{ZM_HOST}/zm/api/host/login.json", data=creds, timeout=10, verify=False
        )
    except Exception as exc:
        result["message"] = f"ZoneMinder tidak dapat dihubungi: {exc}"
        return result

    result["reachable"] = True
    if res.status_code != 200:
        result["message"] = f"ZoneMinder menolak permintaan login (HTTP {res.status_code})."
        return result

    try:
        data = res.json()
    except Exception:
        result["message"] = "Respons ZoneMinder bukan JSON."
        return result

    result["zm_version"] = data.get("version")
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


# ==============================================================================
# AUTENTIKASI DASHBOARD (login, logout, ganti password)
# ==============================================================================
dash_auth.install_auth(app, dashboard_auth, zm_credentials)

# Buat akun dashboard awal (admin / admin) bila belum ada. Tanpa langkah ini
# tidak ada satu pun user yang bisa login pada instalasi baru.
if dashboard_auth.bootstrap():
    log.warning(
        "Login pertama: gunakan admin / admin, lalu SEGERA ganti password "
        "di halaman Pengaturan (https://<host>:%s/settings).",
        os.environ.get("DASHBOARD_HTTPS_PORT", "9443"),
    )

if not zm_credentials.status().get("has_password"):
    log.warning(
        "Kredensial ZoneMinder belum tersimpan di brankas terenkripsi. "
        "Dashboard memakai nilai dari .env sampai Anda menyimpannya di halaman Pengaturan."
    )


COMPONENT_SEPARATOR = "/"

# Skema autentikasi web ZoneMinder v1.36 (WAJIB dipahami sebelum mengubah)
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


@app.route("/login", methods=["GET", "POST"])

def login():
    next_url = request.args.get("next") or ""
    error = ""

    if request.method == "POST":
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
        locked, remaining = dash_auth.is_locked_out(ip)
        if locked:
            error = f"Terlalu banyak percobaan login. Coba lagi dalam {remaining} detik."
            return render_template(
                "login.html", error=error, next_url=next_url, host_label=request.host
            ), 429

        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        ok, message = dashboard_auth.authenticate(username, password)
        if ok:
            dash_auth.clear_attempts(ip)
            session.clear()
            session["user"] = username
            session["issued_at"] = dash_auth.time.time()
            session.permanent = True

            entry = dashboard_auth.user(username) or {}
            if entry.get("must_change_password"):
                return redirect(url_for("settings") + "?force=1")
            return redirect(next_url if next_url.startswith("/") else url_for("index"))

        dash_auth.record_attempt(ip)
        error = message

    return render_template(
        "login.html", error=error, next_url=next_url, host_label=request.host
    )


@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# ==============================================================================
# 1. SERVING STATIC FILES & PAGES
# ==============================================================================
@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/healthz")
def healthz():
    """Probe sederhana untuk Docker healthcheck (tanpa data sensitif)."""
    return jsonify({"ok": True, "encryption": token_crypto.crypto_available()})


@app.route("/favicon.ico")
def favicon():
    return ("", 204)


@app.route("/<path:filename>")
def serve_static(filename):
    # Tidak ada lagi endpoint /api/config: kredensial ZM tidak pernah dikirim
    # ke browser. Halaman memanggil /api/* yang diproksi backend.
    if os.path.exists(os.path.join(".", filename)) and not filename.endswith((".py", ".enc", ".json")):
        return send_from_directory(".", filename)
    return jsonify({"error": "File tidak ditemukan"}), 404


# ==============================================================================
# 1b. PENGATURAN: KREDENSIAL ZONEMINDER + AKUN DASHBOARD
# ==============================================================================
@app.route("/settings")
def settings():
    return send_from_directory(".", "settings.html")


@app.route("/api/settings/status", methods=["GET"])
def settings_status():
    """Ringkasan status tanpa membocorkan password."""
    user = session.get("user")
    entry = dashboard_auth.user(user) or {}
    status = zm_credentials.status()
    return jsonify({
        "dashboard_user": user,
        "dashboard_display_name": dashboard_auth.display_name(user),
        "dashboard_hint": entry.get("hint", ""),
        "must_change_password": bool(entry.get("must_change_password")),
        "last_login": entry.get("last_login"),
        "zm": status,
    })


@app.route("/api/settings/credentials", methods=["POST"])
def settings_credentials():
    """Menyimpan kredensial ZM baru ke brankas terenkripsi."""
    body = request.json or {}
    user = (body.get("zm_user") or "").strip()
    password = body.get("zm_pass") or ""

    if not user:
        return jsonify({"status": "error", "message": "Username ZoneMinder wajib diisi."}), 400
    if not password:
        return jsonify({"status": "error", "message": "Password ZoneMinder wajib diisi."}), 400

    try:
        zm_credentials.save(user, password, updated_by=session.get("user", ""))
    except token_crypto.CredentialError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500
    except Exception as exc:
        log.exception("Gagal menyimpan kredensial ZM")
        return jsonify({"status": "error", "message": f"Gagal menyimpan: {exc}"}), 500

    invalidate_zm_session()

    # Verifikasi langsung: lebih baik memberi tahu operator sekarang daripada
    # membiarkan dashboard tampak normal lalu gagal di halaman lain.
    test = zm_connection_test(user, password)
    return jsonify({
        "status": "success",
        "message": "Kredensial ZoneMinder tersimpan terenkripsi.",
        "test": test,
    })


@app.route("/api/settings/test", methods=["POST"])
def settings_test():
    """Uji kredensial (tersimpan atau kandidat dari form) tanpa menyimpan."""
    body = request.json or {}
    user = body.get("zm_user")
    password = body.get("zm_pass")

    # Bila form tidak diisi, uji nilai yang tersimpan.
    if not user or password in (None, ""):
        test = zm_connection_test()
    else:
        test = zm_connection_test(user.strip(), password)

    return jsonify({"status": "success" if test.get("authenticated") else "error", "test": test})


@app.route("/api/settings/password", methods=["POST"])
def change_password():
    """Mengganti password dashboard (wajib saat masih memakai default)."""
    body = request.json or {}
    current = body.get("current_password") or ""
    new = body.get("new_password") or ""
    confirm = body.get("confirm_password") or ""
    hint = body.get("hint")

    if new != confirm:
        return jsonify({"status": "error", "message": "Konfirmasi password tidak sama."}), 400

    ok, message = dashboard_auth.change_password(
        session.get("user", ""), current, new, hint=hint
    )
    if not ok:
        return jsonify({"status": "error", "message": message}), 400

    return jsonify({
        "status": "success",
        "message": "Password dashboard berhasil diubah. Gunakan password baru saat login berikutnya.",
    })

# ==============================================================================
# 2. API PROXY KE ZONEMINDER
# ==============================================================================
@app.route("/api/zm/health.json", methods=["GET"])
@app.route("/zm/api/health.json", methods=["GET"])
def zm_health():
    """Status koneksi ZoneMinder untuk badge di halaman dashboard.

    Hanya mengembalikan status, versi, dan pesan — tidak pernah mengirim
    username/password ke browser.
    """
    test = zm_connection_test()
    if not test.get("authenticated"):
        log.warning("Health ZoneMinder gagal: %s", test.get("message"))
    return jsonify({
        "connected": bool(test.get("authenticated")),
        "reachable": bool(test.get("reachable")),
        "version": test.get("zm_version"),
        "message": test.get("message", ""),
    }), (200 if test.get("authenticated") else 502)


@app.route("/api/zm/<path:subpath>", methods=["GET", "POST", "PUT", "DELETE"])
@app.route("/zm/api/<path:subpath>", methods=["GET", "POST", "PUT", "DELETE"])
def proxy_zm(subpath):
    """Proxy umum ke API ZoneMinder.

    PENTING: permintaan dari browser TIDAK membawa kredensial ZM apa pun —
    itu disengaja, agar password ZM tidak pernah sampai ke sisi klien. Karena
    itu token autentikasi HARUS ditempelkan di sini. Tanpa langkah ini,
    ZoneMinder selalu membalas HTTP 401 "Not Authenticated" meskipun
    kredensial di brankas sudah benar, dan seluruh tabel kamera gagal dimuat.
    """
    url = f"{ZM_BASE_URL}/{subpath}"
    session, token = zm_authenticated_session()
    if not token and not session.cookies.get_dict():
        return jsonify({
            "error": "Kredensial ZoneMinder tidak valid. Periksa di halaman Pengaturan.",
            "success": False,
        }), 502

    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ("host", "cookie", "content-length")
    }

    # Token ditaruh di query string (jalur yang bekerja pada ZM 1.36).
    params = request.args.to_dict(flat=False)
    if token:
        params["token"] = [token]

    try:
        resp = session.request(
            method=request.method,
            url=url,
            headers=headers,
            data=request.get_data(),
            params=params,
            allow_redirects=False,
            timeout=15
        )

        # Header hop-by-hop (RFC 7230) HARUS dibuang saat mem-proxy.
        # Apache ZoneMinder mengirim "Keep-Alive" sejak KeepAlive diaktifkan;
        # bila diteruskan mentah, Waitress/WSGI menolaknya dengan
        # AssertionError dan request berakhir HTTP 500 (PEP 3333).
        excluded_headers = [
            "content-encoding",
            "content-length",
            "transfer-encoding",
            "connection",
            "keep-alive",
            "proxy-authenticate",
            "proxy-authorization",
            "te",
            "trailer",
            "upgrade",
        ]
        resp_headers = [
            (name, value)
            for (name, value) in resp.raw.headers.items()
            if name.lower() not in excluded_headers
        ]

        content = resp.content

        # Daftar monitor memuat field Path yang berisi rtsp://user:password@host.
        # Nilai itu TIDAK boleh sampai ke browser: halaman Kelola Kamera cukup
        # menampilkan host-nya. Payload JSON disaring di sini, bukan di sisi
        # klien, supaya kebocoran tidak bergantung pada perilaku JavaScript.
        if (
            resp.status_code == 200
            and "application/json" in resp.headers.get("Content-Type", "")
            and re.search(rb"monitors", subpath.encode() or b"")
        ):
            try:
                payload = json.loads(content.decode("utf-8"))
                if isinstance(payload, dict) and isinstance(payload.get("monitors"), list):
                    for item in payload["monitors"]:
                        target = item.get("Monitor") if isinstance(item, dict) else None
                        if isinstance(target, dict) and target.get("Path"):
                            target["Path"] = _redact_rtsp(target["Path"])
                    content = json.dumps(payload).encode("utf-8")
                    resp_headers = [(k, v) for k, v in resp_headers
                                    if k.lower() != "content-type"]
                    resp_headers.append(("Content-Type", "application/json"))
            except Exception as exc:
                log.warning("Gagal menyaring kredensial monitor: %s", exc)

        response = Response(content, resp.status_code, resp_headers)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "*"
        return response
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==============================================================================
# 3. API PENDAFTARAN KAMERA TUNGGAL (DIRECT RTSP KE ZONEMINDER)
# ==============================================================================
@app.route("/api/zoneminder/add-camera", methods=["POST"])
def add_single_camera():
    """Mendaftarkan kamera langsung dengan RTSP URL ke ZoneMinder."""
    data = request.json or {}

    raw_name = data.get("name", "").strip()
    source = data.get("source", "").strip()
    zm_function = data.get("zmFunction", "Monitor")
    width = str(data.get("width", "1920"))
    height = str(data.get("height", "1080"))
    max_fps = str(data.get("maxFps", ""))
    colorspace = str(data.get("colorspace", "4"))

    if not raw_name or not source:
        return jsonify({"status": "error", "message": "Nama kamera dan URL RTSP wajib diisi!"}), 400

    if not source.lower().startswith("rtsp://"):
        return jsonify({"status": "error", "message": "URL kamera harus diawali dengan rtsp://"}), 400

    clean_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", raw_name)

    token = get_zm_token()
    auth_param = f"?token={token}" if token else ""

    zm_payload = {
        "Monitor[Name]": clean_name,
        "Monitor[Type]": "Ffmpeg",
        "Monitor[Function]": zm_function,
        "Monitor[Enabled]": "1",
        "Monitor[Path]": source,
        "Monitor[Method]": "rtsp",
        "Monitor[Options]": "rtsp_transport=tcp",
        "Monitor[Width]": width,
        "Monitor[Height]": height,
        "Monitor[Colours]": colorspace,
        "Monitor[TargetColorspace]": "4",
        "Monitor[ServerId]": "0",
    }
    if max_fps:
        zm_payload["Monitor[MaxFPS]"] = max_fps

    try:
        res = requests.post(
            f"{ZM_HOST}/zm/api/monitors.json{auth_param}",
            data=zm_payload,
            timeout=10,
            verify=False
        )

        if res.status_code in [200, 201]:
            res_data = res.json()

            # Zone deteksi WAJIB ada, kalau tidak Modect tidak akan pernah
            # menghasilkan alarm (ZM hanya menilai gerakan di dalam zone).
            # Kegagalan zone tidak membatalkan pendaftaran kamera: kamera
            # tetap dibuat, dan status zone dilaporkan apa adanya ke UI.
            zone_result = {"created": False, "skipped": True,
                           "reason": "Pembuatan zone dinonaktifkan."}
            zone_mode = normalize_zone_mode(data.get("zoneMode"))
            if data.get("createZone", True) and zone_mode:
                # ZM 1.36 hanya membalas {"message":"Saved"} tanpa Id, jadi
                # urutannya: coba baca Id dari respons dulu (build lain bisa
                # menyertakannya), lalu cari berdasarkan nama.
                monitor = {}
                if isinstance(res_data, dict):
                    monitor = res_data.get("monitor", res_data) or {}
                    if isinstance(monitor, list) and monitor:
                        monitor = monitor[0].get("Monitor", monitor[0]) if isinstance(monitor[0], dict) else monitor[0]
                monitor_id = (monitor or {}).get("Id") or (res_data or {}).get("Id")
                if not monitor_id:
                    monitor_id = find_monitor_id_by_name(clean_name)

                if monitor_id:
                    zone_result = ensure_zone_for_monitor(
                        monitor_id,
                        mode_key=zone_mode,
                        overwrite=bool(data.get("overwriteZone", False)),
                        width=width,
                        height=height,
                    )
                else:
                    zone_result = {
                        "created": False, "skipped": False, "mode": zone_mode,
                        "reason": "ID monitor baru tidak ditemukan pada respons ZoneMinder.",
                    }

            MONITOR_CACHE["ts"] = 0

            message = f"Kamera '{clean_name}' berhasil didaftarkan ke ZoneMinder!"
            if zone_result.get("created"):
                message += f" Zone deteksi dibuat: {zone_result.get('label', zone_mode)}."
            elif zone_result.get("skipped"):
                message += f" Zone dilewati: {zone_result.get('reason', '-')}"
            else:
                message += f" PERINGATAN zone gagal: {zone_result.get('reason', '-')}"

            return jsonify({
                "status": "success",
                "message": message,
                "zone": zone_result,
                "data": res_data
            }), 200
        else:
            return jsonify({
                "status": "error",
                "message": f"ZoneMinder API Error ({res.status_code}): {res.text}"
            }), res.status_code

    except Exception as e:
        return jsonify({"status": "error", "message": f"Koneksi ke ZoneMinder gagal: {str(e)}"}), 500


# ==============================================================================
# 4. API BURST ADD MASSAL (UPGRADED)
# ==============================================================================
@app.route("/api/zoneminder/burst-add", methods=["POST"])
def burst_add_monitors():
    """Menambahkan daftar kamera CCTV secara massal (Burst Add) ke ZoneMinder."""
    data = request.json or {}
    monitors = data.get("monitors", [])

    if not monitors or not isinstance(monitors, list):
        return jsonify({"status": "error", "message": "Tidak ada data kamera yang dikirim!"}), 400

    token = get_zm_token()
    auth_param = f"?token={token}" if token else ""

    zone_mode = normalize_zone_mode(data.get("zoneMode"))
    create_zone = bool(data.get("createZone", True)) and zone_mode is not None
    overwrite_zone = bool(data.get("overwriteZone", False))

    results = []
    success_count = 0
    fail_count = 0
    zone_created = 0
    zone_skipped = 0
    zone_failed = 0

    for idx, item in enumerate(monitors):
        monitor_data = item.get("Monitor", item)
        name = monitor_data.get("Name", f"CCTV_{idx+1}")
        clean_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(name).strip())
        path = monitor_data.get("Path", "").strip()

        # Validasi dasar
        if not path or not path.lower().startswith("rtsp://"):
            fail_count += 1
            results.append({
                "name": clean_name,
                "status": "failed",
                "error": "URL RTSP tidak valid atau kosong"
            })
            continue

        # Format payload ZoneMinder
        payload = {
            "Monitor[Name]": clean_name,
            "Monitor[Type]": monitor_data.get("Type", "Ffmpeg"),
            "Monitor[Function]": monitor_data.get("Function", "Monitor"),
            "Monitor[Enabled]": "1",
            "Monitor[Path]": path,
            "Monitor[Method]": "rtsp",
            "Monitor[Options]": "rtsp_transport=tcp",
            "Monitor[Width]": str(monitor_data.get("Width", "1920")),
            "Monitor[Height]": str(monitor_data.get("Height", "1080")),
            "Monitor[Colours]": str(monitor_data.get("Colours", "4")),
            "Monitor[TargetColorspace]": "4",
            "Monitor[ServerId]": "0"
        }
        if monitor_data.get("MaxFPS"):
            payload["Monitor[MaxFPS]"] = str(monitor_data.get("MaxFPS"))

        try:
            res = requests.post(
                f"{ZM_HOST}/zm/api/monitors.json{auth_param}",
                data=payload,
                timeout=10,
                verify=False
            )
            res_json = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}

            if res.status_code in [200, 201] or "message" in res_json:
                success_count += 1
                entry = {"name": clean_name, "status": "success", "id": res_json.get("Id", "")}

                if create_zone:
                    monitor_id = res_json.get("Id")
                    if not monitor_id:
                        monitor = res_json.get("monitor", res_json)
                        if isinstance(monitor, list) and monitor:
                            monitor = monitor[0]
                        if isinstance(monitor, dict):
                            monitor_id = (monitor.get("Monitor", monitor) or {}).get("Id")
                    if not monitor_id:
                        # ZM 1.36 tidak menyertakan Id pada respons simpan.
                        monitor_id = find_monitor_id_by_name(clean_name)

                    # Mode zone per baris (dari kolom Excel) menang atas mode
                    # global. Nilai kosong/tidak dikenal jatuh ke mode global,
                    # sehingga berkas Excel lama tetap berperilaku sama.
                    row_mode = normalize_zone_mode(monitor_data.get("ZoneMode"))
                    effective_mode = row_mode or zone_mode

                    if monitor_id:
                        zr = ensure_zone_for_monitor(
                            monitor_id, mode_key=effective_mode, overwrite=overwrite_zone,
                            width=payload.get("Monitor[Width]"),
                            height=payload.get("Monitor[Height]"),
                        )
                        zr["mode_source"] = "baris" if row_mode else "global"
                    else:
                        zr = {"created": False, "skipped": False,
                              "reason": "ID monitor baru tidak ditemukan."}

                    if zr.get("created"):
                        zone_created += 1
                        entry["zone"] = "created"
                    elif zr.get("skipped"):
                        zone_skipped += 1
                        entry["zone"] = "skipped"
                        entry["zone_reason"] = zr.get("reason", "")
                    else:
                        zone_failed += 1
                        entry["zone"] = "failed"
                        entry["zone_reason"] = zr.get("reason", "")

                results.append(entry)
            else:
                fail_count += 1
                results.append({"name": clean_name, "status": "failed", "error": res.text[:120]})
        except Exception as e:
            fail_count += 1
            results.append({"name": clean_name, "status": "failed", "error": str(e)})

    MONITOR_CACHE["ts"] = 0

    return jsonify({
        "status": "completed",
        "total": len(monitors),
        "success_count": success_count,
        "fail_count": fail_count,
        "zone_mode": zone_mode,
        "zone_created_count": zone_created,
        "zone_skipped_count": zone_skipped,
        "zone_fail_count": zone_failed,
        "details": results
    })


# ==============================================================================
# 5. API MQTT LOGS
# ==============================================================================
def _redact_rtsp(text):
    """Buang kredensial dari URL RTSP apa pun di dalam sebuah string.

    Log lama (sebelum checker diperbaiki) memuat rtsp://user:pass@host di
    dalam payload. Nilai itu TIDAK boleh keluar ke browser, jadi disaring
    saat dibaca — bukan hanya saat ditulis.
    """
    if not isinstance(text, str) or "@" not in text or "rtsp://" not in text.lower():
        return text
    try:
        scheme, _, rest = text.partition("//")
        hostpart = rest.rsplit("@", 1)[-1]
        return f"{scheme}//{hostpart}" if hostpart else "rtsp://<kredensial-dihilangkan>"
    except Exception:
        return "<kredensial-dihilangkan>"


def _scrub_payload(value):
    """Rekursif: bersihkan rtsp_url dan kredensial di semua bentuk payload."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key == "rtsp_url":
                out[key] = _redact_rtsp(item)
            else:
                out[key] = _scrub_payload(item)
        return out
    if isinstance(value, list):
        return [_scrub_payload(item) for item in value]
    if isinstance(value, str):
        return _redact_rtsp(value)
    return value


def _mqtt_log_path():
    """Lokasi berkas log MQTT yang benar-benar dipakai.

    Ada dua kemungkinan: path dari environment (di dalam container:
    /app/data/mqtt_logs.json) atau berkas di direktori kerja sebagai
    cadangan untuk pengembangan tanpa Docker. Urutan ini harus sama dengan
    jalur tulis, kalau tidak penghapusan akan menyentuh berkas yang salah.
    """
    if os.path.exists(MQTT_LOG_FILE):
        return MQTT_LOG_FILE
    return "mqtt_logs.json"


# Penghapusan log menulis ulang seluruh berkas. Tanpa kunci ini, dua
# permintaan bersamaan (mis. dua tab browser) bisa saling menimpa dan
# menyisakan berkas setengah jadi.
_mqtt_log_lock = threading.Lock()


def _read_mqtt_logs_raw():
    """Baca berkas log apa adanya sebagai list. None bila berkas tidak ada."""
    target = _mqtt_log_path()
    if not os.path.exists(target):
        return None
    with open(target, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def _write_mqtt_logs_atomic(entries):
    """Tulis ulang berkas log secara atomik.

    Ditulis ke berkas sementara di direktori yang SAMA lalu di-rename.
    os.replace bersifat atomik pada filesystem yang sama, sehingga
    cctv_checker tidak pernah membaca berkas yang setengah tertulis saat
    penghapusan berjalan. Menulis langsung ke berkas tujuan akan
    meninggalkan JSON rusak bila proses berhenti di tengah jalan.
    """
    target = _mqtt_log_path()
    directory = os.path.dirname(os.path.abspath(target))
    os.makedirs(directory, exist_ok=True)
    tmp_path = target + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, target)
    return target


def _parse_log_timestamp(value):
    """Timestamp log berbentuk 'YYYY-MM-DD HH:MM:SS' -> datetime, atau None.

    Memakai datetime.strptime, BUKAN time.strptime: yang kedua mengembalikan
    struct_time yang tidak punya .strftime() maupun operator perbandingan,
    sehingga pemakaian di ringkasan langsung melempar AttributeError.
    """
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _log_cutoff_string(days):
    """Batas waktu 'N hari lalu' dalam format timestamp log yang sama.

    Perbandingan dilakukan sebagai string, dan itu aman khusus untuk format
    'YYYY-MM-DD HH:MM:SS': lebar tiap bagian tetap, urutan leksikografis
    identik dengan urutan waktu. Format lain (mis. RFC 2822) tidak boleh
    dibandingkan begitu.
    """
    cutoff = datetime.now() - timedelta(days=days)
    return cutoff.strftime("%Y-%m-%d %H:%M:%S")


@app.route("/api/mqtt-logs", methods=["GET"])
def get_mqtt_logs():
    """Membaca isi file log MQTT dan menyajikan dalam format JSON untuk log_display.html.

    Setiap payload disaring sebelum dikirim: URL RTSP tidak pernah lagi
    membawa user/password ke browser (lihat _redact_rtsp).

    Setiap entri juga diberi ``_id`` (indeksnya di dalam berkas). Indeks
    dipakai sebagai pegangan untuk menghapus satu entri tertentu, karena
    baris log tidak punya ID sendiri. Dikirim setelah penyaringan supaya
    urutannya selalu sama dengan isi berkas di server.
    """
    try:
        logs = _read_mqtt_logs_raw()
    except Exception as e:
        return jsonify({"error": f"Gagal membaca file log: {str(e)}"}), 500

    if logs is None:
        return jsonify([])

    out = []
    for index, entry in enumerate(logs):
        cleaned = _scrub_payload(entry)
        if isinstance(cleaned, dict):
            cleaned["_id"] = index
        out.append(cleaned)
    return jsonify(out)


@app.route("/api/mqtt-logs/summary", methods=["GET"])
def mqtt_logs_summary():
    """Ringkasan ukuran log untuk ditampilkan sebelum operator menghapus."""
    try:
        logs = _read_mqtt_logs_raw()
    except Exception as e:
        return jsonify({"status": "error", "message": f"Gagal membaca log: {e}"}), 500

    target = _mqtt_log_path()
    size = os.path.getsize(target) if os.path.exists(target) else 0
    entries = logs or []

    oldest = None
    newest = None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        ts = _parse_log_timestamp(entry.get("timestamp"))
        if ts is None:
            continue
        if oldest is None or ts < oldest:
            oldest = ts
        if newest is None or ts > newest:
            newest = ts

    return jsonify({
        "status": "ok",
        "count": len(entries),
        "bytes": size,
        "file": os.path.basename(target),
        "oldest": oldest.strftime("%Y-%m-%d %H:%M:%S") if oldest else None,
        "newest": newest.strftime("%Y-%m-%d %H:%M:%S") if newest else None,
    })


@app.route("/api/mqtt-logs", methods=["DELETE"])
def delete_mqtt_logs():
    """Menghapus entri log MQTT.

    Body JSON (semua opsional):
      mode      : "all" (default) | "ids" | "older_than"
      ids       : daftar indeks entri yang dihapus (mode="ids")
      older_than: jumlah HARI; entri lebih tua dari itu dibuang
                  (mode="older_than"). Nilai 0 = semua entri.

    Mengembalikan jumlah yang terhapus dan sisa entri, sehingga UI bisa
    melaporkan hasil sebenarnya, bukan menebak.

    Modul ini sengaja TIDAK menyentuh berkas lain: hanya log MQTT. Berkas
    konfigurasi checker dan kredensial tidak pernah ikut terhapus.
    """
    body = request.get_json(silent=True) or {}
    mode = str(body.get("mode") or "all").strip().lower()

    if mode not in ("all", "ids", "older_than"):
        return jsonify({
            "status": "error",
            "message": f"Mode hapus '{mode}' tidak dikenali. Pilihan: all, ids, older_than.",
        }), 400

    with _mqtt_log_lock:
        try:
            logs = _read_mqtt_logs_raw()
        except Exception as e:
            return jsonify({"status": "error", "message": f"Gagal membaca log: {e}"}), 500

        if logs is None:
            return jsonify({
                "status": "success", "deleted": 0, "remaining": 0,
                "message": "Berkas log belum ada — tidak ada yang perlu dihapus.",
            })

        before = len(logs)

        if mode == "all":
            kept = []
        elif mode == "ids":
            raw_ids = body.get("ids") or []
            if not isinstance(raw_ids, list):
                return jsonify({
                    "status": "error",
                    "message": "Parameter 'ids' harus berupa daftar angka.",
                }), 400
            try:
                drop = {int(str(x).strip()) for x in raw_ids}
            except (TypeError, ValueError):
                return jsonify({
                    "status": "error",
                    "message": "Parameter 'ids' berisi nilai yang bukan angka.",
                }), 400
            if not drop:
                return jsonify({
                    "status": "error",
                    "message": "Tidak ada entri yang dipilih untuk dihapus.",
                }), 400
            kept = [e for i, e in enumerate(logs) if i not in drop]
        else:  # older_than
            try:
                days = int(body.get("older_than", 0))
            except (TypeError, ValueError):
                return jsonify({
                    "status": "error",
                    "message": "Parameter 'older_than' harus berupa angka hari.",
                }), 400
            if days < 0:
                return jsonify({
                    "status": "error",
                    "message": "Parameter 'older_than' tidak boleh negatif.",
                }), 400

            cutoff = _log_cutoff_string(days)

            def _keep(entry):
                """Entri tanpa timestamp valid DIPERTAHANKAN.

                Log yang timestamp-nya tidak terbaca tidak boleh hilang
                hanya karena tidak bisa dibandingkan — kehilangan data
                diam-diam lebih buruk daripada menyisakan entri rusak.
                """
                if not isinstance(entry, dict):
                    return True
                stamp = entry.get("timestamp")
                if not stamp:
                    return True
                return str(stamp) >= cutoff

            kept = [e for e in logs if _keep(e)]

        deleted = before - len(kept)

        if deleted == 0:
            return jsonify({
                "status": "success",
                "deleted": 0,
                "remaining": before,
                "message": "Tidak ada entri yang memenuhi kriteria hapus.",
            })

        try:
            _write_mqtt_logs_atomic(kept)
        except Exception as e:
            log.exception("Gagal menulis ulang log MQTT")
            return jsonify({
                "status": "error",
                "message": f"Gagal menyimpan log setelah penghapusan: {e}",
            }), 500

    label = {"all": "semua entri", "ids": "entri terpilih",
             "older_than": "entri lama"}.get(mode, "entri")
    log.info("Log MQTT: %d entri dihapus (%s), sisa %d", deleted, label, len(kept))

    return jsonify({
        "status": "success",
        "deleted": deleted,
        "remaining": len(kept),
        "mode": mode,
        "message": f"{deleted} {label} dihapus. Sisa {len(kept)} entri.",
    })


# ==============================================================================
# 6. API KONTROL CCTV CHECKER (TOGGLE AKTIF/MATI & DELAY INTERVAL)
# ==============================================================================
def get_checker_config():
    default_cfg = {
        "enabled": False,
        "interval": 600,
        "rtsp_timeout": 3.0,
        "run_now": False,
        "status": "Paused",
        "last_check": None
    }
    if os.path.exists(CHECKER_CONFIG_FILE):
        try:
            with open(CHECKER_CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                default_cfg.update(saved)
        except Exception:
            pass
    return default_cfg


def save_checker_config(cfg):
    try:
        os.makedirs(os.path.dirname(CHECKER_CONFIG_FILE), exist_ok=True)
        with open(CHECKER_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        return True
    except Exception as e:
        print(f"[ERROR SAVE CHECKER CONFIG] {e}")
        return False


@app.route("/api/checker/config", methods=["GET", "POST"])
def manage_checker_config():
    """Endpoint untuk membaca dan memperbarui konfigurasi CCTV Checker."""
    cfg = get_checker_config()

    if request.method == "POST":
        data = request.json or {}
        if "enabled" in data:
            cfg["enabled"] = bool(data["enabled"])
            cfg["status"] = "Running" if cfg["enabled"] else "Paused"
        if "interval" in data:
            try:
                new_interval = max(5, int(data["interval"]))
                cfg["interval"] = new_interval
            except (ValueError, TypeError):
                pass
        if "rtsp_timeout" in data:
            try:
                cfg["rtsp_timeout"] = max(1.0, float(data["rtsp_timeout"]))
            except (ValueError, TypeError):
                pass

        save_checker_config(cfg)
        return jsonify({"status": "success", "message": "Konfigurasi checker berhasil disimpan!", "config": cfg})

    return jsonify(cfg)


@app.route("/api/checker/run-now", methods=["POST"])
def checker_run_now():
    """Memicu CCTV Checker untuk segera melakukan pengecekan tanpa menunggu interval."""
    cfg = get_checker_config()
    cfg["run_now"] = True
    save_checker_config(cfg)
    return jsonify({"status": "success", "message": "Trigger pengecekan segera dikirim ke checker!"})


# ==============================================================================
# 7. WALL DASHBOARD (GRID KAMERA + GROUP)
# ==============================================================================
MONITOR_CACHE = {"data": None, "ts": 0}
MONITOR_CACHE_TTL = 10  # detik

# Session persisten ke ZoneMinder. Berisi cookie ZMSESSID bila login web
# dipakai; jalur utama pada ZM v1.36 adalah access token pada query string
# (lihat get_zm_token), karena endpoint /zm/api/host/login.json tidak
# memasang cookie apa pun.
ZM_SESSION = requests.Session()
ZM_SESSION.verify = False
ZM_SESSION_AUTHED = False
# Hasil percobaan login web terakhir: (berhasil, pesan, waktu).
# Dipakai agar password salah TIDAK dikirim berulang kali - setiap
# pengiriman yang ditolak menulis error auth ke log ZoneMinder.
ZM_LOGIN_RESULT = (None, "", 0)


def zm_login_session():
    """Pastikan ada jalur autentikasi yang siap dipakai.

    Mengembalikan access_token bila ZM memberikannya, atau None bila ZM
    memakai autentikasi cookie murni.
    """
    session, token = zm_authenticated_session()
    if token is None and not session.cookies.get_dict():
        log.warning(
            "ZoneMinder tidak memberikan token maupun cookie. Periksa kredensial "
            "ZM di halaman Pengaturan."
        )
    return token


def zm_api_get(path, params=None, retry=True):
    """GET ke ZoneMinder API dengan access token (dan cookie bila ada).

    Bug lama: token hasil login TIDAK pernah ditempelkan ke query string,
    sehingga setiap GET berakhir HTTP 401 'Not Authenticated'. Token kini
    diambil langsung dari hasil login pada request yang sama.
    """
    session, token = zm_authenticated_session()

    q = dict(params or {})
    if token:
        q["token"] = token

    try:
        res = session.get(f"{ZM_BASE_URL}/{path}", params=q, timeout=10)

        if res.status_code in (401, 403) and retry:
            # Token/sesi basi: bersihkan lalu ulangi SEKALI dengan token baru.
            global ZM_SESSION_AUTHED
            ZM_SESSION.cookies.clear()
            ZM_SESSION_AUTHED = False
            return zm_api_get(path, params, retry=False)

        if res.status_code == 200:
            return res.json()
        log.warning("ZM GET %s -> HTTP %s", path, res.status_code)
    except Exception as e:
        log.error("ZM GET %s gagal: %s", path, e)
    return None


def normalize_monitor(raw):
    """Ambil field penting dari objek Monitor ZM."""
    m = raw.get("Monitor", raw) if isinstance(raw, dict) else {}

    # ZM mengirim GroupIds hanya jika monitor memang punya group.
    # Bila kosong, coba relasi Groups (perlu ?recursive=1).
    group_ids = m.get("GroupIds")
    if not group_ids:
        raw_groups = m.get("Groups") or m.get("Group")
        if isinstance(raw_groups, list):
            group_ids = ",".join(
                str(g.get("Id", "") if isinstance(g, dict) else g) for g in raw_groups
            )
        elif isinstance(raw_groups, dict):
            group_ids = str(raw_groups.get("Id", ""))
        else:
            group_ids = raw_groups or ""

    return {
        "id": str(m.get("Id", "")),
        "name": m.get("Name", "Unknown"),
        "function": m.get("Function", "None"),
        "enabled": str(m.get("Enabled", "0")) == "1",
        "width": m.get("Width", ""),
        "height": m.get("Height", ""),
        "capture_fps": m.get("CaptureFPS", ""),
        "path": _redact_rtsp(m.get("Path", "")),
        "group_ids": [g.strip() for g in str(group_ids).split(",") if g.strip()],
    }


def get_all_monitors_cached():
    """Daftar monitor dari ZM, di-cache sebentar agar tidak membanjiri ZM."""
    import time
    now = time.time()
    if MONITOR_CACHE["data"] and (now - MONITOR_CACHE["ts"]) < MONITOR_CACHE_TTL:
        return MONITOR_CACHE["data"]

    data = zm_api_get("monitors.json")
    if data is None:
        return MONITOR_CACHE["data"] or []

    monitors = [normalize_monitor(m) for m in data.get("monitors", [])]
    MONITOR_CACHE["data"] = monitors
    MONITOR_CACHE["ts"] = now
    return monitors


def get_groups_from_zm():
    """
    Daftar Group asli ZoneMinder (ZM >= 1.34).
    ZM mengirim tiap group dengan relasi 'Monitor' di dalamnya, jadi daftar
    anggota group sudah tersedia tanpa request tambahan.
    Mengembalikan None bila endpoint tidak didukung.
    """
    data = zm_api_get("groups.json")
    if not isinstance(data, dict):
        return None
    raw = data.get("groups")
    if not isinstance(raw, list):
        return None

    groups = []
    for g in raw:
        if not isinstance(g, dict):
            continue
        d = g.get("Group", g)
        gid = str(d.get("Id", "")).strip()
        if not gid:
            continue
        members = g.get("Monitor") or []
        if isinstance(members, dict):
            members = [members]
        groups.append({
            "id": gid,
            "name": d.get("Name", f"Group {gid}"),
            "monitors": [str(m.get("Id", "")) for m in members if isinstance(m, dict) and m.get("Id")],
        })
    return groups


@app.route("/api/cameras/groups", methods=["GET"])
def api_camera_groups():
    """
    Daftar Group + jumlah kamera per group.
    Prioritas: API ZoneMinder. Fallback: data/camera_groups.json (group lokal).
    """
    monitors = get_all_monitors_cached()
    groups = get_groups_from_zm()
    source = "zone_minder"

    if not groups:
        source = "local"
        local_file = os.environ.get("CAMERA_GROUPS_FILE", "/app/data/camera_groups.json")
        groups = []
        if os.path.exists(local_file):
            try:
                with open(local_file, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                for g in raw:
                    gid = str(g.get("id", "")).strip()
                    if not gid:
                        continue
                    groups.append({
                        "id": gid,
                        "name": g.get("name", f"Group {gid}"),
                        "monitors": [str(x) for x in g.get("monitors", [])],
                    })
            except Exception as e:
                print(f"[ERROR LOCAL GROUPS] {e}")

    for g in groups:
        # Group ZM: anggota sudah dari relasi Monitor. Fallback: cocokkan GroupIds.
        if not g.get("monitors"):
            g["monitors"] = [m["id"] for m in monitors if g["id"] in m["group_ids"]]
        g["camera_count"] = len(g["monitors"])

    return jsonify({
        "source": source,
        "total_cameras": len(monitors),
        "groups": groups,
    })


@app.route("/api/cameras/stream/<monitor_id>", methods=["GET"])
def api_camera_stream(monitor_id):
    """
    Proxy stream MJPEG dari ZoneMinder.
    ZM sudah multiplex stream: N klien menonton stream yang sama tidak menambah decode.
    Parameter: scale (mis. 320), maxfps
    """
    if not re.fullmatch(r"\d+", str(monitor_id)):
        return jsonify({"error": "ID kamera tidak valid"}), 400

    session, token = zm_authenticated_session()

    params = {"mode": "jpeg", "monitor": monitor_id}
    params["scale"] = request.args.get("scale", "320")
    # Batasi laju frame per kamera untuk menghemat bandwidth dan CPU ZM.
    params["maxfps"] = request.args.get("maxfps", "5")
    if token:
        params["token"] = token

    try:
        upstream = session.get(
            f"{ZM_HOST}/zm/cgi-bin/nph-zms",
            params=params,
            stream=True,
            timeout=(10, None),
        )
    except Exception as e:
        return jsonify({"error": f"Stream gagal: {e}"}), 502

    if upstream.status_code != 200:
        upstream.close()
        return jsonify({"error": f"ZoneMinder menolak stream ({upstream.status_code})"}), upstream.status_code

    content_type = upstream.headers.get("Content-Type", "multipart/x-mixed-replace; boundary=--myboundary")

    @stream_with_context
    def generate():
        try:
            for chunk in upstream.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk
        except Exception:
            pass
        finally:
            upstream.close()

    resp = Response(generate(), content_type=content_type)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp


# Wall Dashboard (wall.html / wall_view.html) DIHAPUS.
# Halaman pemilihan kamera dan grid live-nya tidak lagi disajikan, dan
# endpoint /api/cameras/wall ikut dihapus bersama halamannya.
# API group & normalisasi monitor TETAP dipertahankan karena dipakai oleh
# kontrol massal (bulk-function) dan pemetaan fungsi monitor.

# ==============================================================================
# 8. BULK CONTROL SELURUH KAMERA
# ==============================================================================
# ZM memakai "Function" sebagai mode operasi monitor. "None" = kamera mati.
ZM_OFF_FUNCTION = "None"
ZM_ACTIVE_FUNCTIONS = ("Monitor", "Modect", "Record", "Mocord", "Nodect")

# Catatan fungsi terakhir tiap kamera, supaya tombol "Aktifkan Semua" bisa
# mengembalikan mode asli (mis. Modect) dan bukan selalu jatuh ke Monitor.
CAMERA_FUNCTIONS_FILE = os.environ.get("CAMERA_FUNCTIONS_FILE", "/app/data/camera_functions.json")


def load_saved_functions():
    if os.path.exists(CAMERA_FUNCTIONS_FILE):
        try:
            with open(CAMERA_FUNCTIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
        except Exception as e:
            print(f"[ERROR LOAD CAMERA FUNCTIONS] {e}")
    return {}


def save_saved_functions(mapping):
    try:
        os.makedirs(os.path.dirname(CAMERA_FUNCTIONS_FILE), exist_ok=True)
        with open(CAMERA_FUNCTIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(mapping, f, indent=2)
    except Exception as e:
        print(f"[ERROR SAVE CAMERA FUNCTIONS] {e}")


def zm_post(path, data, retry=True):
    """POST form ke ZoneMinder API dengan access token pada query string."""
    session, token = zm_authenticated_session()

    q = {"token": token} if token else {}
    try:
        res = session.post(f"{ZM_BASE_URL}/{path}", params=q, data=data, timeout=15)
        if res.status_code in (401, 403) and retry:
            global ZM_SESSION_AUTHED
            ZM_SESSION.cookies.clear()
            ZM_SESSION_AUTHED = False
            return zm_post(path, data, retry=False)
        return res.status_code
    except Exception as e:
        log.error("ZM POST %s gagal: %s", path, e)
        return 0


def zm_delete(path, retry=True):
    """DELETE ke ZoneMinder API. Dipakai untuk membersihkan zone sementara."""
    session, token = zm_authenticated_session()

    q = {"token": token} if token else {}
    try:
        res = session.delete(f"{ZM_BASE_URL}/{path}", params=q, timeout=15)
        if res.status_code in (401, 403) and retry:
            global ZM_SESSION_AUTHED
            ZM_SESSION.cookies.clear()
            ZM_SESSION_AUTHED = False
            return zm_delete(path, retry=False)
        return res.status_code
    except Exception as e:
        log.error("ZM DELETE %s gagal: %s", path, e)
        return 0


# ==============================================================================
# 7b. ZONE DETEKSI OTOMATIS — 5 MODE OPERASIONAL
# ==============================================================================
# ZoneMinder hanya mengevaluasi gerakan DI DALAM zone. Monitor tanpa zone
# sama sekali tidak akan pernah menghasilkan alarm, sekalipun Function-nya
# Modect: ZM merekam, tapi tidak ada piksel yang dinilai sebagai gerakan.
# Karena itu setiap kamera baru wajib punya minimal satu zone.
#
# Semua mode di bawah memakai Units="Percent", sehingga nilainya tidak
# bergantung pada resolusi kamera dan tidak perlu dihitung ulang saat
# resolusi berubah. Ini juga menghindari jebakan Units="Pixels" yang membuat
# ambang 5% pada kamera 4K membengkak jadi angka berbeda per kamera.
#
# PENTING — arah sensitivitas: MinPixelThreshold adalah ambang perbedaan
# nilai warna per piksel (0-255). Angka KECIL = LEBIH SENSITIF. Ini
# kontra-intuitif dan sering dibaca terbalik, jadi jangan "memperbaiki"
# nilai-nilai ini tanpa memahami efeknya.
#
# Urutan mode = urutan beban CPU, dari paling murah ke paling mahal.
ZONE_MODES = {
    "lightest": {
        "label": "1. Paling Ringan",
        "short": "Paling Ringan",
        "description": (
            "CheckMethod=AlarmedPixels (tanpa filter blobs) + ambang 60%. "
            "Beban CPU terendah, hanya gerakan besar yang memicu alarm. "
            "Pilihan tepat untuk server dengan banyak kamera."
        ),
        "base_preset": "Fast, low sensitivity",
        "check": {"CheckMethod": "AlarmedPixels", "MinPixelThreshold": 60, "MinAlarmPixels": 20},
    },
    "light": {
        "label": "2. Ringan",
        "short": "Ringan",
        "description": (
            "CheckMethod=AlarmedPixels dengan ambang 20% dan alarm 5%. "
            "Beban CPU sama dengan Paling Ringan, tapi jauh lebih sensitif."
        ),
        "base_preset": "Fast, high sensitivity",
        "check": {"CheckMethod": "AlarmedPixels", "MinPixelThreshold": 20, "MinAlarmPixels": 5},
    },
    "medium": {
        "label": "3. Sedang",
        "short": "Sedang",
        "description": (
            "CheckMethod=Blobs + ambang 25%. Nilai persis preset 'Default' "
            "ZoneMinder. Objek dikelompokkan lebih dulu sehingga noise titik "
            "ditolak. Titik seimbang antara akurasi dan beban CPU."
        ),
        "base_preset": "Default",
        "check": {"CheckMethod": "Blobs", "MinPixelThreshold": 25, "MinAlarmPixels": 3,
                  "MinBlobPixels": 2, "MinBlobs": 1},
    },
    "heavy": {
        "label": "4. Berat",
        "short": "Berat",
        "description": (
            "CheckMethod=Blobs + ambang 60% dan blob minimal 20. Hanya gerakan "
            "besar yang lolos. Beban CPU tinggi, false alarm paling sedikit."
        ),
        "base_preset": "Best, low sensitivity",
        "check": {"CheckMethod": "Blobs", "MinPixelThreshold": 60, "MinAlarmPixels": 36,
                  "MinBlobPixels": 20, "MinBlobs": 1},
    },
    "heaviest": {
        "label": "5. Paling Berat",
        "short": "Paling Berat",
        "description": (
            "CheckMethod=Blobs + ambang 20% dan alarm 8%. Paling sensitif dan "
            "paling mahal: filter serta deteksi blob berjalan penuh tiap frame. "
            "Pakai hanya untuk sedikit kamera di area yang benar-benar penting."
        ),
        "base_preset": "Best, high sensitivity",
        "check": {"CheckMethod": "Blobs", "MinPixelThreshold": 20, "MinAlarmPixels": 8,
                  "MinBlobPixels": 5, "MinBlobs": 1},
    },
}

# Mode default saat kamera didaftarkan tanpa menyebut mode. "light" dipilih
# karena menjalankan Modect yang benar-benar berfungsi tanpa membebani CPU
# seperti halnya Blobs pada jaringan banyak kamera.
ZONE_MODE_DEFAULT = "light"

# Nama zone yang dibuat otomatis. Dipakai untuk mengenali zone buatan
# dashboard, supaya konfigurasi manual pengguna tidak pernah ditimpa.
ZONE_DEFAULT_NAME = "All"

# Preset ZoneMinder dibaca dari API zonePresets.json bila tersedia; bila
# gagal, nilai cadangan ini dipakai. Isinya SAMA dengan yang tertanam di
# zm_create.sql, jadi Dashboard tetap berfungsi walau ZM tidak merespons.
ZONE_PRESET_FALLBACK = {
    "Default": {
        "Units": "Percent", "CheckMethod": "Blobs",
        "MinPixelThreshold": 25, "MaxPixelThreshold": None, "MinAlarmPixels": 3,
        "MaxAlarmPixels": None, "FilterX": None, "FilterY": None, "MinFilterPixels": None,
        "MaxFilterPixels": None, "MinBlobPixels": 2, "MaxBlobPixels": None,
        "MinBlobs": 1, "MaxBlobs": None, "OverloadFrames": 0, "ExtendAlarmFrames": 0,
    },
    "Fast, low sensitivity": {
        "Units": "Percent", "CheckMethod": "AlarmedPixels",
        "MinPixelThreshold": 60, "MaxPixelThreshold": None, "MinAlarmPixels": 20,
        "MaxAlarmPixels": None, "FilterX": None, "FilterY": None, "MinFilterPixels": None,
        "MaxFilterPixels": None, "MinBlobPixels": None, "MaxBlobPixels": None,
        "MinBlobs": None, "MaxBlobs": None, "OverloadFrames": 0, "ExtendAlarmFrames": 0,
    },
    "Fast, high sensitivity": {
        "Units": "Percent", "CheckMethod": "AlarmedPixels",
        "MinPixelThreshold": 20, "MaxPixelThreshold": None, "MinAlarmPixels": 5,
        "MaxAlarmPixels": None, "FilterX": None, "FilterY": None, "MinFilterPixels": None,
        "MaxFilterPixels": None, "MinBlobPixels": None, "MaxBlobPixels": None,
        "MinBlobs": None, "MaxBlobs": None, "OverloadFrames": 0, "ExtendAlarmFrames": 0,
    },
    "Best, low sensitivity": {
        "Units": "Percent", "CheckMethod": "Blobs",
        "MinPixelThreshold": 60, "MaxPixelThreshold": None, "MinAlarmPixels": 36,
        "MaxAlarmPixels": None, "FilterX": None, "FilterY": None, "MinFilterPixels": None,
        "MaxFilterPixels": None, "MinBlobPixels": 20, "MaxBlobPixels": None,
        "MinBlobs": 1, "MaxBlobs": None, "OverloadFrames": 0, "ExtendAlarmFrames": 0,
    },
}

_PRESET_CACHE = {"data": None, "ts": 0.0}


def get_zm_zone_presets():
    """Preset zone asli dari ZoneMinder, di-cache singkat.

    Dibaca langsung dari ZM supaya nilai mode selalu konsisten dengan versi
    ZoneMinder yang berjalan — bukan hasil salinan yang bisa basi setelah
    upgrade. Bila API tidak menjawab, dipakai ZONE_PRESET_FALLBACK.
    """
    import time
    now = time.time()
    if _PRESET_CACHE["data"] and (now - _PRESET_CACHE["ts"]) < 300:
        return _PRESET_CACHE["data"]

    data = zm_api_get("zonePresets.json")
    presets = {}
    if isinstance(data, dict):
        for raw in data.get("zonePresets", []) or []:
            p = raw.get("ZonePreset", raw) if isinstance(raw, dict) else None
            if isinstance(p, dict) and p.get("Name"):
                presets[str(p["Name"])] = p

    if not presets:
        presets = ZONE_PRESET_FALLBACK
    _PRESET_CACHE["data"] = presets
    _PRESET_CACHE["ts"] = now
    return presets


def normalize_zone_mode(value):
    """Petakan input bebas ke key mode yang valid. None bila tidak dikenali."""
    if value is None:
        return ZONE_MODE_DEFAULT
    key = str(value).strip().lower().replace(" ", "_")
    aliases = {
        "paling_ringan": "lightest", "1": "lightest",
        "ringan": "light", "2": "light",
        "sedang": "medium", "3": "medium",
        "berat": "heavy", "4": "heavy",
        "paling_berat": "heaviest", "5": "heaviest",
    }
    if key in ZONE_MODES:
        return key
    return aliases.get(key)


def zone_modes_public():
    """Bentuk mode yang aman dikirim ke browser (tanpa data internal)."""
    return [
        {
            "key": key,
            "label": spec["label"],
            "short": spec["short"],
            "description": spec["description"],
            "check_method": spec["check"]["CheckMethod"],
            "min_pixel_threshold": spec["check"]["MinPixelThreshold"],
        }
        for key, spec in ZONE_MODES.items()
    ]


def build_zone_payload(mode_key, width, height):
    """Susun payload zone layar penuh untuk ZoneMinder.

    width/height HARUS berasal dari monitor sebagaimana disimpan ZoneMinder
    (bukan dari input pengguna), karena koordinat zone memakai ruang resolusi
    monitor dan ZM menghitungnya 0-based.
    """
    spec = ZONE_MODES[mode_key]
    base = dict(ZONE_PRESET_FALLBACK["Default"])

    # Preset dasar diambil dari ZoneMinder bila tersedia, lalu ditimpa nilai
    # khusus mode. Hasilnya: field yang tidak kita sentuh tetap mengikuti
    # preset asli, jadi upgrade ZoneMinder tidak membuat mode kita menyimpang.
    presets = get_zm_zone_presets()
    base_name = spec["base_preset"]
    if base_name in presets:
        for field in base.keys():
            if field in presets[base_name]:
                base[field] = presets[base_name][field]
    base.update(spec["check"])

    w = int(width) if str(width).isdigit() and int(width) > 1 else 1920
    h = int(height) if str(height).isdigit() and int(height) > 1 else 1080
    max_x = w - 1
    max_y = h - 1

    payload = {
        "Zone[Name]": ZONE_DEFAULT_NAME,
        "Zone[Type]": "Active",
        "Zone[Units]": base.get("Units") or "Percent",
        "Zone[NumCoords]": "4",
        "Zone[Coords]": f"0 0 {max_x} 0 {max_x} {max_y} 0 {max_y}",
        "Zone[Area]": str(w * h),
        "Zone[AlarmRGB]": "16711680",  # 0xFF0000, merah penuh
    }
    for field, value in base.items():
        if value is None or field in ("Units",):
            continue
        payload[f"Zone[{field}]"] = str(value)
    return payload


def _unwrap_zm(obj, *names):
    """Ambil objek dari respons ZoneMinder yang bersarang.

    ZM membungkus hasil dalam beberapa lapis tergantung endpoint, dan
    jumlah lapisnya tidak konsisten antar versi:

      {"zone":  {"Zone":  {...}}}                 -> /zones/{id}.json
      {"monitor":{"Monitor":{...}}}               -> /monitors/{id}.json
      {"monitors":[{"Monitor":{...}}, ...]}       -> /monitors.json

    Fungsi ini menelusuri lapisan itu sampai menemukan dict yang benar-benar
    berisi data, sehingga pemanggil tidak perlu menebak bentuknya.
    """
    cur = obj
    seen = 0
    while isinstance(cur, dict) and seen < 6:
        advanced = False
        for name in names:
            if name in cur and isinstance(cur[name], (dict, list)):
                cur = cur[name]
                advanced = True
                break
        if advanced:
            seen += 1
            continue
        break
    if isinstance(cur, list):
        cur = cur[0] if cur else None
        if isinstance(cur, dict):
            for name in names:
                if name in cur and isinstance(cur[name], dict):
                    cur = cur[name]
                    break
    return cur if isinstance(cur, dict) else None


def get_monitor_zones(monitor_id):
    """Daftar zone milik satu monitor. None bila ZM tidak menjawab.

    CATATAN PENTING: endpoint bersarang /monitors/{id}/zones.json TIDAK ADA
    pada ZoneMinder 1.36 (balas HTTP 404). Satu-satunya endpoint zone yang
    tersedia adalah daftar global /zones.json, yang isinya harus disaring
    per MonitorId. Jalur bersarang tetap dicoba lebih dulu agar build yang
    menyediakannya (lebih hemat) tetap terpakai.
    """
    raw = None
    nested = zm_api_get(f"monitors/{monitor_id}/zones.json")
    if isinstance(nested, dict):
        candidate = nested.get("zones")
        if isinstance(candidate, list):
            raw = candidate

    if raw is None:
        data = zm_api_get("zones.json")
        if not isinstance(data, dict):
            return None
        raw = data.get("zones")
        if not isinstance(raw, list):
            return None

    zones = []
    for item in raw:
        z = _unwrap_zm(item, "Zone")
        if z is None and isinstance(item, dict):
            z = item
        if isinstance(z, dict) and z.get("Id") is not None:
            zones.append(z)

    # Daftar global memuat zone semua monitor, jadi wajib disaring.
    return [z for z in zones if str(z.get("MonitorId", "")) == str(monitor_id)]


def find_monitor_id_by_name(name):
    """Cari ID monitor dari namanya — dipakai setelah POST pembuatan monitor.

    ZoneMinder 1.36 membalas POST /monitors.json hanya dengan
    {"message":"Saved"}, TANPA menyertakan Id. Tanpa pencarian ini, ID monitor
    tidak pernah ditemukan sehingga zone otomatis selalu dilaporkan gagal
    padahal kamera berhasil dibuat. Nama sudah dibersihkan (clean_name) dan
    unik di ZoneMinder, jadi pencarian berdasarkan nama aman dipakai di sini.
    """
    want = str(name or "").strip()
    if not want:
        return None

    data = zm_api_get("monitors.json")
    if not isinstance(data, dict):
        return None

    for item in data.get("monitors", []) or []:
        m = _unwrap_zm(item, "Monitor")
        if isinstance(m, dict) and str(m.get("Name", "")) == want:
            mid = m.get("Id")
            if mid is not None:
                return str(mid)
    return None


def resolve_monitor_geometry(monitor_id):
    """Ambil Width/Height monitor SEBAGAIMANA DISIMPAN ZoneMinder.

    Bentuk respons /monitors/{id}.json adalah {"monitor":{"Monitor":{...}}},
    jadi objek harus ditelusuri dua lapis. Sebelumnya lapisan "Monitor" tidak
    pernah dibuka, akibatnya Width/Height tidak ditemukan dan pembuatan zone
    selalu gagal dengan alasan "resolusi tidak dapat dibaca" — padahal datanya
    ada. Nilai dari form pengguna sengaja tidak dipakai di sini: zone harus
    memakai ruang koordinat yang sama dengan frame yang benar-benar didekode ZM.
    """
    data = zm_api_get(f"monitors/{monitor_id}.json")
    m = _unwrap_zm(data, "monitor", "Monitor")
    if m and m.get("Width") and m.get("Height"):
        w, h = str(m["Width"]), str(m["Height"])
        if w.isdigit() and h.isdigit() and int(w) > 1 and int(h) > 1:
            return w, h

    # Jalur cadangan: daftar monitor global memuat Width/Height juga.
    listing = zm_api_get("monitors.json")
    if isinstance(listing, dict):
        for item in listing.get("monitors", []):
            cand = _unwrap_zm(item, "Monitor")
            if cand and str(cand.get("Id", "")) == str(monitor_id):
                w, h = str(cand.get("Width", "")), str(cand.get("Height", ""))
                if w.isdigit() and h.isdigit() and int(w) > 1 and int(h) > 1:
                    return w, h
    return None, None


def ensure_zone_for_monitor(monitor_id, mode_key=None, overwrite=False, width=None, height=None):
    """Pastikan monitor punya zone deteksi sesuai mode yang diminta.

    Idempotent dan aman terhadap konfigurasi manual:
      - Bila monitor sudah punya zone dan overwrite=False, zone TIDAK disentuh.
      - Bila overwrite=True, hanya zone yang dibuat dashboard (nama "All")
        yang diganti; zone buatan pengguna dibiarkan utuh.

    Mengembalikan dict berisi created/skipped/reason supaya UI bisa
    melaporkan status zone secara jujur, bukan menebak.
    """
    mode = normalize_zone_mode(mode_key)
    if mode is None:
        return {"created": False, "skipped": True, "reason": f"Mode zone '{mode_key}' tidak dikenali."}

    existing = get_monitor_zones(monitor_id)
    if existing is None:
        return {
            "created": False, "skipped": True, "mode": mode,
            "reason": "Tidak dapat membaca daftar zone dari ZoneMinder.",
        }

    auto_zones = [z for z in existing if str(z.get("Name", "")) == ZONE_DEFAULT_NAME]

    if existing and not overwrite:
        return {
            "created": False, "skipped": True, "mode": mode,
            "existing": len(existing),
            "reason": f"Monitor sudah punya {len(existing)} zone. Konfigurasi manual tidak ditimpa.",
        }

    if not width or not height:
        width, height = resolve_monitor_geometry(monitor_id)
    if not width or not height:
        return {
            "created": False, "skipped": True, "mode": mode,
            "reason": "Resolusi monitor tidak dapat dibaca dari ZoneMinder.",
        }

    payload = build_zone_payload(mode, width, height)

    if overwrite:
        # Buang HANYA zone buatan dashboard; zone milik pengguna tidak pernah
        # disentuh, sekalipun overwrite=True.
        for z in auto_zones:
            zm_delete(f"zones/{z.get('Id')}.json")

    # MonitorId WAJIB ada di payload. Tanpa itu ZM menolak simpan karena
    # validasi checkMonitorId di model Zone gagal.
    payload["Zone[MonitorId]"] = str(monitor_id)

    # Endpoint bersarang 404 pada ZM 1.36, jadi jalur utama adalah zone global.
    code = zm_post("zones.json", payload)
    if code not in (200, 201):
        code = zm_post(f"monitors/{monitor_id}/zones.json", payload)

    if code in (200, 201):
        return {
            "created": True, "skipped": False, "mode": mode,
            "label": ZONE_MODES[mode]["label"],
            "coords": payload["Zone[Coords]"],
            "width": width, "height": height,
        }
    return {
        "created": False, "skipped": False, "mode": mode,
        "reason": f"ZoneMinder menolak pembuatan zone (HTTP {code}).",
    }


@app.route("/api/zones/save-camera", methods=["POST"])
def api_save_camera_with_zone():
    """Simpan kamera (baru/edit) lalu buat zone deteksinya dalam satu panggilan.

    Kenapa endpoint ini ada:
      Halaman Kelola Kamera dulu mem-POST langsung ke /zm/api/monitors.json
      dari browser. ZoneMinder 1.36 membalas {"message":"Saved"} TANPA Id,
      sehingga browser tidak pernah tahu ID monitor yang baru dibuat — dan
      pembuatan zone selalu gagal dengan "ID monitor baru tidak terbaca".
      ID itu baru diketahui setelah daftar monitor dibaca ulang.

      Endpoint ini melakukan penyimpanan di sisi server, lalu mencari ID
      berdasarkan NAMA monitor (satu-satunya penanda yang dikirim balik oleh
      ZM). Dengan begitu pembuatan zone berjalan tanpa menebak ID.

    Body JSON:
      id        : ID monitor saat mengedit (kosong/null = kamera baru)
      name      : nama kamera
      path      : URL RTSP
      function  : Monitor | Modect | Record | Mocord | Nodect
      width     : lebar piksel
      height    : tinggi piksel
      zoneMode  : lightest | light | medium | heavy | heaviest
      createZone: bool
      overwriteZone: bool
      colorspace: opsional
    """
    body = request.json or {}

    name = str(body.get("name", "")).strip()
    path = str(body.get("path", "")).strip()
    edit_id = str(body.get("id", "") or "").strip()

    if not name or not path:
        return jsonify({
            "status": "error",
            "message": "Nama kamera dan RTSP Path wajib diisi.",
        }), 400

    clean_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", name)
    width = str(body.get("width") or "1920")
    height = str(body.get("height") or "1080")
    function = str(body.get("function") or "Monitor")

    payload = {
        "Monitor[Name]": clean_name,
        "Monitor[Type]": "Ffmpeg",
        "Monitor[Function]": function,
        "Monitor[Enabled]": "1",
        "Monitor[Path]": path,
        "Monitor[Method]": "rtsp",
        "Monitor[Options]": "rtsp_transport=tcp",
        "Monitor[Width]": width,
        "Monitor[Height]": height,
        "Monitor[Colours]": str(body.get("colorspace") or "4"),
        "Monitor[TargetColorspace]": "4",
        "Monitor[ServerId]": "0",
    }

    # ID kustom hanya dipakai saat membuat kamera baru. Saat mengedit, ID
    # sudah ditentukan oleh URL target.
    custom_id = str(body.get("customId", "") or "").strip()
    if not edit_id and custom_id.isdigit():
        payload["Monitor[Id]"] = custom_id

    if edit_id:
        target = f"monitors/{edit_id}.json"
    else:
        target = "monitors.json"

    code = zm_post(target, payload)
    if code not in (200, 201):
        return jsonify({
            "status": "error",
            "message": f"ZoneMinder menolak penyimpanan kamera (HTTP {code}).",
        }), 502

    MONITOR_CACHE["ts"] = 0

    # ID hasil simpan: pakai ID edit bila ada, lalu ID kustom, selain itu
    # cari berdasarkan nama (satu-satunya penanda yang dikirim balik ZM).
    monitor_id = edit_id or (custom_id if custom_id.isdigit() else "") \
        or find_monitor_id_by_name(clean_name)
    if monitor_id and not str(monitor_id).isdigit():
        monitor_id = find_monitor_id_by_name(clean_name)

    zone_result = {"created": False, "skipped": True,
                   "reason": "Pembuatan zone dinonaktifkan."}
    zone_mode = normalize_zone_mode(body.get("zoneMode"))

    # Saat mengedit, zone lama sengaja dibiarkan agar penyesuaian manual di
    # antarmuka ZoneMinder tidak terhapus.
    if body.get("createZone", True) and zone_mode and not edit_id:
        if not monitor_id:
            zone_result = {
                "created": False, "skipped": False, "mode": zone_mode,
                "reason": "ID monitor baru tidak ditemukan setelah penyimpanan.",
            }
        else:
            zone_result = ensure_zone_for_monitor(
                monitor_id,
                mode_key=zone_mode,
                overwrite=bool(body.get("overwriteZone", False)),
                width=width,
                height=height,
            )

    return jsonify({
        "status": "success",
        "monitor_id": monitor_id,
        "name": clean_name,
        "editing": bool(edit_id),
        "zone": zone_result,
    })


@app.route("/api/cameras/bulk-function", methods=["POST"])
def bulk_set_function():
    """
    Mengubah Function seluruh kamera sekaligus (enable/disable massal).

    Body JSON:
      action  : "on" | "off" | "custom"
      function: dipakai saat action="custom", mis. "Monitor" / "Mocord"
      ids     : opsional, daftar ID kamera. Kosong = semua kamera.

    Saat action="on", kamera yang sebelumnya "None" dikembalikan ke Fungsi
    terakhir yang tersimpan di data/camera_functions.json. Bila belum ada
    catatan, dipakai "Monitor" (aman: tanpa motion detection).
    """
    body = request.json or {}
    action = str(body.get("action", "")).strip().lower()
    target_ids = [str(x) for x in body.get("ids", []) if str(x).strip()]

    monitors = get_all_monitors_cached()
    if target_ids:
        wanted = set(target_ids)
        monitors = [m for m in monitors if m["id"] in wanted]

    if not monitors:
        return jsonify({"status": "error", "message": "Tidak ada kamera yang diproses."}), 400

    saved = load_saved_functions()

    if action == "on":
        # Hidupkan kembali sesuai fungsi terakhir yang tercatat
        jobs = []
        for m in monitors:
            fn = saved.get(m["id"], "Monitor")
            if fn not in ZM_ACTIVE_FUNCTIONS:
                fn = "Monitor"
            jobs.append((m["id"], fn, m["function"]))
    elif action == "off":
        jobs = []
        for m in monitors:
            # Ingat fungsi yang sedang aktif sebelum dimatikan, supaya
            # "Pulihkan Fungsi Asli" tetap bisa mengembalikannya.
            if m["function"] in ZM_ACTIVE_FUNCTIONS:
                saved[m["id"]] = m["function"]
            jobs.append((m["id"], ZM_OFF_FUNCTION, m["function"]))
    elif action == "custom":
        fn = str(body.get("function", "")).strip()
        if fn not in ZM_ACTIVE_FUNCTIONS and fn != ZM_OFF_FUNCTION:
            return jsonify({
                "status": "error",
                "message": f"Function '{fn}' tidak valid. Pilihan: {', '.join(ZM_ACTIVE_FUNCTIONS + (ZM_OFF_FUNCTION,))}"
            }), 400
        jobs = [(m["id"], fn, m["function"]) for m in monitors]
    else:
        return jsonify({"status": "error", "message": "action harus 'on', 'off', atau 'custom'."}), 400

    results = []
    ok_count = 0
    fail_count = 0

    for mon_id, new_fn, old_fn in jobs:
        wants_enabled = new_fn != ZM_OFF_FUNCTION
        code = zm_post(f"monitors/{mon_id}.json", {
            "Monitor[Function]": new_fn,
            "Monitor[Enabled]": "1" if wants_enabled else "0",
        })

        if code in (200, 201):
            ok_count += 1
            results.append({"id": mon_id, "status": "ok", "function": new_fn})
            # Catat fungsi AKTIF terakhir. Saat kamera dimatikan ("None"),
            # catatan LAMA sengaja tidak dihapus agar tombol
            # "Pulihkan Fungsi Asli" bisa mengembalikan mode sebelumnya.
            if wants_enabled:
                saved[mon_id] = new_fn
        else:
            fail_count += 1
            results.append({"id": mon_id, "status": "failed", "http": code})

    save_saved_functions(saved)
    # Paksa refresh cache agar panggilan berikutnya membaca kondisi terbaru
    MONITOR_CACHE["ts"] = 0

    return jsonify({
        "status": "completed",
        "action": action,
        "total": len(jobs),
        "success_count": ok_count,
        "fail_count": fail_count,
        "details": results,
    })


# ==============================================================================
# 9. ZONE DETEKSI — 5 MODE OPERASIONAL
# ==============================================================================
@app.route("/api/zones/modes", methods=["GET"])
def api_zone_modes():
    """Daftar 5 mode zone beserta parameter efektifnya.

    Nilai yang dikirim adalah hasil resolusi preset ZoneMinder yang hidup,
    jadi UI menampilkan angka yang benar-benar akan ditulis ke ZM.
    """
    presets = get_zm_zone_presets()
    modes = zone_modes_public()
    for m in modes:
        spec = ZONE_MODES[m["key"]]
        base_name = spec["base_preset"]
        source = presets.get(base_name)
        m["base_preset"] = base_name
        m["preset_available"] = bool(source)
        m["units"] = (source or {}).get("Units", "Percent")
    return jsonify({
        "default_mode": ZONE_MODE_DEFAULT,
        "zone_name": ZONE_DEFAULT_NAME,
        "modes": modes,
    })


@app.route("/api/zones/<monitor_id>", methods=["GET"])
def api_zones_for_monitor(monitor_id):
    """Zone yang dimiliki satu monitor — dipakai UI untuk menampilkan status."""
    if not re.fullmatch(r"\d+", str(monitor_id)):
        return jsonify({"status": "error", "message": "ID kamera tidak valid."}), 400

    zones = get_monitor_zones(monitor_id)
    if zones is None:
        return jsonify({
            "status": "error",
            "message": "Tidak dapat membaca daftar zone dari ZoneMinder.",
        }), 502

    return jsonify({
        "status": "ok",
        "monitor_id": str(monitor_id),
        "count": len(zones),
        "has_auto_zone": any(str(z.get("Name", "")) == ZONE_DEFAULT_NAME for z in zones),
        "zones": [
            {
                "id": str(z.get("Id", "")),
                "name": z.get("Name", ""),
                "type": z.get("Type", ""),
                "units": z.get("Units", ""),
                "check_method": z.get("CheckMethod", ""),
                "min_pixel_threshold": z.get("MinPixelThreshold"),
                "min_alarm_pixels": z.get("MinAlarmPixels"),
                "min_blob_pixels": z.get("MinBlobPixels"),
                "coords": z.get("Coords", ""),
            }
            for z in zones
        ],
    })


@app.route("/api/zones/<monitor_id>/set-mode", methods=["POST"])
def api_set_zone_mode(monitor_id):
    """Buat/perbarui zone deteksi satu kamera sesuai mode yang dipilih.

    Body JSON:
      mode      : lightest | light | medium | heavy | heaviest
      overwrite : opsional (bool). true = ganti zone buatan dashboard.
                  Zone buatan tangan pengguna TIDAK pernah dihapus.
    """
    if not re.fullmatch(r"\d+", str(monitor_id)):
        return jsonify({"status": "error", "message": "ID kamera tidak valid."}), 400

    body = request.json or {}
    mode = normalize_zone_mode(body.get("mode"))
    if mode is None:
        return jsonify({
            "status": "error",
            "message": f"Mode zone '{body.get('mode')}' tidak dikenali. "
                       f"Pilihan: {', '.join(ZONE_MODES.keys())}",
        }), 400

    result = ensure_zone_for_monitor(
        monitor_id,
        mode_key=mode,
        overwrite=bool(body.get("overwrite", False)),
    )

    if result.get("created"):
        MONITOR_CACHE["ts"] = 0
        return jsonify({
            "status": "success",
            "message": f"Zone '{ZONE_DEFAULT_NAME}' dibuat di kamera {monitor_id} "
                       f"dengan mode {ZONE_MODES[mode]['label']}.",
            "data": result,
        })
    if result.get("skipped"):
        return jsonify({
            "status": "skipped",
            "message": result.get("reason", "Zone dilewati."),
            "data": result,
        }), 200
    return jsonify({
        "status": "error",
        "message": result.get("reason", "Gagal membuat zone."),
        "data": result,
    }), 502


@app.route("/api/zones/bulk-set-mode", methods=["POST"])
def api_bulk_zone_mode():
    """Terapkan satu mode zone ke banyak kamera sekaligus.

    Body JSON:
      mode      : lightest | light | medium | heavy | heaviest
      ids       : opsional, daftar ID kamera. Kosong = semua kamera.
      overwrite : opsional (bool), default false.
    """
    body = request.json or {}
    mode = normalize_zone_mode(body.get("mode"))
    if mode is None:
        return jsonify({
            "status": "error",
            "message": f"Mode zone '{body.get('mode')}' tidak dikenali. "
                       f"Pilihan: {', '.join(ZONE_MODES.keys())}",
        }), 400

    overwrite = bool(body.get("overwrite", False))
    target_ids = [str(x) for x in body.get("ids", []) if str(x).strip()]

    monitors = get_all_monitors_cached()
    if target_ids:
        wanted = set(target_ids)
        monitors = [m for m in monitors if m["id"] in wanted]

    if not monitors:
        return jsonify({"status": "error", "message": "Tidak ada kamera yang diproses."}), 400

    details = []
    created = skipped = failed = 0

    for mon in monitors:
        # Geometri diambil dari data monitor yang sudah ada di cache, sehingga
        # tidak perlu satu request tambahan per kamera.
        res = ensure_zone_for_monitor(
            mon["id"], mode_key=mode, overwrite=overwrite,
            width=mon.get("width"), height=mon.get("height"),
        )
        if res.get("created"):
            created += 1
            details.append({"id": mon["id"], "name": mon["name"], "status": "created"})
        elif res.get("skipped"):
            skipped += 1
            details.append({
                "id": mon["id"], "name": mon["name"],
                "status": "skipped", "reason": res.get("reason", ""),
            })
        else:
            failed += 1
            details.append({
                "id": mon["id"], "name": mon["name"],
                "status": "failed", "reason": res.get("reason", ""),
            })

    MONITOR_CACHE["ts"] = 0

    return jsonify({
        "status": "completed",
        "mode": mode,
        "mode_label": ZONE_MODES[mode]["label"],
        "total": len(monitors),
        "created_count": created,
        "skipped_count": skipped,
        "fail_count": failed,
        "details": details,
    })


# ==============================================================================
# MAIN ENTRYPOINT
# ==============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"[*] Menjalankan Dashboard CCTV pada port {port}")

    # Flask dev server tidak sanggup menangani banyak koneksi MJPEG persisten
    # sekaligus (koneksi terputus: ERR_EMPTY_RESPONSE). Waitress memakai thread
    # pool sehingga puluhan stream bisa berjalan bersamaan.
    try:
        from waitress import serve
        threads = int(os.environ.get("WSGI_THREADS", "64"))
        print(f"[*] WSGI server: waitress ({threads} threads)")
        serve(app, host="0.0.0.0", port=port, threads=threads, channel_timeout=300)
    except ImportError:
        print("[WARN] waitress tidak terpasang, memakai Flask dev server (tidak disarankan).")
        app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
