# Split ZoneMinder ke root, dashboard ke port tersembunyi + login & kredensial

_Written 2026-11-12_

# Rencana: ZoneMinder di root, Dashboard di port tersembunyi, Login + Manajemen Kredensial

## Tujuan

Tujuh perubahan, semuanya terverifikasi terhadap kondisi repo saat ini:

1. **`https://localhost/` → ZoneMinder**, bukan portal. Redirect `/` ke `/zm`.
2. **Semua halaman non-ZoneMinder pindah ke port terpisah** (`https://localhost:XXXX`), tidak terlihat dari user root.
3. **Sistem login** untuk port XXXX: pertama kali `admin`/`admin`, ada menu ubah password, dan field **hint** yang tampil di halaman login.
4. **Branding dashboard**: link ZoneMinder di-highlight + tersedia di setiap halaman.
5. **Hapus `wall.html` + `wall_view.html` + semua container/route/API terkait.**
6. **Halaman pengaturan kredensial ZM** — simpan `ZM_USER`/`ZM_PASS` dari UI, bukan hardcode di `.env`.
7. Konsekuensi dari (6): kredensial ZM yang tersimpan di disk **terenkripsi**, karena `data/` sebelumnya bocor plaintext lewat `/api/config`.

---

## Kondisi Awal Terverifikasi (bukti)

| Aspek | Fakta | Sumber |
|---|---|---|
| Port bind | `"${DASHBOARD_PORT:-8080}:8080"` → bind `0.0.0.0` | `docker-compose.yml:74` |
| Port bind ZM | `"${ZONEMINDER_PORT:-8082}:80"` → bind `0.0.0.0` | `docker-compose.yml:52` |
| Routing | `handle /zm*` → zoneminder, `handle {}` → ui-interface | `caddy/Caddyfile:8,17` |
| **Caddy tidak punya sesi `:8080`** | Hanya blok `:443` | `caddy/Caddyfile` — terbukti `curl -sk https://localhost:8080` akan gagal |
| Kebocoran kredensial | `GET /api/config` → `{"zm_user":"admin","zm_pass":"P@ssw0rd"}` | live probe, `app.py:67-79` |
| CORS terbuka | `origins:"*"`, `supports_credentials=True` | `app.py:8` |
| Pemakai `/api/config` | **hanya** `zoneminder.html:512` | grep seluruh repo |
| Wall surface | `/wall` (`app.py:655`), `/wall/view` (`app.py:659`), `/api/cameras/wall` (`app.py:564`), `/api/cameras/stream/<id>` (`app.py:606`), 2 HTML, 1 kartu di `index.html:187` | grep |
| Kartu portal | 6 kartu, Wall = kartu ke-6 | `index.html:187-197` |
| `camera_functions.json` | 50 entri, dipakai fitur **bulk-function** (bukan wall) | `app.py:672` |
| ZM auth | via cookie `ZMSESSID` (HTTP) + fallback `access_token` | `app.py:385-420` |
| `.env` kunci | identik dengan `.env.example` | diff key-set |

**Keputusan desain yang sudah ditetapkan oleh pemilik repo:**
- Username ZM **tetap** `admin` ke depannya; hanya password yang akan berubah.
- Password **awal** ZM adalah `admin` (bukan `P@ssw0rd` — itu masih default di `.env` sekarang dan akan diganti).

---

## Berkas yang Akan Disentuh

**Dibuat baru:**
- `html_dashboard/auth.py` — modul login, hash password, penyimpanan terenkripsi, sesi
- `html_dashboard/login.html` — form login + tampilan hint
- `html_dashboard/settings.html` — ubah password dashboard + simpan kredensial ZM
- `html_dashboard/token_crypto.py` — enkripsi kredensial ZM at-rest

**Dimodifikasi:**
- `caddy/Caddyfile` — tambah blok sesi dashboard di port terpisah, root jadi ZM
- `docker-compose.yml` — expose port dashboard via Caddy, hapus bila ada referensi wall
- `html_dashboard/app.py` — hapus route wall, tambah route login/settings, pindah `/api/config`, tambah auth guard
- `html_dashboard/index.html` — hapus kartu Wall, highlight link ZM, tambah link ZM di header
- `html_dashboard/zoneminder.html` — ambil kredensial dari sesi, bukan `/api/config`
- `html_dashboard/add_camera.html`, `burst.html`, `log_display.html` — tambah header link ZM + logout
- `.env.example` — dokumentasikan kunci enkripsi + port dashboard
- `README.md` + `PANDUAN_PENGGUNAAN.md` — URL baru, alur login, alur ganti password

**Dihapus:**
- `html_dashboard/wall.html`
- `html_dashboard/wall_view.html`

**Catatan:** `data/` sekarang akan menyimpan kredensial ZM terenkripsi (`.gitignore` sudah menutup `data/*.json` — aman).

---

## Urutan Langkah

