from datetime import datetime, timedelta
import json
import os
import re
import socket
import sys
import threading
import time
from urllib.parse import urlparse
import paho.mqtt.client as mqtt
import requests
import urllib3
import warnings

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

# ==============================================================================
# KONFIGURASI ENVIRONMENT
# ==============================================================================
LOG_FILE = os.environ.get("MQTT_LOG_FILE", "/app/data/mqtt_logs.json")
CHECKER_CONFIG_FILE = os.environ.get("CHECKER_CONFIG_FILE", "/app/data/checker_config.json")

# MQTT Broker
MQTT_BROKER_HOST = os.environ.get("MQTT_BROKER_HOST", "mosquitto")
MQTT_BROKER_PORT = int(os.environ.get("MQTT_BROKER_PORT", 1883))
MQTT_TOPIC_SUB = os.environ.get("MQTT_TOPIC", "cctv/#")

# ZoneMinder
ZM_HOST = os.environ.get("ZM_HOST", "http://zoneminder:80")
ZM_USER = os.environ.get("ZM_USER", "admin")
ZM_PASS = os.environ.get("ZM_PASS", "admin")

# Interval Pengecekan Kamera default (detik). 600 = 10 menit.
CHECK_INTERVAL = int(os.environ.get("CHECK_INTERVAL", 600))
RTSP_TIMEOUT = float(os.environ.get("RTSP_TIMEOUT", 3.0))
RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", 10))

# State monitor lokal untuk mengingat fungsi asli kamera (misal: Monitor / Modect)
state_backup = {}
last_known_status = {}  # { "monitor_id": "ONLINE" / "OFFLINE" }
file_lock = threading.Lock()

ACTIVE_FUNCTIONS = ["Monitor", "Modect", "Record", "Mocord", "Nodect"]
OFFLINE_FUNCTION = "None"

zm_session = requests.Session()
access_token = None


# ==============================================================================
# 1. FILE LOG & CONFIG MANAGEMENT
# ==============================================================================
def ensure_data_dir():
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    os.makedirs(os.path.dirname(CHECKER_CONFIG_FILE), exist_ok=True)


def load_checker_config():
    """
    Membaca file konfigurasi controller cctv_checker.
    Default saat pertama kali dijalankan (file belum ada): checkernya MATI,
    agar tidak ada pengecekan otomatis tanpa sepengetahuan operator.
    """
    default_cfg = {
        "enabled": False,
        "interval": CHECK_INTERVAL,
        "rtsp_timeout": RTSP_TIMEOUT,
        "run_now": False,
        "status": "Paused",
        "last_check": None
    }
    if os.path.exists(CHECKER_CONFIG_FILE):
        try:
            with open(CHECKER_CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if isinstance(saved, dict):
                    default_cfg.update(saved)
        except Exception:
            pass
    return default_cfg


def update_checker_config(cfg_updates):
    """Memperbarui nilai tertentu di file konfigurasi controller cctv_checker."""
    ensure_data_dir()
    with file_lock:
        current = load_checker_config()
        current.update(cfg_updates)
        try:
            with open(CHECKER_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(current, f, indent=2)
        except Exception as e:
            print(f"[ERROR] Gagal menyimpan config checker: {e}", flush=True)


def clean_old_logs(logs):
    """Menghapus entri log yang lebih dari RETENTION_DAYS."""
    cutoff = datetime.now() - timedelta(days=RETENTION_DAYS)
    filtered = []
    for entry in logs:
        try:
            ts = datetime.strptime(entry.get("timestamp"), "%Y-%m-%d %H:%M:%S")
            if ts >= cutoff:
                filtered.append(entry)
        except Exception:
            filtered.append(entry)
    return filtered


def save_log_entry(topic, payload_str):
    """Menyimpan log event yang diterima dari MQTT ke file JSON."""
    ensure_data_dir()
    with file_lock:
        logs = []
        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, "r", encoding="utf-8") as f:
                    logs = json.load(f)
                    if not isinstance(logs, list):
                        logs = []
            except Exception:
                logs = []

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        payload_data = payload_str
        try:
            payload_data = json.loads(payload_str)
        except Exception:
            pass

        new_entry = {
            "timestamp": now_str,
            "topic": topic,
            "payload": payload_data
        }
        logs.insert(0, new_entry)
        logs = clean_old_logs(logs)

        try:
            with open(LOG_FILE, "w", encoding="utf-8") as f:
                json.dump(logs, f, indent=2, ensure_ascii=False)
            print(f"[LOG SAVED] [{now_str}] {topic}: {payload_str[:80]}", flush=True)
        except Exception as e:
            print(f"[ERROR] Gagal menulis ke {LOG_FILE}: {e}", flush=True)


# ==============================================================================
# 2. MQTT CLIENT HANDLERS & REMOTE CONTROL TOPICS
# ==============================================================================
if hasattr(mqtt, "CallbackAPIVersion"):
    mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
else:
    mqtt_client = mqtt.Client()


def on_mqtt_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"[MQTT] Berhasil terhubung ke Broker ({MQTT_BROKER_HOST}:{MQTT_BROKER_PORT})", flush=True)
        client.subscribe(MQTT_TOPIC_SUB)
        print(f"[MQTT] Subscribed ke topik: '{MQTT_TOPIC_SUB}'", flush=True)
    else:
        print(f"[MQTT ERROR] Gagal terhubung ke Broker MQTT, return code: {rc}", flush=True)


