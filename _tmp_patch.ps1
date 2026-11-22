$ErrorActionPreference = 'Stop'
$path = 'E:\CodeFile\kemnaker\zoneminder_cc\.env.example'

$old = @(
'# ------------------------------------------------------------------------------',
'# 1b. DATABASE ZONEMINDER (OPSIONAL - hanya untuk scripts/test_db.py)',
'# ------------------------------------------------------------------------------',
'# Skrip diagnostik database TIDAK ikut container; dijalankan manual dari host.',
'# Blok ini sengaja TIDAK dipakai docker-compose, jadi tidak akan membuat',
'# docker compose up gagal walaupun dibiarkan seperti apa adanya.',
'#',
'# Perhatian: user MySQL ZoneMinder (default zmuser) berbeda dari user web',
'# ZoneMinder. Lihat zm-conf/ atau Options > Database untuk nilainya.',
'ZM_DB_HOST=localhost',
'ZM_DB_PORT=3306',
'ZM_DB_NAME=zm',
'# ZM_DB_USER=zmuser',
'# ZM_DB_PASS=ganti_dengan_password_mysql'
) -join "`n"

$new = @(
'# ------------------------------------------------------------------------------',
'# 1b. DATABASE ZONEMINDER (OPSIONAL - HANYA untuk skrip host scripts/test_db.py)',
'# ------------------------------------------------------------------------------',
'# PENTING: blok ini TIDAK dipakai docker-compose. Database produksi mengambil',
'# password dari docker secret (lihat docker-compose.yml):',
'#   secrets/zm_db_pass.txt        -> service db & zoneminder',
'#   secrets/mariadb_root_pass.txt -> service db',
'#',
'# Skrip diagnostik (python scripts/test_db.py) memakai PyMySQL langsung ke DB,',
'# sehingga butuh host+port yang terekspos. Karena port DB produksi sengaja',
'# tidak dipublikasikan, skrip ini biasanya perlu tunnel; jalur DB yang sudah',
'# terbukti dari host adalah:',
'#   bash scripts/dbq.sh "SELECT Id,Name FROM Monitors"',
'#',
'# Nilai contoh di bawah TIDAK sama dengan secret produksi. Isi ulang hanya',
'# bila Anda benar-benar menjalankan scripts/test_db.py dari host.',
'ZM_DB_HOST=localhost',
'ZM_DB_PORT=3306',
'ZM_DB_NAME=zm',
'# ZM_DB_USER=zmuser',
'# ZM_DB_PASS=ganti_sesuai_secrets_zm_db_pass.txt'
) -join "`n"

$text = [IO.File]::ReadAllText($path)
$text = $text -replace "`r`n", "`n"
$text = $text -replace "`r", "`n"

if (-not $text.Contains($old)) { throw 'OLD BLOCK NOT FOUND' }
$count = ([regex]::Matches($text, [regex]::Escape($old))).Count
Write-Output ("occurrences=" + $count)
if ($count -ne 1) { throw 'EXPECTED EXACTLY ONE OCCURRENCE' }

$text = $text.Replace($old, $new)
[IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding($false)))
Write-Output 'patched'
