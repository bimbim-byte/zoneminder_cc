import json
import logging
import os
import re
import threading

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

# ==============================================================================
# JEBAKAN API ZONEMINDER 1.38 — JANGAN DIHAPUS
# ==============================================================================
# Dua perilaku di bawah ini tidak terlihat seperti bug, tetapi membuat SEMUA
# pembuatan kamera gagal tanpa pesan yang jelas.
#
# 1) DEVICE_REQUIRED
#    Model `Monitor` di ZM 1.38 punya aturan validasi (api/app/Model/Monitor.php):
#        'Device' => array('validPath' => array(
#            'rule' => array('custom', '#^(/dev/[\w/.\-]+)?$#'),
#            'allowEmpty' => true, 'required' => false))
#    `allowEmpty` hanya berlaku bila kolomnya HADIR di data yang dikirim. Bila
#    kuncinya tidak ada sama sekali, CakePHP melewatkan nilai NULL ke regex dan
#    aturan itu GAGAL — padahal kolomnya NOT NULL dengan default ''.
#    Jadi "Monitor[Device]" WAJIB selalu dikirim, walau isinya string kosong.
#    Bila lupa, ZM membalas HTTP 200 (bukan 4xx) dengan body:
#        {"message":{"Device":["Invalid device path. Must be a valid /dev/ ..."]}}
#    Inilah kenapa kamera "tidak muncul" padahal UI melaporkan sukses: kode
#    lama hanya memeriksa status_code == 200, dan 200 juga dipakai untuk gagal.
#
# 2) SUKSES DITENTUKAN OLEH "message", BUKAN STATUS HTTP
#    POST /monitors.json membalas 200 untuk DUA kondisi berbeda:
#        sukses : {"message":"Saved"}
#        gagal  : {"message":{...pesan validasi...}}
#    Karena itu setiap respons WAJIB diperiksa isinya. Lihat zm_post_monitor().
DEVICE_REQUIRED = ""


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
# SUMBER RTSP UNTUK MONITOR TIPE Ffmpeg (ZONE MINDER 1.38)
# ==============================================================================
# Di ZM 1.38 zmc sendiri yang menerjemahkan Monitor[Method] menjadi opsi
# transport ffmpeg (terverifikasi dari string binary /usr/bin/zmc):
#     rtpRtsp     -> rtsp_transport=tcp
#     rtpUni      -> rtsp_transport=udp
#     rtpMulti    -> rtsp_transport=udp_multicast
#     rtpRtspHttp -> rtsp_transport=http
#     selain itu  -> "Unknown method (<nilai>)" dan transport TIDAK disetel
#
# Nilai "rtsp" adalah warisan ZM 1.36 (dipakai tipe sumber Remote) dan TIDAK
# dikenali oleh 1.38. Karena itu jangan pernah mengirim "rtsp" lagi.
#
# Monitor[Options] TIDAK dipakai untuk transport: isinya diteruskan apa adanya
# sebagai opsi input ffmpeg, dan "rtsp_transport" bukan opsi level format
# sehingga muncul peringatan "Option rtsp_transport not recognized by ffmpeg".
# Transport cukup lewat Method di atas.
ZM_FFMPEG_METHOD = "rtpRtsp"   # RTSP over TCP

from rtsp_path import (  # noqa: E402  (setelah konstanta, bukan di blok import atas)
    ANALYSIS_FPS_DEFAULT,
    ZM_FFMPEG_OPTIONS,
    _monitor_fps_payload as _rtsp_fps_payload,
    normalize_analysis_fps,
    normalize_rtsp_path,
)
from zm_triad import (  # noqa: E402
    DEFAULT_ENCODER_PARAMETERS,
    OUTPUT_CODECS,
    OUTPUT_CONTAINERS,
    VALID_ANALYSING,
    VALID_CAPTURING,
    VALID_DECODERS,
    VALID_ENCODERS,
    VALID_RECORDING,
    VIDEO_WRITER_VALUES,
    build_zm138_full_payload,
    build_zm138_triad,
    derive_function_from_triad,
    normalize_analysing,
    normalize_capturing,
    normalize_encoder,
    normalize_encoder_parameters,
    normalize_output_codec,
    normalize_output_container,
    normalize_recording,
    normalize_storage_id,
    normalize_video_writer,
    zm138_monitor_payload,
)

# Batas laju analisa motion + normalisasi path RTSP kini hidup di modul
# terpisah (rtsp_path.py) supaya bisa diuji tanpa menyeret Flask. Lihat
# _verify_rtsp_path.py untuk uji perilakunya.
ZM_FFMPEG_TIMEOUT_US = "5000000"


def _monitor_fps_payload(analysis_fps=None):
    """Field FPS yang dikirim saat membuat/menyimpan monitor.

    Hanya AnalysisFPSLimit yang diisi; MaxFPS sengaja tidak dikirim agar
    capture tidak dipotong. Implementasi ada di rtsp_path.py.
    """
    return _rtsp_fps_payload(analysis_fps)


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
# 1b. PENGATURAN: KREDENSIAL ZONEMINDER + AKUN DASHBOARD & STATUS
# ==============================================================================
@app.route("/settings")
def settings():
    return send_from_directory(".", "settings.html")


@app.route("/status")
@app.route("/status.html")
def status_page():
    return send_from_directory(".", "status.html")


@app.route("/checker")
@app.route("/checker.html")
def checker_page():
    """Halaman terpisah untuk kendali CCTV Health Checker.

    Dipisah dari status.html supaya Status Server tetap murni informatif dan
    kendali checker (toggle, interval, run-now) punya tempat sendiri.
    """
    return send_from_directory(".", "checker.html")


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
# UTILITAS: REDAKSI KREDENSIAL RTSP
# ==============================================================================
def _redact_rtsp(text):
    """Buang kredensial dari URL RTSP apa pun di dalam sebuah string.

    Path monitor di ZoneMinder berbentuk rtsp://user:pass@host/stream dan ikut
    terkirim ke browser saat daftar kamera dibaca. Nilai kredensial TIDAK
    boleh keluar ke klien, jadi disaring di sini — bukan hanya saat menulis.
    """
    if not isinstance(text, str) or "@" not in text or "rtsp://" not in text.lower():
        return text
    try:
        scheme, _, rest = text.partition("//")
        hostpart = rest.rsplit("@", 1)[-1]
        return f"{scheme}//{hostpart}" if hostpart else "rtsp://<kredensial-dihilangkan>"
    except Exception:
        return "<kredensial-dihilangkan>"


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
        # menampilkan host-nya. Saring juga monitor yang sudah di-soft-delete (Deleted=1)
        # agar sinkron dengan konsol ZoneMinder (WHERE M.Deleted = false).
        if (
            resp.status_code == 200
            and request.method == "GET"
            and "application/json" in resp.headers.get("Content-Type", "")
            and re.search(rb"monitors", subpath.encode() or b"")
            and content.strip().startswith((b"{", b"["))
        ):
            try:
                payload = json.loads(content.decode("utf-8"))
                if isinstance(payload, dict) and isinstance(payload.get("monitors"), list):
                    filtered_monitors = []
                    for item in payload["monitors"]:
                        target = item.get("Monitor") if isinstance(item, dict) else None
                        if isinstance(target, dict):
                            # Saring monitor soft-deleted (Deleted=1)
                            if str(target.get("Deleted", "0")).lower() in ("1", "true"):
                                continue
                            if target.get("Path"):
                                target["Path"] = _redact_rtsp(target["Path"])
                        filtered_monitors.append(item)
                    payload["monitors"] = filtered_monitors
                    content = json.dumps(payload).encode("utf-8")
                    resp_headers = [(k, v) for k, v in resp_headers
                                    if k.lower() != "content-type"]
                    resp_headers.append(("Content-Type", "application/json"))
            except Exception as exc:
                log.warning("Gagal menyaring kredensial/status monitor: %s", exc)

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
def _pick(data, *keys, default=None):
    """Ambil nilai pertama yang BENAR-BENAR ADA dari dict.

    Berbeda dari pola `data.get(a) or data.get(b)`, nilai 0 dan "" tetap
    dianggap nilai sah. Ini penting untuk field konfigurasi event di mana
    angka 0 bermakna (FrameSkip=0, AnalysisUpdateDelay=0, StartupDelay=0):
    dengan pola `or`, nilai 0 akan tergeser ke default dan input operator
    diam-diam hilang.
    """
    for key in keys:
        if key in data:
            val = data[key]
            if val is None:
                continue
            if isinstance(val, str) and not val.strip():
                continue
            return val
    return default


# ==============================================================================
# FIELD ENCODING VIDEO — DIBACA SERAGAM DARI KETIGA JALUR
# ==============================================================================
# Enam field di bawah menentukan ke mana rekaman disimpan dan bagaimana video
# dikodekan. Ketiganya (tunggal, burst, Excel) memakai pembaca ini supaya satu
# kamera yang didaftarkan lewat jalur mana pun menghasilkan setelan identik.
ENCODING_FIELD_KEYS = {
    # nama argumen build_zm138_full_payload -> variasi nama yang diterima
    "storage_id": ("storageId", "storage_id", "StorageId", "Storage", "Storage Area"),
    "video_writer": ("videoWriter", "video_writer", "VideoWriter", "Video Writer", "VideoWriterMode"),
    "output_codec": ("outputCodec", "output_codec", "OutputCodec", "Output Codec", "OutputCodecName"),
    "encoder": ("encoder", "Encoder", "Video Encoder"),
    "encoder_parameters": ("encoderParameters", "encoder_parameters", "EncoderParameters", "Encoder Parameters"),
    "output_container": ("outputContainer", "output_container", "OutputContainer", "Output Container", "Container"),
}

