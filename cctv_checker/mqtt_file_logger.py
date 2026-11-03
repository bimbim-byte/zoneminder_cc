from datetime import datetime, timedelta
import json
import os
import sys
import time
import paho.mqtt.client as mqtt

# Path file log di dalam container (terhubung via Docker Volume ke ./data/mqtt_logs.json di host)
LOG_FILE = os.environ.get("MQTT_LOG_FILE", "/app/data/mqtt_logs.json")

# Konfigurasi Broker MQTT (mengambil dari env var docker-compose / fallback ke localhost)
MQTT_BROKER_HOST = os.environ.get("MQTT_BROKER_HOST", "localhost")
MQTT_BROKER_PORT = int(os.environ.get("MQTT_BROKER_PORT", 1883))
MQTT_TOPIC = os.environ.get("MQTT_TOPIC", "cctv/#")  # Sesuaikan dengan topic MQTT kamu (misal: "cctv/#" atau "#")

# Retensi Log dalam Hari
RETENTION_DAYS = 10


def ensure_data_dir():
  """Memastikan direktori tujuan file JSON sudah ada."""
  os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)


def clean_old_logs(logs):
  """Menghapus entri log yang usianya lebih dari RETENTION_DAYS (10 Hari)."""
  cutoff_time = datetime.now() - timedelta(days=RETENTION_DAYS)
  filtered_logs = []

  for entry in logs:
    try:
      # Format timestamp: YYYY-MM-DD HH:MM:SS
      entry_time = datetime.strptime(
          entry.get("timestamp"), "%Y-%m-%d %H:%M:%S"
      )
      if entry_time >= cutoff_time:
        filtered_logs.append(entry)
    except Exception:
      # Jika format tanggal gagal di-parse, simpan saja
      filtered_logs.append(entry)

  return filtered_logs


def save_log_entry(topic, payload_str):
  """Membaca file JSON log, menambahkan entri baru di atas, menyaring log tua, lalu menyimpan kembali."""
  ensure_data_dir()

  logs = []
  if os.path.exists(LOG_FILE):
    try:
      with open(LOG_FILE, "r", encoding="utf-8") as f:
        logs = json.load(f)
        if not isinstance(logs, list):
          logs = []
    except Exception as e:
      print(f"[WARN] Gagal membaca {LOG_FILE}: {e}. Membuat list log baru.")
      logs = []

  # Buat entri data baru
  now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
  new_entry = {"timestamp": now_str, "topic": topic, "payload": payload_str}

  # Sisipkan pesan baru ke urutan paling atas (terbaru)
  logs.insert(0, new_entry)

  # Bersihkan log yang lebih dari 10 hari
  logs = clean_old_logs(logs)

  # Tulis ulang file JSON
  try:
    with open(LOG_FILE, "w", encoding="utf-8") as f:
      json.dump(logs, f, indent=2, ensure_ascii=False)
    print(f"[LOG SAVED] [{now_str}] {topic}: {payload_str}")
  except Exception as e:
    print(f"[ERROR] Gagal menulis ke {LOG_FILE}: {e}")


# --- CALLBACK MQTT CLIENT ---


def on_connect(client, userdata, flags, rc):
  if rc == 0:
    print(
        f"[CONNECTED] Berhasil terhubung ke Broker MQTT ({MQTT_BROKER_HOST}:{MQTT_BROKER_PORT})"
    )
    # Subscribe ke topik yang ditentukan
    client.subscribe(MQTT_TOPIC)
    print(f"[SUBSCRIBED] Mendengarkan topik: '{MQTT_TOPIC}'")
  else:
    print(f"[ERROR CONNECT] Gagal terhubung ke Broker MQTT, return code: {rc}")


def on_message(client, userdata, msg):
  try:
    topic = msg.topic
    payload = msg.payload.decode("utf-8", errors="ignore")
    # Simpan ke file JSON
    save_log_entry(topic, payload)
  except Exception as e:
    print(f"[ERROR MESSAGE] Gagal memproses pesan MQTT: {e}")


# --- MAIN EXECUTION ---

if __name__ == "__main__":
  ensure_data_dir()
  print("=" * 50)
  print(f"[*] Starting MQTT File Logger Service...")
  print(f"[*] Target Log File: {LOG_FILE}")
  print(f"[*] Broker Target  : {MQTT_BROKER_HOST}:{MQTT_BROKER_PORT}")
  print("=" * 50)

  client = mqtt.Client()
  client.on_connect = on_connect
  client.on_message = on_message

  # Loop Reconnect ke Broker MQTT jika broker belum siap/restart
  connected = False
  while not connected:
    try:
      client.connect(MQTT_BROKER_HOST, MQTT_BROKER_PORT, keepalive=60)
      connected = True
    except Exception as e:
      print(
          f"[RETRY] Broker MQTT belum siap ({e}). Mencoba lagi dalam 5"
          " detik..."
      )
      time.sleep(5)

  # Jalankan loop paho-mqtt secara terus menerus
  client.loop_forever()
