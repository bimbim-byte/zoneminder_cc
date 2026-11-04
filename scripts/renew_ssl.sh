#!/usr/bin/env bash
# ==============================================================================
# Script: renew_ssl.sh
# Deskripsi: Otomasi pembaruan sertifikat SSL (Certbot / OpenSSL) dan
#            reload kontainer Caddy tanpa downtime.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
CERT_DIR="${BASE_DIR}/caddy/certs"

# Konfigurasi Domain / IP Anda
DOMAIN="${1:-localhost}"
CONTAINER_NAME="caddy_proxy"

echo "========================================================"
echo "[*] Menjalankan Pemeriksaan & Pembaruan Sertifikat SSL"
echo "[*] Target Host : ${DOMAIN}"
echo "[*] Direktori   : ${CERT_DIR}"
echo "========================================================"

mkdir -p "${CERT_DIR}"

# 1. Pengecekan Certbot jika menggunakan domain resmi publik
if command -v certbot &> /dev/null && [ -d "/etc/letsencrypt/live/${DOMAIN}" ]; then
    echo "[*] Mendeteksi Certbot Let's Encrypt. Menjalankan 'certbot renew'..."
    certbot renew --quiet --no-self-upgrade

    echo "[*] Menyalin sertifikat terbaru ke folder caddy/certs..."
    cp -L "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" "${CERT_DIR}/cert.pem"
    cp -L "/etc/letsencrypt/live/${DOMAIN}/privkey.pem" "${CERT_DIR}/key.pem"
    chmod 644 "${CERT_DIR}/cert.pem"
    chmod 600 "${CERT_DIR}/key.pem"
    echo "[+] Sertifikat Let's Encrypt berhasil diperbarui."

else
    # 2. Alternatif pembuatan / pembaruan sertifikat OpenSSL mandiri
    echo "[*] Menggunakan OpenSSL untuk membuat/memperbarui sertifikat (Masa berlaku 365 hari)..."
    
    if [[ "${DOMAIN}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        SAN_EXT="subjectAltName=IP:${DOMAIN},IP:127.0.0.1,DNS:localhost"
    else
        SAN_EXT="subjectAltName=DNS:${DOMAIN},DNS:*.${DOMAIN},DNS:localhost,IP:127.0.0.1,IP:::1"
    fi

    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout "${CERT_DIR}/key.pem" \
        -out "${CERT_DIR}/cert.pem" \
        -subj "/C=ID/ST=DKI Jakarta/L=Jakarta/O=Kementerian Ketenagakerjaan/OU=IT/CN=${DOMAIN}" \
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