# Default aman saat field tidak dikirim sama sekali (mis. baris Excel lama).
# OutputCodec 0/'auto' dipakai ketika VideoWriter bukan Encode, sesuai aturan
# ZM 1.38.6: kodec tidak dipakai sehingga tidak boleh meninggalkan sisa nilai.
ENCODING_FIELD_DEFAULTS = {
    "storage_id": 1,
    "video_writer": 1,
    "output_codec": "h264",
    "encoder": "libx264",
    "encoder_parameters": DEFAULT_ENCODER_PARAMETERS,
    "output_container": "mp4",
}


def read_encoding_fields(source, video_writer_default=1):
    """Baca enam field encoding video dari body JSON atau baris Excel.

    Selalu mengembalikan dict lengkap siap dioper sebagai kwargs
    build_zm138_full_payload(). Nilai yang tidak dikenal TIDAK menggagalkan
    pendaftaran: normalizer di zm_triad memetakannya ke default yang sah,
    karena satu sel Excel salah ketik tidak boleh mematikan pembuatan monitor.

    Bila VideoWriter bukan Encode (0=Disabled, 2=Camera Passthrough), kodec
    dan encoder dikunci ke 'auto' — ZM tidak memakainya dan nilai lama akan
    menyesatkan operator yang membuka monitor di konsol ZM.
    """
    if not isinstance(source, dict):
        source = {}

    writer_raw = _pick(source, *ENCODING_FIELD_KEYS["video_writer"],
                       default=video_writer_default)
    writer = normalize_video_writer(writer_raw, default=str(video_writer_default))

    fields = {
        "storage_id": normalize_storage_id(
            _pick(source, *ENCODING_FIELD_KEYS["storage_id"],
                  default=ENCODING_FIELD_DEFAULTS["storage_id"])
        ),
        "video_writer": writer,
    }

    if writer == "1":
        fields["output_codec"] = normalize_output_codec(
            _pick(source, *ENCODING_FIELD_KEYS["output_codec"],
                  default=ENCODING_FIELD_DEFAULTS["output_codec"])
        )
        fields["encoder"] = normalize_encoder(
            _pick(source, *ENCODING_FIELD_KEYS["encoder"],
                  default=ENCODING_FIELD_DEFAULTS["encoder"])
        )
        fields["encoder_parameters"] = normalize_encoder_parameters(
            _pick(source, *ENCODING_FIELD_KEYS["encoder_parameters"],
                  default=ENCODING_FIELD_DEFAULTS["encoder_parameters"])
        )
    else:
        fields["output_codec"] = "auto"
        fields["encoder"] = "auto"
        fields["encoder_parameters"] = normalize_encoder_parameters(
            _pick(source, *ENCODING_FIELD_KEYS["encoder_parameters"],
                  default=ENCODING_FIELD_DEFAULTS["encoder_parameters"])
        )

    # OutputContainer: hanya Auto/Mp4/Mkv yang diterima API ZM 1.38.6.
    # 'webm' dan nilai asing dipetakan ke mp4 oleh normalize_output_container.
    fields["output_container"] = normalize_output_container(
        _pick(source, *ENCODING_FIELD_KEYS["output_container"],
              default=ENCODING_FIELD_DEFAULTS["output_container"])
    )
    return fields


def encoding_fields_public():
    """Daftar nilai sah encoding untuk dikirim ke browser.

    Sumber tunggal: konstanta di zm_triad.py. UI tidak menyalin daftar ini
    supaya penambahan encoder/kodec baru cukup diubah di satu tempat.
    """
    return {
        "video_writers": [
            {"value": key, "label": label}
            for key, label in VIDEO_WRITER_VALUES.items()
        ],
        "output_codecs": [
            {"value": key, "label": name, "code": code}
            for key, (name, code) in OUTPUT_CODECS.items()
        ],
        # Kunci kosong dan 'auto' sama-sama berarti 'auto'; kirim sekali saja
        # supaya dropdown tidak punya dua pilihan yang identik.
        "output_containers": [
            {"value": key or "auto", "label": label}
            for key, label in OUTPUT_CONTAINERS.items()
            if key != "auto"
        ],
        "encoders": list(VALID_ENCODERS),
        "default_encoder_parameters": DEFAULT_ENCODER_PARAMETERS,
        "defaults": {
            "storage_id": ENCODING_FIELD_DEFAULTS["storage_id"],
            "video_writer": ENCODING_FIELD_DEFAULTS["video_writer"],
            "output_codec": ENCODING_FIELD_DEFAULTS["output_codec"],
            "encoder": ENCODING_FIELD_DEFAULTS["encoder"],
            "encoder_parameters": ENCODING_FIELD_DEFAULTS["encoder_parameters"],
            "output_container": ENCODING_FIELD_DEFAULTS["output_container"],
        },
    }


STORAGE_CACHE = {"data": None, "ts": 0.0}


def get_zm_storages():
    """Daftar area penyimpanan ZoneMinder, di-cache singkat.

    Endpoint ZM bernama `storage.json` (TUNGGAL) — `storages.json` membalas
    404. Di instalasi bawaan hanya ada satu baris: Id=1, Name='Default'.
    Bila API tidak menjawab, dikembalikan daftar fallback berisi Default/1
    agar dropdown tetap terisi dan pendaftaran tidak pernah gagal hanya
    karena pembacaan daftar storage bermasalah.
    """
    import time
    now = time.time()
    if STORAGE_CACHE["data"] and (now - STORAGE_CACHE["ts"]) < 300:
        return STORAGE_CACHE["data"]

    data = zm_api_get("storage.json")
    items = []
    if isinstance(data, dict):
        raw = data.get("storage") or data.get("storages") or data.get("Storage")
        if isinstance(raw, dict):
            raw = [raw]
        if isinstance(raw, list):
            for entry in raw:
                node = entry.get("Storage", entry) if isinstance(entry, dict) else None
                if not isinstance(node, dict):
                    continue
                sid = node.get("Id")
                if sid is None:
                    continue
                items.append({
                    "id": str(sid),
                    "name": str(node.get("Name") or ("Storage %s" % sid)),
                    "path": str(node.get("Path") or ""),
                    "type": str(node.get("Type") or ""),
                    "enabled": str(node.get("Enabled", "1")),
                })

    if not items:
        items = [{"id": "1", "name": "Default", "path": "", "type": "", "enabled": "1"}]

    STORAGE_CACHE["data"] = items
    STORAGE_CACHE["ts"] = now
    return items


@app.route("/api/zm/storageareas", methods=["GET"])
def api_storage_areas():
    """Area penyimpanan ZM untuk dropdown Storage pada form pendaftaran."""
    items = get_zm_storages()
    return jsonify({
        "status": "ok",
        "count": len(items),
        "default_id": items[0]["id"] if items else "1",
        "storages": items,
    })


@app.route("/api/zm/encoding-options", methods=["GET"])
def api_encoding_options():
    """Nilai sah VideoWriter / OutputCodec / Encoder / OutputContainer."""
    return jsonify(encoding_fields_public())


