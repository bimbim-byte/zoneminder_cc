<#
.SYNOPSIS
    Script Pembaruan Sertifikat SSL untuk Caddy di Windows / PowerShell.
.DESCRIPTION
    Menghasilkan sertifikat SSL baru via OpenSSL dengan SAN IP dan melakukan reload pada kontainer Caddy.
.PARAMETER HostIP
    Alamat IP atau Domain host (otomatis mendeteksi IP LAN jika tidak diisi).
.PARAMETER ValidDays
    Masa aktif sertifikat dalam hari (default: 365).
#>
param(
    [string]$HostIP = "",
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

# Deteksi IP lokal jika parameter kosong
if (-not $HostIP) {
    try {
        $detected = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -notmatch 'vEthernet|Loopback' -and $_.IPAddress -notmatch '^169\.' } | Select-Object -First 1).IPAddress
        if ($detected) { $HostIP = $detected } else { $HostIP = "127.0.0.1" }
    } catch {
        $HostIP = "127.0.0.1"
    }
}

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "[*] Memperbarui Sertifikat SSL untuk IP/Host: $HostIP" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan

if ($HostIP -match '^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$') {
    $San = "subjectAltName=IP:$HostIP,IP:127.0.0.1,IP:::1,DNS:localhost"
} else {
    $San = "subjectAltName=DNS:$HostIP,DNS:*.$HostIP,IP:127.0.0.1,IP:::1,DNS:localhost"
}

# Pastikan file konfigurasi OpenSSL minimal tersedia untuk Windows
$CnfPath = Join-Path $CertDir "openssl.cnf"
if (-not (Test-Path $CnfPath)) {
    $cnfContent = "[req]`ndistinguished_name = req_distinguished_name`n[req_distinguished_name]"
    Set-Content -Path $CnfPath -Value $cnfContent -Encoding ASCII
}

# Jalankan OpenSSL dengan ekstensi serverAuth dan basicConstraints=CA:FALSE
$openSslArgs = @(
    "req", "-x509", "-nodes", "-days", "$ValidDays", "-newkey", "rsa:2048",
    "-config", "$CnfPath",
    "-keyout", "$KeyPath",
    "-out", "$CertPath",
    "-subj", "/C=ID/ST=Jakarta/L=Jakarta/O=ZoneMinder NVR/OU=Security/CN=$HostIP",
    "-addext", "$San",
    "-addext", "basicConstraints=CA:FALSE",
    "-addext", "keyUsage=critical,digitalSignature,keyEncipherment",
    "-addext", "extendedKeyUsage=serverAuth"
)

& openssl @openSslArgs

if ($LASTEXITCODE -eq 0) {
    Write-Host '[+] Sertifikat SSL berhasil dibuat/diperbarui:' -ForegroundColor Green
    Write-Host "    - Cert : $CertPath" -ForegroundColor Gray
    Write-Host "    - Key  : $KeyPath" -ForegroundColor Gray

    # Reload Caddy Docker
    Write-Host '[*] Melakukan reload pada kontainer Caddy...' -ForegroundColor Yellow
    $caddyRunning = docker ps --format '{{.Names}}' | Select-String -Pattern '^caddy_proxy$'
    if ($caddyRunning) {
        docker exec caddy_proxy caddy reload --config /etc/caddy/Caddyfile
        Write-Host '[✓] Caddy berhasil memuat sertifikat baru tanpa restart!' -ForegroundColor Green
    } else {
        Write-Host '[!] Kontainer caddy_proxy belum berjalan. Sertifikat akan dimuat saat docker compose up.' -ForegroundColor Yellow
    }
} else {
    Write-Host '[!] Gagal memperbarui sertifikat dengan OpenSSL.' -ForegroundColor Red
}
