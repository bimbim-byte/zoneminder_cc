# 🛡️ ZoneMinder Central CCTV Management & MQTT Monitoring System

Sistem manajemen kamera CCTV terpusat berbasis **ZoneMinder NVR** dengan antarmuka web modern (*Single Page Application*), reverse proxy aman berbasis **HTTPS (Caddy)**, pendaftaran kamera massal (*Burst Add* via teks & Excel), serta deteksi keaktifan kamera otomatis berbasis *TCP Socket RTSP* yang dilaporkan secara *real-time* melalui broker **Mosquitto MQTT**.

---

## 📋 Daftar Isi
1. [Deskripsi & Arsitektur](#-arsitektur-layanan-docker-stack)
2. [Fitur Utama](#-fitur-utama)
3. [Daftar URL & Akses Layanan](#-daftar-url--akses-layanan)
4. [Panduan Instalasi Cepat](#-panduan-instalasi-cepat)
5. [Panduan Penggunaan Fitur](#-panduan-penggunaan-fitur)
6. [Panduan Notifikasi MQTT di HP & Device Lain](#-panduan-notifikasi-mqtt-di-hp-android--ios)
7. [Keamanan & Berkas yang Diabaikan Git (.gitignore)](#-keamanan--berkas-yang-diabaikan-git-gitignore)
8. [Pembaruan Sertifikat SSL / TLS](#-pembaruan-sertifikat-ssl--tls)
9. [Struktur Direktori Proyek](#-struktur-direktori-proyek)
10. [Informasi Akun Default & Troubleshooting](#-informasi-akun-default--troubleshooting)

---

## 🏗️ Arsitektur Layanan (Docker Stack)

Sistem ini dibangun menggunakan arsitektur *microservices* terisolasi dalam satu jaringan Docker (`cctv_net`):

```text
                       [ Pengguna / Browser / HP / IoT ]
                                       │
                                       ▼
                       ┌───────────────────────────────┐
                       │      Caddy Reverse Proxy      │ (:443 HTTPS & :80 HTTP)
                       └───────────────┬───────────────┘
                                       │
            ┌──────────────────────────┼──────────────────────────┐
            │ (/zm*, /cgi-bin*)        │ (/)                      │ (/mqtt)
            ▼                          ▼                          ▼
┌────────────────────────┐ ┌───────────────────────┐ ┌────────────────────────┐
│     ZoneMinder NVR     │ │   Camera Dashboard    │ │     Mosquitto MQTT     │
│  (Core NVR & CakePHP)  │ │ (Flask Backend & SPA) │ │ (Port 1883 TCP & 9001) │
└───────────┬────────────┘ └───────────┬───────────┘ └────────────▲───────────┘
            │                          │                          │
            │         ┌────────────────┴──────────────────────────┤
            ▼         ▼                                           │
     ┌────────────────────────────────────────────────────────────┴┐
     │                CCTV Health Checker & Reporter               │
     │      (TCP Socket RTSP & Auto Function Switch & Control)     │
     └─────────────────────────────────────────────────────────────┘
```

1. **Caddy Proxy (`caddy_proxy`)**: Reverse proxy HTTPS standar industri yang mengikat ke port universal `:443`, melayani traffic untuk domain maupun IP manapun dengan sertifikat TLS terintegrasi.
2. **ZoneMinder (`zoneminder`)**: Core NVR (v1.36) dengan database MySQL internal untuk perekaman, streaming RTSP, event storage, dan motion detection.
3. **Camera Dashboard (`camera-dashboard`)**: Web UI SPA berbasis HTML5, CSS3, dan Python Flask backend untuk manajemen monitor, ekspor/impor Excel, dan kontrol checker.
4. **CCTV Health Checker (`cctv_checker_service`)**: Background service Python yang menguji konektivitas TCP RTSP setiap kamera secara berkala, auto-switch fungsi monitor di ZoneMinder (`Monitor` <-> `None`), serta mempublikasikan event ke broker Mosquitto MQTT.
5. **Mosquitto MQTT Broker (`mosquitto_broker`)**: Broker MQTT v5/v3.1.1 pada port `1883` (TCP Native untuk aplikasi HP/IoT) dan `9001` (WebSocket).

---

## 🚀 Fitur Utama

- **🖥️ Antarmuka Terpadu (SPA Light Theme)**: Semua halaman mengusung tema terang (*light theme*), modern, *responsive*, dan pas dalam satu layar desktop (*full height SPA*).
- **⚡ Pendaftaran Kamera Massal (Burst Add Upgraded)**:
  - **Quick Paste RTSP**: Salin puluhan URL RTSP sekaligus, beri prefix nama otomatis, pratinjau tabel, dan daftarkan sekaligus dalam satu klik.
  - **Impor Spreadsheet Excel (.xlsx)**: Unduh template Excel bawaan, isi daftar kamera, lalu unggah untuk pendaftaran massal otomatis.
- **🛡️ ZoneMinder Camera Manager**:
  - Autentikasi otomatis API ZoneMinder v1.36.
  - Registrasi kamera tunggal dan pengeditan konfigurasi (Nama, RTSP Path, Resolusi, Fungsi) dengan proteksi primary key ID.
  - Shortcut fungsi cepat (*Quick Set Function* & *Quick OFF*).
  - Pengecekan CPU Load server ZoneMinder secara langsung.
- **⚙️ Kendali Dinamis CCTV Health Checker**:
  - Tombol **Jeda (Pause) / Aktifkan (Resume)** tanpa perlu mematikan kontainer Docker.
  - Pengaturan **Delay Interval Pengecekan** (dalam detik, misal 10s, 30s, 60s).
  - Tombol **⚡ Cek Semua Kamera Sekarang (Run Now)** untuk memicu pemeriksaan instan.
- **📡 Pusat Log & Notifikasi MQTT Real-Time**:
  - Menampilkan log aktivitas kamera (Timestamp, Topik, Status ONLINE/OFFLINE, Payload).
  - Filter pencarian instan berdasarkan nama kamera, topik, atau status.
  - Panduan lengkap menghubungkan notifikasi alarm ke HP Android/iOS (MQTT Dash / IoT MQTT Panel), Home Assistant, atau script Python mandiri.

---

## 🌐 Daftar URL & Akses Layanan

> **Catatan Penggunaan:** Ganti `<IP_SERVER>` dengan alamat IP komputer/server Anda (misal `192.168.1.50`, atau `127.0.0.1` jika diakses di komputer lokal yang sama).

| Antarmuka | URL Akses | Keterangan |
| :--- | :--- | :--- |
| **Portal Utama** | `https://<IP_SERVER>/` | Dashboard navigasi utama ke semua menu |
| **ZoneMinder Web Console** | `https://<IP_SERVER>/zm/` | Antarmuka resmi ZoneMinder NVR bawaan |
| **Kelola Monitor ZoneMinder** | `https://<IP_SERVER>/zoneminder.html` | CRUD kamera, edit, quick toggle, dan kendali checker |
| **Burst Add Massal (Upgraded)** | `https://<IP_SERVER>/burst.html` | Pendaftaran massal via Quick Paste RTSP & Excel |
| **Tambah Kamera Tunggal** | `https://<IP_SERVER>/add_camera.html` | Form tambah 1 kamera RTSP secara instan |
| **Live MQTT Health Log** | `https://<IP_SERVER>/log_display.html` | Live log stream, statistik kamera, dan tutorial MQTT |
| **ZoneMinder Direct Port** | `http://<IP_SERVER>:8082/zm/` | Port langsung (fallback tanpa HTTPS) |
| **Dashboard Direct Port** | `http://<IP_SERVER>:8080/` | Port langsung dashboard (fallback tanpa HTTPS) |

---

## 🛠️ Panduan Instalasi Cepat

### Prasyarat
- **Docker Desktop** (versi 4.x ke atas) terpasang di Windows atau Linux/WSL2.
- **Docker Compose** v2.
- **OpenSSL** (sudah tersedia bawaan di Linux/WSL/Git for Windows).

### 1. Kloning Repository
```bash
git clone https://github.com/<username>/zoneminder_cc.git
cd zoneminder_cc
```

### 2. Generate Sertifikat SSL Lokal (Wajib Sebelum Start Pertama)
Jalankan skrip berikut agar sertifikat SSL dibuat sesuai IP host Anda:
- **Pada Windows (PowerShell):**
  ```powershell
  .\scripts\renew_ssl.ps1
  ```
- **Pada Linux / WSL Ubuntu:**
  ```bash
  chmod +x ./scripts/renew_ssl.sh
  ./scripts/renew_ssl.sh
  ```

### 3. Jalankan Seluruh Kontainer
```bash
docker compose up -d
```
Tunggu sekitar 1–2 menit saat pertama kali dijalankan agar inisialisasi database ZoneMinder selesai.

### 4. Buka Antarmuka di Browser
Buka browser dan akses:
```text
https://<IP_SERVER>/
```
*(Terima peringatan sertifikat SSL self-signed di browser dengan mengklik "Advanced" -> "Proceed to ...")*.

---

## 📖 Panduan Penggunaan Fitur

### 1. Pendaftaran Kamera Massal (Burst Add)
1. Buka menu **Burst Add Massal** (`https://<IP_SERVER>/burst.html`).
2. Pilih salah satu metode:
   - **Opsi 1 (Quick Paste):** Tempel daftar URL RTSP pada kolom textarea (satu URL per baris), tentukan prefix nama (misal: `CAM_LT1_`), lalu klik **Generate & Preview**.
   - **Opsi 2 (Excel):** Klik **Unduh Format (.xlsx)**, isi kolom nama dan RTSP stream di Excel, lalu unggah berkasnya.
3. Review tabel pratinjau di bagian bawah.
4. Klik **⚡ Daftarkan Semua ke ZoneMinder**. Sistem akan mendaftarkan seluruh kamera secara otomatis.

### 2. Pendaftaran Kamera Tunggal
1. Buka menu **Tambah Kamera Tunggal** (`https://<IP_SERVER>/add_camera.html`).
2. Masukkan nama kamera dan URL stream RTSP (contoh: `rtsp://admin:pass@192.168.1.100:554/stream1`).
3. Pilih resolusi dan fungsi default (`Monitor`/`Modect`).
4. Klik **Daftarkan Kamera**.

### 3. Mengelola & Mengedit Kamera di ZoneMinder
1. Buka menu **Kelola Monitor ZoneMinder** (`https://<IP_SERVER>/zoneminder.html`).
2. Daftar kamera akan termuat otomatis.
3. Untuk mengubah fungsi kamera secara cepat, gunakan dropdown shortcut lalu klik **Set**, atau klik **OFF** untuk mematikan monitor.
4. Untuk mengedit konfigurasi lengkap, klik tombol **✏️ Edit** pada baris kamera. Data kamera akan otomatis mengisi form di atas. Lakukan perubahan lalu klik **💾 Perbarui Kamera**.

### 4. Mengontrol CCTV Health Checker
Pada halaman `zoneminder.html` maupun `log_display.html` tersedia widget kendali checker:
- **Tombol ⏸ Jeda / ▶ Aktifkan:** Menjeda atau melanjutkan loop pengecekan kesehatan kamera tanpa mematikan kontainer.
- **Delay Interval Pengecekan:** Ubah angka detik (minimal 5 detik) lalu klik **Simpan Delay**.
- **Tombol ⚡ Cek Semua Kamera Sekarang:** Memeriksa status konektivitas seluruh kamera RTSP saat itu juga tanpa menunggu interval waktu.

---

## 📱 Panduan Notifikasi MQTT di HP (Android / iOS)

Anda dapat menerima notifikasi popup suara/getar seketika saat ada kamera CCTV yang mati atau hidup kembali:

### 1. Parameter Koneksi Broker
- **Broker Host / IP**: Masukkan alamat IP LAN komputer server Anda (contoh: `192.168.1.50`).
- **Port**: **`1883`** (TCP Native MQTT).
- **Username & Password**: *Dikosongkan (Anonymous)*.
- **Client ID**: Acak / Bebas.

### 2. Topik Notifikasi (MQTT Topics)
- **`cctv/events`** *(Sangat Disarankan)*: Mengirimkan peringatan setiap kali ada kamera yang beralih status:
  ```json
  {
    "timestamp": "2026-11-05 10:15:00",
    "monitor_id": "2",
    "name": "Kamera_Gerbang_Utama",
    "status": "OFFLINE",
    "rtsp_url": "rtsp://admin:pass@192.168.1.100:554/stream1",
    "message": "Kamera 'Kamera_Gerbang_Utama' TERPUTUS (OFFLINE)"
  }
  ```
- **`cctv/summary`**: Mengirimkan rekapitulasi jumlah total kamera, online, dan offline secara berkala.
- **`cctv/control/run_now`**: Kirim payload kosong ke topik ini dari HP untuk memicu pengecekan kamera jarak jauh.

### 3. Langkah Pemasangan di Aplikasi HP (MQTT Dash / IoT MQTT Panel)
1. Pasang aplikasi **MQTT Dash** (Google Play Store) atau **IoT MQTT Panel** (App Store / Play Store).
2. Tambahkan Broker baru:
   - Nama: `ZoneMinder CCTV Alert`
   - Address: `<IP_SERVER>` (misal `192.168.1.50`)
   - Port: `1883`
3. Simpan dan hubungkan hingga status koneksi berwarna hijau (*Connected*).
4. Buat widget baru bertipe **Text / Log** atau **Multi-State**, masukkan Topic: `cctv/events`.
5. Aktifkan fitur **"Enable notifications on receive"**.

---

## 🔐 Keamanan & Berkas yang Diabaikan Git (.gitignore)

Untuk memastikan kredensial pribadi dan data CCTV aman saat proyek disimpan di GitHub, berkas `.gitignore` telah dikonfigurasi untuk **tidak pernah mengunggah berkas sensitif berikut**:

| Kategori Berkas | Pola .gitignore | Alasan Keamanan |
| :--- | :--- | :--- |
| **Kunci Privat SSL** | `caddy/certs/*.key`, `*.pem` | Melindungi sertifikat dan *private key* TLS server Anda dari akses publik. |
| **Log Runtime Kamera** | `data/*.json`, `data/*.log` | Log event MQTT menyimpan URL stream RTSP yang sering kali mengandung username & password kamera (`rtsp://admin:password@...`). |
| **Environment / Secrets** | `.env`, `*.env` | Melindungi variabel rahasia atau token API internal. |
| **Cache Python & IDE** | `__pycache__/`, `.vscode/`, `.continue/` | Mencegah file biner dan cache lokal mengotori repository. |

> Folder `caddy/certs/` dan `data/` tetap dipertahankan strukturnya di repository menggunakan file penanda `.gitkeep` agar mount volume Docker tetap berfungsi normal pada instalasi baru.

---

## 🔒 Pembaruan Sertifikat SSL / TLS

Sertifikat SSL self-signed disimpan di folder `caddy/certs/`. Jika Anda ingin memperbarui atau menyertakan alamat IP server yang baru:

- **Pada Windows (PowerShell):**
  ```powershell
  # Otomatis mendeteksi IP lokal:
  .\scripts\renew_ssl.ps1
  # Atau berikan IP spesifik:
  .\scripts\renew_ssl.ps1 -HostIP "192.168.1.50"
  ```
- **Pada Linux / WSL Ubuntu:**
  ```bash
  chmod +x ./scripts/renew_ssl.sh
  ./scripts/renew_ssl.sh 192.168.1.50
  ```

Skrip tersebut otomatis meregenerasi pasangan kunci `cert.pem` & `key.pem` dengan ekstensi TLS lengkap (`serverAuth`, `SAN: IP:<IP_SERVER>, IP:127.0.0.1, DNS:localhost`) dan me-reload Caddy tanpa downtime.

---

## 📁 Struktur Direktori Proyek

```text
zoneminder_cc/
├── .gitignore                 # Konfigurasi proteksi berkas sensitif & kredensial
├── docker-compose.yml         # Konfigurasi orkestrasi 5 layanan Docker
├── mosquitto.conf             # Konfigurasi broker MQTT Mosquitto
├── README.md                  # Dokumentasi teknis & panduan lengkap
├── caddy/
│   ├── Caddyfile              # Konfigurasi reverse proxy universal (:443 HTTPS)
│   └── certs/                 # Direktori sertifikat TLS (diabaikan git demi keamanan)
│       ├── .gitkeep           # Mempertahankan struktur direktori di git
│       └── openssl.cnf        # Konfigurasi minimal OpenSSL
├── cctv_checker/
│   ├── Dockerfile             # Dockerfile service CCTV Health Checker
│   └── main.py                # Core Python penguji RTSP & MQTT publisher
├── data/
│   └── .gitkeep               # Direktori runtime (log json diabaikan git)
├── html_dashboard/
│   ├── Dockerfile             # Dockerfile web interface dashboard
│   ├── app.py                 # Backend Flask proxy API ZoneMinder & kontrol checker
│   ├── index.html             # Portal navigasi utama ZoneMinder
│   ├── zoneminder.html        # CRUD Camera Manager, status & checker controls
│   ├── add_camera.html        # Form pendaftaran kamera tunggal
│   ├── burst.html             # Pendaftaran massal via Quick Paste RTSP & Excel
│   ├── log_display.html       # Live stream MQTT log & panduan notifikasi
│   └── requirements.txt       # Dependencies Python Flask
└── scripts/
    ├── renew_ssl.ps1          # Script auto-renew SSL untuk Windows
    └── renew_ssl.sh           # Script auto-renew SSL untuk Linux/WSL
```

---

## 💡 Informasi Akun Default & Troubleshooting

- **ZoneMinder Admin Username**: `admin`
- **ZoneMinder Admin Password**: `admin`
- **Mosquitto MQTT Auth**: `Anonymous (Tanpa password)`

### Troubleshooting:
1. **Peringatan SSL di Browser (*Your connection is not private*):**
   Karena sertifikat dibuat secara mandiri (*self-signed*), klik tombol **Advanced** (Lanjutan) lalu pilih **Proceed to `<IP_SERVER>` (unsafe)**. Ini normal untuk sertifikat lokal.
2. **Error Kredensial Saat Build Docker (*error getting credentials*):**
   Hapus baris `"credsStore": "desktop"` dari berkas konfigurasi Docker komputer Anda (`~/.docker/config.json`), lalu jalankan `docker compose build` kembali.
3. **Melihat Log Kontainer Tertentu:**
   ```bash
   # Log CCTV Checker:
   docker logs -f cctv_checker_service
   # Log Caddy Proxy:
   docker logs -f caddy_proxy
   # Log ZoneMinder:
   docker logs -f zoneminder
   ```
