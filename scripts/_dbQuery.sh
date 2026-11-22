#!/bin/sh
# =============================================================================
# Wrapper query database ZoneMinder (dipakai oleh skrip tuning & diagnosa)
# =============================================================================
# Pemakaian (dari root repo, Git Bash / WSL / Linux):
#     sh scripts/_dbQuery.sh <file.sql>        -> keluaran tabel (mudah dibaca)
#     sh scripts/_dbQuery.sh -r <file.sql>     -> keluaran mentah, tab-separated
#
# Kenapa wrapper ini ada:
#   Password DB hanya tersimpan di docker secret. Menjalankan
#   `docker exec ... sh -c 'export MYSQL_PWD=$(cat ...)'` gagal di beberapa
#   kombinasi shell (msys mengutip ulang, sehingga `$(cat` menjadi literal dan
#   muncul "Unterminated quoted string"). Karena itu password dibaca SEKALI di
#   dalam container lalu ditulis ke /tmp/.dbpw (tanpa newline, mode 600), dan
#   query berikutnya cukup memakai --defaults-extra-file.
#
# File password itu berada di /tmp container DB (sementara, hanya root
# container yang bisa membacanya) dan hilang saat container dibuat ulang.
#
# Catatan: untuk skrip di dalam container ini SUDAH BOLEH berisi potongan shell
# yang saling mengutip, karena file ditulis lewat heredoc terpisah -- bukan
# dilempar sebagai argumen `sh -c` dari host.
# =============================================================================

set -eu

DB_CONTAINER="${DB_CONTAINER:-zm_db}"
ZM_DB="${ZM_DB:-zm}"
ZM_DB_USER="${ZM_DB_USER:-zmuser}"

RAW=0
if [ "${1:-}" = "-r" ]; then
  RAW=1
  shift
fi

SQLFILE="${1:-}"
if [ -z "$SQLFILE" ] || [ ! -f "$SQLFILE" ]; then
  echo "GAGAL: file SQL tidak ditemukan: ${SQLFILE:-<kosong>}" >&2
  echo "       Pemakaian: sh scripts/_dbQuery.sh [-r] <file.sql>" >&2
  exit 1
fi

if ! docker inspect -f '{{.State.Running}}' "$DB_CONTAINER" >/dev/null 2>&1; then
  echo "GAGAL: container '$DB_CONTAINER' tidak berjalan." >&2
  exit 1
fi

# Siapkan kredensial di dalam container. Idempoten: /tmp/.dbpw selalu
# ditulis ulang dari secret supaya rotasi password ikut terbaca.
#
# /tmp/.dbpw HARUS berupa file opsi my.cnf ("[client]" + "password=..."),
# bukan password polos: karena namanya seperti file konfigurasi, MariaDB
# memperlakukannya sebagai option file. Isi polos ditolak dengan
#   "Found option without preceding group in config file".
#
# Perintah pendukung ditulis ke skrip sementara lalu disalin via `docker cp`.
# Ini menghindari pola `docker exec sh -c 'export P=$(cat ...)'` yang sering
# rusak karena quoting shell host (msys mengutip ulang).
# MSYS_NO_PATHCONV juga harus aktif saat docker cp / docker exec dipanggil.
set MSYS_NO_PATHCONV=1
export MSYS_NO_PATHCONV

# Path sementara harus RELATIF: Docker Desktop di Windows tidak mengenali
# path MSYS absolut seperti "/tmp/..." (gagal "GetFileAttributesEx E:\tmp").
MKTMP="${TMPDIR:-.}/zm_mkcred.$$"
echo "MKTMP=$MKTMP" >&2
cat > "$MKTMP" <<'CRED_EOF'
awk 'NR==1 { sub(/\r/, "" ) } { print }' /run/secrets/zm_db_pass > /dev/null 2>&1
{
  printf '[client]\nuser=zmuser\npassword='
  tr -d '\r\n' < /run/secrets/zm_db_pass
  printf '\n'
} > /tmp/.dbpw
chmod 600 /tmp/.dbpw
CRED_EOF

docker cp "$MKTMP" "$DB_CONTAINER":/tmp/.zm_mkcred.sh >/dev/null
rm -f "$MKTMP"
docker exec "$DB_CONTAINER" sh /tmp/.zm_mkcred.sh

# PENTING (Windows/Git Bash): setiap argumen yang diawali "/" diubah menjadi
# path Windows oleh MSYS (mis. "sh" -> "C:/Program Files/Git/sh", "/tmp/x" ->
# "C:/Users/.../Temp/x"), sehingga perintah gagal dengan "cannot open ...".
# set MSYS_NO_PATHCONV=1 mematikan konversi itu untuk seluruh blok ini.
set MSYS_NO_PATHCONV=1
export MSYS_NO_PATHCONV

if [ "$RAW" = "1" ]; then
  docker exec -i "$DB_CONTAINER" sh -c \
    "exec mariadb --defaults-extra-file=/tmp/.dbpw -u$ZM_DB_USER -B $ZM_DB" < "$SQLFILE"
else
  docker exec -i "$DB_CONTAINER" sh -c \
    "exec mariadb --defaults-extra-file=/tmp/.dbpw -u$ZM_DB_USER -B -t $ZM_DB" < "$SQLFILE"
fi