### Langkah 1 — Hapus Wall sepenuhnya
- Hapus `html_dashboard/wall.html`, `html_dashboard/wall_view.html`.
- `app.py`: hapus route `wall_picker()` (`:655`), `wall_view()` (`:659`), `api_camera_wall()` (`:564`), `api_camera_stream()` (`:606`).
- `index.html`: hapus kartu ke-6 (baris `187-197`).
- **Pertahankan**: `normalize_monitor()` (`app.py:527`), `get_groups_from_zm()` (`app.py:545`), `api_camera_groups()` (`app.py:545`), `get_all_monitors_cached()` (`app.py:518`), `MONITOR_CACHE`, `zm_session`, `zm_api_get`, `zm_post`. Ini dipakai bulk-function & manajemen kamera — **bukan** bagian wall.
- Verifikasi: `grep -rn "wall" html_dashboard/ docker-compose.yml caddy/` → hanya sisa di komentar non-fungsional.

### Langkah 2 — Root ke ZoneMinder
- `caddy/Caddyfile`: ganti `handle {}` → redirect ke `/zm/`; tambah `redir / /zm/ 302` **sebelum** `handle /zm*`.
- Verifikasi: `curl -sk -o /dev/null -w '%{http_code} %{redirect_url}' https://localhost/` → `302 https://localhost/zm/`.

### Langkah 3 — Sahkan port tersembunyi untuk dashboard
- Pilih port (default **9443**, konfigurabel via `CADDY_DASH_PORT`).
- `caddy/Caddyfile`: tambah blok sesi kedua `:9443` dengan TLS cert yang sama → `reverse_proxy ui-interface:8080`.
- `docker-compose.yml`: `caddy-proxy` expose `"${CADDY_DASH_PORT:-9443}:9443"`.
- **Kunci keamanan**: port dashboard harus **tertutup** oleh blok root `:443`. Uji: `curl -sk https://localhost/zoneminder.html` → harus **404**, bukan halaman dashboard.
  - Ini berarti `handle {}` di `:443` **tidak boleh lagi** meneruskan ke `ui-interface`.
- Verifikasi: `curl -sk https://localhost:9443/` → 200 + halaman login. `curl -sk https://localhost/zoneminder.html` → 404.

### Langkah 4 — Modul auth + penyimpanan kredensial terenkripsi
- Buat `token_crypto.py`: enkripsi simetris memakai kunci dari `.env` (`DASH_SECRET_KEY`). Simpan kredensial ZM di `data/zm_credentials.enc`.
- Buat `auth.py`:
  - Hash password dashboard pakai `werkzeug.security` (sudah tersedia via Flask) — `generate_password_hash` / `check_password_hash`.
  - Simpan di `data/dashboard_auth.json`: `password_hash`, `hint`, `must_change_password` (bool), `created_at`.
  - Seed saat pertama kali: user `admin`, password `admin`, `hint` kosong, `must_change_password: True`.
  - Sesi memakai cookie Flask `session` (perlu `app.secret_key` dari `DASH_SECRET_KEY`).
- Verifikasi: unit check kecil — hash→verify round-trip, file tercipta di jalur yang benar.

### Langkah 5 — Halaman login + hint
- `login.html`: form user/password, **tombol "Lupa password?"** → menampilkan `hint` yang tersimpan (bukan reset password — hanya petunjuk).
- Setelah login sukses dengan `must_change_password: True` → **paksa** redirect ke `/settings` (tidak bisa lewati).
- Route: `GET/POST /login`, `GET /logout`, `GET /api/auth/hint` (mengembalikan hint saja, tidak pernah hash).
- Verifikasi: login `admin`/`admin` → redirect paksa ke settings. Hint tampil. Logout → kembali ke login.

### Langkah 6 — Halaman pengaturan (password dashboard + kredensial ZM)
- `settings.html` dua bagian:
  1. **Ubah password dashboard** — password lama, baru, konfirmasi, + field **hint**. Setelah simpan → `must_change_password = False`.
  2. **Kredensial ZoneMinder** — `ZM_USER` (default `admin`), `ZM_PASS`, tombol **Uji Koneksi** yang benar-benar memanggil `POST /zm/api/host/login.json` dan melaporkan hasilnya.
- Route: `GET/POST /api/settings/dashboard-password`, `GET/POST /api/settings/zm-credentials`, `POST /api/settings/test-zm`.
- **Penting**: `ZM_USER`/`ZM_PASS` sekarang dibaca **runtime dari file terenkripsi**, dengan fallback ke env `ZM_USER`/`ZM_PASS` (agar instalasi lama tetap jalan sebelum user mengisi).
- Verifikasi: simpan kredensial → `docker compose restart ui-interface` → kredensial tetap ada (persisten), bukan hilang saat restart.

### Langkah 7 — Auth guard + tutup kebocoran `/api/config`
- **Hapus** `GET /api/config` (`app.py:67-79`) — akar kebocoran kredensial plaintext.
- `zoneminder.html:512` beralih: tidak lagi `fetch('/api/config')`. Karena browser memanggil ZM langsung (`fetchWithAutoAuth` → `/zm/api/...`), ganti ke pemanggilan **relatif** `/zm/api/host/login.json` supaya lewat Caddy dan tidak butuh kredensial di klien sama sekali.
- Tambah `@app.before_request` guard: semua route kecuali `/login`, `/api/auth/hint`, file statis login → wajib sesi valid.
- Verifikasi: `curl -sk https://localhost:9443/api/config` → 404. `curl -sk https://localhost:9443/api/cameras/groups` tanpa sesi → 401/302.

