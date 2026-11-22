#!/bin/bash
# =============================================================================
# Menjalankan SQL ke container zm_db sebagai root.
#
# Kenapa skrip ini ada:
#   Kombinasi cmd.exe + Git Bash sering merusak quoting pada pola
#   `docker exec ... sh -c 'mariadb -p$(cat /run/secrets/...)'`, dan MSYS
#   mengubah "/run/secrets/..." menjadi "C:/Program Files/Git/run/secrets/...".
#   Skrip ini menyelesaikan dua masalah itu:
#     1. MSYS_NO_PATHCONV=1 agar path di dalam container tidak diterjemahkan.
#     2. Password dibaca SEKALI ke variabel host, lalu diteruskan sebagai argumen.
#
# Pemakaian (dari Git Bash, di root repo):
#   bash scripts/dbq.sh "SELECT Id,Name,Path FROM Monitors"
#
# Password tidak ditulis ke disk dan tidak masuk riwayat shell sebagai literal.
# =============================================================================
set -uo pipefail

SQL="${1:?SQL wajib diisi: bash scripts/dbq.sh \"SELECT ...\"}"

export MSYS_NO_PATHCONV=1

if ! docker inspect -f '{{.State.Running}}' zm_db 2>/dev/null | grep -q true; then
  echo "GAGAL: container zm_db tidak berjalan." >&2
  exit 1
fi

DB_ROOT_PASS="$(docker exec zm_db cat /run/secrets/mariadb_root_pass)"

exec docker exec zm_db mariadb -uroot -p"$DB_ROOT_PASS" zm -e "$SQL"