def on_mqtt_message(client, userdata, msg):
    try:
        topic = msg.topic
        payload_str = msg.payload.decode("utf-8", errors="ignore").strip()

        # Handle remote MQTT control commands
        if topic == "cctv/control/run_now":
            print("[MQTT CONTROL] Perintah 'run_now' diterima via MQTT!", flush=True)
            update_checker_config({"run_now": True})
        elif topic == "cctv/control/pause":
            print("[MQTT CONTROL] Perintah 'pause' diterima via MQTT!", flush=True)
            update_checker_config({"enabled": False, "status": "Paused"})
        elif topic == "cctv/control/resume":
            print("[MQTT CONTROL] Perintah 'resume' diterima via MQTT!", flush=True)
            update_checker_config({"enabled": True, "status": "Running"})
        elif topic == "cctv/control/interval":
            try:
                new_sec = int(payload_str)
                if new_sec >= 5:
                    print(f"[MQTT CONTROL] Interval diubah ke {new_sec}s via MQTT!", flush=True)
                    update_checker_config({"interval": new_sec})
            except Exception:
                pass

        # Catat ke log hanya jika bukan control ping internal
        if not topic.startswith("cctv/control/"):
            save_log_entry(topic, payload_str)
    except Exception as e:
        print(f"[MQTT MESSAGE ERROR] {e}", flush=True)


mqtt_client.on_connect = on_mqtt_connect
mqtt_client.on_message = on_mqtt_message


# ==============================================================================
# 3. ZONEMINDER API CLIENT
# ==============================================================================
def wait_for_zoneminder():
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


def zm_login():
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


def get_all_monitors():
    """Mengambil daftar seluruh monitor dari ZoneMinder."""
    global access_token
    url = f"{ZM_HOST}/zm/api/monitors.json"
    params = {"token": access_token} if access_token else {}
    try:
        res = zm_session.get(url, params=params, verify=False, timeout=10)
        if res.status_code == 200:
            data = res.json()
            return [m["Monitor"] for m in data.get("monitors", []) if "Monitor" in m]
        elif res.status_code in [401, 403]:
            if zm_login():
                return get_all_monitors()
    except Exception as e:
        print(f"[ZM API ERROR] Gagal mengambil monitors: {e}", flush=True)
    return []


def update_monitor_function(monitor_id, new_function):
    """Mengubah fungsi monitor (None atau Monitor/Modect)."""
    global access_token
    url = f"{ZM_HOST}/zm/api/monitors/{monitor_id}.json"
    params = {"token": access_token} if access_token else {}
    payload = {"Monitor[Function]": new_function}
    try:
        res = zm_session.post(url, params=params, data=payload, verify=False, timeout=8)
        if res.status_code in [401, 403]:
            if zm_login():
                params = {"token": access_token} if access_token else {}
                res = zm_session.post(url, params=params, data=payload, verify=False, timeout=8)
        return res.status_code in [200, 201]
    except Exception as e:
        print(f"[ZM API ERROR] Gagal update fungsi ID {monitor_id}: {e}", flush=True)
        return False


# ==============================================================================
# 4. RTSP CONNECTIVITY CHECKER
# ==============================================================================
def check_rtsp_online(rtsp_url, timeout=None):
    """
    Memeriksa keaktifan kamera melalui TCP Socket Ping ke Host & Port RTSP (default 554).
    """
    if not rtsp_url or not str(rtsp_url).lower().startswith("rtsp://"):
        return False

    if timeout is None:
        timeout = RTSP_TIMEOUT

    try:
        parsed = urlparse(rtsp_url)
        host = parsed.hostname
        port = parsed.port if parsed.port else 554

        if not host:
            return False

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()

        return result == 0
    except Exception:
        return False