@app.route("/api/zoneminder/add-camera", methods=["POST"])
def add_single_camera():
    """Mendaftarkan kamera langsung dengan RTSP URL ke ZoneMinder (Triad ZM 1.38.6)."""
    data = request.json or {}

    raw_name = data.get("name", "").strip()
    source = data.get("source", "") or data.get("path", "")
    source = source.strip()
    zm_function = data.get("zmFunction") or data.get("function")
    width = str(data.get("width", "1280"))
    height = str(data.get("height", "720"))
    username = data.get("username") or data.get("user")
    password = data.get("password") or data.get("pass")

    if not raw_name or not source:
        return jsonify({"status": "error", "message": "Nama kamera dan URL RTSP wajib diisi!"}), 400

    if not source.lower().startswith("rtsp://"):
        return jsonify({"status": "error", "message": "URL kamera harus diawali dengan rtsp://"}), 400

    # Kredensial boleh dikirim sebagai URL utuh ATAU sebagai field terpisah.
    path, path_warnings = normalize_rtsp_path(source, username, password)
    clean_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", raw_name)

    # Bangun payload lengkap ZM 1.38.6 (disamakan dengan struktur native API)
    zm_payload = build_zm138_full_payload(
        name=clean_name,
        path=path,
        username=username,
        password=password,
        capturing=data.get("capturing"),
        analysing=data.get("analysing") or data.get("analysis"),
        recording=data.get("recording") or data.get("record"),
        width=width,
        height=height,
        max_fps=data.get("maxFps") or data.get("max_fps") or "10.00",
        analysis_fps_limit=data.get("analysisFps") or data.get("analysis_fps_limit") or "8.00",
        decoder=data.get("decoder") or "Auto",
        enabled=data.get("enabled", "1"),
        function=zm_function,
        # Konfigurasi event & analisis (default: 300 / 60 / system / 0 / 0 / 250 / Normal / 0)
        section_length=_pick(data, "sectionLength", "section_length", "SectionLength", default=300),
        min_section_length=_pick(data, "minSectionLength", "min_section_length", "MinSectionLength", default=60),
        event_close_mode=_pick(data, "eventCloseMode", "event_close_mode", "EventCloseMode", default="system"),
        frame_skip=_pick(data, "frameSkip", "frame_skip", "FrameSkip", default=0),
        analysis_update_delay=_pick(data, "analysisUpdateDelay", "analysis_update_delay", "AnalysisUpdateDelay", default=0),
        fps_report_interval=_pick(data, "fpsReportInterval", "fps_report_interval", "FPSReportInterval", default=250),
        importance=_pick(data, "importance", "Importance", default="Normal"),
        startup_delay=_pick(data, "startupDelay", "startup_delay", "StartupDelay", default=0),
        # Konfigurasi encoding video (default: 1 / 1 / h264 / libx264 / crf=23 / mp4)
        **read_encoding_fields(data),
    )

    try:
        # Sukses dinilai dari isi respons, bukan status HTTP. ZM 1.38 membalas
        # 200 untuk kegagalan validasi juga — lihat DEVICE_REQUIRED di atas.
        ok, err_message, res_data = zm_post_monitor("monitors.json", zm_payload)

        if ok:
            # Cari ID monitor (dari respons langsung atau pencarian nama)
            monitor_id = None
            if isinstance(res_data, dict):
                monitor = res_data.get("monitor", res_data) or {}
                if isinstance(monitor, list) and monitor:
                    monitor = monitor[0].get("Monitor", monitor[0]) if isinstance(monitor[0], dict) else monitor[0]
                monitor_id = (monitor or {}).get("Id") or (res_data or {}).get("Id")
            if not monitor_id:
                monitor_id = find_monitor_id_by_name(clean_name)

            # Zone deteksi WAJIB ada, kalau tidak Modect tidak akan pernah
            # menghasilkan alarm (ZM hanya menilai gerakan di dalam zone).
            # Kegagalan zone tidak membatalkan pendaftaran kamera: kamera
            # tetap dibuat, dan status zone dilaporkan apa adanya ke UI.
            zone_result = {"created": False, "skipped": True,
                           "reason": "Pembuatan zone dinonaktifkan."}
            zone_mode = normalize_zone_mode(data.get("zoneMode"))
            if data.get("createZone", True) and zone_mode:
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

            if path_warnings:
                message += " Catatan path: " + " ".join(path_warnings)

            # Triad yang efektif sudah tersimpan di dalam payload; kirim balik
            # ke UI supaya tampilan bisa memverifikasi nilai Cap/Ana/Rec.
            effective_triad = {
                "capturing": zm_payload.get("Monitor[Capturing]", ""),
                "analysing": zm_payload.get("Monitor[Analysing]", ""),
                "recording": zm_payload.get("Monitor[Recording]", ""),
                "enabled": zm_payload.get("Monitor[Enabled]", "1"),
            }

            return jsonify({
                "status": "success",
                "message": message,
                "monitor_id": monitor_id,
                "triad": effective_triad,
                "zone": zone_result,
                "path_warnings": path_warnings,
                "analysis_fps": zm_payload.get("Monitor[AnalysisFPSLimit]", "8.00"),
                # Peringatan preflight encoding (mis. Pre/PostEventCount lebih
                # besar dari SectionLength) — bukan kegagalan, hanya catatan.
                "encoding_warnings": validate_encoding_payload(zm_payload),
                "encoding": {
                    "storage_id": zm_payload.get("Monitor[StorageId]", ""),
                    "video_writer": zm_payload.get("Monitor[VideoWriter]", ""),
                    "output_codec": zm_payload.get("Monitor[OutputCodec]", ""),
                    "output_codec_name": zm_payload.get("Monitor[OutputCodecName]", ""),
                    "encoder": zm_payload.get("Monitor[Encoder]", ""),
                    "encoder_parameters": zm_payload.get("Monitor[EncoderParameters]", ""),
                    "output_container": zm_payload.get("Monitor[OutputContainer]", ""),
                },
                "data": res_data
            }), 200
        else:
            # Pesan validasi asli diteruskan supaya operator tahu field mana
            # yang ditolak, bukan sekadar "gagal".
            return jsonify({
                "status": "error",
                "message": f"ZoneMinder menolak kamera: {err_message}"
            }), 400

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
        clean_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(name or "").strip())
        raw_path = str(monitor_data.get("Path", "") or "").strip()

        # Validasi dasar. Nama kosong TIDAK boleh lolos: ZoneMinder menerima
        # monitor tanpa nama, sehingga baris rusak dari Excel akan tersimpan
        # sebagai kamera tak bernama dan sulit dilacak operator.
        if not clean_name:
            fail_count += 1
            results.append({
                "row": idx + 1,
                "name": "",
                "status": "failed",
                "error": "Nama kamera kosong",
            })
            continue

        if not raw_path or not raw_path.lower().startswith("rtsp://"):
            fail_count += 1
            results.append({
                "name": clean_name,
                "status": "failed",
                "error": "URL RTSP tidak valid atau kosong"
            })
            continue

        u_name = (
            monitor_data.get("User")
            or monitor_data.get("Username")
            or monitor_data.get("user")
            or monitor_data.get("username")
        )
        u_pass = (
            monitor_data.get("Pass")
            or monitor_data.get("Password")
            or monitor_data.get("pass")
            or monitor_data.get("password")
        )
        path, path_warnings = normalize_rtsp_path(raw_path, u_name, u_pass)

        # Bangun payload lengkap ZM 1.38.6 native
        payload = build_zm138_full_payload(
            name=clean_name,
            path=path,
            username=u_name,
            password=u_pass,
            capturing=monitor_data.get("Capturing") or monitor_data.get("capturing"),
            analysing=monitor_data.get("Analysing") or monitor_data.get("Analysis") or monitor_data.get("analysing"),
            recording=monitor_data.get("Recording") or monitor_data.get("Record") or monitor_data.get("recording"),
            width=str(monitor_data.get("Width") or "1280"),
            height=str(monitor_data.get("Height") or "720"),
            max_fps=monitor_data.get("MaxFPS") or monitor_data.get("Max_FPS") or monitor_data.get("Max FPS") or "10.00",
            analysis_fps_limit=monitor_data.get("AnalysisFPS") or monitor_data.get("AnalysisFPSLimit") or monitor_data.get("Analysis FPS") or "8.00",
            decoder=monitor_data.get("Decoder") or monitor_data.get("decoder") or "Auto",
            enabled=monitor_data.get("Enabled", "1"),
            function=monitor_data.get("Function") or monitor_data.get("zmFunction"),
            # Konfigurasi event & analisis per baris (dari Excel) — nilai 0
            # dihormati lewat _pick, tidak tergeser ke default.
            section_length=_pick(monitor_data, "SectionLength", "sectionLength", "section_length", "Section Length", default=300),
            min_section_length=_pick(monitor_data, "MinSectionLength", "minSectionLength", "min_section_length", "Minimum Section Length", default=60),
            event_close_mode=_pick(monitor_data, "EventCloseMode", "eventCloseMode", "event_close_mode", "Event Close Mode", default="system"),
            frame_skip=_pick(monitor_data, "FrameSkip", "frameSkip", "frame_skip", "Frame Skip", default=0),
            analysis_update_delay=_pick(monitor_data, "AnalysisUpdateDelay", "analysisUpdateDelay", "analysis_update_delay", "Analysis Update Delay", default=0),
            fps_report_interval=_pick(monitor_data, "FPSReportInterval", "fpsReportInterval", "fps_report_interval", "FPS report interval", "FPS Report Interval", default=250),
            importance=_pick(monitor_data, "Importance", "importance", default="Normal"),
            startup_delay=_pick(monitor_data, "StartupDelay", "startupDelay", "startup_delay", "Startup Delay", default=0),
            # Konfigurasi encoding video per baris (dari Excel) — kolom kosong
            # mewarisi default 1.38.6, bukan mengosongkan setelan kamera.
            **read_encoding_fields(monitor_data),
        )

        try:
            # Sukses TIDAK dinilai dari status HTTP: ZM membalas 200 untuk
            # kegagalan validasi juga (lihat DEVICE_REQUIRED di atas).
            ok, message, res_json = zm_post_monitor("monitors.json", payload)

            if ok:
                success_count += 1
                entry = {
                    "name": clean_name,
                    "status": "success",
                    "id": res_json.get("Id", ""),
                    "analysis_fps": payload.get("Monitor[AnalysisFPSLimit]", ""),
                    # Peringatan preflight encoding per baris (bukan kegagalan).
                    "encoding_warnings": validate_encoding_payload(payload),
                    "encoding": {
                        "storage_id": payload.get("Monitor[StorageId]", ""),
                        "video_writer": payload.get("Monitor[VideoWriter]", ""),
                        "output_codec": payload.get("Monitor[OutputCodec]", ""),
                        "output_codec_name": payload.get("Monitor[OutputCodecName]", ""),
                        "encoder": payload.get("Monitor[Encoder]", ""),
                        "encoder_parameters": payload.get("Monitor[EncoderParameters]", ""),
                        "output_container": payload.get("Monitor[OutputContainer]", ""),
                    },
                }
                if path_warnings:
                    entry["path_warnings"] = path_warnings

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
                # Pesan asli dari ZoneMinder diteruskan apa adanya supaya
                # operator tahu field mana yang ditolak.
                fail_count += 1
                results.append({"name": clean_name, "status": "failed", "error": message})
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
# 5. API KONTROL CCTV CHECKER (TOGGLE AKTIF/MATI & DELAY INTERVAL)
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
# 6. WALL DASHBOARD (GRID KAMERA + GROUP)
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

    is_deleted = str(m.get("Deleted", "0")).lower() in ("1", "true")

    return {
        "id": str(m.get("Id", "")),
        "name": m.get("Name", "Unknown"),
        "function": m.get("Function", "None"),
        "capturing": m.get("Capturing", "None"),
        "analysing": m.get("Analysing", "None"),
        "recording": m.get("Recording", "None"),
        "enabled": str(m.get("Enabled", "0")) == "1",
        "deleted": is_deleted,
        "width": m.get("Width", ""),
        "height": m.get("Height", ""),
        "capture_fps": m.get("CaptureFPS", ""),
        "max_fps": m.get("MaxFPS", "10.00"),
        "analysis_fps": m.get("AnalysisFPSLimit", "8.00"),
        "decoder": m.get("Decoder", "Auto"),
        "user": m.get("User", ""),
        "path": _redact_rtsp(m.get("Path", "")),
        "raw_path": m.get("Path", ""),
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

    # Saring monitor yang telah di-soft-delete (Deleted=1) oleh ZoneMinder
    monitors = []
    for m in data.get("monitors", []):
        m_dict = m.get("Monitor", m) if isinstance(m, dict) else {}
        if str(m_dict.get("Deleted", "0")).lower() in ("1", "true"):
            continue
        monitors.append(normalize_monitor(m))

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
# 7. BULK CONTROL SELURUH KAMERA — TRIAD NATIVE ZM 1.38.6
# ==============================================================================
# ZM 1.38.6 tidak lagi mengendalikan monitor lewat Function legacy di UI.
# Kontrol operasional adalah triad: Capturing / Analysing / Recording.
# Kolom Function hanya dipertahankan skema database (NOT NULL) dan diisi
# otomatis oleh derive_function_from_triad() — UI tidak pernah memakainya.

# Catatan triad terakhir tiap kamera, supaya tombol "Pulihkan Triad" bisa
# mengembalikan mode asli setelah kamera dimatikan massal.
CAMERA_FUNCTIONS_FILE = os.environ.get("CAMERA_FUNCTIONS_FILE", "/app/data/camera_functions.json")


def _coerce_saved_triad(value):
    """Terima bentuk baru (dict triad) maupun lama (string Function) ->
    dict triad. File lama data/camera_functions.json berisi string Function,
    jadi migrasi harus berjalan tanpa intervensi operator.
    """
    if isinstance(value, dict) and any(k in value for k in ("capturing", "analysing", "recording")):
        return {
            "capturing": normalize_capturing(value.get("capturing"), default="Always"),
            "analysing": normalize_analysing(value.get("analysing"), default="None"),
            "recording": normalize_recording(value.get("recording"), default="None"),
        }
    if isinstance(value, str) and value:
        tr = build_zm138_triad(function=value)
        return {
            "capturing": tr["Capturing"],
            "analysing": tr["Analysing"],
            "recording": tr["Recording"],
        }
    return None


def load_saved_triads():
    if os.path.exists(CAMERA_FUNCTIONS_FILE):
        try:
            with open(CAMERA_FUNCTIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                out = {}
                for k, v in data.items():
                    triad = _coerce_saved_triad(v)
                    if triad:
                        out[str(k)] = triad
                return out
        except Exception as e:
            print(f"[ERROR LOAD CAMERA FUNCTIONS] {e}")
    return {}


def save_saved_triads(mapping):
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


def _zm_explain_response(res):
    """Ubah respons JSON ZoneMinder menjadi (sukses: bool, pesan: str).

    ZoneMinder 1.38 membalas HTTP 200 untuk DUA kondisi yang sangat berbeda:

        berhasil : {"message":"Saved"}
        validasi : {"message":{"Device":["Invalid device path. ..."]}}
        ditolak  : {"success":false,"data":{"name":"...","message":"..."}}

    Memeriksa status code saja membuat kegagalan validasi terlihat sukses.
    Fungsi ini membaca isi body dan mengembalikan pesan yang bisa ditampilkan
    apa adanya ke operator.
    """
    try:
        body = res.json()
    except Exception:
        text = (res.text or "").strip()
        return False, f"ZoneMinder membalas HTTP {res.status_code}: {text[:200] or 'tanpa isi'}"

    if not isinstance(body, dict):
        return False, f"Respons ZoneMinder tidak dikenali: {str(body)[:200]}"

    # Bentuk gagal eksplisit dari CakePHP Crud.
    if body.get("success") is False:
        data = body.get("data") or {}
        msg = data.get("message") or body.get("message") or "ditolak ZoneMinder"
        return False, str(msg)

    message = body.get("message")

    if message == "Saved":
        return True, "Saved"

    if isinstance(message, dict):
        # Pesan validasi per-field. Ratakan menjadi satu kalimat.
        parts = []
        for field, errs in message.items():
            if isinstance(errs, (list, tuple)):
                parts.append(f"{field}: " + "; ".join(str(e) for e in errs))
            else:
                parts.append(f"{field}: {errs}")
        return False, "Validasi ZoneMinder gagal — " + " | ".join(parts)

    if isinstance(message, str) and message:
        # Contoh: "Error <pre>...</pre>" dari cabang edit().
        return ("Saved" in message), message

    return False, f"Respons ZoneMinder tidak dikenali: {str(body)[:200]}"


def zm_post_monitor(path, data, retry=True):
    """POST monitor/zone ke ZM dan kembalikan (ok: bool, pesan: str, body: dict).

    Dipakai SEMUA jalur pembuatan & pengubahan monitor. Keberhasilan dinilai
    dari isi respons, bukan dari status HTTP — lihat _zm_explain_response().
    """
    session, token = zm_authenticated_session()

    q = {"token": token} if token else {}
    try:
        res = session.post(f"{ZM_BASE_URL}/{path}", params=q, data=data, timeout=20)
        if res.status_code in (401, 403) and retry:
            global ZM_SESSION_AUTHED
            ZM_SESSION.cookies.clear()
            ZM_SESSION_AUTHED = False
            return zm_post_monitor(path, data, retry=False)

        if res.status_code not in (200, 201):
            return False, f"ZoneMinder membalas HTTP {res.status_code}.", {}

        ok, msg = _zm_explain_response(res)
        try:
            body = res.json()
        except Exception:
            body = {}
        if not ok:
            log.warning("ZM POST %s ditolak: %s", path, msg)
        return ok, msg, (body if isinstance(body, dict) else {})

    except Exception as e:
        log.error("ZM POST %s gagal: %s", path, e)
        return False, f"Tidak dapat menghubungi ZoneMinder: {e}", {}



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
# ------------------------------------------------------------------------------
# DUA JEBAKAN FORMAT YANG PERNAH MEMBUAT "No zones to check"
# ------------------------------------------------------------------------------
# Keduanya sudah dibuktikan langsung pada ZoneMinder 1.36.32 di container ini.
# Jangan diubah tanpa membaca ulang src/zm_zone.cpp.
#
# 1) FORMAT Coords
#    ZM menyimpan Coords sebagai daftar pasangan "x,y" yang dipisah SPASI:
#        "0,0 1279,0 1279,719 0,719"
#    Bukan deret angka yang dipisah spasi seperti "0 0 1279 0 ...".
#    Bukti: skema zone bawaan ZM sendiri (includes/actions/monitor.php:207)
#    menulis sprintf('%d,%d %d,%d ...'). Parser C++ Zone::ParsePolygonString
#    mencari ',' lebih dulu, lalu melewati satu spasi setelahnya.
#
#    Kode lama menulis "0 0 1279 0 1279 719 0 719". Akibatnya ZM mencatat:
#        ERR-zm_zone.cpp/759 [Bogus coordinate 0 0 1279 0 1279 719 0 719 ...]
#        ERR-zm_zone.cpp/780 [Not enough coordinates to form a polygon!]
#        ERR-zm_zone.cpp/873 [... for zone 1/All for monitor ..., ignoring]
#    Zone DIBUANG tanpa pesan apa pun ke API, daftar zones jadi kosong, lalu
#    Monitor::DetectMotion() memunculkan Warning("No zones to check!").
#    Zone tetap ada di database, jadi pembuatan zone terlihat "berhasil".
#
# 2) SEMANTIK ANGKA AMBANG (MinAlarmPixels / MinBlobPixels / FilterPixels)
#    Di ZM 1.36.32 nilai ini adalah JUMLAH PIXEL MUTLAK, bukan persen.
#    Zone::Load() menulis `if ( false && !strcmp(Units, "Percent") )` sebelum
#    mengalikan persen — cabang itu dimatikan, jadi konversi tidak pernah
#    terjadi. Nilai langsung dipakai apa adanya di Zone::CheckAlarms().
#    Konsekuensinya: menulis "3" pada kamera 1280x720 berarti "3 piksel",
#    bukan "3% dari 921600 px" (= 27648 piksel) seperti yang tertulis di
#    komentar lama berkas ini. Itu akan memicu alarm dari noise 3 piksel.
#    Karena itu mode di bawah menyimpan ambang dalam PERSEN, lalu
#    build_zone_payload() mengalikannya dengan Area zone yang sebenarnya.
#
# Ukuran piksel polygon dihitung dengan algoritma shoelace yang sama
# (Polygon::UpdateArea) supaya angka yang kita kirim = angka yang dipakai ZM.
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
        # Nilai *_pct adalah PERSEN dari luas zone; dikonversi ke piksel saat
        # payload dibangun. Lihat catatan "SEMANTIK ANGKA AMBANG" di atas.
        "check": {"CheckMethod": "AlarmedPixels", "MinPixelThreshold": 60,
                  "MinAlarm_pct": 5, "MaxAlarm_pct": 75},
    },
    "light": {
        "label": "2. Ringan",
        "short": "Ringan",
        "description": (
            "CheckMethod=AlarmedPixels dengan ambang 20% dan alarm 1%. "
            "Beban CPU sama dengan Paling Ringan, tapi jauh lebih sensitif."
        ),
        "base_preset": "Fast, high sensitivity",
        "check": {"CheckMethod": "AlarmedPixels", "MinPixelThreshold": 20,
                  "MinAlarm_pct": 1, "MaxAlarm_pct": 75},
    },
    "medium": {
        "label": "3. Sedang",
        "short": "Sedang",
        "description": (
            "CheckMethod=Blobs dengan ambang 25% dan alarm 3%. Nilai ini persis "
            "preset 'Default' ZoneMinder (sudah dikonversi ke piksel). Objek "
            "dikelompokkan lebih dulu sehingga noise titik ditolak. Titik "
            "seimbang antara akurasi dan beban CPU."
        ),
        "base_preset": "Default",
        "check": {"CheckMethod": "Blobs", "MinPixelThreshold": 25,
                  "MinAlarm_pct": 3, "MaxAlarm_pct": 75,
                  "FilterX": 3, "FilterY": 3,
                  "MinFilter_pct": 3, "MaxFilter_pct": 75,
                  "MinBlob_pct": 2, "MaxBlob_pct": None, "MinBlobs": 1},
    },
    "heavy": {
        "label": "4. Berat",
        "short": "Berat",
        "description": (
            "CheckMethod=Blobs + ambang 60% dan blob minimal 0,5% luas frame. "
            "Hanya gerakan besar yang lolos. Beban CPU tinggi, false alarm "
            "paling sedikit."
        ),
        "base_preset": "Best, low sensitivity",
        "check": {"CheckMethod": "Blobs", "MinPixelThreshold": 60,
                  "MinAlarm_pct": 5, "MaxAlarm_pct": 75,
                  "FilterX": 7, "FilterY": 7,
                  "MinFilter_pct": 3.5, "MaxFilter_pct": None,
                  "MinBlob_pct": 0.5, "MaxBlob_pct": None, "MinBlobs": 1},
    },
    "heaviest": {
        "label": "5. Paling Berat",
        "short": "Paling Berat",
        "description": (
            "CheckMethod=Blobs + ambang 20% dan alarm 0,2%. Paling sensitif dan "
            "paling mahal: filter serta deteksi blob berjalan penuh tiap frame. "
            "Pakai hanya untuk sedikit kamera di area yang benar-benar penting."
        ),
        "base_preset": "Best, high sensitivity",
        "check": {"CheckMethod": "Blobs", "MinPixelThreshold": 20,
                  "MinAlarm_pct": 0.2, "MaxAlarm_pct": 75,
                  "FilterX": 3, "FilterY": 3,
                  "MinFilter_pct": 0.14, "MaxFilter_pct": None,
                  "MinBlob_pct": 0.12, "MaxBlob_pct": None, "MinBlobs": 1},
    },
}

