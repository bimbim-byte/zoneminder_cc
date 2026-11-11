#!/usr/bin/env bash
# ==============================================================================
# Script: preflight.sh
# Deskripsi: Memeriksa kesiapan instalasi SEBELUM `docker compose up`.
#
# Hanya membaca (read-only) — tidak mengubah apa pun. Jalankan dari root repo:
#     bash scripts/preflight.sh
# ==============================================================================

set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR" || exit 1

FAIL=0

pass() { printf '  [ OK ]   %s\n' "$1"; }
warn() { printf '  [WARN]   %s\n' "$1"; }
fail() { printf '  [GAGAL]  %s\n' "$1"; FAIL=$((FAIL + 1)); }

echo "========================================================"
echo " Pemeriksaan Kesiapan Instalasi (Pre-flight)"
echo " Lokasi: $REPO_DIR"
echo "========================================================"

# ---------------------------------------------------------------- 1. Docker
echo
echo "[1/5] Docker & Docker Compose"
if command -v docker >/dev/null 2>&1; then
    pass "docker ditemukan ($(docker --version 2>/dev/null | cut -d, -f1))"
else
    fail "docker tidak ditemukan di PATH. Pasang Docker Desktop lalu buka WSL ulang."
fi

if docker info >/dev/null 2>&1; then
    pass "daemon Docker berjalan"
else
    fail "daemon Docker tidak bisa dihubungi. Buka Docker Desktop dan tunggu sampai status 'Running'."
fi

if docker compose version >/dev/null 2>&1; then
    pass "docker compose v2 tersedia"
else
    fail "plugin 'docker compose' tidak tersedia (butuh Compose v2)."
fi

# ---------------------------------------------------------------- 2. .env
echo
echo "[2/5] File konfigurasi .env"
if [ -f .env ]; then
    pass "file .env ada"

    # Muat tanpa mengeksekusi konten berbahaya. `tr -d` membuang CR
    # agar file .env yang tersimpan dengan akhir baris Windows tetap terbaca.
    ZM_USER_VAL="$(grep -E '^ZM_USER=' .env | tail -1 | cut -d= -f2- | tr -d '\r' | sed 's/[[:space:]]*$//' || true)"
    ZM_PASS_VAL="$(grep -E '^ZM_PASS=' .env | tail -1 | cut -d= -f2- | tr -d '\r' | sed 's/[[:space:]]*$//' || true)"

    if [ -z "${ZM_USER_VAL:-}" ]; then
        fail "ZM_USER kosong di .env"
    else
        pass "ZM_USER terisi ('$ZM_USER_VAL')"
    fi

    if [ -z "${ZM_PASS_VAL:-}" ]; then
        fail "ZM_PASS kosong di .env"
    elif [ "$ZM_PASS_VAL" = "admin" ]; then
        warn "ZM_PASS masih 'admin' (default). Ganti sebelum dipakai di jaringan nyata."
    else
        pass "ZM_PASS terisi (panjang ${#ZM_PASS_VAL} karakter)"
    fi
else
    if [ -f .env.example ]; then
        fail "file .env BELUM ADA. Jalankan: cp .env.example .env"
    else
        fail "file .env DAN .env.example sama-sama tidak ada."
    fi
fi

# ---------------------------------------------------------------- 3. SSL
echo
echo "[3/5] Sertifikat SSL untuk Caddy"
if [ -f caddy/certs/cert.pem ] && [ -f caddy/certs/key.pem ]; then
    pass "cert.pem & key.pem tersedia"

    if command -v openssl >/dev/null 2>&1; then
        EXPIRY="$(openssl x509 -enddate -noout -in caddy/certs/cert.pem 2>/dev/null | cut -d= -f2)"
        if [ -n "$EXPIRY" ]; then
            if openssl x509 -checkend 0 -noout -in caddy/certs/cert.pem >/dev/null 2>&1; then
                pass "sertifikat masih berlaku (sampai: $EXPIRY)"
            else
                fail "sertifikat sudah KEDALUWARSA ($EXPIRY). Jalankan ulang scripts/renew_ssl.sh"
            fi
        fi
    else
        warn "openssl tidak tersedia — masa berlaku sertifikat tidak diperiksa."
    fi
else
    fail "caddy/certs/cert.pem atau key.pem tidak ada. Jalankan: bash scripts/renew_ssl.sh"
fi

# ---------------------------------------------------------------- 4. Port
echo
echo "[4/5] Ketersediaan port (80, 443, 8080, 8082)"
if command -v ss >/dev/null 2>&1; then
    # Port yang dipakai kontainer stack ini sendiri BUKAN masalah —
    # itu justru tanda stack sudah berjalan. Hanya proses LAIN yang dilaporkan.
    OWN_CONTAINERS="$(docker ps --format '{{.Names}}' 2>/dev/null | grep -E '^(caddy_proxy|zoneminder|camera-dashboard)$' || true)"
    for P in 80 443 8080 8082; do
        if ss -tln 2>/dev/null | grep -qE "[:.]${P}[[:space:]]"; then
            if [ -n "$OWN_CONTAINERS" ]; then
                warn "port $P sedang dipakai — kemungkinan oleh stack ini sendiri (sedang berjalan)."
            else
                warn "port $P sudah dipakai proses lain — ubah di .env atau hentikan prosesnya."
            fi
        else
            pass "port $P bebas"
        fi
    done
else
    warn "'ss' tidak tersedia — pemeriksaan port dilewati."
fi

# ---------------------------------------------------------------- 5. Berkas
echo
echo "[5/5] Berkas penting"
for F in docker-compose.yml caddy/Caddyfile mosquitto.conf; do
    if [ -f "$F" ]; then
        pass "$F ada"
    else
        fail "$F tidak ditemukan"
    fi
done

# grep dengan -x (baris cocok persis) dan toleransi CR agar tetap benar
# walau .gitignore tersimpan dengan akhir baris Windows.
if grep -qxE '[[:space:]]*\.env[[:space:]]*' .gitignore 2>/dev/null; then
    pass ".env terlindungi oleh .gitignore (tidak akan ter-commit)"
else
    warn ".env TIDAK ada di .gitignore — risiko kredensial ikut ter-commit!"
fi

# ---------------------------------------------------------------- Ringkasan
echo
echo "========================================================"
if [ "$FAIL" -eq 0 ]; then
    echo " HASIL: SIAP. Lanjutkan dengan:  docker compose up -d"
else
    echo " HASIL: $FAIL masalah perlu diperbaiki lebih dulu."
    echo " Perbaiki poin [GAGAL] di atas, lalu jalankan skrip ini lagi."
fi
echo "========================================================"

exit "$FAIL"
