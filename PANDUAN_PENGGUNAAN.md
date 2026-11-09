# 📖 Panduan Lengkap Penggunaan (Step-by-Step Guide)

Panduan ini ditujukan bagi siapa pun yang baru pertama kali mengunduh atau mengkloning repository ini dan ingin langsung menjalankan sistem **ZoneMinder CCTV Management** dengan mudah melalui **Command Prompt (CMD)** atau **PowerShell**.

---

## ❓ Menjawab Kebingungan: Apakah Harus Mengganti IP Manual?

> **Jawaban Singkat: TIDAK PERLU! Sistem sudah 100% OTOMATIS.**

Anda **TIDAK PERLU** mengedit kode program atau file konfigurasi apa pun untuk mengubah IP. 
- **Caddy Reverse Proxy**: Sudah dikonfigurasi dengan `:443` (otomatis menerima IP apa pun yang mengaksesnya).
- **Web Dashboard & JavaScript**: Menggunakan `window.location.hostname` (otomatis menyesuaikan dengan IP apa pun yang Anda ketik di browser).
- **Skrip Pembuat Sertifikat SSL**: Otomatis mendeteksi alamat IP lokal komputer Anda tanpa perlu Anda ketik manual.

### Lalu apa maksud `<IP_SERVER>` di panduan?
Tulisan `<IP_SERVER>` hanyalah petunjuk alamat yang **Anda ketik di browser** atau **aplikasi HP**:
- Jika membuka dari komputer server ini sendiri: cukup ketik `https://127.0.0.1/` atau `https://localhost/`.
- Jika membuka dari HP / Laptop lain yang terhubung ke WiFi yang sama: ketik alamat IP komputer ini, misalnya `https://192.168.1.50/`.

---

## 🔍 Cara Mengetahui Alamat IP Komputer Anda

Sebelum memulai, Anda bisa mengecek IP komputer Anda sendiri dengan cara:

### Pada Windows (CMD / PowerShell):
1. Buka **Command Prompt** atau **PowerShell**.
2. Ketik perintah:
   ```cmd
   ipconfig
   ```
3. Cari bagian **IPv4 Address** (biasanya berformat `192.168.x.x` atau `10.x.x.x`).  
   *Contoh:* `IPv4 Address. . . . . . . . . . . : 192.168.1.50`

### Pada Linux / WSL Ubuntu:
Ketik perintah:
```bash
hostname -I
```
Angka pertama yang muncul adalah IP lokal Anda.

---

## 🚀 Langkah-demi-Langkah Menjalankan Sistem

Pastikan aplikasi **Docker Desktop** sudah dibuka dan berjalan di komputer Anda.

### Langkah 1: Buka Command Prompt / PowerShell
Buka terminal PowerShell atau CMD, lalu arahkan ke folder proyek:
```cmd
cd E:\CodeFile\kemnaker\zoneminder_cc
```
*(Sesuaikan dengan lokasi folder tempat Anda menyimpan repository ini).*

---

### Langkah 2: Buat Sertifikat SSL (Cukup Dijalankan Sekali di Awal)
Jalankan skrip pembuat sertifikat otomatis yang telah disediakan. Skrip ini akan otomatis mendeteksi IP komputer Anda:

- **Jika Menggunakan Windows (PowerShell):**
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\scripts\renew_ssl.ps1
  ```

- **Jika Menggunakan Linux / WSL Ubuntu:**
  ```bash
  chmod +x ./scripts/renew_ssl.sh
  ./scripts/renew_ssl.sh
  ```

*Output yang diharapkan:*
```text
========================================================
[*] Memperbarui Sertifikat SSL untuk IP/Host: 192.168.1.50
========================================================
[+] Sertifikat SSL berhasil dibuat/diperbarui:
    - Cert : .../caddy/certs/cert.pem
    - Key  : .../caddy/certs/key.pem
```

---

### Langkah 3: Jalankan Sistem dengan Docker Compose
Ketik perintah berikut untuk mendownload image dan menyalakan semua kontainer di latar belakang (*background*):

```cmd
docker compose up -d
```

*Output yang diharapkan:*
```text
[+] Running 5/5
 ✔ Container mosquitto_broker       Started
 ✔ Container zoneminder             Started
 ✔ Container camera-dashboard       Started
 ✔ Container cctv_checker_service   Started
 ✔ Container caddy_proxy            Started