# Mode default saat kamera didaftarkan tanpa menyebut mode. "light" dipilih
# karena menjalankan Modect yang benar-benar berfungsi tanpa membebani CPU
# seperti halnya Blobs pada jaringan banyak kamera.
ZONE_MODE_DEFAULT = "light"

# Nama zone yang dibuat otomatis. Dipakai untuk mengenali zone buatan
# dashboard, supaya konfigurasi manual pengguna tidak pernah ditimpa.
ZONE_DEFAULT_NAME = "All"

# Preset ZoneMinder dipakai HANYA sebagai sumber nilai non-ambang
# (Units, CheckMethod, ExtendAlarmFrames). Nilai ambangnya SENGAJA tidak
# diambil dari sini: pada ZM 1.36.32 API mengembalikan ambang dalam persen
# (skema Percent) sedangkan runtime membacanya sebagai piksel mutlak, jadi
# menyalinnya mentah-mentah menghasilkan alarm palsu. Ambang selalu dihitung
# di build_zone_payload() dari ZONE_MODES + luas zone sebenarnya.
ZONE_PRESET_FALLBACK = {
    "Default": {
        "Units": "Percent", "CheckMethod": "Blobs",
        "ExtendAlarmFrames": 0, "OverloadFrames": 0,
    },
    "Fast, low sensitivity": {
        "Units": "Percent", "CheckMethod": "AlarmedPixels",
        "ExtendAlarmFrames": 0, "OverloadFrames": 0,
    },
    "Fast, high sensitivity": {
        "Units": "Percent", "CheckMethod": "AlarmedPixels",
        "ExtendAlarmFrames": 0, "OverloadFrames": 0,
    },
    "Best, low sensitivity": {
        "Units": "Percent", "CheckMethod": "Blobs",
        "ExtendAlarmFrames": 0, "OverloadFrames": 0,
    },
    "Best, high sensitivity": {
        "Units": "Percent", "CheckMethod": "Blobs",
        "ExtendAlarmFrames": 0, "OverloadFrames": 0,
    },
}

