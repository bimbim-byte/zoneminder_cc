#!/usr/bin/env bash
# =============================================================================
# Perbaiki sumber monitor tipe Ffmpeg hasil impor dari ZoneMinder 1.36
# =============================================================================
# GEJALA DI LOG ZONEMINDER (menu Log, atau tabel Logs):
#   zmc_mN  WAR  Option rtsp_transport not recognized by ffmpeg  zm_ffmpeg_camera.cpp:574
#   zmc_mN  WAR  Unknown method (rtsp)                           zm_ffmpeg_camera.cpp:315
#
# SEBAB:
#   Skema 1.36 menyimpan Monitor.Method='rtsp' (nilai tipe sumber "Remote" versi
#   lama) dan menaruh transport di Monitor.Options. Pada 1.38, untuk tipe sumber
#   Ffmpeg, zmc yang menerjemahkan Method menjadi opsi transport ffmpeg
#   (terverifikasi dari string binary /usr/bin/zmc):
#       rtpRtsp     -> rtsp_transport=tcp
#       rtpUni      -> rtsp_transport=udp
#       rtpMulti    -> rtsp_transport=udp_multicast
#       rtpRtspHttp -> rtsp_transport=http
#       lainnya     -> "Unknown method (<nilai>)", transport tidak disetel
#   Karena transport sudah diurus Method, sisa 'rtsp_transport=...' di
#   Monitor[Options] ikut dikirim ke ffmpeg sebagai opsi level format - padahal
#   opsi itu milik demuxer RTSP - sehingga muncul peringatan kedua.
#
# YANG DILAKUKAN SKRIP INI (idempoten, aman diulang):
#   1. Monitor tipe Ffmpeg/Libvlc dengan Method tidak dikenal -> Method=rtpRtsp.
#      (rtpRtsp = TCP, sama dengan maksud lama 'rtsp_transport=tcp'.)
#   2. Token 'rtsp_transport=...' dibuang dari Monitor.Options.
#   3. Proses zmc/zma monitor yang berubah direstart supaya konfigurasi baru
#      dibaca (tanpa restart, zmc masih memegang konfigurasi lama di memori).
#   4. Diverifikasi: daftar kandidat harus kosong + log terbaru bersih.
#
# PEMAKAIAN (dari root repo, butuh Git Bash / WSL / Linux):
#     bash scripts/fix_monitor_source_138.sh              # terapkan
#     DRY_RUN=1 bash scripts/fix_monitor_source_138.sh    # lihat rencana saja
#     METHOD_DEFAULT=rtpUni bash scripts/fix_monitor_source_138.sh
#     RESTART_ALL=1 bash scripts/fix_monitor_source_138.sh  # hanya restart zmc/zma
#       (dipakai bila database sudah diubah manual dan proses perlu memuat ulang)
# =============================================================================

set -euo pipefail

DB_CONTAINER="${DB_CONTAINER:-zm_db}"
ZM_CONTAINER="${ZM_CONTAINER:-zoneminder}"
DRY_RUN="${DRY_RUN:-0}"
METHOD_DEFAULT="${METHOD_DEFAULT:-rtpRtsp}"
# RESTART_ALL=1: selain memperbaiki yang bermasalah, restart proses zmc/zma
# semua monitor. Berguna saat konfigurasi sudah diubah manual di database.
RESTART_ALL="${RESTART_ALL:-0}"

# Nilai Method yang dikenal zmc 1.38 untuk tipe sumber Ffmpeg/Libvlc.
VALID_METHODS_SQL="'rtpRtsp','rtpUni','rtpMulti','rtpRtspHttp'"

# Predikat SQL "monitor ini perlu diperbaiki".
NEEDS_FIX_SQL="Type IN ('Ffmpeg', 'Libvlc') AND (
        Method IS NULL
     OR Method NOT IN ($VALID_METHODS_SQL)
     OR Options LIKE '%rtsp_transport%'
   )"

if ! command -v docker >/dev/null 2>&1; then
  echo "GAGAL: docker tidak ada di PATH." >&2
  exit 1
fi

case "$METHOD_DEFAULT" in
  rtpRtsp|rtpUni|rtpMulti|rtpRtspHttp) ;;
  *)
    echo "GAGAL: METHOD_DEFAULT '$METHOD_DEFAULT' bukan nilai yang dikenal zmc 1.38." >&2
    echo "       Pilihan: rtpRtsp (TCP), rtpUni (UDP), rtpMulti (UDP multicast), rtpRtspHttp (HTTP tunnel)." >&2
    exit 1
    ;;
esac

for c in "$DB_CONTAINER" "$ZM_CONTAINER"; do
  if [ "$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null || echo false)" != "true" ]; then
    echo "GAGAL: container '$c' tidak berjalan." >&2
    exit 1
  fi
done

# Semua query dijalankan DI DALAM container DB. Password dibaca dari docker
# secret supaya tidak pernah muncul di command line host maupun di .env.
#   sql       -> keluaran tabel (untuk dibaca manusia)
#   sql_plain -> keluaran tab-separated tanpa hiasan (untuk di-parse skrip)
sql() {
  docker exec -i "$DB_CONTAINER" sh -c \
    'export MYSQL_PWD=$(cat /run/secrets/zm_db_pass); exec mariadb -uzmuser -B -t zm'
}
sql_plain() {
  docker exec -i "$DB_CONTAINER" sh -c \
    'export MYSQL_PWD=$(cat /run/secrets/zm_db_pass); exec mariadb -uzmuser -B zm'
}

candidates_sql() {
  cat <<SQL
SELECT Id, Name, Type, Method, COALESCE(Options, '') AS Options
  FROM Monitors
 WHERE $NEEDS_FIX_SQL
 ORDER BY Id;
SQL
}

