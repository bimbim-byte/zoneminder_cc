<#
.SYNOPSIS
    Script Pembaruan Sertifikat SSL untuk Caddy di Windows / PowerShell.
.DESCRIPTION
    Menghasilkan sertifikat SSL baru via OpenSSL dan melakukan reload pada kontainer Caddy.
.PARAMETER Domain
    Domain atau IP host (default: localhost).
.PARAMETER ValidDays
    Masa aktif sertifikat dalam hari (default: 365).
#>
param(
    [string]$Domain = "localhost",
    [int]$ValidDays = 365
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BaseDir = Split-Path -Parent $ScriptDir
$CertDir = Join-Path $BaseDir "caddy\certs"

if (-not (Test-Path $CertDir)) {
    New-Item -ItemType Directory -Path $CertDir -Force | Out-Null
}

$CertPath = Join-Path $CertDir "cert.pem"
$KeyPath = Join-Path $CertDir "key.pem"

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "[*] Memperbarui Sertifikat SSL untuk: $Domain" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan

if ($Domain -match '^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$') {
    $San = "subjectAltName=IP:$Domain,IP:127.0.0.1,DNS:localhost"
} else {
    $San = "subjectAltName=DNS:$Domain,DNS:*.$Domain,DNS:localhost,IP:127.0.0.1,IP:::1"
}

# Jalankan OpenSSL dengan ekstensi serverAuth dan basicConstraints=CA:FALSE
openssl req -x509 -nodes -days $ValidDays -newkey rsa:2048 `
    -keyout $KeyPath `
    -out $CertPath `
    -subj "/C=ID/ST=DKI Jakarta/L=Jakarta/O=Kementerian Ketenagakerjaan/CN=$Domain" `
    -addext $San `
    -addext "basicConstraints=CA:FALSE" `
    -addext "keyUsage=critical,digitalSignature,keyEncipherment" `
    -addext "extendedKeyUsage=serverAuth"

if ($LASTEXITCODE -eq 0) {
    Write-Host "[+] Sertifikat SSL berhasil dibuat/diperbarui:" -ForegroundColor Green
    Write-Host "    - Cert : $CertPath" -ForegroundColor Gray
    Write-Host "    - Key  : $KeyPath" -ForegroundColor Gray

    # Reload Caddy Docker
    Write-Host "[*] Melakukan reload pada kontainer Caddy..." -ForegroundColor Yellow
    $caddyRunning = docker ps --format '{{.Names}}' | Select-String -Pattern '^caddy_proxy$'
    if ($caddyRunning) {
        docker exec caddy_proxy caddy reload --config /etc/caddy/Caddyfile
        Write-Host "[✓] Caddy berhasil memuat sertifikat baru tanpa restart!" -ForegroundColor Green
    } else {
        Write-Host "[!] Kontainer caddy_proxy belum berjalan. Sertifikat akan dimuat saat 'docker compose up'." -ForegroundColor Yellow
    }
} else {
    Write-Host "[!] Gagal memperbarui sertifikat dengan OpenSSL." -ForegroundColor Red
}
