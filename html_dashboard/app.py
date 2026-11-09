import json
import os
import re
import requests
from flask import Flask, Response, jsonify, request, send_from_directory, stream_with_context
from flask_cors import CORS

app = Flask(__name__, static_folder=".")
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# ==============================================================================
# KONFIGURASI ENVIRONMENT
# ==============================================================================
ZM_HOST = os.environ.get("ZM_HOST", "http://zoneminder:80")
ZM_BASE_URL = os.environ.get("ZM_BASE_URL", f"{ZM_HOST}/zm/api")
ZM_USER = os.environ.get("ZM_USER", "admin")
ZM_PASS = os.environ.get("ZM_PASS", "admin")

MQTT_LOG_FILE = os.environ.get("MQTT_LOG_FILE", "/app/data/mqtt_logs.json")
CHECKER_CONFIG_FILE = os.environ.get("CHECKER_CONFIG_FILE", "/app/data/checker_config.json")

# Cache token auth ZM di memori
ZM_TOKEN = None


# ==============================================================================
# HELPER AUTH ZONEMINDER
# ==============================================================================
def get_zm_token():
    """Mengambil Access Token dari ZoneMinder API."""
    global ZM_TOKEN
    login_url = f"{ZM_HOST}/zm/api/host/login.json"
    try:
        res = requests.post(
            login_url,
            data={"user": ZM_USER, "pass": ZM_PASS},
            timeout=8,
            verify=False
        )
        if res.status_code == 200:
            data = res.json()
            ZM_TOKEN = data.get("access_token")
            return ZM_TOKEN
    except Exception as e:
        print(f"[ERROR AUTH ZM] {e}")
    return ZM_TOKEN


# ==============================================================================
# 1. SERVING STATIC FILES & PAGES
# ==============================================================================
@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/<path:filename>")
def serve_static(filename):
    if os.path.exists(os.path.join(".", filename)):
        return send_from_directory(".", filename)
    return jsonify({"error": "File tidak ditemukan"}), 404