all_monitor_ids_sql() {
  cat <<'SQL'
SELECT Id FROM Monitors ORDER BY Id;
SQL
}

# 1) Method: hanya yang nilainya tidak dikenal zmc 1.38. Monitor dengan Method
#    yang sudah sah (mis. rtpUni/UDP) tidak dipaksa berubah.
fix_method_sql() {
  cat <<SQL
UPDATE Monitors
   SET Method = '$METHOD_DEFAULT'
 WHERE Type IN ('Ffmpeg', 'Libvlc')
   AND (Method IS NULL OR Method NOT IN ($VALID_METHODS_SQL));
SQL
}

# 2) Options: buang token rtsp_transport=<nilai> dari daftar koma.
#    CONCAT koma di depan/belakang memudahkan pencocokan token di tengah;
#    TRIM koma merapikan sisa pemisah; NULLIF mengembalikan NULL bila kosong.
fix_options_sql() {
  cat <<'SQL'
UPDATE Monitors
   SET Options = NULLIF(TRIM(BOTH ',' FROM REGEXP_REPLACE(
         CONCAT(',', COALESCE(Options, ''), ','),
         ',( *rtsp_transport[^,]*)', ''
       )), '')
 WHERE Type IN ('Ffmpeg', 'Libvlc')
   AND Options LIKE '%rtsp_transport%';
SQL
}

echo "=== 1. Kondisi sebelum perbaikan ==="
sql <<'SQL'
SELECT COUNT(*) AS total_monitor FROM Monitors;
SQL
sql <<'SQL'
SELECT Method, COUNT(*) AS jumlah FROM Monitors GROUP BY Method ORDER BY Method;
SQL
echo
echo "--- monitor yang perlu diperbaiki ---"
candidates_sql | sql

# Hanya baris yang kolom pertamanya angka (Id) yang dipakai; header dan baris
# hiasan lain dibuang oleh awk.
pick_ids() {
  tr -d '\r' | awk 'NF && $1 ~ /^[0-9]+$/ {print $1}' | tr '\n' ' '
}

CHANGED_IDS="$(candidates_sql | sql_plain | pick_ids)"
CHANGED_IDS="${CHANGED_IDS% }"
SKIP_WRITE=0

if [ -n "$CHANGED_IDS" ]; then
  echo
  echo "ID monitor yang akan diperbaiki: $CHANGED_IDS"
elif [ "$RESTART_ALL" = "1" ]; then
  CHANGED_IDS="$(all_monitor_ids_sql | sql_plain | pick_ids)"
  CHANGED_IDS="${CHANGED_IDS% }"
  SKIP_WRITE=1
  echo
  echo "Tidak ada konfigurasi yang perlu diperbaiki. RESTART_ALL=1 -> proses"
  echo "monitor berikut akan direstart: $CHANGED_IDS"
else
  echo
  echo "Tidak ada monitor yang perlu diperbaiki. Konfigurasi sumber sudah sesuai ZM 1.38."
  exit 0
fi

if [ "$DRY_RUN" = "1" ]; then
  echo
  echo "DRY_RUN=1 -> tidak ada perubahan yang ditulis dan proses tidak direstart."
  exit 0
fi

if [ "$SKIP_WRITE" = "1" ]; then
  echo
  echo "=== 2. Menulis perbaikan: dilewati (tidak ada yang perlu diubah) ==="
else
  echo
  echo "=== 2. Menulis perbaikan (Method -> $METHOD_DEFAULT, Options dibersihkan) ==="
  fix_method_sql | sql
  fix_options_sql | sql
fi

echo
echo "=== 3. Restart proses monitor yang berubah ==="
# zmc/zma baru membaca database saat start, jadi restart wajib. Monitor yang
# fungsinya None memang tidak punya zma - kegagalan restart zma diabaikan.
# Nama daemon di zmdc 1.38 memakai argumen, bukan 'zmc_m<id>': 'zmc_m1' ditolak
# dengan "Invalid daemon". Bentuk yang benar adalah argumen terpisah:
#     zmdc.pl restart zmc -m 1
for id in $CHANGED_IDS; do
  for proc in zmc zma; do
    if docker exec "$ZM_CONTAINER" zmdc.pl restart "$proc" -m "$id" >/dev/null 2>&1; then
      echo "  restart $proc -m $id: OK"
    else
      echo "  restart $proc -m $id: dilewati (kemungkinan tidak aktif)"
    fi
  done
done

echo
echo "=== 4. Kondisi sesudah perbaikan (harus kosong) ==="
candidates_sql | sql

echo
echo "=== 5. State monitor (Status harus Connected, fps terisi) ==="
IDS_CSV="$(printf '%s' "$CHANGED_IDS" | tr ' ' ',')"
sql <<SQL
SELECT MonitorId, Status, CaptureFPS, AnalysisFPS, CaptureBandwidth, UpdatedOn
  FROM Monitor_Status
 WHERE MonitorId IN ($IDS_CSV)
 ORDER BY MonitorId;
SQL

echo
echo "=== 6. Log peringatan ZM terbaru (Level<0) ==="
echo "Peringatan 'Unknown method' / 'not recognized by ffmpeg' tidak boleh muncul lagi."
sql <<'SQL'
SELECT Id, Component, File, Line, LEFT(Message, 110) AS Pesan
  FROM Logs
 WHERE Level < 0
 ORDER BY Id DESC
 LIMIT 15;
SQL

echo
echo "SELESAI. Bila langkah 4 kosong dan tidak ada peringatan baru di langkah 6,"
echo "konfigurasi sumber sudah bersih untuk ZoneMinder 1.38."