# Kolom numerik yang BOLEH disalin dari preset ZM. Field ambang pixel
# sengaja tidak ada di sini — lihat catatan di atas ZONE_PRESET_FALLBACK.
_PRESET_SAFE_FIELDS = ("Units", "CheckMethod", "ExtendAlarmFrames", "OverloadFrames")


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


# ==============================================================================
# DEFAULT ENCODING MONITOR - SINGLE SOURCE OF TRUTH
# ==============================================================================
# Semua jalur pendaftaran kamera - tunggal, burst, dan unggah Excel - memakai
# blok ini. Kamera yang baru didaftarkan langsung merekam ke MP4 h264 tanpa
# perlu disetel manual satu per satu di antarmuka ZoneMinder.
#
# NILAI DI BAWAH SUDAH DIUJI TERHADAP ZONEMINDER 1.36.32 YANG BERJALAN:
#   * OutputContainer TIDAK boleh dikirim sebagai null atau string kosong: API
#     menolak dengan "Please choose one of the following values : Auto, Mp4,
#     Mkv" dan SELURUH pembuatan monitor gagal. Karena itu field ini ada di
#     ENCODING_SKIP_FIELDS: tidak dikirim sama sekali, dan kolomnya tetap NULL
#     di database - persis keadaan yang diinginkan.
#   * OutputCodec 27 adalah kode h264; 0 = Auto, 27 = h264, 173 = h265.
#   * DefaultRate dan DefaultScale hanya memengaruhi stream ke browser, bukan
#     perekaman. Nilai 0 pada DefaultScale berarti 100 persen, yaitu resolusi
#     asli kamera.
#
# Hubungan SectionLength dengan Pre/PostEventCount diperiksa oleh
# validate_encoding_defaults() dan dilaporkan sebagai PERINGATAN, bukan
# pemblokiran, supaya nilai tidak lazim tetap bisa dipakai.
MONITOR_ENCODING_DEFAULTS = {
    "SaveJPEGs": "0",            # 0 = jangan simpan JPEG, MP4 saja
    "StorageId": "1",            # 1 = area 'Default' bawaan ZM
    "VideoWriter": "1",          # 1 = aktifkan penulis video
    "OutputCodec": "27",         # 27 = h264 (terverifikasi di ZM 1.38.6)
    # OutputCodecName WAJIB berpasangan dengan OutputCodec: API memvalidasi
    # kode int, sedangkan konsol ZM membaca nama. 27 <-> h264.
    "OutputCodecName": "h264",
    "OutputContainer": "mp4",     # hanya auto/mp4/mkv yang diterima API
    "Encoder": "libx264",
    "EncoderParameters": "crf=23",
    "PreEventCount": "50",       # frame sebelum alarm disertakan
    "PostEventCount": "50",      # frame sesudah alarm disertakan
    "StreamReplayBuffer": "0",
    "AlarmFrameCount": "1",
    "SectionLength": "300",      # detik maksimum satu berkas rekaman
    "MinSectionLength": "60",
    "DefaultRate": "100",        # stream browser: 100 persen
    "DefaultScale": "0",         # 0 dibaca ZM sebagai 100 persen (resolusi asli)
    "DefaultCodec": "auto",
}

# Field yang SEKALI-KALI tidak boleh dikirim ke API ZoneMinder. Mengirim
# OutputContainer dengan nilai kosong membuat ZM menolak SELURUH permintaan
# simpan, jadi field ini dibuang di satu tempat saja: build_encoding_payload().
# OutputContainer kini SELALU dikirim dengan nilai sah (auto/mp4/mkv), jadi
# tidak ada lagi field yang perlu dibuang. Tuple dipertahankan supaya mekanisme
# penyaring di build_encoding_payload() tetap bekerja bila nanti ada field yang
# memang tidak boleh dikirim.
ENCODING_SKIP_FIELDS = ()

# Field yang boleh ditimpa per kamera dari UI maupun kolom Excel.
# Urutannya sekaligus menjadi daftar kunci yang diterima dari berkas Excel.
ENCODING_OVERRIDE_FIELDS = (
    "Encoder", "OutputCodec", "OutputCodecName", "EncoderParameters",
    "PreEventCount", "PostEventCount", "AlarmFrameCount",
    "SectionLength", "MinSectionLength",
    "DefaultRate", "DefaultScale", "DefaultCodec",
    "StorageId", "VideoWriter", "OutputContainer",
    "SaveJPEGs", "StreamReplayBuffer",
)

# Field numerik untuk sanity check di validate_encoding_defaults().
_ENCODING_NUMERIC_FIELDS = (
    "OutputCodec", "PreEventCount", "PostEventCount", "AlarmFrameCount",
    "SectionLength", "MinSectionLength", "DefaultRate", "DefaultScale",
    "VideoWriter", "SaveJPEGs", "StreamReplayBuffer",
)


