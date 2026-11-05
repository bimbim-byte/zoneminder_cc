#!/usr/bin/env bash
# ==============================================================================
# Script: renew_ssl.sh
# Deskripsi: Otomasi pembaruan sertifikat SSL berbasis IP / Domain untuk Caddy
#            dan reload kontainer Caddy tanpa downtime.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
CERT_DIR="${BASE_DIR}/caddy/certs"

# Deteksi IP lokal jika parameter tidak diberikan
DEFAULT_IP="$(hostname -I 2>/dev/null | awk '{print $1}' || echo "127.0.0.1")"
TARGET_HOST="${1:-$DEFAULT_IP}"
CONTAINER_NAME="caddy_proxy"

echo "========================================================"
echo "[*] Menjalankan Pembaruan Sertifikat SSL"
echo "[*] Target Host / IP : ${TARGET_HOST}"
echo "[*] Direktori        : ${CERT_DIR}"
echo "========================================================"

mkdir -p "${CERT_DIR}"

# 1. Pengecekan Certbot jika menggunakan domain resmi publik
if command -v certbot &> /dev/null && [ -d "/etc/letsencrypt/live/${TARGET_HOST}" ]; then
    echo "[*] Mendeteksi Certbot Let's Encrypt. Menjalankan 'certbot renew'..."
    certbot renew --quiet --no-self-upgrade

    echo "[*] Menyalin sertifikat terbaru ke folder caddy/certs..."
    cp -L "/etc/letsencrypt/live/${TARGET_HOST}/fullchain.pem" "${CERT_DIR}/cert.pem"
    cp -L "/etc/letsencrypt/live/${TARGET_HOST}/privkey.pem" "${CERT_DIR}/key.pem"
    chmod 644 "${CERT_DIR}/cert.pem"
    chmod 600 "${CERT_DIR}/key.pem"
    echo "[+] Sertifikat Let's Encrypt berhasil diperbarui."

else
    # 2. Pembuatan / pembaruan sertifikat OpenSSL mandiri dengan SAN IP lengkap
    echo "[*] Menggunakan OpenSSL untuk membuat/memperbarui sertifikat (Masa berlaku 365 hari)..."
    
    if [[ "${TARGET_HOST}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        SAN_EXT="subjectAltName=IP:${TARGET_HOST},IP:127.0.0.1,IP:::1,DNS:localhost"
    else
        SAN_EXT="subjectAltName=DNS:${TARGET_HOST},DNS:*.${TARGET_HOST},IP:127.0.0.1,IP:::1,DNS:localhost"
    fi

    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout "${CERT_DIR}/key.pem" \
        -out "${CERT_DIR}/cert.pem" \
        -subj "/C=ID/ST=Jakarta/L=Jakarta/O=ZoneMinder NVR/OU=Security/CN=${TARGET_HOST}" \
        -addext "${SAN_EXT}" \
        -addext "basicConstraints=CA:FALSE" \
        -addext "keyUsage=critical,digitalSignature,keyEncipherment" \
        -addext "extendedKeyUsage=serverAuth"

    chmod 644 "${CERT_DIR}/cert.pem"
    chmod 600 "${CERT_DIR}/key.pem"
    echo "[+] Sertifikat baru berhasil dibuat di ${CERT_DIR}"
fi

# 3. Reload Caddy tanpa restart (Zero Downtime)
echo "[*] Mengirim sinyal reload ke kontainer Caddy (${CONTAINER_NAME})..."
if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    docker exec "${CONTAINER_NAME}" caddy reload --config /etc/caddy/Caddyfile
    echo "[✓] Caddy berhasil memuat sertifikat SSL baru tanpa memutus koneksi!"
else
    echo "[!] Kontainer '${CONTAINER_NAME}' tidak sedang berjalan. Sertifikat akan aktif saat kontainer dinyalakan."
fi

echo "========================================================"
echo "[✓] Selesai!"
echo "========================================================"