# ==============================================================================
# 5. CAMERA HEALTH CHECK EXECUTION & CONTROLLER LOOP
# ==============================================================================
def perform_single_health_check(timeout_val=3.0):
    """Menjalankan 1 siklus pengecekan status kamera RTSP."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        monitors = get_all_monitors()

        if monitors:
            online_count = 0
            offline_count = 0
            changed_count = 0

            for mon in monitors:
                mon_id = str(mon.get("Id", ""))
                name = mon.get("Name", f"Cam_{mon_id}")
                curr_func = mon.get("Function", OFFLINE_FUNCTION)
                path = mon.get("Path", "")

                if curr_func in ACTIVE_FUNCTIONS:
                    state_backup[mon_id] = curr_func

                target_active_func = state_backup.get(mon_id, "Monitor")
                is_online = check_rtsp_online(path, timeout=timeout_val)
                status_str = "ONLINE" if is_online else "OFFLINE"
                prev_status = last_known_status.get(mon_id)

                status_changed = (prev_status is not None and prev_status != status_str)
                is_initial = (prev_status is None)

                if is_online:
                    online_count += 1
                    if curr_func == OFFLINE_FUNCTION:
                        update_monitor_function(mon_id, target_active_func)
                        changed_count += 1
                else:
                    offline_count += 1
                    if curr_func != OFFLINE_FUNCTION:
                        update_monitor_function(mon_id, OFFLINE_FUNCTION)
                        changed_count += 1

                if status_changed or is_initial:
                    msg_text = (
                        f"Kamera '{name}' TERHUBUNG (ONLINE)"
                        if is_online
                        else f"Kamera '{name}' TERPUTUS (OFFLINE)"
                    )

                    event_payload = {
                        "timestamp": now_str,
                        "monitor_id": mon_id,
                        "name": name,
                        "status": status_str,
                        "rtsp_url": path,
                        "message": msg_text
                    }

                    clean_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", name).lower()
                    mqtt_client.publish(
                        f"cctv/status/{clean_name}",
                        json.dumps(event_payload),
                        qos=1
                    )
                    mqtt_client.publish(
                        "cctv/events",
                        json.dumps(event_payload),
                        qos=1
                    )

                last_known_status[mon_id] = status_str

            summary_payload = {
                "timestamp": now_str,
                "total_monitors": len(monitors),
                "online": online_count,
                "offline": offline_count,
                "status_changed": changed_count
            }
            mqtt_client.publish("cctv/summary", json.dumps(summary_payload), qos=1)

            print(
                f"[CHECKER {now_str}] Total: {len(monitors)} | "
                f"🟢 Online: {online_count} | 🔴 Offline: {offline_count} | 🔄 Diperbarui: {changed_count}",
                flush=True
            )
        else:
            print(f"[CHECKER {now_str}] Belum ada monitor yang terdaftar di ZoneMinder.", flush=True)

    except Exception as e:
        print(f"[CHECKER ERROR] Terjadi kesalahan: {e}", flush=True)


def run_camera_health_check():
    """Loop utama dengan kendali dynamic pause, variable interval, dan instant run trigger."""
    wait_for_zoneminder()
    zm_login()

    initial_cfg = load_checker_config()
    update_checker_config({
        "status": "Running" if initial_cfg.get("enabled", False) else "Paused"
    })

    print("[CHECKER] Service Health Checker siap menerima instruksi kontrol...", flush=True)

    last_run_timestamp = 0.0

    while True:
        try:
            cfg = load_checker_config()
            is_enabled = cfg.get("enabled", False)
            interval = max(5, int(cfg.get("interval", CHECK_INTERVAL)))
            timeout_val = float(cfg.get("rtsp_timeout", RTSP_TIMEOUT))
            should_run_now = bool(cfg.get("run_now", False))

            current_time = time.time()

            # Jalankan jika dipicu tombol "Cek Sekarang" ATAU jika enabled dan interval telah tercapai
            if should_run_now or (is_enabled and (current_time - last_run_timestamp >= interval)):
                if should_run_now:
                    print("[CHECKER] Trigger manual 'Cek Sekarang' diterima!", flush=True)
                    update_checker_config({"run_now": False})

                perform_single_health_check(timeout_val=timeout_val)

                last_run_timestamp = time.time()
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                update_checker_config({
                    "status": "Running" if is_enabled else "Paused",
                    "last_check": now_str
                })

        except Exception as e:
            print(f"[CHECKER LOOP ERROR] {e}", flush=True)

        # Polling rate 1 detik untuk segera mendeteksi perubahan konfigurasi / tombol trigger
        time.sleep(1)


# ==============================================================================
# 6. MAIN SERVICE ENTRYPOINT
# ==============================================================================
def main():
    ensure_data_dir()
    print("=" * 60, flush=True)
    print("[*] Starting CCTV Health Checker & MQTT Reporter Service", flush=True)
    print(f"[*] Target Broker : {MQTT_BROKER_HOST}:{MQTT_BROKER_PORT}", flush=True)
    print(f"[*] ZoneMinder    : {ZM_HOST}", flush=True)
    print(f"[*] Check Interval: {CHECK_INTERVAL} detik (Dapat diubah dinamis)", flush=True)
    print(f"[*] Log File JSON : {LOG_FILE}", flush=True)
    print(f"[*] Config File   : {CHECKER_CONFIG_FILE}", flush=True)
    print("=" * 60, flush=True)

    connected = False
    while not connected:
        try:
            mqtt_client.connect(MQTT_BROKER_HOST, MQTT_BROKER_PORT, keepalive=60)
            connected = True
        except Exception as e:
            print(f"[MQTT RETRY] Mosquitto belum siap ({e}). Coba lagi dalam 5 detik...", flush=True)
            time.sleep(5)

    mqtt_client.loop_start()
    run_camera_health_check()


if __name__ == "__main__":
    main()