def _encoding_int(value):
    """Baca nilai integer secara longgar. None bila tidak masuk akal."""
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def resolve_encoding_defaults(overrides=None):
    """Default encoding + penimpaan per kamera, sudah dibersihkan.

    overrides: dict opsional dari UI atau baris Excel. Kunci yang tidak
    dikenal dibuang, dan nilai kosong diabaikan (jatuh ke default) sehingga
    satu sel Excel yang kosong tidak mengosongkan setelan kamera.
    """
    result = dict(MONITOR_ENCODING_DEFAULTS)
    if isinstance(overrides, dict):
        for key in ENCODING_OVERRIDE_FIELDS:
            if key not in overrides:
                continue
            value = overrides[key]
            if value is None:
                continue
            text = str(value).strip()
            if text == "":
                continue
            result[key] = text
    return result


def validate_encoding_defaults(values):
    """Periksa kewajaran setelan encoding. Mengembalikan daftar peringatan.

    SENGAJA hanya peringatan, bukan penolakan: nilai tidak lazim tetap
    disimpan, tapi pengguna diberi tahu supaya tidak menemukan rekaman yang
    terpotong-potong tanpa sebab yang jelas.
    """
    warnings = []
    nums = {key: _encoding_int(values.get(key)) for key in _ENCODING_NUMERIC_FIELDS}

    section = nums.get("SectionLength")
    pre = nums.get("PreEventCount")
    post = nums.get("PostEventCount")

    if section is not None and section > 0:
        # Pre/PostEventCount dihitung dalam FRAME, sedangkan SectionLength
        # dalam DETIK. Pada 15 fps, 50 frame kira-kira 3,3 detik. Bila jumlah
        # frame pre+post melebihi panjang section, ZM tidak punya cukup frame
        # untuk memenuhi permintaan dan potongan rekaman bisa terpangkas.
        if pre is not None and pre > section:
            warnings.append(
                "PreEventCount (%s) lebih besar dari SectionLength (%s). "
                "Nilai ini dalam frame, sedangkan SectionLength dalam detik."
                % (pre, section)
            )
        if post is not None and post > section:
            warnings.append(
                "PostEventCount (%s) lebih besar dari SectionLength (%s). "
                "Nilai ini dalam frame, sedangkan SectionLength dalam detik."
                % (post, section)
            )
        if pre is not None and post is not None and (pre + post) > section:
            warnings.append(
                "PreEventCount + PostEventCount (%s) melebihi SectionLength (%s). "
                "Rekaman berpotensi terpotong pada bagian pre/post event."
                % (pre + post, section)
            )

    scale = nums.get("DefaultScale")
    if scale is not None and scale < 0:
        warnings.append(
            "DefaultScale (%s) negatif; nilai 0 berarti 100 persen (resolusi asli)." % scale
        )

    rate = nums.get("DefaultRate")
    if rate is not None and rate < 0:
        warnings.append("DefaultRate (%s) negatif." % rate)

    codec = str(values.get("OutputCodec", "")).strip()
    if codec and codec not in ("0", "27", "173", "167", "226"):
        # 0=Auto, 27=h264, 173=h265, 167=vp9, 226=av1 pada ZM 1.38.6. Kode lain
        # tetap diterima ZM bila memang terdaftar, jadi ini hanya catatan.
        warnings.append("OutputCodec=%s bukan 0/27/173/167/226 (Auto/h264/h265/vp9/av1)." % codec)

    if str(values.get("VideoWriter", "")).strip() in ("0", "") \
            and str(values.get("SaveJPEGs", "")).strip() == "0":
        warnings.append(
            "VideoWriter=0 dan SaveJPEGs=0: tidak ada berkas rekaman yang akan "
            "tersimpan. Hanya berguna bila perekaman memang sengaja dimatikan."
        )

    return warnings


def validate_encoding_payload(payload):
    """Peringatan preflight untuk payload Monitor[...] ZM 1.38.6.

    Dipakai jalur pendaftaran (tunggal & burst) supaya operator melihat
    peringatan yang sama dengan yang diperiksa validate_encoding_defaults()
    pada jalur lama — mis. Pre/PostEventCount yang lebih besar dari
    SectionLength sehingga potongan rekaman bisa terpangkas.
    """
    if not isinstance(payload, dict):
        return []
    values = {}
    for key, value in payload.items():
        if key.startswith("Monitor[") and key.endswith("]"):
            values[key[len("Monitor["):-1]] = value
    return validate_encoding_defaults(values)


def build_encoding_payload(overrides=None):
    """Bentuk pasangan Monitor[*] siap kirim untuk field encoding.

    Mengembalikan tuple (payload, warnings). Field di ENCODING_SKIP_FIELDS
    selalu dibuang di sini - satu-satunya tempat pembuangan - sehingga tidak
    ada jalur pendaftaran yang bisa tidak sengaja mengirim OutputContainer
    kosong lalu menggagalkan seluruh penyimpanan.
    """
    values = resolve_encoding_defaults(overrides)

    # Pasangan kodec dijaga di SATU tempat ini: OutputCodec (int) dan
    # OutputCodecName (varchar) tidak boleh terpisah, karena API ZM memvalidasi
    # kode sedangkan konsol ZM membaca nama. Bila VideoWriter bukan Encode
    # (0/2), kodec dan encoder tidak dipakai ZM sehingga dikunci ke 'auto'.
    writer_key = normalize_video_writer(values.get("VideoWriter"))
    codec_key = normalize_output_codec(
        values.get("OutputCodecName") or values.get("OutputCodec")
    )
    if writer_key != "1":
        codec_key = "auto"
        values["Encoder"] = "auto"
    codec_name, codec_code = OUTPUT_CODECS[codec_key]
    values["VideoWriter"] = writer_key
    values["OutputCodec"] = codec_code
    values["OutputCodecName"] = codec_name
    values["StorageId"] = normalize_storage_id(values.get("StorageId"))
    values["Encoder"] = normalize_encoder(values.get("Encoder"))
    values["EncoderParameters"] = normalize_encoder_parameters(values.get("EncoderParameters"))
    values["OutputContainer"] = normalize_output_container(values.get("OutputContainer"))

    payload = {}
    for key in values:
        if key in ENCODING_SKIP_FIELDS:
            continue
        value = values[key]
        if value is None:
            continue
        payload["Monitor[%s]" % key] = str(value)
    return payload, validate_encoding_defaults(values)


def _key_aliases(key):
    """Variasi nama kolom untuk satu kunci camelCase.

    Excel ditulis manusia, jadi "OutputContainer" bisa muncul sebagai
    "Output Container", "output_container", atau "outputcontainer". Semua
    bentuk itu menunjuk field yang sama supaya satu kolom tidak diam-diam
    diabaikan hanya karena beda spasi.
    """
    spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", key)
    merged = key.replace("_", "")
    return (
        key,
        spaced,
        spaced.lower(),
        key.lower(),
        merged,
        merged.lower(),
    )


def read_encoding_overrides(source):
    """Ambil penimpaan encoding dari body request maupun baris Excel.

    Menerima bentuk bersarang {"encoding": {...}} yang dipakai UI, dan bentuk
    datar {"Encoder": "...", "Output Container": "mkv"} yang dipakai kolom
    Excel. Nilai kosong diabaikan agar sel kosong tidak mengosongkan setelan.
    """
    if not isinstance(source, dict):
        return {}
    nested = source.get("encoding")
    flat = nested if isinstance(nested, dict) else source
    out = {}
    for key in ENCODING_OVERRIDE_FIELDS:
        value = _pick(flat, *_key_aliases(key), default=None)
        if value is None:
            continue
        out[key] = value
    return out


  
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


def polygon_area(points):
    """Luas polygon dengan algoritma shoelace — rumus yang SAMA dengan
    ZoneMinder (Polygon::UpdateArea di src/zm_poly.cpp).

    Dipakai supaya angka yang dikirim dashboard identik dengan yang nanti
    dipakai ZM saat mengevaluasi gerakan. Bila keduanya berbeda, ambang
    piksel ikut berbeda dari yang dimaksud.
    """
    n = len(points)
    if n < 3:
        return 0
    total = 0.0
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        total += (float(x1) * float(y2)) - (float(x2) * float(y1))
    return int(round(abs(total) / 2.0))


def build_full_frame_points(width, height):
    """Empat sudut frame dalam koordinat piksel monitor (0-based).

    Urutan mengikuti jejak blok zone bawaan ZoneMinder
    (includes/actions/monitor.php): (0,0) -> (W-1,0) -> (W-1,H-1) -> (0,H-1).
    """
    return [(0, 0), (width - 1, 0), (width - 1, height - 1), (0, height - 1)]


def format_zone_coords(points):
    """Serialkan titik ke format Coords yang benar-benar dibaca ZoneMinder.

    WAJIB pasangan "x,y" dipisah SPASI: "0,0 1279,0 1279,719 0,719".
    Deret angka dipisah spasi ("0 0 1279 0 ...") DITOLAK parser ZM dan zone
    dibuang tanpa error ke API — penyebab "No zones to check". Lihat catatan
    "DUA JEBAKAN FORMAT" di atas ZONE_MODES.
    """
    return " ".join(f"{int(x)},{int(y)}" for x, y in points)