```

> **Catatan:** Pada saat pertama kali dijalankan, tunggu sekitar **1 sampai 2 menit** agar inisialisasi database ZoneMinder selesai sempurna.

---

### Langkah 4: Pastikan Semua Layanan Berjalan Normal
Ketik perintah berikut untuk melihat status kontainer:
```cmd
docker compose ps
```
Pastikan pada kolom **STATUS**, semua kontainer berstatus **`Up`** (bukan *Exited*):
- `caddy_proxy` (Port 80, 443 HTTPS)
- `camera-dashboard` (Port 8080)
- `zoneminder` (Port 8082)
- `mosquitto_broker` (Port 1883, 9001)
- `cctv_checker_service`

---

## 🌐 Cara Membuka Portal di Browser

### 1. Dari Komputer Ini Sendiri:
Buka browser (Google Chrome, Microsoft Edge, atau Mozilla Firefox), lalu ketik di bilah alamat:
```text
https://127.0.0.1/
```
atau:
```text
https://localhost/
```

### 2. Dari HP / Laptop Lain di Jaringan WiFi yang Sama:
Ketik alamat IP komputer server yang Anda dapatkan di langkah awal tadi:
```text
https://192.168.1.50/
```
*(Ganti `192.168.1.50` dengan IP komputer Anda).*

---

## ⚠️ Cara Melewati Peringatan SSL di Browser (Self-Signed Certificate)

Saat pertama kali membuka `https://`, browser akan memunculkan peringatan keamanan seperti:  
`Your connection is not private` (*Koneksi Anda tidak privat*).

**Hal ini 100% normal** karena sertifikat SSL dibuat sendiri (*self-signed*) untuk jaringan lokal, bukan dibeli dari pihak ketiga seperti Verisign/Google.

**Cara melewatinya:**
1. Klik tombol **Advanced** (Lanjutan).
2. Klik tautan **Proceed to 127.0.0.1 (unsafe)** atau **Lanjutkan ke 192.168.x.x (tidak aman)**.
3. Halaman web portal akan langsung terbuka dengan aman!

---

## 🎯 Panduan Menu & Fitur yang Tersedia

Setelah portal terbuka di `https://<IP_ANDA>/`, Anda akan melihat 6 menu utama:

| No | Nama Menu | Fungsi |
| :---: | :--- | :--- |
| **1** | **ZoneMinder Web Console** (`/zm/`) | Membuka antarmuka resmi bawaan ZoneMinder NVR untuk melihat rekaman, live view, dan setting kamera. *(Login default: user `admin`, password `admin`)*. |
| **2** | **Kelola Monitor ZoneMinder** (`/zoneminder.html`) | Mengatur kamera yang sudah ada, mengedit nama/resolusi/fungsi, menyalakan/mematikan kamera (*Quick OFF*), dan mengatur CCTV Health Checker. |
| **3** | **Tambah Kamera Tunggal** (`/add_camera.html`) | Menambahkan 1 kamera baru secara cepat dengan memasukkan alamat RTSP stream kamera. |
| **4** | **Burst Add Massal** (`/burst.html`) | Mendaftarkan puluhan kamera sekaligus cukup dengan *copy-paste* daftar RTSP atau *upload* file Excel (.xlsx). |
| **5** | **Live MQTT Monitor Log** (`/log_display.html`) | Memantau log status kamera hidup/mati secara *real-time*, mengatur jeda waktu pemeriksaan (*delay interval*), dan panduan memasang notifikasi ke HP. |
| **6** | **Wall Dashboard** (`/wall`) | Menampilkan banyak kamera secara grid live. Pilih **seluruh kamera** atau **sebagian group** (bisa lebih dari satu group), lalu atur jumlah kolom, rasio, resolusi, dan FPS. Hanya kamera yang terlihat di layar yang dimuat, sehingga tidak membebani ZoneMinder. |

### Detail Menu 6: Wall Dashboard

**Langkah penggunaan:**
1. Dari portal, klik **Wall Dashboard (Grid Kamera)**, atau buka langsung `https://<IP_ANDA>/wall`.
2. Pilih salah satu opsi:
   - **Seluruh Kamera** — semua kamera yang terdaftar di ZoneMinder.
   - **Berdasarkan Group** — centang satu atau beberapa group sekaligus. Jumlah kamera yang akan tampil langsung terlihat di bagian bawah.
3. Klik **Buka Wall Dashboard**. Halaman grid live akan terbuka.

