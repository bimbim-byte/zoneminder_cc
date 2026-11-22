# 🛡️ ZoneMinder Central CCTV Management System

Sistem manajemen kamera CCTV terpusat berbasis **ZoneMinder NVR** dengan antarmuka web modern (*Single Page Application*), reverse proxy aman berbasis **HTTPS (Caddy)**, pendaftaran kamera massal (*Burst Add* via teks & Excel), serta deteksi keaktifan kamera otomatis berbasis *TCP Socket RTSP* (cek konektivitas berkala + auto-switch fungsi monitor di ZoneMinder).

> 💡 **Panduan Pemula Lengkap:** Bagi pengguna baru yang membutuhkan tutorial langkah-demi-langkah Command Prompt / terminal dari awal, silakan baca **[PANDUAN_PENGGUNAAN.md](PANDUAN_PENGGUNAAN.md)**.

---

## 📋 Daftar Isi
1. [Deskripsi & Arsitektur](#-arsitektur-layanan-docker-stack)
2. [Fitur Utama](#-fitur-utama)
3. [Daftar URL & Akses Layanan](#-daftar-url--akses-layanan)
4. [Panduan Instalasi Cepat](#-panduan-instalasi-cepat)
5. [Panduan Penggunaan Fitur](#-panduan-penggunaan-fitur)
6. [Keamanan & Berkas yang Diabaikan Git (.gitignore)](#-keamanan--berkas-yang-diabaikan-git-gitignore)
7. [Pembaruan Sertifikat SSL / TLS](#-pembaruan-sertifikat-ssl--tls)
8. [Struktur Direktori Proyek](#-struktur-direktori-proyek)
9. [Informasi Akun Default & Troubleshooting](#-informasi-akun-default--troubleshooting)

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
            ┌──────────────────────────┴───────────────────────────┐
            │ (/zm*, /cgi-bin*)                                 │ (/)
            ▼                                                   ▼
┌────────────────────────┐                     ┌───────────────────────┐
│     ZoneMinder NVR     │◄──── API/stream ────┤   Camera Dashboard    │
│  (Core NVR & CakePHP)  │                     │ (Flask Backend & SPA) │
└───────────┬────────────┘                     └───────────┬───────────┘
            │                                              │
            │            config & kontrol checker          │
            ▼                                              ▼
     ┌─────────────────────────────────────────────────────────────┐
     │                     CCTV Health Checker                     │
     │      (TCP Socket RTSP & Auto Function Switch & Kontrol)     │
     └─────────────────────────────────────────────────────────────┘
```

1. **Caddy Proxy (`caddy_proxy`)**: Reverse proxy HTTPS standar industri yang mengikat ke port universal `:443`, melayani traffic untuk domain maupun IP manapun dengan sertifikat TLS terintegrasi.
2. **ZoneMinder (`zoneminder`)**: Core NVR **v1.38.6** (image resmi `zoneminder/zoneminder`) untuk perekaman, streaming RTSP, event storage, dan motion detection. Sejak migrasi, database **tidak lagi** berada di dalam container ini.
3. **Database (`zm_db`)**: MariaDB 11.8 khusus ZoneMinder (skema `zm`). Hanya dijangkau lewat network internal `cctv_net` — tanpa port ke host. Tuning di `zm-conf/db-tuning.cnf`, kredensial di docker secret.
4. **Camera Dashboard (`camera-dashboard`)**: Web UI SPA berbasis HTML5, CSS3, dan Python Flask backend untuk manajemen monitor, ekspor/impor Excel, dan kontrol checker.
5. **CCTV Health Checker (`cctv_checker_service`)**: Background service Python yang menguji konektivitas TCP RTSP setiap kamera secara berkala dan auto-switch fungsi monitor di ZoneMinder (`Monitor` <-> `None`). Hasil pemeriksaan ditulis ke log container; tidak ada perantara pesan eksternal.

---

## 🚀 Fitur Utama

- **🖥️ Antarmuka Terpadu (SPA Light Theme)**: Semua halaman mengusung tema terang (*light theme*), modern, *responsive*, dan pas dalam satu layar desktop (*full height SPA*).
- **⚡ Pendaftaran Kamera Massal (Burst Add Upgraded)**:
  - **Quick Paste RTSP**: Salin puluhan URL RTSP sekaligus, beri prefix nama otomatis, pratinjau tabel, dan daftarkan sekaligus dalam satu klik.
  - **Impor Spreadsheet Excel (.xlsx)**: Unduh template Excel bawaan, isi daftar kamera, lalu unggah untuk pendaftaran massal otomatis.
- **🛡️ ZoneMinder Camera Manager**:
  - Autentikasi otomatis API ZoneMinder v1.38.6 (parity dengan kontrak 1.36 sudah diuji ulang).
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
- **📡 Log Kesehatan Kamera di Log Container**:
  - Setiap perubahan status (ONLINE/OFFLINE) dan jumlah fungsi monitor yang diperbarui dicatat ke log `cctv_checker_service`.
  - URL RTSP ditulis tanpa kredensial, sehingga aman disalin ke tiket atau chat.
  - Lihat dengan: `docker logs -f cctv_checker_service`.

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
| **Wall Dashboard (Pilih Kamera)** | `https://<IP_SERVER>/wall` | Pilih seluruh kamera atau sebagian group (multi-group) |
| **Wall Dashboard (Grid Live)** | `https://<IP_SERVER>/wall/view?mode=all` | Grid live stream kamera, atur kolom/rasio/resolusi/FPS |
| **ZoneMinder (port langsung)** | — | **Tidak tersedia.** Port ZM hanya `expose` di network internal; akses wajib lewat Caddy (`:443/zm/` atau `:9443/zm/`) |
| **Dashboard (port langsung)** | — | **Tidak tersedia.** Dashboard hanya lewat Caddy `:9443` (login Flask) |

---

## 🛠️ Panduan Instalasi Cepat

### Prasyarat
- **Docker Desktop** (versi 4.x ke atas) terpasang di Windows atau Linux/WSL2.
- **Docker Compose** v2.
- **OpenSSL** (sudah tersedia bawaan di Linux/WSL/Git for Windows).

> **Menjalankan dari Windows?** Jika Anda memakai WSL2, jalankan seluruh perintah
> di bawah **dari dalam WSL Ubuntu**, bukan PowerShell. Jalankan
> `wsl --distribution Ubuntu`, lalu `cd /mnt/e/CodeFile/kemnaker/zoneminder_cc`.
> Docker Desktop juga harus dalam keadaan menyala.

### 0. Checklist Instalasi (Ringkas)

Urutan ini wajib diikuti; melewati satu langkah akan menghentikan proses berikutnya.

| # | Langkah | Perintah | Wajib? |
| :--: | :--- | :--- | :--- |
| 1 | Kloning repo | `git clone <url> && cd zoneminder_cc` | ✔ |
| 2 | Buat file `.env` | `cp .env.example .env` | **✔ WAJIB** |
| 3 | Isi `ZM_USER` / `ZM_PASS` | edit `.env` | **✔ WAJIB** |
| 4 | Buat sertifikat SSL | `./scripts/renew_ssl.sh` | **✔ WAJIB** |
| 5 | Nyalakan stack | `docker compose up -d` | ✔ |
| 6 | Periksa kontainer | `docker compose ps` | disarankan |
| 7 | Jalankan pre-flight | `bash scripts/preflight.sh` | disarankan |

> **Langkah 2 dan 4 tidak bisa dilewati.** Docker Compose akan langsung gagal
> dengan pesan `required variable ZM_USER is missing a value` bila `.env` belum
> ada, dan Caddy akan gagal memuat karena `cert.pem` belum dibuat.

**Cek dulu sebelum menyalakan** — jalankan skrip pre-flight. Skrip ini memeriksa
Docker, `.env`, sertifikat, port, dan berkas penting, lalu memberi tahu apa yang
kurang:

```bash
bash scripts/preflight.sh
```

Contoh keluaran bila sudah siap:
```text
 HASIL: SIAP. Lanjutkan dengan:  docker compose up -d
```

### 1. Kloning Repository
```bash
git clone https://github.com/<username>/zoneminder_cc.git
cd zoneminder_cc
```

### 2. Siapkan File Konfigurasi `.env`
```bash
cp .env.example .env
```
Sesuaikan `ZM_USER` dan `ZM_PASS` dengan akun ZoneMinder Anda. Nilai default
adalah `admin` / `P@ssw0rd`. File ini menjadi satu-satunya tempat menyimpan
kredensial — dashboard dan checker membacanya dari sini.

### 3. Generate Sertifikat SSL Lokal (Wajib Sebelum Start Pertama)
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

### 4. Jalankan Seluruh Kontainer
```bash
docker compose up -d
```
Tunggu sekitar 1–2 menit saat pertama kali dijalankan agar inisialisasi database ZoneMinder selesai.

> **Jangan memakai `docker compose up -d --build`.** Pada Compose v5.x perintah itu
> gagal dengan pesan menyesatkan `error getting credentials`. Lihat
> *Troubleshooting* nomor 2 untuk perintah build yang benar.

### 5. Buka Antarmuka di Browser
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
   Bila kamera memakai password dengan karakter khusus (`@`, `:`, `/`), **tidak perlu
   menulis `%40` manual** — lihat bagian *Penulisan URL RTSP & Password Khusus* di bawah.
3. Pilih resolusi, **Analysis FPS** (default `8`), dan fungsi default (`Monitor`/`Modect`).
4. Klik **Daftarkan Kamera**.

#### Penulisan URL RTSP & Password Khusus

Password kamera sering mengandung `@` (mis. `0p3r@t0r`, `PT@2024`). Dulu ini
menghasilkan URL dengan dua `@` yang membuat ffmpeg membaca **host** sebagai
`t0r@10.121.10.145` sehingga kamera tidak pernah mengirim frame. Sekarang dashboard
menormalkannya otomatis:

| Ditulis operator | Tersimpan di ZoneMinder | Catatan |
| :--- | :--- | :--- |
| `rtsp://operator:0p3r@t0r@10.121.10.145:554/Streaming/Channels/101` | `rtsp://operator:0p3r%40t0r@10.121.10.145:554/Streaming/Channels/101` | password utuh, host benar |
| URL tanpa kredensial + kolom **Username**/**Password** diisi | kredensial digabung dengan encoding otomatis | karakter `@ : /` di-encode |
| `rtsp://user:pa:ss@10.0.0.9:554/ch1` | `rtsp://user:pa%3Ass@10.0.0.9:554/ch1` | `:` di dalam password bukan port |

Aturan yang dipakai: **userinfo = semua sebelum `@` terakhir yang diikuti bentuk
`host[:port]` yang sah**; di dalam userinfo, `:` **pertama** memisahkan username dan
password. Karena itu password yang mengandung `@` maupun `:` tetap utuh.

Bila URL sudah memuat kredensial, kolom Username/Password terpisah **diabaikan**
(dashboard memberi catatan di log form). Bila URL belum memuat kredensial, kolom itu
yang dipakai.

Semua perbaikan dilaporkan sebagai catatan (`path_warnings`) di log form dan tidak
pernah menolak penyimpanan: kamera lama yang path-nya rusak ikut diperbaiki begitu
operator menekan **💾 Perbarui Kamera**.

Uji perilaku ini tanpa menyentuh database:
```bash
docker exec camera-dashboard python /app/_verify_rtsp_path.py
docker exec camera-dashboard python /app/_e2e_rtsp_payload.py
```

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
Pada halaman `zoneminder.html` tersedia widget kendali checker:
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

## 🔐 Keamanan & Berkas yang Diabaikan Git (.gitignore)

Untuk memastikan kredensial pribadi dan data CCTV aman saat proyek disimpan di GitHub, berkas `.gitignore` telah dikonfigurasi untuk **tidak pernah mengunggah berkas sensitif berikut**:

| Kategori Berkas | Pola .gitignore | Alasan Keamanan |
| :--- | :--- | :--- |
| **Kunci Privat SSL** | `caddy/certs/*.key`, `*.pem` | Melindungi sertifikat dan *private key* TLS server Anda dari akses publik. |
| **Log Runtime Kamera** | `data/*.json`, `data/*.log` | Konfigurasi checker & cache monitor menyimpan URL stream RTSP yang sering kali mengandung username & password kamera (`rtsp://admin:password@...`). |
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
├── docker-compose.yml         # Konfigurasi orkestrasi 4 layanan Docker
├── README.md                  # Dokumentasi teknis & panduan lengkap
├── .env.example               # Template konfigurasi (kredensial, interval, port)
├── .env                       # Konfigurasi aktual — DIABAIKAN GIT
├── caddy/
│   ├── Caddyfile              # Konfigurasi reverse proxy universal (:443 HTTPS)
│   └── certs/                 # Direktori sertifikat TLS (diabaikan git demi keamanan)
│       ├── .gitkeep           # Mempertahankan struktur direktori di git
│       └── openssl.cnf        # Konfigurasi minimal OpenSSL
├── cctv_checker/
│   ├── Dockerfile             # Dockerfile service CCTV Health Checker
│   └── main.py                # Core Python penguji RTSP & auto-switch fungsi ZM
├── data/
│   └── .gitkeep               # Direktori runtime (log json & config diabaikan git)
├── html_dashboard/
│   ├── Dockerfile             # Dockerfile web interface dashboard
│   ├── app.py                 # Backend Flask proxy API ZoneMinder & kontrol checker
│   ├── index.html             # Portal navigasi utama ZoneMinder
│   ├── zoneminder.html        # CRUD Camera Manager, kontrol massal & checker controls
│   ├── add_camera.html        # Form pendaftaran kamera tunggal
│   ├── burst.html             # Pendaftaran massal via Quick Paste RTSP & Excel
│   ├── wall.html              # Wall Dashboard: pemilihan kamera / multi-group
│   ├── wall_view.html         # Wall Dashboard: grid live kamera (grid, rasio, FPS)
│   ├── requirements.txt       # Dependencies Python (Flask, Waitress)
├── zm-conf/
│   ├── Dockerfile             # Image turunan ZM 1.38.6 (base resmi) + tuning Apache
│   ├── db-tuning.cnf          # Tuning MariaDB untuk service db (buffer pool, koneksi, flush)
│   ├── apache-limit.conf      # Tuning Apache MPM (ServerLimit, worker, keepalive)
│   └── zoneminder.conf        # Referensi konfigurasi Apache ZoneMinder
├── secrets/                   # Password DB (file-based secret, gitignored)
│   ├── zm_db_pass.txt         # Password user `zmuser` untuk ZoneMinder
│   └── mariadb_root_pass.txt  # Password root MariaDB (hanya untuk admin/import)
├── backups/                   # Dump & konfigurasi pra-migrasi 1.36 (gitignored)
└── scripts/
    ├── preflight.sh           # Cek kesiapan instalasi sebelum `docker compose up`
    ├── fix_monitor_source_138.sh # Normalisasi sumber monitor 1.36 -> 1.38 (Method/Options)
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
| **MariaDB** (`zm_db`) | `innodb_buffer_pool_size` | **2 GB** | Default dari image hanya 256 MB → query event menyentuh disk |
| MariaDB | `innodb_buffer_pool_instances` | *(dihapus)* | Opsi ini tidak ada lagi di MariaDB 11.x; dibuang dari `db-tuning.cnf` agar log bersih |
| MariaDB | `innodb_flush_log_at_trx_commit` | 2 | Flush per detik, bukan per commit → jauh lebih cepat |
| MariaDB | `max_connections` | 500 | Default 151 terlalu kecil untuk checker + wall + API |
| MariaDB | `tmp_table_size` | 64 MB | Query event ZM butuh tabel sementara lebih besar |
| **Apache** | `ServerLimit` | 512 | **Wajib** — bila tidak diset, Apache memotong `MaxRequestWorkers` |
| Apache | `MaxRequestWorkers` | 512 | Satu stream = satu worker; cukup untuk 100 kamera + web |
| Apache | `KeepAlive` | On | Cegah buka-tutup koneksi pada streaming MJPEG |
| **CCTV Checker** | Interval default | **600 detik** | Cek tiap 10 menit; cukup untuk pemantauan |
| CCTV Checker | Status awal | **Nonaktif (OFF)** | Mencegah pengecekan otomatis tanpa sepengetahuan operator |
| **Konfigurasi** | Sumber kredensial | **`.env`** | Satu tempat untuk `ZM_USER`/`ZM_PASS`; ubah password tanpa edit kode |

### Catatan penting: image turunan (Apache) vs tuning DB

ZoneMinder **menolak file config yang world-writable**:

```
[Warning] World-writable config file '...zz-zm-tuning.cnf' is ignored.
```

Saat file config **Apache** di-*bind mount* dari filesystem Windows (9p/drvfs), permission
dipaksa menjadi `777` dan `chmod` gagal karena mount bersifat read-only. Akibatnya
seluruh tuning Apache diabaikan tanpa error yang jelas.

Solusinya: [`zm-conf/Dockerfile`](zm-conf/Dockerfile) menyalin file config ke dalam
layer image dengan permission `644`. Ini bekerja konsisten di host mana pun
(Proxmox/ext4 maupun Windows), dan container tetap portabel.

Untuk **MariaDB** tidak diperlukan image turunan: `zm-conf/db-tuning.cnf`
di-mount read-only ke `/etc/mysql/conf.d/zz-zm-tuning.cnf` pada service `db`.
Ini sudah diverifikasi bekerja di Windows — `docker compose logs db` bersih dari
`world-writable ... ignored` maupun `deprecated`, dan nilai
`innodb_buffer_pool_size` (2 GB), `max_connections` (500), serta
`transaction_isolation` (READ-COMMITTED) benar-benar terpakai.
Mengubah file itu cukup dengan `docker compose up -d --force-recreate db`
(data di volume `zm_db_data` tidak terhapus).

Setelah mengubah file di `zm-conf/`, wajib rebuild:

```bash
docker compose build zoneminder
docker compose up -d zoneminder
```

### Cara verifikasi tuning sudah terpakai

```bash
# MariaDB (service db) — harus menampilkan buffer pool 2 GB dan maxconn 500
docker exec zm_db mariadb -uroot -p"$(cat /run/secrets/mariadb_root_pass)" -e \
  "SELECT @@innodb_buffer_pool_size/1024/1024 AS bufferpool_MB, \
   @@max_connections AS maxconn, @@transaction_isolation;"

# Tidak boleh ada warning "world-writable"
docker compose logs db | grep -iE "world-writable|deprecated"

# Apache — tidak boleh muncul warning "exceeds ServerLimit"
docker exec zoneminder apache2ctl configtest

# Shared memory — harus 8.0G
docker exec zoneminder df -h /dev/shm
```

---

## 💡 Kredensial, Akun Default & Troubleshooting

### Konfigurasi kredensial lewat file `.env`

Seluruh kredensial ZoneMinder dibaca dari satu file `.env` di root proyek —
tidak ada lagi password yang ditulis langsung di kode Python maupun HTML.

**Langkah pertama setelah kloning:**
```bash
cp .env.example .env
```

Lalu sesuaikan isinya:

| Variabel | Default | Keterangan |
| :--- | :--- | :--- |
| `ZM_USER` | `admin` | Username ZoneMinder untuk API & login |
| `ZM_PASS` | `P@ssw0rd` | Password ZoneMinder untuk API & login |
| `CHECK_INTERVAL` | `600` | Interval pengecekan RTSP (detik) |
| `RTSP_TIMEOUT` | `3.0` | Timeout koneksi TCP ke kamera (detik) |
| `CHECKER_ENABLED` | `false` | Status awal checker saat pertama dinyalakan |
| `WSGI_THREADS` | `64` | Thread waitress untuk stream MJPEG |

**Setelah mengubah password di ZoneMinder:**
1. Ubah `ZM_PASS` di file `.env`.
2. Jalankan `docker compose up -d` — kedua service (dashboard & checker)
   otomatis memakai password baru. Tidak perlu mengedit kode.

> File `.env` **tidak** ikut ter-commit (lihat `.gitignore` bagian 3).
> Gunakan `.env.example` sebagai template yang aman dibagikan.

### Akun

- **ZoneMinder Admin**: `admin` / `P@ssw0rd` *(ubah segera setelah instalasi)*
- **Dashboard**: akun dikelola di halaman Pengaturan (`data/dashboard_users.json`)

### Troubleshooting:
1. **Peringatan SSL di Browser (*Your connection is not private*):**
   Karena sertifikat dibuat secara mandiri (*self-signed*), klik tombol **Advanced** (Lanjutan) lalu pilih **Proceed to `<IP_SERVER>` (unsafe)**. Ini normal untuk sertifikat lokal.
2. **Error Kredensial Saat Build Docker (*error getting credentials - err: exit status 1, out: ``*):**
   Ini BUKAN masalah kredensial. Penyebab sebenarnya adalah **gerbang entitlement pada
   `docker compose build`** (Compose v5.x memakai bake/buildx), yang menolak membaca Dockerfile
   di luar konteks lalu menampilkan pesan menyesatkan:

   ```
   additional privileges requested: pass "--allow=fs.read=zm-conf\Dockerfile" to grant requested privileges
   ```

   **Jangan** mengubah `~/.docker/config.json` dan **jangan** menghapus `credsStore` —
   keduanya tidak berhubungan dan justru merusak login registry Anda.

   **Solusi yang terbukti bekerja** (buildx v0.38.1) — tambahkan `--allow=fs.read=.`:

   ```bash
   docker buildx bake --allow=fs.read=. -f docker-compose.yml \
     --set zoneminder.tags=zoneminder_tuned:1.38.6 \
     --set ui-interface.tags=zoneminder_cc-ui-interface:latest \
     --set cctv-checker.tags=zoneminder_cc-cctv-checker:latest

   docker compose up -d
   ```

   **Alternatif** bila bake tetap bermasalah — build per service dengan builder klasik:

   ```bash
   docker build -t zoneminder_tuned:1.38.6   -f zm-conf/Dockerfile        zm-conf
   docker build -t zoneminder_cc-ui-interface:latest     -f html_dashboard/Dockerfile html_dashboard
   docker build -t zoneminder_cc-cctv-checker:latest     -f cctv_checker/Dockerfile   cctv_checker
   docker compose up -d
   ```

   > Catatan: `docker compose build` **tidak** menyediakan flag `--allow`, sehingga
   > `docker compose up -d --build` akan selalu gagal pada versi Compose ini.
3. **Melihat Log Kontainer Tertentu:**
   ```bash
   # Log CCTV Checker:
   docker logs -f cctv_checker_service
   # Log Caddy Proxy:
   docker logs -f caddy_proxy
   # Log ZoneMinder 1.38.6:
   docker logs -f zoneminder
   # Log Database (MariaDB):
   docker logs -f zm_db
   ```
4. **Log ZoneMinder penuh peringatan `Unknown method (rtsp)` / `Option rtsp_transport not recognized by ffmpeg`:**
   Kamera masih memakai setelan sumber 1.36. Jalankan `bash scripts/fix_monitor_source_138.sh`
   (lihat bagian *Perbaikan sumber kamera setelah migrasi* di dokumen ini).
5. **Dashboard melaporkan "berhasil", tetapi kamera tidak pernah muncul di ZoneMinder:**
   Ini bug API ZoneMinder 1.38 yang **sudah diperbaiki** di `html_dashboard/app.py`.
   Dua penyebabnya, keduanya mudah terlewat:

   **a. `Monitor[Device]` wajib dikirim walau kosong.**
   Model `Monitor` di ZM 1.38 memvalidasi kolom `Device` dengan regex
   `#^(/dev/[\w/.\-]+)?$#` dan `allowEmpty => true`. Namun `allowEmpty` hanya
   berlaku bila **kuncinya ada** di data. Kalau `Monitor[Device]` tidak dikirim
   sama sekali, nilai `NULL` dilewatkan ke regex dan validasi **GAGAL**, walau
   kolomnya `NOT NULL DEFAULT ''`. Jadi selalu kirim `Monitor[Device]=` (string kosong).

   **b. Sukses ditentukan oleh `message`, bukan status HTTP.**
   `POST /monitors.json` membalas **HTTP 200 untuk dua kondisi berbeda**:

   ```json
   {"message":"Saved"}                                  <- berhasil
   {"message":{"Device":["Invalid device path. ..."]}}  <- GAGAL validasi
   ```

   Kode yang hanya memeriksa `status_code == 200` akan melaporkan sukses palsu.
   Karena itu semua jalur memakai `zm_post_monitor()` di `app.py`, yang membaca
   isi respons dan meneruskan pesan asli ZoneMinder ke UI.

   **Cek cepat bahwa perbaikan aktif:**

   ```bash
   docker exec camera-dashboard python /app/error_path_test.py   # jalur error
   docker exec camera-dashboard python /app/e2e_api_test.py      # tambah/edit/hapus
   docker exec camera-dashboard python /app/burst_api_test.py    # burst massal
   ```

   Semua harus berakhir dengan `SEMUA PEMERIKSAAN ... LULUS`.

   > Setelah mengubah `app.py`, **restart** container dashboard:
   > `docker compose restart ui-interface`. Tanpa restart, kode lama masih
   > berjalan di memori dan bug tetap muncul.

6. **Monitor yang dihapus masih terlihat di API ZoneMinder:**
   Itu normal. ZM memakai **soft delete**: baris tidak dibuang, hanya ditandai
   `Deleted=1`, dan daftar monitor di konsol menyembunyikannya. Untuk
   membersihkan baris sisa monitor uji:

   ```bash
   bash scripts/dbclean.sh
   ```

7. **Kamera berjalan lebih cepat dari target (mis. 15–25 fps padahal target 10 fps):**
   Kolom `MaxFPS` di tabel `Monitors` masih `NULL`. ZoneMinder membedakan dua
   batas laju yang mudah tertukar:

   | Kolom | Yang dibatasi | Komponen |
   |---|---|---|
   | `AnalysisFPSLimit` | laju **analisa motion** | `zma` |
   | `MaxFPS` | laju **capture** | `zmc` |

   Selama `MaxFPS` `NULL`, `zmc` menelan stream secepat laju asli kamera.
   Terukur di server ini (kamera 25 fps, target 10 fps):

   ```text
   MaxFPS = NULL  ->  CaptureFPS 14.98 (CAM_SQ_01), 25.10 (CAM_SQ_02)
   MaxFPS = 10    ->  CaptureFPS 10.00 (keduanya)
   ```

   Pembatasan dilakukan di sisi capture, jadi CPU dan I/O ikut turun — ini yang
   membuat target 60 kamera @ 10 fps masuk akal. Dashboard sekarang mengirim
   `MaxFPS` dan `AlarmMaxFPS` otomatis untuk setiap kamera baru
   (`CAPTURE_FPS_DEFAULT` di `html_dashboard/rtsp_path.py`).

   **Catatan penting:** komentar lama di `rtsp_path.py` menyatakan `MaxFPS`
   sengaja tidak dikirim "karena membuat zmc membuang frame". Itu **keliru** dan
   sudah dikoreksi. Untuk kamera yang terlanjur dibuat sebelum perbaikan:

   ```bash
   bash scripts/dbq.sh "UPDATE Monitors SET MaxFPS=10, AlarmMaxFPS=10 WHERE MaxFPS IS NULL"
   docker exec zoneminder zmdc.pl restart zmc -m <IdMonitor>
   ```

8. **`Option timeout not recognized by ffmpeg` di log `zmc`:**
   **Aman, kosmetik.** `zmc` 1.38 punya daftar opsi ffmpeg internal sendiri
   (`thread_count`, `probesize`, `reorder_queue_size`, `buffer_size`,
   `rtsp_transport`, …). `timeout` tidak ada di daftar itu sehingga `zmc`
   memperingatkan — tetapi nilainya **tetap diteruskan** ke `av_dict` dan ffmpeg
   7.1 memakainya sebagai timeout socket RTSP. Buktinya:

   ```bash
   docker exec zoneminder ffmpeg -hide_banner -rtsp_transport tcp \
       -timeout 5000000 -i rtsp://10.121.10.145:554/x -t 1 -f null -
   # -> mencoba koneksi sungguhan (kamera membalas 401), bukan "option not found"
   ```

   `scripts/verify_monitors.sh` sengaja **tidak** menghitung peringatan ini;
   kalau dihitung, pemeriksaan akan selalu gagal untuk konfigurasi yang sehat.

---

## 🔄 Migrasi ZoneMinder 1.36.32 → 1.38.6 (image resmi)

Dilakukan pada 2026-11-18. Ringkasnya: **bukan ganti tag**, tapi pindah
arsitektur. Versi lama memakai image turunan `pppasantos/zoneminder` (Ubuntu
18.04 + MySQL 5.7 **di dalam** container), versi baru memakai image resmi
`zoneminder/zoneminder:1.38.6` (Debian) yang **mewajibkan database eksternal**.

### Apa yang berubah

| Hal | Sebelum (1.36.32) | Sesudah (1.38.6) |
| :--- | :--- | :--- |
| Image ZM | `zoneminder_tuned:latest` (turunan `pppasantos/zoneminder`) | `zoneminder_tuned:1.38.6` (turunan `zoneminder/zoneminder:1.38.6`) |
| Database | mysqld di dalam container ZM, volume `zoneminder_mysql` | service `db` = `mariadb:11.8`, volume `zm_db_data` |
| Path event | **efektif** `/var/cache/zoneminder/events` (volume anonim), walau compose menamai `/var/lib/zoneminder/events` | `/var/cache/zoneminder` (volume `zm_cache`) — path benar-benar cocok |
| Log ZM | volume anonim | volume `zm_logs` (`/var/log/zm`) |
| Entrypoint | `entrypoint.sh` (bash) | s6-overlay (butuh tmpfs `/run` dengan `exec`) |
| Kredensial DB | tidak ada (DB lokal tanpa password aplikasi) | docker secret `secrets/zm_db_pass.txt` → `ZM_DB_PASS_FILE` |
| Tuning MySQL | `zz-zm-tuning.cnf` di image ZM | `zm-conf/db-tuning.cnf` di service `db` |
| `zm-root.conf` | dipakai (ZM 1.36 memancarkan URL `/zm/` dari root) | **dihapus** — image resmi sudah `RedirectMatch ^/$ /zm/` di `zm-docker.conf` |
| go2rtc | tidak ada | ada di `/zm/go2rtc/`; **diblokir 404 di `:443`** karena API-nya tanpa login |
| Tag | `latest` (bergerak) | **pin eksplisit** `1.38.6` (bukan `latest`, bukan `-es`) |

### Langkah yang dijalankan (ringkas, bisa diulang)

```bash
# 1. Backup — WAJIB, skema 1.38 tidak bisa diturunkan oleh kode 1.36
docker exec zoneminder mysqldump --single-transaction --routines --triggers zm > backups/zm_pre_138.sql
docker tag zoneminder_tuned:latest zoneminder_tuned:rollback-13632

# 2. Database baru + import dump
docker compose up -d db
docker cp scripts/_db_root.sh zm_db:/tmp/dbroot.sh
docker exec -i zm_db sh /tmp/dbroot.sh --default-character-set=utf8mb4 zm < backups/zm_pre_138.sql

# 3. ZoneMinder baru (otomatis menjalankan zmupdate.pl 1.36.32 -> 1.38.6)
docker compose up -d

# 4. Verifikasi
docker compose logs zoneminder | grep -i "database upgrade"
docker exec cctv_checker_service python3 /tmp/api_parity.py   # uji parity API (lihat scripts/_api_parity.py)
```

### Verifikasi yang sudah lulus

| Uji | Hasil |
| :--- | :--- |
| Upgrade skema `zmupdate.pl` | `Database upgrade to version 1.38.6 successful` (1.36.32 → 1.37.76 … → 1.38.6) |
| Tuning MariaDB | pool **2 GB**, `max_connections` **500**, `transaction_isolation` **READ-COMMITTED**, TZ `+07:00`, `utf8mb4` |
| Tuning Apache | `apache-limit.conf` terpasang (644), `apache2ctl -t` → **Syntax OK**, 19 proses prefork |
| `GET /zm/api/monitors.json` | **200**, 2 monitor, field `Function`/`Enabled` utuh |
| `POST /zm/api/monitors/{id}.json` (`Monitor[Function]`) | **200** `{"message":"Saved"}` — auto-switch checker aman, tanpa drift state |
| `POST /zm/api/host/login.json` | **200** + `access_token` (dipakai dashboard & checker) |
| Capture | `Monitor_Status`: kedua monitor `Connected`, **10 fps** |
| Dashboard `:9443` | `/login` **200**, `/zm/api/*` **401** (auth ZM tetap aktif) |
| go2rtc publik | `https://<host>/zm/go2rtc/...` → **404 dari Caddy** (tidak sampai Apache) |
| Jejak MQTT | tetap **nol** di config aktif (hanya tersisa di riwayat git) |

### Perbaikan sumber kamera setelah migrasi (Method 1.36 → 1.38)

Setelah dump 1.36 diimpor, monitor masih membawa setelan sumber versi lama.
Gejalanya di log ZoneMinder (`zmc_mN`, level **WAR**):

```
Option rtsp_transport not recognized by ffmpeg   zm_ffmpeg_camera.cpp 574
Unknown method (rtsp)                            zm_ffmpeg_camera.cpp 315
```

Penyebabnya: skema 1.36 menyimpan `Monitors.Method = 'rtsp'` (nilai tipe sumber
**Remote** versi lama) dan menaruh transport di `Monitors.Options`. Di 1.38,
untuk tipe sumber **Ffmpeg**, zmc sendiri yang menerjemahkan `Method` menjadi
opsi transport ffmpeg — terverifikasi dari string binary `/usr/bin/zmc`:

| `Monitor.Method` | Opsi ffmpeg yang dipasang zmc |
| :--- | :--- |
| `rtpRtsp` | `rtsp_transport=tcp` |
| `rtpUni` | `rtsp_transport=udp` |
| `rtpMulti` | `rtsp_transport=udp_multicast` |
| `rtpRtspHttp` | `rtsp_transport=http` |
| selain itu | `Unknown method (<nilai>)` — transport **tidak** disetel |

Karena transport sudah diurus `Method`, sisa `rtsp_transport=...` di
`Monitor[Options]` diteruskan apa adanya ke ffmpeg sebagai opsi level format
(padahal itu opsi demuxer RTSP) sehingga muncul peringatan kedua.

Perbaikan (idempoten, aman diulang):

```bash
DRY_RUN=1 bash scripts/fix_monitor_source_138.sh   # lihat rencana dulu
bash scripts/fix_monitor_source_138.sh             # terapkan + restart zmc
RESTART_ALL=1 bash scripts/fix_monitor_source_138.sh  # hanya restart proses zmc/zma
```

Skrip ini: mengganti `Method` yang tidak dikenal menjadi `rtpRtsp` (TCP), membuang
token `rtsp_transport=...` dari `Options`, lalu me-restart `zmc`/`zma` monitor
yang berubah. Kode dashboard/checker juga sudah tidak lagi menulis `Method=rtsp`
(lihat `ZM_FFMPEG_METHOD` di `html_dashboard/app.py`), jadi kamera baru tidak
akan menghasilkan peringatan ini lagi.

> Catatan: `zmc` hanya membaca konfigurasi monitor saat start. Mengubah
> database tanpa restart membuat proses lama tetap memakai `Method` lama —
> karena itu restart adalah bagian wajib dari perbaikan.

### Rollback (kalau 1.38 bermasalah)

```bash
docker compose down                       # JANGAN pakai -v
cp backups/docker-compose-1.36.yml docker-compose.yml
docker tag zoneminder_tuned:rollback-13632 zoneminder_tuned:latest
cp backups/Dockerfile-1.36 zm-conf/Dockerfile          # agar build tidak memakai base 1.38
cp backups/mysql-tuning-1.36.cnf zm-conf/mysql-tuning.cnf
docker compose up -d --no-build           # container lama memakai DB-nya sendiri
# Volume zoneminder_mysql TIDAK ikut dimigrasi (migrasi lewat dump), jadi
# datanya masih skema 1.36 asli. Kalau volume itu hilang, pulihkan dari dump:
#   docker exec -i zoneminder mysql zm < backups/zm_pre_138.sql
```

> **Penting:** begitu `zmupdate.pl` menaikkan skema ke 1.38, container 1.36
> hanya mau jalan dengan database yang **dipulihkan dari dump** di atas.
> Volume lama (`zoneminder_mysql`, `zoneminder_events`, `zoneminder_images`)
> sengaja masih dideklarasikan di `docker-compose.yml` agar tidak terhapus.