### Langkah 8 — Branding: highlight + link ZM di semua halaman
- `index.html`: kartu ZoneMinder Web Console di-highlight (border/aksen berbeda, badge "Utama"). Hapus kartu Wall.
- Tambah **header bar konsisten** di `index.html`, `zoneminder.html`, `add_camera.html`, `burst.html`, `log_display.html`, `settings.html`: berisi tombol **"🖥️ Buka ZoneMinder"** (highlight) + **"Logout"**.
- Verifikasi: grep memastikan setiap HTML punya link ke `/zm/`.

### Langkah 9 — Perbarui `.env.example` + dokumentasi
- Tambah `DASH_SECRET_KEY` (dengan catatan generate via `openssl rand -hex 32`), `CADDY_DASH_PORT=9443`.
- `README.md`: URL baru (`https://<IP>:9443` untuk dashboard, `https://<IP>/` untuk ZM), alur login pertama, alur ganti password ZM dua sisi.
- `PANDUAN_PENGGUNAAN.md`: sesuaikan bagian URL & kredensial (baris `75, 78, 186, 313`).
- Verifikasi: tidak ada lagi penyebutan `/wall` di dokumentasi.

### Langkah 10 — Uji end-to-end
- `docker compose build ui-interface && docker compose up -d`
- Rantai uji: root→ZM redirect, dashboard login, paksa ganti password, simpan kredensial ZM, uji koneksi, restart container, kredensial persist, dashboard tetap baca 46 kamera, bulk-function masih jalan, `/api/config` mati, `/wall` 404.
- Jalankan `bash scripts/preflight.sh` untuk sanity instalasi.

---

## Cara Verifikasi Tiap Langkah

| # | Langkah | Perintah / Bukti |
|---|---|---|
| 1 | Wall dihapus | `grep -rn "wall" html_dashboard/` → kosong; `curl -sk https://localhost:9443/wall` → 404 |
| 2 | Root → ZM | `curl -skI https://localhost/` → `302` + `location: /zm/` |
| 3 | Port tersembunyi | `curl -sk https://localhost:9443/` → 200 login; `curl -sk https://localhost/zoneminder.html` → **404** |
| 4 | Crypto/auth | `python -c "import token_crypto; ..."` round-trip; file `data/*.enc` ada & tidak terbaca sebagai plaintext |
| 5 | Login + hint | Login `admin`/`admin` → redirect `/settings`; hint tampil di halaman login |
| 6 | Settings | Simpan → uji koneksi hijau → restart → masih tersimpan |
| 7 | Kebocoran tertutup | `curl -sk https://localhost:9443/api/config` → 404; endpoint lain tanpa sesi → 401/302 |
| 8 | Branding | grep `/zm/` ada di setiap HTML; kartu ZM ter-highlight |
| 9 | Dokumentasi | `grep -rn "wall" README.md PANDUAN_PENGGUNAAN.md` → kosong |
| 10 | E2E | Semua di atas + `docker compose ps` 5 container healthy + `/api/cameras/wall`→404 tapi `/api/cameras/groups` masih 200 |

---

## Risiko & Catatan

1. **ZM di root `:443` + dashboard di `:9443` = dua sesi TLS.** Keduanya memakai cert yang sama dari `caddy/certs/` — tidak perlu cert baru, tapi SAN cert harus mencakup IP host (sudah ditangani `renew_ssl.sh`).
2. **Port 8080 dan 8082 saat ini ter-bind `0.0.0.0`** — artinya jalur bypass ke dashboard masih terbuka meski `:443` sudah ditutup. Untuk "tersembunyi" yang sesungguhnya, kedua mapping port di `docker-compose.yml` perlu dihapus atau di-bind ke `127.0.0.1` saja. **Saya perlukan konfirmasi apakah boleh dihapus**, karena itu menghilangkan fallback tanpa HTTPS yang saat ini terdokumentasi di README.
3. **`must_change_password` memaksa ganti password saat login pertama.** Kalau Anda mau `admin`/`admin` bisa dipakai langsung tanpa paksa ganti, set flag ini `False` — sebutkan saja.
4. **Fallback ke env `ZM_USER`/`ZM_PASS` sengaja dipertahankan** agar instalasi yang sedang jalan tidak langsung rusak saat upgrade. Setelah Anda mengisi kredensial lewat UI, file terenkripsi jadi sumber utama.
5. **`DASH_SECRET_KEY` wajib di-set** sebelum start, karena dipakai untuk `app.secret_key` (sesi) **dan** enkripsi. Kalau kunci berubah, kredensial tersimpan tidak bisa didekripsi dan sesi lama invalid — perlu disimpan aman.
6. **`api_camera_stream()` dihapus bersama wall** — periksa apakah ada konsumen lain. Hasil grep: hanya `wall_view.html:401` yang memanggilnya. Aman.
