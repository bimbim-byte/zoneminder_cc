# 🛡️ ZoneMinder Central CCTV Management & MQTT Monitoring System

Sistem manajemen kamera CCTV terpusat berbasis **ZoneMinder NVR** dengan antarmuka web modern (*Single Page Application*), reverse proxy aman berbasis **HTTPS (Caddy)**, pendaftaran kamera massal (*Burst Add* via teks & Excel), serta deteksi keaktifan kamera otomatis berbasis *TCP Socket RTSP* yang dilaporkan secara *real-time* melalui broker **Mosquitto MQTT**.

> 💡 **Panduan Pemula Lengkap:** Bagi pengguna baru yang membutuhkan tutorial langkah-demi-langkah Command Prompt / terminal dari awal, silakan baca **[PANDUAN_PENGGUNAAN.md](PANDUAN_PENGGUNAAN.md)**.

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
  - **Kontrol massal seluruh kamera**: aktifkan semua dengan mode fungsi tertentu, matikan semua, atau pulihkan tiap kamera ke fungsi asli yang tersimpan.
  - Pengecekan CPU Load server ZoneMinder secara langsung.
- **⚙️ Kendali Dinamis CCTV Health Checker**:
  - Tombol **Jeda (Pause) / Aktifkan (Resume)** tanpa perlu mematikan kontainer Docker.
  - Pengaturan **Delay Interval Pengecekan** (dalam detik, misal 10s, 30s, 60s).
  - Tombol **⚡ Cek Semua Kamera Sekarang (Run Now)** untuk memicu pemeriksaan instan.
- **🖥️ Wall Dashboard (Grid Live Kamera)**:
  - Halaman khusus menonton banyak kamera sekaligus tanpa membebani ZoneMinder (tanpa memicu perekaman/analisis tambahan).
  - Pemilihan sumber kamera: **Seluruh Kamera** atau **sebagian Group** (mendukung **multi-group** dengan penggabungan otomatis tanpa duplikat).
  - Grid dapat dikustomisasi: jumlah **kolom**, **rasio** tile (16:9 / 4:3 / 1:1 / 21:9), **resolusi**, dan **FPS** per kamera.
  - **Lazy load viewport**: kamera hanya dimuat saat terlihat di layar, sehingga hemat bandwidth dan CPU.
  - **Batas stream bersamaan** (dapat diatur) dengan indikator `live` / `antre` untuk menjaga kestabilan server.
  - Mode layar penuh per kamera, jeda massal, dan URL langsung yang bisa dijadikan bookmark atau kiosk display.
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
| **Wall Dashboard (Pilih Kamera)** | `https://<IP_SERVER>/wall` | Pilih seluruh kamera atau sebagian group (multi-group) |
| **Wall Dashboard (Grid Live)** | `https://<IP_SERVER>/wall/view?mode=all` | Grid live stream kamera, atur kolom/rasio/resolusi/FPS |
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

#### Kontrol Massal Seluruh Kamera
Di atas tabel kamera terdapat baris **⚡ Kontrol Seluruh Kamera**:

| Tombol | Fungsi |
| :--- | :--- |
| **▶ Aktifkan Semua** | Mengaktifkan seluruh kamera memakai mode fungsi pada dropdown di sebelahnya (Monitor / Modect / Record / Mocord / Nodect) |
| **↺ Pulihkan Fungsi Asli** | Mengembalikan setiap kamera ke mode terakhir yang tercatat. Berguna setelah *Matikan Semua* — kamera kembali ke mode asalnya, bukan seragam ke satu mode |
| **⏹ Matikan Semua** | Mengubah seluruh kamera ke `Function=None` dan `Enabled=0` (perekaman & deteksi berhenti) |

Catatan:
- Setiap tombol meminta konfirmasi sebelum dijalankan, dan menampilkan ringkasan `X berhasil, Y gagal` setelah selesai.
- Mode terakhir tiap kamera dicatat di `data/camera_functions.json`, sehingga *Pulihkan Fungsi Asli* tetap bekerja meski container sempat di-restart.
- Mengaktifkan/mematikan kamera **tidak menghapus** rekaman atau event yang sudah ada.

