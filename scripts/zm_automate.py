import os
import json
import time
import requests
import urllib3
import subprocess
from datetime import datetime
import socket
import subprocess
from urllib.parse import urlparse

# Mematikan peringatan SSL unverified di terminal
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# KONFIGURASI ZONEMINDER & INTERVAL
# ==========================================
# Kredensial dibaca dari file .env di root repo (lihat .env.example).
# Environment asli menang atas .env, jadi override lewat shell juga bisa.
from _env_loader import load_env  # noqa: E402  (butuh path skrip di sys.path)

load_env()

ZM_HOST = os.environ.get("ZM_HOST", "https://localhost/zm")
ZM_USER = os.environ.get("ZM_USER", "admin")
ZM_PASS = os.environ.get("ZM_PASS", "admin")
CHECK_INTERVAL_SECONDS = 300         # 300 detik = 5 menit
RTSP_TIMEOUT_SECONDS = 5             # Timeout pengecekan RTSP per kamera

if ZM_PASS == "admin":
    print("[WARN] ZM_PASS masih 'admin' (default). Set ZM_PASS di file .env!")

# File lokal untuk menyimpan state/fungsi asli kamera
BACKUP_FILE = "zm_monitor_state.json"

# List fungsi ZoneMinder yang dianggap aktif/ON
ACTIVE_FUNCTIONS = ["Monitor", "Modect", "Record", "Mocord", "Nodect"]
OFFLINE_FUNCTION = "None"

session = requests.Session()
ACCESS_TOKEN = None

# ==========================================
# FUNGSI BACKUP / RESTORE STATE LOKAL
# ==========================================
def load_state_backup():
    if os.path.exists(BACKUP_FILE):
        try:
            with open(BACKUP_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"  [WARNING] Gagal membaca file backup state: {e}")
    return {}

def save_state_backup(state_data):
    try:
        with open(BACKUP_FILE, "w") as f:
            json.dump(state_data, f, indent=4)
    except Exception as e:
        print(f"  [WARNING] Gagal menyimpan file backup state: {e}")

# ==========================================
# FUNGSI ZONEMINDER API WITH AUTH TOKEN
# ==========================================
def zm_login():
    """Autentikasi login ke ZoneMinder API & mengambil access_token."""
    global ACCESS_TOKEN
    login_url = f"{ZM_HOST}/api/host/login.json"
    payload = {'user': ZM_USER, 'pass': ZM_PASS}
    try:
        # verify=False digunakan untuk melewati SSL certificate error
        res = session.post(login_url, data=payload, verify=False, timeout=10)
        if res.status_code == 200:
            res_data = res.json()
            ACCESS_TOKEN = res_data.get('access_token')
            return True
        else:
            print(f"  [ERROR] Login ZM Gagal! HTTP Status: {res.status_code}")
            return False
    except Exception as e:
        print(f"  [ERROR] Gagal koneksi login ZM: {e}")
        return False

def get_auth_params():
    """Menambahkan parameter token ke setiap query string API."""
    params = {}
    if ACCESS_TOKEN:
        params['token'] = ACCESS_TOKEN
    return params

def get_all_monitors():
    """Mengambil seluruh daftar monitor dari ZoneMinder."""
    url = f"{ZM_HOST}/api/monitors.json"
    try:
        res = session.get(url, params=get_auth_params(), verify=False, timeout=10)
        if res.status_code == 200:
            data = res.json()
            return [m['Monitor'] for m in data.get('monitors', [])]
        elif res.status_code == 401:
            # Re-auth jika token expired
            if zm_login():
                return get_all_monitors()
    except Exception as e:
        print(f"  [ERROR] Gagal mengambil data monitor dari ZoneMinder: {e}")
    return []

def update_monitor_function(monitor_id, new_function):
    """Mengubah fungsi monitor via API ZoneMinder."""
    url = f"{ZM_HOST}/api/monitors/{monitor_id}.json"
    payload = {
        "Monitor[Function]": new_function
    }
    try:
        res = session.post(url, params=get_auth_params(), data=payload, verify=False, timeout=10)
        return res.status_code in [200, 201]
    except Exception as e:
        print(f"  [ERROR] Gagal update ID {monitor_id}: {e}")
        return False