def build_zone_payload(mode_key, width, height):
    """Susun payload zone layar penuh untuk ZoneMinder.

    width/height HARUS berasal dari monitor sebagaimana disimpan ZoneMinder
    (bukan dari input pengguna), karena koordinat zone memakai ruang resolusi
    monitor dan ZM menghitungnya 0-based.
    """
    spec = ZONE_MODES[mode_key]

    w = int(width) if str(width).isdigit() and int(width) > 1 else 1920
    h = int(height) if str(height).isdigit() and int(height) > 1 else 1080

    # Polygon dan luasnya dihitung, bukan ditebak: luas HARUS berasal dari
    # polygon yang benar-benar dikirim, karena dari situ ZM menurunkan
    # ambang dan skor alarm.
    points = build_full_frame_points(w, h)
    area = polygon_area(points)

    # Nilai non-ambang boleh ikut preset ZM supaya perilaku tetap selaras
    # bila ZoneMinder di-upgrade. Field ambang TIDAK diambil dari preset.
    preset = {}
    presets = get_zm_zone_presets()
    if isinstance(presets, dict) and spec["base_preset"] in presets:
        src = presets[spec["base_preset"]]
        if isinstance(src, dict):
            preset = {k: src[k] for k in _PRESET_SAFE_FIELDS if k in src}

    payload = {
        "Zone[Name]": ZONE_DEFAULT_NAME,
        "Zone[Type]": "Active",
        "Zone[Units]": str(preset.get("Units") or "Percent"),
        "Zone[NumCoords]": str(len(points)),
        "Zone[Coords]": format_zone_coords(points),
        # Luas polygon dalam piksel. ZM menghitung ulang saat load, tapi
        # nilai yang benar di sini membuat baris database langsung konsisten
        # dan mudah diverifikasi.
        "Zone[Area]": str(area),
        "Zone[AlarmRGB]": "16711680",  # 0xFF0000, merah penuh
        "Zone[CheckMethod]": str(spec["check"]["CheckMethod"]),
        "Zone[MinPixelThreshold]": str(spec["check"]["MinPixelThreshold"]),
        "Zone[ExtendAlarmFrames]": str(preset.get("ExtendAlarmFrames") or 0),
        "Zone[OverloadFrames]": str(preset.get("OverloadFrames") or 0),
    }

    # Ambang di bawah ini JUMLAH PIKEL MUTLAK pada ZM 1.36.x, jadi persen
    # dari ZONE_MODES dikalikan luas zone lebih dulu. Tanpa konversi ini,
    # "3" akan berarti 3 piksel dan alarm menyala karena noise sekecil apa pun.
    for key, column in (
        ("MinAlarm_pct", "MinAlarmPixels"),
        ("MaxAlarm_pct", "MaxAlarmPixels"),
        ("MinFilter_pct", "MinFilterPixels"),
        ("MaxFilter_pct", "MaxFilterPixels"),
        ("MinBlob_pct", "MinBlobPixels"),
        ("MaxBlob_pct", "MaxBlobPixels"),
    ):
        pct = spec["check"].get(key)
        if pct is None:
            continue
        payload[f"Zone[{column}]"] = str(int(round(area * float(pct) / 100.0)))

    # Hitungan blob adalah cacah objek, bukan piksel — tidak dikonversi.
    for key in ("MinBlobs", "MaxBlobs", "FilterX", "FilterY"):
        value = spec["check"].get(key)
        if value is not None:
            payload[f"Zone[{key}]"] = str(value)

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
    # ZM 1.38.6 TIDAK punya endpoint bersarang ini (balas 404), jadi jalur
    # utama adalah daftar global. Endpoint bersarang hanya dicoba bila daftar
    # global gagal, supaya log tidak dipenuhi "HTTP 404" yang wajar terjadi.
    raw = None
    data = zm_api_get("zones.json")
    if isinstance(data, dict):
        candidate = data.get("zones")
        if isinstance(candidate, list):
            raw = candidate

    if raw is None:
        nested = zm_api_get(f"monitors/{monitor_id}/zones.json")
        if isinstance(nested, dict):
            candidate = nested.get("zones")
            if isinstance(candidate, list):
                raw = candidate

    if raw is None:
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
            if str(m.get("Deleted", "0")).lower() in ("1", "true"):
                continue
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

    # ZM 1.38 membalas 200 untuk sukses MAUPUN gagal, jadi hasilnya dibaca
    # dari isi respons (lihat _zm_explain_response).
    ok, zone_message, zone_body = zm_post_monitor("zones.json", payload)
    if not ok:
        ok, zone_message, zone_body = zm_post_monitor(
            f"monitors/{monitor_id}/zones.json", payload
        )

    if not ok:
        return {
            "created": False, "skipped": False, "mode": mode,
            "reason": f"ZoneMinder menolak pembuatan zone: {zone_message}",
        }

    # ZM 1.38 menyertakan zone yang baru dibuat: {"zone":{"Zone":{"Id":N,...}}}
    new_zone_id = None
    zobj = zone_body.get("zone")
    if isinstance(zobj, dict):
        inner = zobj.get("Zone") or zobj
        if isinstance(inner, dict):
            new_zone_id = inner.get("Id")

    # ------------------------------------------------------------------
    # VERIFIKASI SETELAH SIMPAN — jangan percaya "Saved".
    #
    # ZoneMinder 1.36 membalas {"message":"Saved"} walau polygon-nya tidak
    # bisa diparse. Itu persis yang terjadi sebelumnya: zone tercatat di
    # database, API melaporkan sukses, tapi saat runtime zone dibuang dan
    # Modect berhenti dengan "No zones to check". Tanpa pembacaan ulang di
    # sini, kegagalan itu tidak akan pernah terlihat dari dashboard.
    # ------------------------------------------------------------------
    verify = verify_zone_saved(monitor_id, payload)
    if verify.get("ok"):
        return {
            "created": True, "skipped": False, "mode": mode,
            "label": ZONE_MODES[mode]["label"],
            "coords": payload["Zone[Coords]"],
            "width": width, "height": height,
            "zone_id": verify.get("zone_id") or new_zone_id,
            "area": verify.get("area"),
        }

    return {
        "created": False, "skipped": False, "mode": mode,
        "reason": verify.get("reason") or "Zone tersimpan tetapi tidak terbaca ulang.",
        "coords": payload["Zone[Coords]"],
        "width": width, "height": height,
    }