### 4. Mengontrol CCTV Health Checker
Pada halaman `zoneminder.html` maupun `log_display.html` tersedia widget kendali checker:
- **Tombol ⏸ Jeda / ▶ Aktifkan:** Menjeda atau melanjutkan loop pengecekan kesehatan kamera tanpa mematikan kontainer.
- **Delay Interval Pengecekan:** Ubah angka detik (minimal 5 detik) lalu klik **Simpan Delay**. Nilai default adalah **600 detik (10 menit)**.
- **Tombol ⚡ Cek Semua Kamera Sekarang:** Memeriksa status konektivitas seluruh kamera RTSP saat itu juga tanpa menunggu interval waktu.

> **Status awal checker adalah NONAKTIF (Paused).** Setelah container dinyalakan
> pertama kali, checker tidak melakukan pengecekan otomatis sampai Anda menekan
> **▶ Aktifkan Checker**. Ini mencegah pemeriksaan RTSP berjalan diam-diam dan
> membebani jaringan tanpa sepengetahuan operator.

### 5. Wall Dashboard (Grid Live Kamera)
Halaman ini dibuat khusus untuk **menonton banyak kamera sekaligus** tanpa membebani ZoneMinder. Berbeda dari montage bawaan ZoneMinder, halaman ini hanya mengambil stream (tanpa memicu perekaman atau analisis tambahan).

**Alur penggunaan:**
1. Buka **Wall Dashboard** (`https://<IP_SERVER>/wall`).
2. Pilih salah satu mode:
   - **Seluruh Kamera** — menampilkan semua kamera yang terdaftar di ZoneMinder.
   - **Berdasarkan Group** — centang **satu atau beberapa group** (multi-group). Kamera gabungan dari group terpilih akan ditampilkan tanpa duplikat.
3. Klik **Buka Wall Dashboard**. Anda akan diarahkan ke halaman grid live.

**Kontrol pada halaman grid:**
| Kontrol | Fungsi |
| :--- | :--- |
| **Kolom** | Jumlah kolom grid (Auto, 1–10) |
| **Rasio** | Perbandingan sisi tile kamera (16:9, 4:3, 1:1, 21:9) |
| **Resolusi** | Ukuran gambar dari ZM (240–640 px, atau Asli) |
| **FPS** | Batas frame per detik per kamera (2, 5, 10, 15, Maks) |
| **Stream** | Jumlah stream yang berjalan bersamaan (4–16) |
| **🏷️** | Tampilkan/sembunyikan nama kamera |
| **⏸️** | Jeda semua stream (menghemat resource) |
| **↻ Reload** | Muat ulang semua stream |

**Indikator status** di kanan atas menampilkan `X kamera · live N · antre M` — berapa stream yang sedang berjalan dan berapa yang menunggu.

**Penting — pemahaman performa:**
- Stream hanya dimuat untuk kamera yang **terlihat di layar** (*lazy load*). Kamera di luar viewport otomatis dilepas.
- Jumlah stream bersamaan dibatasi (default **6**) karena browser hanya mengizinkan ~6 koneksi HTTP/1.1 per host. Stream berlebih masuk antrean.
- ZM melakukan **multiplex stream**: banyak penonton pada kamera yang sama hanya memakai **satu** proses ZM. Jadi 8 orang menonton kamera yang sama ≈ beban 1 kamera.
- Untuk grid berisi banyak kamera (50–100), disarankan **Resolusi 240–320 px** dan **FPS 2–5** agar bandwidth tetap wajar.

**Format URL langsung** (bisa dijadikan bookmark / kiosk display):
```
# Seluruh kamera
https://<IP_SERVER>/wall/view?mode=all

# Satu atau beberapa group
https://<IP_SERVER>/wall/view?mode=groups&groups=3,4

# Kamera spesifik
https://<IP_SERVER>/wall/view?mode=ids&ids=8,10,21
```

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
│   └── .gitkeep               # Direktori runtime (log json & config diabaikan git)
├── html_dashboard/
│   ├── Dockerfile             # Dockerfile web interface dashboard
│   ├── app.py                 # Backend Flask proxy API ZoneMinder & kontrol checker
│   ├── index.html             # Portal navigasi utama ZoneMinder
│   ├── zoneminder.html        # CRUD Camera Manager, kontrol massal & checker controls
│   ├── add_camera.html        # Form pendaftaran kamera tunggal
│   ├── burst.html             # Pendaftaran massal via Quick Paste RTSP & Excel
│   ├── log_display.html       # Live stream MQTT log & panduan notifikasi
│   ├── wall.html              # Wall Dashboard: pemilihan kamera / multi-group
│   ├── wall_view.html         # Wall Dashboard: grid live kamera (grid, rasio, FPS)
│   ├── requirements.txt       # Dependencies Python (Flask, Waitress)
├── zm-conf/
│   ├── Dockerfile             # Image turunan ZM + tuning produksi
│   ├── mysql-tuning.cnf       # Tuning MySQL (buffer pool, koneksi, flush)
│   ├── apache-limit.conf      # Tuning Apache MPM (ServerLimit, worker, keepalive)
│   └── zoneminder.conf        # Konfigurasi Apache ZoneMinder
└── scripts/
    ├── renew_ssl.ps1          # Script auto-renew SSL untuk Windows
    └── renew_ssl.sh           # Script auto-renew SSL untuk Linux/WSL