def check_rtsp_online(rtsp_url):
    """
    Memeriksa keaktifan stream RTSP:
    Method 1: Socket Ping ke Host & Port RTSP (Sangat cepat & reliable)
    Method 2: ffprobe check (Verifikasi kelayakan video stream)
    """
    if not rtsp_url or not str(rtsp_url).startswith("rtsp://"):
        return False

    try:
        # --- TEKNIK 1: QUICK TCP SOCKET CHECK ---
        # Mengambil Host IP dan Port dari URL RTSP (default port 554)
        parsed = urlparse(rtsp_url)
        host = parsed.hostname
        port = parsed.port if parsed.port else 554

        if host:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2.0)  # Timeout socket 2 detik
            result = sock.connect_ex((host, port))
            sock.close()
            
            # Jika Port RTSP (554) tidak dapat dijangkau, dipastikan Offline
            if result != 0:
                return False

        # --- TEKNIK 2: FFPROBE STREAM VALIDATION ---
        # Menambahkan flag -i yang wajib ada pada ffprobe
        cmd = [
            "ffprobe",
            "-v", "error",
            "-rtsp_transport", "tcp",
            "-timeout", str(RTSP_TIMEOUT_SECONDS * 1000000),  # timeout mikrosekon (5000000 us = 5s)
            "-i", rtsp_url  # <-- FLAG -i INI YANG SEBELUMNYA HILANG
        ]

        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=RTSP_TIMEOUT_SECONDS + 2
        )

        return result.returncode == 0

    except Exception as e:
        return False
    
# ==========================================
# MAIN HEALTH CHECKER LOGIC
# ==========================================
def run_health_check():
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("\n" + "=" * 85)
    print(f"  PENGECEKAN KAMERA ZONEMINDER - {now_str}")
    print("=" * 85)

    # Pastikan login & dapat token
    if not ACCESS_TOKEN:
        if not zm_login():
            print("  [CRITICAL] Gagal login ke ZoneMinder. Membatalkan pengecekan.")
            return

    monitors = get_all_monitors()
    if not monitors:
        print("  [INFO] Tidak ada monitor yang ditemukan atau koneksi ZM gagal.")
        return

    state_backup = load_state_backup()

    print(f"{'ID':<5} | {'Nama Monitor':<20} | {'RTSP':<8} | {'Status Awal':<12} | {'Aksi / Status Akhir':<28}")
    print("-" * 85)

    online_count = 0
    offline_count = 0
    changed_count = 0

    for mon in monitors:
        mon_id = str(mon.get('Id'))
        name = mon.get('Name', 'Unknown')[:18]
        curr_func = mon.get('Function', OFFLINE_FUNCTION)
        path = mon.get('Path', '')

        # Simpan fungsi asli kamera ke backup state jika berstatus aktif
        if curr_func in ACTIVE_FUNCTIONS:
            state_backup[mon_id] = curr_func

        # Fungsi pemulihan target
        target_active_func = state_backup.get(mon_id, "Monitor")

        # Pengecekan RTSP
        is_online = check_rtsp_online(path)
        ping_status = "ONLINE" if is_online else "OFFLINE"

        action_str = ""

        if is_online:
            online_count += 1
            if curr_func == OFFLINE_FUNCTION:
                if update_monitor_function(mon_id, target_active_func):
                    action_str = f"🔄 OFF -> ON ({target_active_func})"
                    changed_count += 1
                else:
                    action_str = "❌ Gagal Update"
            else:
                action_str = f"✅ Tetap ON ({curr_func})"
        else:
            offline_count += 1
            if curr_func != OFFLINE_FUNCTION:
                if update_monitor_function(mon_id, OFFLINE_FUNCTION):
                    action_str = f"⚠️ ON ({curr_func}) -> OFF"
                    changed_count += 1
                else:
                    action_str = "❌ Gagal Update"
            else:
                saved_info = f" [Saved: {target_active_func}]" if target_active_func else ""
                action_str = f"🔴 Tetap OFF{saved_info}"

        print(f"{mon_id:<5} | {name:<20} | {ping_status:<8} | {curr_func:<12} | {action_str:<28}")

    save_state_backup(state_backup)

    print("-" * 85)
    print(f"  RINGKASAN: Total {len(monitors)} Kamera | 🟢 Online: {online_count} | 🔴 Offline: {offline_count} | 🔄 Diperbarui: {changed_count}")
    print("=" * 85)

def main():
    print("Menginisialisasi ZoneMinder Auto-Restore Monitor Checker...")
    zm_login()
    
    while True:
        try:
            run_health_check()
        except Exception as e:
            print(f"  [CRITICAL ERROR] Terjadi kesalahan dalam loop: {e}")

        print(f"\n[NEXT] Pengecekan berikutnya dalam {CHECK_INTERVAL_SECONDS // 60} menit ({CHECK_INTERVAL_SECONDS} detik)...")
        time.sleep(CHECK_INTERVAL_SECONDS)

if __name__ == "__main__":
    main()