# ==============================================================================
# 2. API PROXY KE ZONEMINDER
# ==============================================================================
@app.route("/api/zm/<path:subpath>", methods=["GET", "POST", "PUT", "DELETE"])
@app.route("/zm/api/<path:subpath>", methods=["GET", "POST", "PUT", "DELETE"])
def proxy_zm(subpath):
    url = f"{ZM_BASE_URL}/{subpath}"
    headers = {k: v for k, v in request.headers if k.lower() != "host"}

    try:
        resp = requests.request(
            method=request.method,
            url=url,
            headers=headers,
            data=request.get_data(),
            params=request.args,
            cookies=request.cookies,
            allow_redirects=False,
            timeout=15
        )

        excluded_headers = [
            "content-encoding",
            "content-length",
            "transfer-encoding",
            "connection",
        ]
        resp_headers = [
            (name, value)
            for (name, value) in resp.raw.headers.items()
            if name.lower() not in excluded_headers
        ]

        response = Response(resp.content, resp.status_code, resp_headers)
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
            return jsonify({
                "status": "success",
                "message": f"Kamera '{clean_name}' berhasil didaftarkan ke ZoneMinder!",
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

    results = []
    success_count = 0
    fail_count = 0

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
                results.append({"name": clean_name, "status": "success", "id": res_json.get("Id", "")})
            else:
                fail_count += 1
                results.append({"name": clean_name, "status": "failed", "error": res.text[:120]})
        except Exception as e:
            fail_count += 1
            results.append({"name": clean_name, "status": "failed", "error": str(e)})

    return jsonify({
        "status": "completed",
        "total": len(monitors),
        "success_count": success_count,
        "fail_count": fail_count,
        "details": results
    })


# ==============================================================================
# 5. API MQTT LOGS
# ==============================================================================
@app.route("/api/mqtt-logs", methods=["GET"])
def get_mqtt_logs():
    """Membaca isi file log MQTT dan menyajikan dalam format JSON untuk log_display.html"""
    if os.path.exists(MQTT_LOG_FILE):
        try:
            with open(MQTT_LOG_FILE, "r", encoding="utf-8") as f:
                logs = json.load(f)
            return jsonify(logs)
        except Exception as e:
            return jsonify({"error": f"Gagal membaca file log: {str(e)}"}), 500
    elif os.path.exists("mqtt_logs.json"):
        try:
            with open("mqtt_logs.json", "r", encoding="utf-8") as f:
                logs = json.load(f)
            return jsonify(logs)
        except Exception as e:
            return jsonify({"error": f"Gagal membaca file log: {str(e)}"}), 500
    return jsonify([])


# ==============================================================================
# 6. API KONTROL CCTV CHECKER (TOGGLE AKTIF/MATI & DELAY INTERVAL)
# ==============================================================================
def get_checker_config():
    default_cfg = {
        "enabled": True,
        "interval": 60,
        "rtsp_timeout": 3.0,
        "run_now": False,
        "status": "Running",
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

# Session persisten: ZM v1.36 via HTTP memakai cookie sesi, bukan access_token.
ZM_SESSION = requests.Session()
ZM_SESSION.verify = False
ZM_SESSION_AUTHED = False


def zm_login_session():
    """
    Login ke ZoneMinder dan simpan cookie di session.
    Diperlukan karena ZM hanya mengembalikan access_token saat HTTPS;
    pada HTTP autentikasi berjalan lewat cookie session (ZMSESSID).
    """
    global ZM_SESSION_AUTHED
    if ZM_SESSION_AUTHED and ZM_SESSION.cookies.get_dict():
        return True

    try:
        res = ZM_SESSION.post(
            f"{ZM_HOST}/zm/api/host/login.json",
            data={"user": ZM_USER, "pass": ZM_PASS},
            timeout=10,
        )
        if res.status_code == 200:
            ZM_SESSION_AUTHED = True
            return True
        print(f"[WARN ZM LOGIN] HTTP {res.status_code}")
    except Exception as e:
        print(f"[ERROR ZM LOGIN] {e}")
    return False


def zm_api_get(path, params=None, retry=True):
    """
    GET ke ZoneMinder API memakai session cookie, dengan fallback access_token.
    Re-login sekali otomatis bila sesi kedaluwarsa.
    """
    q = dict(params or {})
    token = get_zm_token()
    if token:
        q["token"] = token

    zm_login_session()

    try:
        res = ZM_SESSION.get(f"{ZM_BASE_URL}/{path}", params=q, timeout=10)

        if res.status_code in (401, 403) and retry:
            ZM_SESSION.cookies.clear()
            global ZM_SESSION_AUTHED
            ZM_SESSION_AUTHED = False
            return zm_api_get(path, params, retry=False)

        if res.status_code == 200:
            return res.json()
        print(f"[WARN ZM GET {path}] HTTP {res.status_code}")
    except Exception as e:
        print(f"[ERROR ZM GET {path}] {e}")
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


@app.route("/api/cameras/wall", methods=["GET"])
def api_camera_wall():
    """
    Daftar kamera untuk wall dashboard.
    Query:
      mode=all            -> seluruh kamera
      groups=1,3          -> kamera pada group tersebut (union)
      ids=5,7             -> kamera spesifik
    """
    mode = request.args.get("mode", "all")
    monitors = get_all_monitors_cached()
    by_id = {m["id"]: m for m in monitors}

    if mode == "groups":
        wanted_ids = set()
        ginfo = api_camera_groups().get_json()
        table = {g["id"]: g.get("monitors", []) for g in ginfo.get("groups", [])}
        for gid in [x.strip() for x in request.args.get("groups", "").split(",") if x.strip()]:
            wanted_ids.update(table.get(gid, []))
        selected = [by_id[i] for i in wanted_ids if i in by_id]

    elif mode == "ids":
        wanted = [x.strip() for x in request.args.get("ids", "").split(",") if x.strip()]
        selected = [by_id[i] for i in wanted if i in by_id]

    else:
        selected = monitors

    selected.sort(key=lambda m: (m["name"].lower(), int(m["id"]) if m["id"].isdigit() else 0))

    return jsonify({
        "mode": mode,
        "count": len(selected),
        "cameras": selected,
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

    params = {"mode": "jpeg", "monitor": monitor_id}
    params["scale"] = request.args.get("scale", "320")
    # Batasi laju frame: wall dashboard tidak perlu 30fps per kamera.
    # Ini pengurangan bandwidth paling besar untuk grid berisi banyak kamera.
    params["maxfps"] = request.args.get("maxfps", "5")
    token = get_zm_token()
    if token:
        params["token"] = token

    zm_login_session()

    try:
        upstream = ZM_SESSION.get(
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


@app.route("/wall")
def wall_picker():
    return send_from_directory(".", "wall.html")


@app.route("/wall/view")
def wall_view():
    return send_from_directory(".", "wall_view.html")


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