```

---

## ⚙️ Tuning Produksi (Server 32 Core / 32 GB RAM)

Konfigurasi sudah disetel untuk server kelas Proxmox VM 32 core / 32 GB. Semua nilai
dipilih konservatif: cukup lega untuk 100 kamera, tidak boros RAM.

### Ringkasan nilai tuning

| Komponen | Parameter | Nilai | Alasan |
| :--- | :--- | :--- | :--- |
| **ZoneMinder** | `shm_size` | **8 GB** | Buffer frame ~9 MB/kamera; 8 GB aman untuk 100+ kamera |
| ZoneMinder | `ulimits.nofile` | 65536 | ZM membuka banyak file descriptor (event + shared memory) |
| **MySQL** | `innodb_buffer_pool_size` | **2 GB** | Default hanya 128 MB → query event menyentuh disk |
| MySQL | `innodb_buffer_pool_instances` | 4 | Hindari rebutan latch di CPU banyak |
| MySQL | `innodb_flush_log_at_trx_commit` | 2 | Flush per detik, bukan per commit → jauh lebih cepat |
| MySQL | `max_connections` | 500 | Default 151 terlalu kecil untuk checker + wall + API |
| MySQL | `tmp_table_size` | 64 MB | Query event ZM butuh tabel sementara lebih besar |
| **Apache** | `ServerLimit` | 512 | **Wajib** — bila tidak diset, Apache memotong `MaxRequestWorkers` |
| Apache | `MaxRequestWorkers` | 512 | Satu stream = satu worker; cukup untuk 100 kamera + web |
| Apache | `KeepAlive` | On | Cegah buka-tutup koneksi pada streaming MJPEG |
| **CCTV Checker** | Interval default | **600 detik** | Cek tiap 10 menit; cukup untuk pemantauan |
| CCTV Checker | Status awal | **Nonaktif (OFF)** | Mencegah pengecekan otomatis tanpa sepengetahuan operator |

### Catatan penting: kenapa ZoneMinder memakai image turunan

ZoneMinder **menolak file config yang world-writable**:

```
[Warning] World-writable config file '...zz-zm-tuning.cnf' is ignored.
```

Saat file config di-*bind mount* dari filesystem Windows (9p/drvfs), permission
dipaksa menjadi `777` dan `chmod` gagal karena mount bersifat read-only. Akibatnya
seluruh tuning MySQL diabaikan tanpa error yang jelas.

Solusinya: [`zm-conf/Dockerfile`](zm-conf/Dockerfile) menyalin file config ke dalam
layer image dengan permission `644`. Ini bekerja konsisten di host mana pun
(Proxmox/ext4 maupun Windows), dan container tetap portabel.

Setelah mengubah file di `zm-conf/`, wajib rebuild:

```bash
docker compose build zoneminder
docker compose up -d zoneminder
```

### Cara verifikasi tuning sudah terpakai

```bash
# MySQL — harus menampilkan 2048 MB, instances 4, maxconn 500
docker exec zoneminder mysql -uroot -e \
  "SELECT @@innodb_buffer_pool_size/1024/1024 AS bufferpool_MB, \
   @@innodb_buffer_pool_instances AS inst, @@max_connections AS maxconn;"

# Tidak boleh ada warning "world-writable"
docker exec zoneminder tail -30 /var/log/mysql/error.log | grep -i world-writable

# Apache — tidak boleh muncul warning "exceeds ServerLimit"
docker exec zoneminder apache2ctl configtest

# Shared memory — harus 8.0G
docker exec zoneminder df -h /dev/shm
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
