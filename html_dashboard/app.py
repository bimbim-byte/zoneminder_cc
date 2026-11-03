import json
import os
import re
import requests
import yaml
from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder='.')
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

ZM_BASE_URL = "http://127.0.0.1:80/zm/api"
# Path file log MQTT (menyesuaikan jika menggunakan Docker atau lokal)
MQTT_LOG_FILE = os.environ.get(
    "MQTT_LOG_FILE", "/opt/zoneminder/data/mqtt_logs.json"
)  # ganti ke 'mqtt_logs.json' jika dijalankan lokal tanpa docker


@app.route("/api/zm/<path:subpath>", methods=["GET", "POST", "PUT", "DELETE"])
def proxy_zm(subpath):
  url = f"{ZM_BASE_URL}/{subpath}"

  headers = {
      key: value for key, value in request.headers if key.lower() != "host"
  }

  try:
    resp = requests.request(
        method=request.method,
        url=url,
        headers=headers,
        data=request.get_data(),
        params=request.args,
        cookies=request.cookies,
        allow_redirects=False,
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
    response.headers["Access-Control-Allow-Methods"] = (
        "GET, POST, PUT, DELETE, OPTIONS"
    )
    response.headers["Access-Control-Allow-Headers"] = "*"
    return response

  except Exception as e:
    return jsonify({"error": str(e)}), 500


@app.after_request
def after_request(response):
  response.headers.add("Access-Control-Allow-Origin", "*")
  response.headers.add(
      "Access-Control-Allow-Headers", "Content-Type,Authorization"
  )
  response.headers.add(
      "Access-Control-Allow-Methods", "GET,PUT,POST,DELETE,OPTIONS"
  )
  return response


# REST API MediaMTX v3
MEDIAMTX_API = "http://127.0.0.1:9997/v3/config/paths"

# Path mediamtx.yml di dalam container
YML_PATH = "/opt/zoneminder/mediamtx.yml"

# Konfigurasi ZoneMinder Internal
ZM_HOST = "http://127.0.0.1:80"
ZM_USER = "admin"
ZM_PASS = "admin"


@app.route("/zm/api/<path:path>", methods=["GET", "POST", "PUT", "DELETE"])
def zm_api_proxy(path):
  zm_url = f"{ZM_HOST}/zm/api/{path}"

  resp = requests.request(
      method=request.method,
      url=zm_url,
      headers={k: v for k, v in request.headers if k.lower() != "host"},
      data=request.get_data(),
      cookies=request.cookies,
      allow_redirects=False,
      params=request.args,
  )

  response = (
      jsonify(resp.json())
      if resp.headers.get("Content-Type") == "application/json"
      else resp.content
  )
  return response, resp.status_code


def save_camera_to_mediamtx(name: str, source: str) -> tuple[bool, str]:
  try:
    payload = {"name": name, "source": source, "sourceOnDemand": False}
    api_res = requests.post(
        f"{MEDIAMTX_API}/add/{name}", json=payload, timeout=5
    )
    print(f"[DEBUG API Response] {api_res.status_code}: {api_res.text}")
  except Exception as e:
    print(f"[WARN] MediaMTX API Unreachable: {e}")

  if not os.path.exists(YML_PATH):
    print(f"[ERROR YML] File TIDAK DITEMUKAN di path container: {YML_PATH}")
    return False, f"File config tidak ditemukan di {YML_PATH}"

  try:
    with open(YML_PATH, "r") as f:
      config = yaml.safe_load(f) or {}

    if "paths" not in config or config["paths"] is None:
      config["paths"] = {}

    config["paths"][name] = {"source": source, "sourceOnDemand": False}

    with open(YML_PATH, "w") as f:
      yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    print(f"[SUCCESS] Berhasil menambahkan kamera '{name}' ke {YML_PATH}")
    return True, f"Kamera '{name}' berhasil disimpan ke mediamtx.yml!"

  except Exception as e:
    print(f"[ERROR Write YML] {str(e)}")
    return False, f"Gagal menulis ke file YML: {str(e)}"


def get_zm_token() -> str:
  login_url = f"{ZM_HOST}/zm/api/host/login.json"
  res = requests.post(
      login_url, data={"user": ZM_USER, "pass": ZM_PASS}, timeout=5
  )
  if res.status_code != 200:
    raise Exception("Gagal terhubung ke ZoneMinder API login")

  data = res.json()
  token = data.get("access_token") or data.get("credentials", {}).get(
      "access_token"
  )

  if not token:
    raise Exception("Token autentikasi ZoneMinder tidak ditemukan")

  return token


# --- STATIC FILE ROUTES ---


@app.route("/")
def index():
  return send_from_directory(".", "index.html")


@app.route("/index.html")
def side_index():
  return send_from_directory(".", "index.html")


@app.route("/mediamtx.html")
def mediamtx_page():
  return send_from_directory(".", "mediamtx.html")


@app.route("/unified_add.html")
def unified_add_page():
  return send_from_directory(".", "unified_add.html")


@app.route("/zoneminder.html")
def zoneminder_page():
  return send_from_directory(".", "zoneminder.html")


# ROUTE TAMBAHAN UNTUK LOG DISPLAY HTML
@app.route("/log_display.html")
def log_display_page():
  return send_from_directory(".", "log_display.html")


# --- API ROUTES ---


# API TAMBAHAN UNTUK MEMBACA FILE LOG MQTT
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
    # Fallback jika file berada di root folder proyek
    try:
      with open("mqtt_logs.json", "r", encoding="utf-8") as f:
        logs = json.load(f)
      return jsonify(logs)
    except Exception as e:
      return jsonify({"error": f"Gagal membaca file log: {str(e)}"}), 500
  else:
    return jsonify([])


@app.route("/api/add-camera", methods=["POST"])
def add_camera():
  data = request.json or {}
  name = data.get("name", "").strip().lower()
  source = data.get("source", "").strip()

  if not name or not source:
    return jsonify({"error": "Data nama dan URL RTSP wajib diisi"}), 400

  if not re.match(r"^[a-z0-9\-_]+$", name):
    return (
        jsonify(
            {"error": "Nama kamera hanya boleh huruf, angka, (-), dan (_)"}
        ),
        400,
    )

  if not source.lower().startswith("rtsp://"):
    return jsonify({"error": "URL RTSP harus diawali dengan rtsp://"}), 400

  success, msg = save_camera_to_mediamtx(name, source)
  if not success:
    return jsonify({"error": msg}), 500

  return jsonify({
      "status": "success",
      "message": f"Kamera '{name}' berhasil disimpan ke MediaMTX!",
  })


@app.route("/api/add-camera-dual", methods=["POST"])
def add_camera_dual():
  data = request.json or {}

  raw_name = data.get("name", "").strip()
  zm_name = raw_name
  mediamtx_name = (
      data.get("mediamtx_name", "").strip().lower() or zm_name.lower()
  )

  source = data.get("source", "").strip()
  zm_function = data.get("zmFunction", "Monitor")
  width = data.get("width", "1920")
  height = data.get("height", "1080")

  if not zm_name or not source:
    return jsonify({"error": "Data nama dan URL RTSP wajib diisi"}), 400

  if not re.match(r"^[a-zA-Z0-9\-_]+$", zm_name):
    return (
        jsonify(
            {"error": "Nama kamera hanya boleh huruf, angka, (-), dan (_)"}
        ),
        400,
    )

  if not source.lower().startswith("rtsp://"):
    return jsonify({"error": "URL RTSP harus diawali dengan rtsp://"}), 400

  success, msg = save_camera_to_mediamtx(mediamtx_name, source)
  if not success:
    return jsonify({"error": f"Gagal di MediaMTX: {msg}"}), 500

  try:
    token = get_zm_token()
    server_ip = request.host.split(":")[0]
    mediamtx_relay_url = f"rtsp://{server_ip}:8554/{mediamtx_name}"

    zm_payload = {
        "Monitor[Name]": zm_name,
        "Monitor[Type]": "Ffmpeg",
        "Monitor[Function]": zm_function,
        "Monitor[Enabled]": "1",
        "Monitor[Path]": mediamtx_relay_url,
        "Monitor[Method]": "rtsp",
        "Monitor[Options]": "rtsp_transport=tcp",
        "Monitor[Width]": width,
        "Monitor[Height]": height,
        "Monitor[Colours]": "4",
        "Monitor[TargetColorspace]": "4",
        "Monitor[ServerId]": "0",
    }

    zm_res = requests.post(
        f"{ZM_HOST}/zm/api/monitors.json?token={token}",
        data=zm_payload,
        timeout=5,
    )

    if zm_res.status_code not in [200, 201]:
      raise Exception(
          f"ZoneMinder API Error ({zm_res.status_code}): {zm_res.text}"
      )

    print(
        f"[SUCCESS] Kamera '{zm_name}' (Path: {mediamtx_name}) Berhasil"
        " Terdaftar di MediaMTX DAN ZoneMinder!"
    )
    return (
        jsonify({
            "status": "success",
            "message": (
                f"Kamera '{zm_name}' berhasil didaftarkan ke MediaMTX &"
                " ZoneMinder!"
            ),
        }),
        200,
    )

  except Exception as e:
    print(f"[ERROR ZM Server-Side] {str(e)}")
    return (
        jsonify({
            "error": f"MediaMTX Berhasil, tetapi ZoneMinder Gagal: {str(e)}"
        }),
        500,
    )


@app.route("/api/remove-camera/<name>", methods=["DELETE"])
def remove_camera(name):
  name = name.strip().lower()

  try:
    requests.delete(f"{MEDIAMTX_API}/delete/{name}", timeout=5)
  except Exception as e:
    print(f"[WARN] MediaMTX DELETE API Error: {e}")

  if not os.path.exists(YML_PATH):
    return (
        jsonify({"error": f"File config tidak ditemukan di {YML_PATH}"}),
        500,
    )

  try:
    with open(YML_PATH, "r") as f:
      config = yaml.safe_load(f) or {}

    if "paths" in config and config["paths"] and name in config["paths"]:
      del config["paths"][name]

      with open(YML_PATH, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

      return jsonify({
          "status": "success",
          "message": f"Kamera '{name}' berhasil dihapus dari mediamtx.yml!",
      })

  except Exception as e:
    return jsonify({"error": f"Gagal update file YML: {str(e)}"}), 500


if __name__ == "__main__":
  print(f"[*] Target YAML File: {YML_PATH}")
  # app.run(host='0.0.0.0', port=8081)
  app.run(host="0.0.0.0", port=8081, ssl_context="adhoc", debug=True)
