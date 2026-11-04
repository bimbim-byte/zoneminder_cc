import json
import os
import re
import requests
from flask import Flask, Response, jsonify, request, send_from_directory
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
# MAIN ENTRYPOINT
# ==============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"[*] Menjalankan Dashboard CCTV pada port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