**Pengaturan di halaman grid:**

| Kontrol | Pilihan | Keterangan |
| :--- | :--- | :--- |
| **Kolom** | Auto, 1–10 | Jumlah kolom grid |
| **Rasio** | 16:9, 4:3, 1:1, 21:9 | Perbandingan sisi tiap kamera |
| **Resolusi** | 240, 320, 480, 640 px, Asli | Ukuran gambar; makin kecil makin ringan |
| **FPS** | 2, 5, 10, 15, Maks | Batas frame per detik; makin kecil makin hemat bandwidth |
| **Stream** | 4, 6, 9, 12, 16 | Jumlah stream yang berjalan bersamaan |

Indikator di kanan atas (`X kamera · live N · antre M`) menunjukkan berapa stream aktif dan berapa yang menunggu.

**Tips untuk 50–100 kamera:**
- Gunakan **Resolusi 240–320 px** dan **FPS 2–5**.
- Biarkan **Stream** di angka **6** (batas aman browser).
- Sortir dengan mengecilkan **Kolom** agar lebih banyak kamera terlihat tanpa membuka terlalu banyak stream.

**Akses langsung lewat URL** (bisa dijadikan *bookmark* atau layar kiosk):
```
https://<IP_ANDA>/wall/view?mode=all              # seluruh kamera
https://<IP_ANDA>/wall/view?mode=groups&groups=3,4 # group 3 dan 4
https://<IP_ANDA>/wall/view?mode=ids&ids=8,10,21   # kamera tertentu
```

---

## 📱 Cara Memasang Notifikasi di HP (Android / iOS)

Agar HP Anda berdering atau memunculkan popup notifikasi saat ada kamera CCTV yang mati:

1. Download aplikasi **MQTT Dash** (di Play Store) atau **IoT MQTT Panel** (di App Store / Play Store).
2. Buka aplikasi dan tambahkan koneksi broker baru:
   - **Name:** `ZoneMinder CCTV Alert`
   - **Address / Server:** Masukkan IP Komputer Anda (misal `192.168.1.50`).
   - **Port:** `1883`
   - **Username & Password:** Kosongkan (*Anonymous*).
3. Klik **Save** dan pastikan status koneksi berubah hijau (*Connected*).
4. Tambahkan tombol/widget baru bertipe **Text / Log**:
   - Masukkan Topic: `cctv/events`
   - Aktifkan centang **"Enable notifications on receive"**.
5. Selesai! Sekarang saat ada kamera yang putus (*OFFLINE*) atau hidup kembali (*ONLINE*), HP Anda akan menerima notifikasi instan.

---

## 🛠️ Perintah-Perintah Penting Command Prompt

Berikut daftar perintah yang sering Anda perlukan:

### 1. Menghentikan Sistem
Jika Anda ingin mematikan seluruh layanan:
```cmd
docker compose down
```

### 2. Menyalakan Kembali Sistem
```cmd
docker compose up -d
```

### 3. Membangun Ulang (*Rebuild*) Setelah Edit Kode
Jika Anda mengubah file Python atau konfigurasi:
```cmd
docker compose up -d --build
```
> Jika Anda mengubah daftar paket di `html_dashboard/requirements.txt` (misal menambah
> `waitress`), rebuild **wajib** dijalankan agar paket ikut terpasang.
> Perubahan file HTML/JS saja cukup di-refresh di browser tanpa rebuild.

### 4. Melihat Log Pemeriksaan Kamera (CCTV Checker)
Untuk memantau apakah checker sedang aktif memeriksa kamera RTSP:
```cmd
docker logs -f cctv_checker_service
```
*(Tekan `Ctrl + C` untuk keluar dari tampilan log).*

### 5. Melihat Log Caddy Reverse Proxy
```cmd
docker logs -f caddy_proxy
```

---

## 🔑 Informasi Akun & Port Default
- **ZoneMinder Login**: Username `admin`, Password `admin`
- **Port HTTPS Web Portal**: `443`
- **Port Mosquitto MQTT Native**: `1883` (untuk aplikasi HP / script Python)
- **Port Mosquitto MQTT WebSocket**: `9001` (untuk browser)
- **Port Alternatif Direct ZoneMinder**: `8082` (contoh: `http://192.168.1.50:8082/zm/`)
- **Port Alternatif Direct Dashboard**: `8080` (contoh: `http://192.168.1.50:8080/`)