def verify_zone_saved(monitor_id, payload):
    """Baca ulang zone yang baru disimpan dan pastikan ZM bisa memakainya.

    Yang diperiksa adalah hal-hal yang membuat Zone::Load() membuang zone
    secara diam-diam:
      - zone benar-benar ada untuk MonitorId ini,
      - Coords tersimpan dalam format pasangan "x,y",
      - polygon menghasilkan >= 3 titik dan luas > 0,
      - Type bukan Inactive/Privacy.

    Tanpa pemeriksaan ini, "zone berhasil dibuat" hanya berarti baris
    database bertambah — bukan berarti Modect akan mendeteksi gerakan.
    """
    zones = get_monitor_zones(monitor_id)
    if zones is None:
        return {"ok": False, "reason": "Zone tersimpan tetapi daftar zone tidak dapat dibaca ulang."}

    wanted_coords = str(payload.get("Zone[Coords]", ""))
    zone = None
    for z in zones:
        if str(z.get("Name", "")) == ZONE_DEFAULT_NAME and str(z.get("Coords", "")) == wanted_coords:
            zone = z
            break
    if zone is None:
        # Fallback: cocokkan berdasarkan nama saja (ZM kadang menormalkan spasi).
        for z in zones:
            if str(z.get("Name", "")) == ZONE_DEFAULT_NAME:
                zone = z
                break
    if zone is None:
        return {"ok": False, "reason": "Zone tersimpan tetapi tidak ditemukan saat dibaca ulang."}

    zone_type = str(zone.get("Type", ""))
    if zone_type in ("Inactive", "Privacy"):
        return {"ok": False, "reason": f"Zone bertipe '{zone_type}' sehingga tidak dinilai Modect."}

    stored = str(zone.get("Coords", "") or "").strip()
    if not stored:
        return {"ok": False, "reason": "Zone tersimpan tanpa titik koordinat."}

    if "," not in stored:
        # Bentuk yang ditolak parser C++: deret angka dipisah spasi.
        return {
            "ok": False,
            "reason": (
                "Koordinat zone tidak dalam format 'x,y' sehingga akan ditolak "
                f"ZoneMinder dan memicu 'No zones to check'. Tersimpan sebagai: {stored}"
            ),
        }

    points = []
    for pair in stored.split():
        if "," not in pair:
            return {
                "ok": False,
                "reason": f"Titik koordinat '{pair}' tidak valid (harus 'x,y').",
            }
        try:
            px, py = pair.split(",", 1)
            points.append((float(px), float(py)))
        except (TypeError, ValueError):
            return {"ok": False, "reason": f"Titik koordinat '{pair}' tidak dapat dibaca."}

    if len(points) < 3:
        return {
            "ok": False,
            "reason": f"Zone hanya punya {len(points)} titik; ZoneMinder butuh minimal 3.",
        }

    area = polygon_area(points)
    if area <= 0:
        return {"ok": False, "reason": "Luas zone nol — gerakan tidak akan pernah terdeteksi."}

    return {"ok": True, "zone_id": zone.get("Id"), "area": area, "points": len(points)}


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
      path      : URL RTSP (boleh sudah memuat user:pass@host, atau kosong
                  kredensialnya lalu diisi lewat username/password)
      username  : opsional — hanya dipakai bila path belum memuat kredensial
      password  : opsional — di-percent-encode otomatis (@ -> %40)
      analysisFps: batas laju analisa motion (default ANALYSIS_FPS_DEFAULT = 8)
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
    raw_path = str(body.get("path", "")).strip()
    edit_id = str(body.get("id", "") or "").strip()

    if not name or not raw_path:
        return jsonify({
            "status": "error",
            "message": "Nama kamera dan RTSP Path wajib diisi.",
        }), 400

    # Perbaiki sekaligus path lama yang terlanjur rusak (user:pass@pass@host).
    # Saat mengedit, path yang tersimpan di DB akan diperbaiki begitu operator
    # menekan Simpan — tidak perlu menyunting database.
    path, path_warnings = normalize_rtsp_path(
        raw_path, body.get("username"), body.get("password")
    )

    clean_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", name)
    width = str(body.get("width") or "1920")
    height = str(body.get("height") or "1080")
    # Bangun payload lengkap ZM 1.38.6 native
    payload = build_zm138_full_payload(
        name=clean_name,
        path=path,
        username=body.get("username") or body.get("user"),
        password=body.get("password") or body.get("pass"),
        capturing=body.get("capturing"),
        analysing=body.get("analysing") or body.get("analysis"),
        recording=body.get("recording") or body.get("record"),
        width=width,
        height=height,
        max_fps=body.get("maxFps") or body.get("max_fps") or "10.00",
        analysis_fps_limit=body.get("analysisFps") or body.get("analysis_fps_limit") or "8.00",
        decoder=body.get("decoder") or "Auto",
        enabled=body.get("enabled", "1"),
        function=str(body.get("function") or "Monitor"),
        # Konfigurasi event & analisis (default 1.38.6: 300/60/system/0/0/250/Normal/0).
        section_length=_pick(body, "sectionLength", "section_length", "SectionLength", default=300),
        min_section_length=_pick(body, "minSectionLength", "min_section_length", "MinSectionLength", default=60),
        event_close_mode=_pick(body, "eventCloseMode", "event_close_mode", "EventCloseMode", default="system"),
        frame_skip=_pick(body, "frameSkip", "frame_skip", "FrameSkip", default=0),
        analysis_update_delay=_pick(body, "analysisUpdateDelay", "analysis_update_delay", "AnalysisUpdateDelay", default=0),
        fps_report_interval=_pick(body, "fpsReportInterval", "fps_report_interval", "FPSReportInterval", default=250),
        importance=_pick(body, "importance", "Importance", default="Normal"),
        startup_delay=_pick(body, "startupDelay", "startup_delay", "StartupDelay", default=0),
        # Konfigurasi encoding video (default: 1 / 1 / h264 / libx264 / crf=23 / mp4)
        **read_encoding_fields(body),
    )

    # ID kustom hanya dipakai saat membuat kamera baru. Saat mengedit, ID
    # sudah ditentukan oleh URL target.
    custom_id = str(body.get("customId", "") or "").strip()
    if not edit_id and custom_id.isdigit():
        payload["Monitor[Id]"] = custom_id

    # Saat MENGEDIT dari modal yang tidak menampilkan field event/analisis,
    # nilai default dari build_zm138_full_payload TIDAK boleh menimpa nilai
    # kustom yang sudah tersimpan di ZM. Hapus 8 field itu dari payload bila
    # request tidak mengirimkannya secara eksplisit.
    if edit_id:
        _EVENT_PAYLOAD_KEYS = (
            "Monitor[SectionLength]", "Monitor[MinSectionLength]",
            "Monitor[EventCloseMode]", "Monitor[FrameSkip]",
            "Monitor[AnalysisUpdateDelay]", "Monitor[FPSReportInterval]",
            "Monitor[Importance]", "Monitor[StartupDelay]",
        )
        _EVENT_BODY_KEYS = (
            "sectionLength", "minSectionLength", "eventCloseMode", "frameSkip",
            "analysisUpdateDelay", "fpsReportInterval", "importance", "startupDelay",
        )
        if not any(k in body for k in _EVENT_BODY_KEYS):
            for k in _EVENT_PAYLOAD_KEYS:
                payload.pop(k, None)

        # Prinsip yang sama untuk 6 field encoding: modal edit yang tidak
        # menampilkan Storage/VideoWriter/Codec/Encoder/Container tidak boleh
        # diam-diam menimpa setelan kustom yang sudah tersimpan di ZM.
        _ENCODING_PAYLOAD_KEYS = (
            "Monitor[StorageId]", "Monitor[VideoWriter]",
            "Monitor[OutputCodec]", "Monitor[OutputCodecName]",
            "Monitor[Encoder]", "Monitor[EncoderParameters]",
            "Monitor[OutputContainer]",
        )
        _ENCODING_BODY_KEYS = (
            "storageId", "storage_id", "StorageId", "videoWriter", "video_writer",
            "outputCodec", "output_codec", "encoder", "encoderParameters",
            "encoder_parameters", "outputContainer", "output_container",
        )
        if not any(k in body for k in _ENCODING_BODY_KEYS):
            for k in _ENCODING_PAYLOAD_KEYS:
                payload.pop(k, None)

    if edit_id:
        target = f"monitors/{edit_id}.json"
    else:
        target = "monitors.json"

    # Sukses dinilai dari isi respons, bukan status HTTP — ZM 1.38 membalas 200
    # untuk kegagalan validasi juga (lihat DEVICE_REQUIRED di atas).
    # Saat MENGEDIT, jalur edit() CakePHP membalas {"message":"Saved"} bila
    # berhasil dan "Error <pre>...</pre>" bila gagal.
    ok, save_message, _save_body = zm_post_monitor(target, payload)
    if not ok:
        return jsonify({
            "status": "error",
            "message": f"ZoneMinder menolak penyimpanan kamera: {save_message}",
        }), 400

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
        "path_warnings": path_warnings,
        "analysis_fps": payload.get("Monitor[AnalysisFPSLimit]", "8.00"),
        "monitor_id": monitor_id,
        "name": clean_name,
        "editing": bool(edit_id),
        "zone": zone_result,
    })


@app.route("/api/cameras/bulk-function", methods=["POST"])
def bulk_set_function():
    """
    Kontrol massal triad native ZM 1.38.6 (Capturing, Analysing, Recording).

    Body JSON:
      action  : "restore" | "off" | "triad"
      ids     : opsional, daftar ID kamera. Kosong = semua kamera.
      triad   : wajib saat action="triad":
                  { capturing: None|Always|Ondemand,
                    analysing: None|Always,
                    recording: None|OnMotion|Always }

    action="off"   -> Capturing=None (analisa & rekam otomatis berhenti);
                      triad lama disimpan agar bisa dipulihkan.
    action="restore" -> kembalikan triad terakhir yang tersimpan.
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

    saved = load_saved_triads()

    if action == "off":
        jobs = []
        for m in monitors:
            # Ingat triad yang sedang aktif sebelum dimatikan, supaya
            # "Pulihkan Triad Asli" tetap bisa mengembalikannya.
            if m.get("capturing") and m["capturing"] != "None":
                saved[m["id"]] = {
                    "capturing": m["capturing"],
                    "analysing": m.get("analysing", "None"),
                    "recording": m.get("recording", "None"),
                }
            jobs.append((m["id"], {"capturing": "None", "analysing": "None", "recording": "None"}))
    elif action == "restore":
        jobs = []
        for m in monitors:
            triad = saved.get(m["id"])
            if not triad or triad.get("capturing", "None") == "None":
                # Tidak ada catatan: pakai default aman.
                triad = {"capturing": "Always", "analysing": "Always", "recording": "OnMotion"}
            jobs.append((m["id"], triad))
    elif action == "triad":
        triad_in = body.get("triad") or {}
        triad = {
            "capturing": normalize_capturing(triad_in.get("capturing"), default="Always"),
            "analysing": normalize_analysing(triad_in.get("analysing"), default="None"),
            "recording": normalize_recording(triad_in.get("recording"), default="None"),
        }
        jobs = [(m["id"], triad) for m in monitors]
    else:
        return jsonify({
            "status": "error",
            "message": "action harus 'triad', 'off', atau 'restore'."
        }), 400

    results = []
    ok_count = 0
    fail_count = 0

    for mon_id, triad in jobs:
        # Isi respons yang menentukan, bukan status HTTP (ZM 1.38 membalas 200
        # untuk kegagalan validasi juga).
        payload = zm138_monitor_payload({
            "Function": derive_function_from_triad(triad["capturing"], triad["analysing"], triad["recording"]),
            "Capturing": triad["capturing"],
            "Analysing": triad["analysing"],
            "Recording": triad["recording"],
            "Enabled": "1" if triad["capturing"] != "None" else "0",
        })
        ok, fn_message, _fn_body = zm_post_monitor(f"monitors/{mon_id}.json", payload)

        if ok:
            ok_count += 1
            results.append({
                "id": mon_id,
                "status": "ok",
                "capturing": triad["capturing"],
                "analysing": triad["analysing"],
                "recording": triad["recording"],
            })
            # Catat triad AKTIF terakhir. Saat kamera dimatikan (Capturing=None),
            # catatan LAMA sengaja tidak dihapus agar tombol
            # "Pulihkan Triad Asli" bisa mengembalikan mode sebelumnya.
            if triad["capturing"] != "None":
                saved[mon_id] = triad
        else:
            fail_count += 1
            results.append({"id": mon_id, "status": "failed", "error": fn_message})

    save_saved_triads(saved)
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
# 8. ZONE DETEKSI — 5 MODE OPERASIONAL
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
