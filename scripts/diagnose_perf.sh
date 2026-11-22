#!/usr/bin/env bash
# ============================================================================
# diagnose_perf.sh — ZoneMinder performance triage (READ-ONLY)
#
# Konteks kasus: 60 kamera 720p modect, RAM terpakai 62 GB, CPU 15-30% dari
# 32 core saat web UI TERTUTUP, naik ke 50-90% saat web UI DIBUKA.
#
# CARA PAKAI (jalankan di KOMPUTER 60 KAMERA):
#
#   # 1) saat web UI ZoneMinder TERTUTUP
#   bash scripts/diagnose_perf.sh closed | tee /tmp/zm-closed.txt
#
#   # 2) buka montage/wall SEMUA kamera, tunggu 60 detik, lalu:
#   bash scripts/diagnose_perf.sh open   | tee /tmp/zm-open.txt
#
#   # 3) bandingkan
#   diff -u /tmp/zm-closed.txt /tmp/zm-open.txt | less
#
# OPSI LINGKUNGAN
#   ZM_CONTAINER=zoneminder   nama container (default). Set kosong -> bare-metal.
#   ZM_QUERY_TIMEOUT=60       batas detik per perintah docker exec / query DB.
#   ZM_PROJECT_N=60           proyeksi biaya ke N kamera (default 60).
#
# DESAIN
#   * Semua metrik mesin dibaca DARI DALAM container. Alasannya: pada Docker
#     Desktop / docker remote, `ps` dan `free` di host skrip hanya melihat host
#     skrip — bukan mesin yang menjalankan ZoneMinder.
#   * Data mentah (teks) diambil sekali, semua parsing dilakukan lokal, jadi
#     tidak ada quoting bersarang yang bisa pecah.
#   * Perintah yang bisa lambat selalu dibungkus timeout.
#   * COUNT(*) penuh tidak dipakai pada Events (pakai estimasi + range terindeks).
#   * Read-only: hanya SELECT/SHOW/cat/ls/ps/top/df/du.
#
# TERVERIFIKASI pada ZoneMinder 1.36.32 (pppasantos/zoneminder) dan diuji ulang
# pada ZoneMinder 1.38.6 (zoneminder/zoneminder, service db = MariaDB 11.8):
#   - kolom waktu Events = StartDateTime (BUKAN StartTime)
#   - buffer frame = /dev/shm/zm.mmap.<id>, ukuran = Width*Height*12 + ~5.5 KB
#     (bukan SysV shm; `ipcs -m` kosong adalah NORMAL)
#   - docker stats template memakai {{.PIDs}}, bukan {{.Pids}}
# ============================================================================
set -uo pipefail

PHASE="${1:-unknown}"
CONTAINER="${ZM_CONTAINER-zoneminder}"
QT="${ZM_QUERY_TIMEOUT:-60}"
PROJECT_N="${ZM_PROJECT_N:-60}"

sec() { printf '\n\033[1m=== %s ===\033[0m\n' "$*"; }
sub() { printf '\n-- %s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

IN_CONTAINER=0
if [ -n "$CONTAINER" ] && have docker && docker inspect "$CONTAINER" >/dev/null 2>&1; then
  IN_CONTAINER=1
fi

incexec() {
  if [ "$IN_CONTAINER" = "1" ]; then
    timeout "$QT" docker exec "$CONTAINER" sh -c "$1" 2>/dev/null
  else
    timeout "$QT" sh -c "$1" 2>/dev/null
  fi
}

# ---------------------------------------------------------------------------
# Kredensial DB dari /etc/zm/zm.conf (dibaca sekali).
# ---------------------------------------------------------------------------
DB_USER="zmuser"; DB_PASS="zmpass"; DB_NAME="zm"
# Database TIDAK lagi di dalam container ZoneMinder (sejak ZM 1.38 resmi):
# semua query dijalankan di container DB terpisah, password dari docker secret.
DB_CONTAINER="zm_db"
DB_PASS_ENV=""
if [ -r secrets/zm_db_pass.txt ]; then DB_PASS_ENV="$(cat secrets/zm_db_pass.txt)"; fi
# Sejak ZM 1.38 (image resmi) kredensial DB ditulis entrypoint ke
# /etc/zm/conf.d/03-docker.conf; zm.conf hanya menyisakan path.
ZMCONF="$(incexec 'cat /etc/zm/zm.conf /etc/zm/conf.d/03-docker.conf 2>/dev/null')"
if [ -n "${ZMCONF:-}" ]; then
  while IFS='=' read -r k v; do
    case "$k" in
      ZM_DB_USER) DB_USER="$v" ;;
      ZM_DB_PASS) DB_PASS="$v" ;;
      ZM_DB_NAME) DB_NAME="$v" ;;
    esac
  done <<< "$ZMCONF"
fi

dbq() {   # output tabel untuk dibaca manusia; SQL lewat stdin
  if [ "$IN_CONTAINER" = "1" ]; then
    timeout "$QT" docker exec -i -e MYSQL_PWD="${DB_PASS_ENV:-$DB_PASS}" "$DB_CONTAINER" mariadb -h 127.0.0.1 -u"$DB_USER" -D "$DB_NAME" -t 2>/dev/null
  else
    timeout "$QT" mysql --protocol=socket -u"$DB_USER" -p"$DB_PASS" -D "$DB_NAME" -t 2>/dev/null
  fi
}
dbR() {   # output mentah tab-separated untuk di-parse
  if [ "$IN_CONTAINER" = "1" ]; then
    timeout "$QT" docker exec -i -e MYSQL_PWD="${DB_PASS_ENV:-$DB_PASS}" "$DB_CONTAINER" mariadb -h 127.0.0.1 -u"$DB_USER" -D "$DB_NAME" -N -B 2>/dev/null
  else
    timeout "$QT" mysql --protocol=socket -u"$DB_USER" -p"$DB_PASS" -D "$DB_NAME" -N -B 2>/dev/null
  fi
}

printf '\033[1m###### ZONEMINDER PERF TRIAGE — FASE: %s ######\033[0m\n' "$PHASE"
echo "waktu      : $(date -Is)"
echo "host skrip : $(hostname)"
if [ "$IN_CONTAINER" = "1" ]; then
  echo "sumber data: container '$CONTAINER' via docker exec — INI mesin yang benar"
else
  echo "sumber data: host lokal (container '$CONTAINER' tidak ditemukan -> mode bare-metal)"
fi

# ===========================================================================
# 1. BASELINE MESIN
# ===========================================================================
sec "1. BASELINE MESIN"
MEMINFO="$(incexec 'cat /proc/meminfo')"
PROCSTAT_A="$(incexec 'cat /proc/stat')"
CORE=$(printf '%s\n' "${PROCSTAT_A:-}" | grep -c '^cpu[0-9]')
echo "core terdeteksi : ${CORE:-?}"

sub "RAM & SWAP"
printf '%s\n' "${MEMINFO:-}" | awk '
/^(MemTotal|MemFree|MemAvailable|Buffers|Cached|SwapTotal|SwapFree|AnonPages|Shmem|SReclaimable|Committed_AS):/ {
  key=$1; sub(/:/,"",key); printf "  %-14s %10.2f GB\n", key, $2/1048576
}'

sub "interpretasi (yang menentukan tekanan, BUKAN angka 'used')"
printf '%s\n' "${MEMINFO:-}" | awk '
/^MemTotal:/     {t=$2} /^MemAvailable:/ {a=$2}
/^SwapTotal:/    {st=$2} /^SwapFree:/   {sf=$2}
/^Committed_AS:/ {ca=$2} /^AnonPages:/  {an=$2}
/^SReclaimable:/ {sr=$2} /^Cached:/     {ch=$2}
END {
  if (t>0) printf "  RAM terpakai (total-available) = %.2f GB dari %.2f GB  (%.1f%%)\n", (t-a)/1048576, t/1048576, 100*(t-a)/t
  printf "  AnonPages (memori NYATA)        = %.2f GB\n", an/1048576
  printf "  Page cache (BISA dibuang)       = %.2f GB\n", (ch+sr)/1048576
  printf "  Committed_AS                    = %.2f GB\n", ca/1048576
  if (st>0) { u=(st-sf); printf "  SWAP terpakai = %.2f GB  -> ", u/1048576
              print (u==0 ? "AMAN (belum swapping)" : "** SUDAH SWAPPING = RAM benar-benar habis **") }
  else print "  SWAP = tidak dikonfigurasi"
}'

sub "tekanan memori PSI (avg60 tinggi = proses menunggu memori)"
PSI="$(incexec 'cat /proc/pressure/memory')"
if [ -n "${PSI:-}" ]; then printf '%s\n' "$PSI" | sed 's/^/  /'; else echo "  (PSI tidak tersedia)"; fi
sub "load average"
incexec 'cat /proc/loadavg' | sed 's/^/  /'

# ---------------------------------------------------------------------------
sleep 4
PROCSTAT_B="$(incexec 'cat /proc/stat')"
# ---------------------------------------------------------------------------

sec "2. SAMPEL 4 DETIK — breakdown CPU + laju fork"
A_CPU=$(printf '%s\n' "${PROCSTAT_A:-}" | grep '^cpu ')
B_CPU=$(printf '%s\n' "${PROCSTAT_B:-}" | grep '^cpu ')
if [ -n "${A_CPU:-}" ] && [ -n "${B_CPU:-}" ]; then
  printf '%s\n%s\n' "$A_CPU" "$B_CPU" | awk '
  NR==1 { for(i=2;i<=10;i++) a[i]=$i; next }
  {
    tot=0; for(i=2;i<=10;i++){ d[i]=$i-a[i]; tot+=d[i] }
    if (tot<=0) { print "  (delta nol - tidak bisa dihitung)"; exit }
    split("user nice system idle iowait irq softirq steal guest", nm, " ")
    for (i=1;i<=9;i++) printf "  %-9s %6.1f%%\n", nm[i], 100*d[i+1]/tot
    printf "  ---------------------------\n"
    printf "  BUSY      %6.1f%%   (= user+nice+system+irq+softirq+steal)\n", 100*(d[2]+d[3]+d[4]+d[7]+d[8]+d[9])/tot
    if (tot>0 && 100*d[9]/tot > 5) print "  ** steal > 5% -> masalah hypervisor, bukan ZoneMinder **"
  }'
else
  echo "  (/proc/stat tidak terbaca)"
fi
FA=$(printf '%s\n' "${PROCSTAT_A:-}" | awk '/^processes/{print $2}')
FB=$(printf '%s\n' "${PROCSTAT_B:-}" | awk '/^processes/{print $2}')
if [ -n "${FA:-}" ] && [ -n "${FB:-}" ]; then
  echo "  fork+exec per detik = $(( (FB - FA) / 4 ))"
  echo "    (ratusan pada fase 'open' = tiap gambar/stream = proses baru -> mahal)"
fi

# ===========================================================================
# 3. SENSUS PROSES
# ===========================================================================
sec "3. SENSUS PROSES"
TOPRAW="$(incexec 'top -bn2 -d 1 -w 512 2>/dev/null')"
if [ -n "${TOPRAW:-}" ]; then
  echo "  sumber: top -bn2 -w 512 (kolom %CPU = sampel INSTAN, bukan rata-rata)"
  sub "per executable — diurut %CPU   (RES = RSS; penjumlahan RES melebih-hitung karena page dibagi antar proses fork)"
  printf '%s\n' "$TOPRAW" | awk '
    /^ *PID / { buf=""; next }
    NF>11 && $1 ~ /^[0-9]+$/ { buf = buf "\n" $0 }
    { last = buf }
    END {
      n=split(last, L, "\n")
      for (i=1;i<=n;i++) { if (L[i]=="") continue; split(L[i], f, " ")
        c[f[12]]++; r[f[12]]+=f[6]; p[f[12]]+=f[9] }
      printf "  %-20s %7s %14s %11s\n","EXECUTABLE","COUNT","RES_TOTAL_MB","CPU_SUM_PCT"
      for (k in c) printf "  %-20s %7d %14.1f %11.1f\n",k,c[k],r[k]/1024,p[k] | "sort -k3 -rn | head -25"
    }'
  sub "TOP 15 proses — CPU"
  printf '%s\n' "$TOPRAW" | awk '
    /^ *PID / { buf=""; next }
    NF>11 && $1 ~ /^[0-9]+$/ { buf = buf "\n" $0 }
    { last = buf }
    END { n=split(last, L, "\n"); for (i=1;i<=n;i++) if (L[i]!="") print L[i] }' \
    | sort -k9 -rn | head -15 \
    | awk 'BEGIN{printf "  %-7s %-9s %9s %9s %7s %s\n","PID","USER","RES_KB","VIRT_KB","CPU%","COMMAND"}
           {printf "  %-7s %-9s %9s %9s %7s %s\n",$1,$2,$6,$5,$9,$12}'
else
  echo "  (top tidak ada; jatuh ke ps — %CPU di sini rata-rata seumur proses)"
  incexec 'ps -eo pid=,user=,rss=,vsz=,pcpu=,comm=' | awk '
    { c[$6]++; r[$6]+=$3; p[$6]+=$5 }
    END { printf "  %-20s %7s %14s %11s\n","EXECUTABLE","COUNT","RES_TOTAL_MB","CPU_LIFETIME"
          for (k in c) printf "  %-20s %7d %14.1f %11.1f\n",k,c[k],r[k]/1024,p[k] | "sort -k3 -rn | head -25" }'
fi

sub "daemon ZM per monitor (zmc/zma) — jumlahnya harus = jumlah kamera aktif"
ZMCS="$(incexec 'ps -eo args= | grep -E "/zm[ca] " | grep -v grep')"
if [ -n "${ZMCS:-}" ]; then
  printf '%s\n' "$ZMCS" | sed -E 's/.*(-m[ =]*[0-9]+).*/\1/' | sort -t' ' -k2 -n \
    | awk '{printf "%s  ",$0} END{print ""}'
else
  echo "  (tidak ada proses zmc/zma)"
fi

sub "penonton stream: proses zms/nph-zms (bukti 'UI dibuka = CPU naik')"
ZMS="$(incexec 'ps -eo args= | grep -E "nph-zms|/zms( |$)" | grep -v grep')"
if [ -z "${ZMS:-}" ]; then
  echo "  TIDAK ADA proses zms -> tidak ada yang menonton stream saat ini"
else
  printf '%s\n' "$ZMS" | awk 'END{printf "  jumlah proses zms = %d\n",NR}'
  printf '%s\n' "$ZMS" | grep -oE '\-m[ =]*[0-9]+' | grep -oE '[0-9]+' | sort -n | uniq -c \
    | awk '{printf "    monitor %-6s x %s\n",$2,$1}'
fi

# ===========================================================================
# 4. ANGGARAN WORKER APACHE
# ===========================================================================
sec "4. ANGGARAN WORKER APACHE (tersangka utama RAM & CPU web UI)"
APCNT="$(incexec 'ps -eo comm= | grep -c "^apache2$"')"
APCNT="${APCNT:-0}"
echo "  worker apache2 hidup sekarang = $APCNT"
APAVG=0
if [ "$APCNT" -gt 0 ]; then
  APAVG=$(incexec 'ps -eo comm=,rss= | grep "^apache2" ' | awk '
    { n++; r+=$2; if (min==""||$2<min) min=$2; if ($2>max) max=$2 }
    END { if(n>0) printf "%.1f %.1f %.1f", min/1024, max/1024, r/n/1024 }')
  printf '%s\n' "${APAVG:-}" | awk -F' ' 'NF==3 { printf "  RES per worker: min=%.1f MB  max=%.1f MB  rata2=%.1f MB\n",$1,$2,$3 }'
  APAVG=$(printf '%s\n' "${APAVG:-}" | awk '{print $3}')
fi

sub "konfigurasi MPM efektif (baris non-komentar, sesuai urutan load Apache)"
MPMRAW="$(incexec 'echo "### mods-enabled"; grep -hvE "^[[:space:]]*#" /etc/apache2/mods-enabled/mpm_*.conf 2>/dev/null; echo "### conf-enabled"; grep -hvE "^[[:space:]]*#" /etc/apache2/conf-enabled/*.conf 2>/dev/null')"
printf '%s\n' "${MPMRAW:-}" | grep -iE '^###|serverlimit|maxrequestworkers|startservers|minspare|maxspare|maxconnectionsperchild|keepalive' \
  | sed 's/^[[:space:]]*/  /' | head -30

# Nilai efektif = kemunculan TERAKHIR (conf-enabled dimuat setelah mods-enabled).
eff() { printf '%s\n' "${MPMRAW:-}" | grep -iE "^[[:space:]]*$1[[:space:]]" | tail -1 | awk '{print $2}'; }
MRW=$(eff MaxRequestWorkers); SL=$(eff ServerLimit); MSS=$(eff MaxSpareServers)
MNS=$(eff MinSpareServers); MCPC=$(eff MaxConnectionsPerChild); KAR=$(eff MaxKeepAliveRequests)
echo
echo "  EFEKTIF: MaxRequestWorkers=${MRW:-?}  ServerLimit=${SL:-?}  MinSpareServers=${MNS:-?}  MaxSpareServers=${MSS:-?}"
echo "           MaxConnectionsPerChild=${MCPC:-?}  MaxKeepAliveRequests=${KAR:-?}"
if [ -n "${MRW:-}" ] && [ -n "${APAVG:-}" ]; then
  awk -v m="$MRW" -v a="$APAVG" 'BEGIN{ printf "  anggaran RAM terburuk = %s worker x %.1f MB = %.1f GB\n", m, a, m*a/1024 }'
fi
if [ -n "${MSS:-}" ] && [ "$MSS" -gt 10 ] 2>/dev/null; then
  awk -v s="$MSS" -v a="${APAVG:-23}" 'BEGIN{ printf "  ** MaxSpareServers=%s -> Apache MENAHAN sampai %s worker idle = %.1f GB selalu terpakai **\n", s, s, s*a/1024 }'
fi
if [ "${KAR:-x}" = "0" ] 2>/dev/null; then
  echo "  ** MaxKeepAliveRequests=0 + stream MJPEG panjang -> worker tidak pernah didaur ulang (MaxConnectionsPerChild tidak akan tercapai) **"
fi

# ===========================================================================
# 5. SHARED MEMORY
# ===========================================================================
sec "5. SHARED MEMORY (buffer frame per kamera)"
sub "kapasitas & pemakaian /dev/shm"
incexec 'df -h /dev/shm' | sed 's/^/  /'

sub "file buffer per kamera — ZM 1.36 memakai /dev/shm/zm.mmap.<Id>"
SHMLS="$(incexec 'ls -la /dev/shm')"
SHMTOT=0
if printf '%s\n' "${SHMLS:-}" | grep -q 'zm\.mmap'; then
  printf '%s\n' "$SHMLS" | awk '/zm\.mmap\./ { id=$9; sub(/.*zm\.mmap\./,"",id);
      printf "%12.2f MB\tmonitor %s\n", $5/1048576, id }' | sort -rn
  SHMTOT=$(printf '%s\n' "$SHMLS" | awk '/zm\.mmap\./ {s+=$5} END{print s+0}')
  printf '%s\n' "$SHMLS" | awk '/zm\.mmap\./ {n++; s+=$5}
    END { printf "\n  FILE=%d   TOTAL_SHM=%.2f MB (%.3f GB)\n", n, s/1048576, s/1073741824 }'
  echo "  rumus terverifikasi: Width x Height x 12 byte + ~5.5 KB per kamera"
else
  echo "  (tidak ada file zm.mmap.* — isi /dev/shm:)"
  printf '%s\n' "${SHMLS:-}" | sed 's/^/  /' | head -20
fi

sub "jalur SysV (untuk ZM versi lama)"
SYSSHM="$(incexec 'cat /proc/sysvipc/shm')"
printf '%s\n' "${SYSSHM:-}" | awk 'NR>1 && NF>=7 {n++; t+=$4}
  END { if (n==0) print "  (0 segmen SysV — NORMAL untuk ZM 1.36+, yang memakai /dev/shm)"
        else printf "  SEGMEN=%d  TOTAL=%.2f MB\n", n, t/1048576 }'

# ===========================================================================
# 6. MARIADB
# ===========================================================================
sec "6. MARIADB"
DBN="$(timeout "$QT" docker exec "$DB_CONTAINER" ps -eo rss=,comm= 2>/dev/null | grep -E "mariadbd|mysqld")"
printf '%s\n' "${DBN:-}" | awk '{r+=$1; n++} END { printf "  proses DB=%d  RSS total=%.2f GB\n", n, r/1048576 }'

sub "ukuran tabel (table_rows InnoDB = PERKIRAAN)"
dbq <<'SQL'
SELECT table_name AS tbl, table_rows AS approx_rows,
       ROUND(data_length/1048576) AS data_mb, ROUND(index_length/1048576) AS idx_mb,
       ROUND((data_length+index_length)/1048576) AS total_mb
FROM information_schema.tables WHERE table_schema=DATABASE()
ORDER BY (data_length+index_length) DESC LIMIT 12;
SQL

sub "aktivitas & koneksi"
dbq <<'SQL'
SHOW GLOBAL STATUS WHERE Variable_name IN (
 'Threads_connected','Threads_running','Max_used_connections','Aborted_connects',
 'Innodb_buffer_pool_reads','Innodb_buffer_pool_read_requests','Innodb_row_lock_waits',
 'Created_tmp_disk_tables','Slow_queries','Table_locks_waited','Uptime');
SQL

sub "rasio hit buffer pool"
BPR="$(dbR <<'SQL'
SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool_reads';
SQL
)"
BPQ="$(dbR <<'SQL'
SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool_read_requests';
SQL
)"
printf '%s\n' "${BPR:-}" | awk -v q="${BPQ:-}" 'BEGIN{
  split($0,a,"\t"); reads=a[2]+0; split(q,b,"\t"); reqs=b[2]+0
  if (reqs<=0) { print "  (tidak bisa dihitung)"; exit }
  printf "  reads=%d  requests=%d  ->  HIT=%.3f%%\n", reads, reqs, 100*(1-reads/reqs)
  if (100*(1-reads/reqs) < 99) print "  ** di bawah 99% = MariaDB terus membaca dari disk **"
}'

sub "variabel penting"
dbq <<'SQL'
SHOW VARIABLES WHERE Variable_name IN (
 'version','innodb_buffer_pool_size','innodb_buffer_pool_instances','innodb_flush_log_at_trx_commit',
 'max_connections','table_open_cache','table_definition_cache',
 'tmp_table_size','max_heap_table_size','sort_buffer_size','join_buffer_size',
 'read_buffer_size','read_rnd_buffer_size','innodb_log_file_size','innodb_flush_method','innodb_io_capacity');
SQL

# ===========================================================================
# 7. KONFIG GLOBAL ZM
# ===========================================================================
sec "7. KONFIG GLOBAL ZM YANG MEMPENGARUHI CPU WEB UI"
sub "semua config STREAM / MONTAGE / REFRESH / THUMB / SCALE"
dbq <<'SQL'
SELECT Name, Value FROM Config WHERE Name REGEXP 'STREAM|MONTAGE|REFRESH|THUMB|SCALE'
ORDER BY Name;
SQL

sub "nilai SAH untuk knob yang akan kita ubah (kolom Hint dari ZM)"
dbq <<'SQL'
SELECT Name, Value, Type, Hint FROM Config WHERE Name IN (
 'ZM_WEB_H_STREAM_METHOD','ZM_WEB_M_STREAM_METHOD','ZM_WEB_L_STREAM_METHOD',
 'ZM_WEB_H_DEFAULT_SCALE','ZM_WEB_M_DEFAULT_SCALE','ZM_WEB_L_DEFAULT_SCALE',
 'ZM_WEB_ANIMATE_THUMBS','ZM_WEB_COMPACT_MONTAGE','ZM_WEB_LIST_THUMBS',
 'ZM_JPEG_STREAM_QUALITY','ZM_OPT_FAST_DELETE','ZM_OPT_ADAPTIVE_SKIP'
) ORDER BY Name;
SQL

sub "operasional & limit"
dbq <<'SQL'
SELECT Name, Value FROM Config WHERE Name IN (
 'ZM_OPT_USE_AUTH','ZM_AUTH_TYPE','ZM_AUTH_RELAY','ZM_AUTH_HASH_IPS',
 'ZM_OPT_FAST_DELETE','ZM_OPT_ADAPTIVE_SKIP','ZM_OPT_FRAME_SERVER','ZM_OPT_EXTRA_DEBUG',
 'ZM_OPT_CONTROL','ZM_OPT_X10','ZM_OPT_TRIGERS','ZM_OPT_USE_ONVIF','ZM_OPT_USE_API',
 'ZM_FFMPEG_INPUT_OPTIONS','ZM_FFMPEG_OUTPUT_OPTIONS','ZM_STATS_UPDATE_INTERVAL',
 'ZM_RUN_STATE_UPDATE_INTERVAL','ZM_WATCH_CHECK_INTERVAL','ZM_DEFAULT_SCALE',
 'ZM_MAX_RESTART_DELAY','ZM_OPT_USE_SHARED_MEM'
) ORDER BY Name;
SQL

# ===========================================================================
# 8. SENSUS MONITOR
# ===========================================================================
sec "8. SENSUS MONITOR"
sub "jumlah per Function"
dbq <<'SQL'
SELECT Function, COUNT(*) AS n FROM Monitors GROUP BY Function ORDER BY n DESC;
SQL
sub "SaveJPEGs x VideoWriter  <-- SaveJPEGs=3 + VideoWriter=0 = default paling boros"
dbq <<'SQL'
SELECT SaveJPEGs, VideoWriter, COUNT(*) AS monitors
FROM Monitors GROUP BY SaveJPEGs, VideoWriter ORDER BY monitors DESC;
SQL
sub "FPS & batas analisa (AnalysisFPSLimit NULL/0 = ANALISA SETIAP FRAME)"
dbq <<'SQL'
SELECT CONCAT('MaxFPS=', IFNULL(MaxFPS,'NULL'),
              '  AlarmMaxFPS=', IFNULL(AlarmMaxFPS,'NULL'),
              '  AnalysisFPSLimit=', IFNULL(AnalysisFPSLimit,'NULL'),
              '  FrameSkip=', IFNULL(FrameSkip,'NULL'),
              '  MotionFrameSkip=', IFNULL(MotionFrameSkip,'NULL')) AS combination,
       COUNT(*) AS monitors
FROM Monitors GROUP BY combination ORDER BY monitors DESC LIMIT 10;
SQL
sub "resolusi & total megapiksel"
dbq <<'SQL'
SELECT Width, Height, COUNT(*) AS n, ROUND(SUM(Width*Height)/1000000) AS total_mp
FROM Monitors GROUP BY Width, Height ORDER BY n DESC;
SQL

sub "resolusi MONITOR vs yang DIKIRIM kamera (mismatch = zmc men-scale tiap frame)"
# Sumber bukti: zm_ffmpeg_camera.cpp:580 —
#   "Monitor dimensions are WxH but camera is sending AxB"
# Artinya ZoneMinder men-DECODE frame pada resolusi ASLI kamera, baru men-scale
# ke Width/Height monitor. Konsekuensinya:
#   * mengecilkan Width/Height di ZM TIDAK mengurangi biaya decode (bagian mahal);
#   * yang berkurang hanya ukuran buffer/shared memory (RAM ikut Width/Height monitor).
MISMATCH="$(incexec 'tail -n 500 /var/log/zm/zmc_m*.log 2>/dev/null | grep -a -o "Monitor dimensions are [0-9]*x[0-9]* but camera is sending [0-9]*x[0-9]*"' | sort | uniq -c | sort -rn | head -20)"
if [ -n "${MISMATCH:-}" ]; then
  printf '%s\n' "$MISMATCH" | sed 's/^/  /'
  echo "  -> angka kiri = jumlah kejadian restart zmc (bukan jumlah frame)."
  echo "     monitor WxH   -> menentukan RAM/shared memory (zmc RSS ~ piksel monitor)."
  echo "     kamera AxB    -> menentukan biaya decode + bandwidth (zmc CPU ~ piksel kamera)."
  echo "     perbaikan terbaik: samakan di KAMERA (main stream), atau pakai sub-stream"
  echo "     (contoh Hikvision: /Streaming/Channels/102). Verifikasi setelah restart:"
  echo "     grep -c 'Monitor dimensions are' /var/log/zm/zmc_m*.log  -> harus 0"
else
  echo "  tidak ada mismatch di log (atau log sudah terotasi / debug mati) — bagus."
fi
sub "buffer pre/post & section length"
dbq <<'SQL'
SELECT PreEventCount, PostEventCount, AlarmFrameCount, SectionLength, COUNT(*) AS n
FROM Monitors GROUP BY PreEventCount, PostEventCount, AlarmFrameCount, SectionLength
ORDER BY n DESC LIMIT 10;
SQL
sub "kolom Monitors yang ADA (guard sebelum menulis UPDATE apa pun)"
dbq <<'SQL'
SELECT COLUMN_NAME, COLUMN_TYPE FROM information_schema.columns
WHERE table_schema=DATABASE() AND table_name='Monitors' ORDER BY ORDINAL_POSITION;
SQL

# Deteksi nama kolom waktu Events secara version-safe.
EVCOL="$(dbR <<'SQL'
SELECT IF(COUNT(*)>0,'StartDateTime','StartTime') FROM information_schema.columns
WHERE table_schema=DATABASE() AND table_name='Events' AND COLUMN_NAME='StartDateTime';
SQL
)"
EVCOL="${EVCOL:-StartDateTime}"
echo "  kolom waktu Events terdeteksi: $EVCOL"

sub "daftar monitor"
dbq <<SQL
SELECT Id, Name, Function, Width, Height, MaxFPS, AnalysisFPSLimit, SaveJPEGs, VideoWriter
FROM Monitors ORDER BY Id;
SQL

sub "kamera yang TIDAK menerima event 24 jam terakhir (mati / salah config)"
dbq <<SQL
SELECT m.Id, m.Name, m.Function FROM Monitors m
WHERE m.Function <> 'None'
  AND NOT EXISTS (SELECT 1 FROM Events e WHERE e.MonitorId=m.Id AND e.$EVCOL > NOW() - INTERVAL 1 DAY);
SQL

# ===========================================================================
# 9. PROYEKSI KE N KAMERA
# ===========================================================================
sec "9. PROYEKSI KE $PROJECT_N KAMERA"
MONN="$(dbR <<'SQL'
SELECT COUNT(*) FROM Monitors WHERE Function <> 'None';
SQL
)"
MONN="${MONN:-0}"
if [ "$MONN" -gt 0 ] 2>/dev/null; then
  PSC="$(incexec 'ps -eo comm=,rss= | grep -v grep')"
  sumof() { printf '%s\n' "${PSC:-}" | awk -v p="$1" 'index($1,p)==1 {s+=$2} END{printf "%.0f", s/1024}'; }
  ZMCMB=$(sumof zmc); ZMAMB=$(sumof zma); APMB=$(sumof apache2)
  # DB berada di container terpisah: RSS diambil langsung dari proses mariadbd.
  DBMB=$(timeout "$QT" docker exec "$DB_CONTAINER" ps -eo rss=,comm= 2>/dev/null \
         | awk '{s+=$1} END {printf "%.0f", s/1024}')
  SHMMB=$(awk -v b="$SHMTOT" 'BEGIN{printf "%.0f", b/1048576}')
  awk -v m="$MONN" -v n="$PROJECT_N" -v zmc="$ZMCMB" -v zma="$ZMAMB" \
      -v ap="${APMB:-0}" -v db="${DBMB:-0}" -v shm="$SHMMB" 'BEGIN{
    printf "  kamera aktif sekarang = %d, proyeksi = %d kamera\n\n", m, n
    printf "  %-22s %14s %14s\n", "KOMPONEN", "SEKARANG(GB)", "PROYEKSI(GB)"
    printf "  %-22s %14.2f %14.2f\n", "zmc (decode)",      zmc/1024, zmc/1024/m*n
    printf "  %-22s %14.2f %14.2f\n", "zma (motion)",      zma/1024, zma/1024/m*n
    printf "  %-22s %14.2f %14.2f\n", "shared memory",     shm/1024, shm/1024/m*n
    printf "  %-22s %14.2f %14.2f\n", "apache2 (web)",     ap/1024,  ap/1024
    printf "  %-22s %14.2f %14.2f\n", "mysqld/mariadbd",   db/1024,  db/1024
    printf "  %-22s %14.2f %14.2f\n", "TOTAL", (zmc+zma+shm+ap+db)/1024, \
                                      (zmc+zma+shm)/1024/m*n + (ap+db)/1024
    print ""
    print "  Catatan penting:"
    print "   * zmc/zma/shm diskalakan linear terhadap jumlah kamera, TAPI memakai"
    print "     rata-rata resolusi monitor yang sedang terpasang. Kalau 60 kamera Anda"
    print "     semua 720p sementara sekarang campuran, angka proyeksi akan MENYIMPANG."
    print "   * apache2 & mysqld TIDAK diskalakan — biayanya tergantung berapa browser"
    print "     menonton stream dan berapa ukuran tabel Events, bukan jumlah kamera."
  }'
  # Peringatan penting: kalau belum ada monitor Modect/Mocord, biaya zma tidak terukur
  # sama sekali (baris zma = 0), sehingga proyeksi Modect akan TERLALU RENDAH.
  if [ "${N_MODECT:-0}" -eq 0 ] 2>/dev/null && [ "${N_MOCORD:-0}" -eq 0 ] 2>/dev/null; then
    echo ""
    echo "  ** PERINGATAN: belum ada monitor ber-Function Modect/Mocord di sini."
    echo "     Artinya baris 'zma (motion)' di atas = 0 dan TIDAK terukur."
    echo "     Untuk 60 kamera modect, tambahkan lagi biaya zma: kira-kira"
    echo "     30-100 MB per kamera = 2-6 GB ekstra yang tidak muncul di tabel ini."
  fi
else
  echo "  (tidak ada monitor aktif — proyeksi dilewati)"
fi

# ===========================================================================
# 10. PENYIMPANAN & LOG
# ===========================================================================
sec "10. PENYIMPANAN & LOG"
sub "filesystem"
incexec 'df -h' | grep -Ei 'Filesystem|/var/lib|/mnt|/media|overlay|/dev/shm|/dev/sd' | sed 's/^/  /' | head -15

sub "skala event (estimasi, TANPA COUNT(*) penuh)"
dbq <<'SQL'
SELECT table_rows AS approx_total_events FROM information_schema.tables
WHERE table_schema=DATABASE() AND table_name='Events';
SQL

sub "event 24 jam terakhir"
dbq <<SQL
SELECT COUNT(*) AS events_24h FROM Events WHERE $EVCOL > NOW() - INTERVAL 1 DAY;
SQL

sub "direktori & ukuran event di disk (timeout ${QT}s)"
# Path event ZM 1.38 = /var/cache/zoneminder/events (ZM_DIR_EVENTS di
# /etc/zm/conf.d/01-system-paths.conf). Path lama /var/lib/zoneminder/events
# hanya dipakai binding compose 1.36 dan tidak pernah ditulis ZoneMinder.
EVL="$(incexec 'ls -d /var/cache/zoneminder/events 2>/dev/null')"
if [ -n "${EVL:-}" ]; then
  echo "  direktori : $EVL"
  echo "  top-level : $(incexec 'ls -1 /var/cache/zoneminder/events 2>/dev/null | wc -l')"
  echo "  ukuran    : $(incexec 'du -sh /var/cache/zoneminder/events 2>/dev/null')"
else
  echo "  (/var/cache/zoneminder/events tidak ada)"
fi

sub "pola error di log ZM"
LOGCHK="$(incexec 'for f in $(ls -1t /var/log/zoneminder/*.log /var/log/zm/*.log 2>/dev/null | head -10); do c=$(grep -ciE "unable to keep up|overrun|timed out|not responding|shared memory|failed to open|no zones to check" "$f" 2>/dev/null); printf "  %-30s %s\n" "$(basename "$f")" "$c"; done')"
if [ -n "${LOGCHK:-}" ]; then printf '%s\n' "$LOGCHK"; else echo "  (tidak ada file log)"; fi

# ===========================================================================
# 11. DOCKER
# ===========================================================================
if [ "$IN_CONTAINER" = "1" ]; then
  sec "11. DOCKER"
  sub "stats container (LIMIT kosong = tanpa batas memori)"
  timeout "$QT" docker stats --no-stream --format \
    'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.PIDs}}' 2>&1 | sed 's/^/  /'
  sub "limit & OOM container ZM"
  timeout "$QT" docker inspect -f \
    '  Memory={{.HostConfig.Memory}}  ShmSize={{.HostConfig.ShmSize}}  PidsLimit={{.HostConfig.PidsLimit}}  OOMKilled={{.State.OOMKilled}}  Restarts={{.RestartCount}}' \
    "$CONTAINER" 2>/dev/null
  sub "cgroup memory container (byte)"
  echo "  current : $(incexec 'cat /sys/fs/cgroup/memory.current 2>/dev/null || cat /sys/fs/cgroup/memory/memory.usage_in_bytes 2>/dev/null')"
  echo "  peak    : $(incexec 'cat /sys/fs/cgroup/memory.peak 2>/dev/null || cat /sys/fs/cgroup/memory/memory.max_usage_in_bytes 2>/dev/null')"
  echo "  limit   : $(incexec 'cat /sys/fs/cgroup/memory.max 2>/dev/null || cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null')"
fi

# ===========================================================================
# 12. TEMUAN OTOMATIS + PERBAIKAN
# ===========================================================================
sec "12. TEMUAN OTOMATIS + PERBAIKAN"

# Kumpulkan config ZM ke associative array.
declare -A CFG=()
while IFS=$'\t' read -r k v; do
  [ -n "${k:-}" ] && CFG["$k"]="$v"
done < <(dbR <<'SQL'
SELECT Name, Value FROM Config WHERE Name IN (
 'ZM_WEB_H_STREAM_METHOD','ZM_WEB_M_STREAM_METHOD','ZM_WEB_L_STREAM_METHOD',
 'ZM_WEB_H_DEFAULT_SCALE','ZM_WEB_M_DEFAULT_SCALE','ZM_WEB_L_DEFAULT_SCALE',
 'ZM_WEB_H_REFRESH_STATUS','ZM_WEB_H_REFRESH_IMAGE','ZM_WEB_M_REFRESH_IMAGE',
 'ZM_WEB_ANIMATE_THUMBS','ZM_WEB_COMPACT_MONTAGE','ZM_WEB_LIST_THUMBS',
 'ZM_JPEG_STREAM_QUALITY','ZM_OPT_FAST_DELETE','ZM_OPT_ADAPTIVE_SKIP','ZM_OPT_CONTROL');
SQL
)
cv() { printf '%s' "${CFG[$1]:-}"; }

# Statistik per-monitor sebagai satu baris tab-separated.
MSTAS="$(dbR <<'SQL'
SELECT SUM(Function='Modect'), SUM(Function='Mocord'), SUM(Function='Record'), SUM(Function='Monitor'),
       SUM(SaveJPEGs=3), SUM(VideoWriter=0),
       SUM(Function IN ('Modect','Mocord') AND IFNULL(AnalysisFPSLimit,0)=0),
       SUM(IFNULL(MaxFPS,0)=0),
       COUNT(*)
FROM Monitors WHERE Function <> 'None';
SQL
)"
read -r N_MODECT N_MOCORD N_RECORD N_MONITOR N_JPEGALL N_VWOFF N_NOAFPS N_NOMAXFPS N_TOTAL <<< "$(printf '%s' "${MSTAS:-}" | awk -F'\t' '{for(i=1;i<=NF;i++) printf "%s ", ($i==""?"0":$i)}')"

FOUND=0
say() { printf '\n  [%s] %s\n' "$1" "$2"; }
fix() { printf '        perbaikan: %s\n' "$1"; }

# --- 12.1 Apache worker ---
if [ "${MSS:-0}" -gt 10 ] 2>/dev/null; then
  FOUND=$((FOUND+1))
  say "TINGGI" "MaxSpareServers=$MSS -> Apache menahan sampai $MSS worker PHP idle terus-menerus"
  [ -n "${APAVG:-}" ] && awk -v s="$MSS" -v a="$APAVG" 'BEGIN{printf "        biaya tetap: %s x %.1f MB = %.1f GB\n", s, a, s*a/1024}'
  fix "di zm-conf/apache-limit.conf: MinSpareServers 4, MaxSpareServers 8, MaxConnectionsPerChild 500"
fi
if [ "${MRW:-0}" -gt 200 ] 2>/dev/null; then
  FOUND=$((FOUND+1))
  say "SEDANG" "MaxRequestWorkers=$MRW terlalu tinggi untuk server ini"
  [ -n "${APAVG:-}" ] && awk -v m="$MRW" -v a="$APAVG" 'BEGIN{printf "        anggaran terburuk: %s x %.1f MB = %.1f GB\n", m, a, m*a/1024}'
  fix "turunkan ke jumlah kamera + 40 (mis. 100 untuk 60 kamera)"
fi
if [ "${KAR:-x}" = "0" ] 2>/dev/null; then
  FOUND=$((FOUND+1))
  say "SEDANG" "MaxKeepAliveRequests=0 -> worker tidak pernah didaur ulang saat stream MJPEG"
  fix "MaxKeepAliveRequests 100 (bukan 0)"
fi

# --- 12.2 Stream / skala ---
for p in H M L; do
  SC="$(cv ZM_WEB_${p}_DEFAULT_SCALE)"
  SM="$(cv ZM_WEB_${p}_STREAM_METHOD)"
  if [ "${SC:-0}" -ge 100 ] 2>/dev/null; then
    FOUND=$((FOUND+1))
    say "TINGGI" "ZM_WEB_${p}_DEFAULT_SCALE=$SC -> stream dikirim pada resolusi PENUH kamera"
    fix "UPDATE Config SET Value='33' WHERE Name='ZM_WEB_${p}_DEFAULT_SCALE';   (nilai sah: 25|33|50|75|100|150|200|300|400)"
  fi
  if [ "${SM:-}" = "jpeg" ]; then
    FOUND=$((FOUND+1))
    say "TINGGI" "ZM_WEB_${p}_STREAM_METHOD=jpeg -> tiap penonton MJPEG = 1 proses zms yang meng-JPEG tiap frame"
    fix "pakai profil bandwidth 'Low' di browser, atau UPDATE Config SET Value='mpeg' WHERE Name='ZM_WEB_${p}_STREAM_METHOD'; (nilai sah: mpeg|jpeg)"
  fi
done

if [ "$(cv ZM_WEB_ANIMATE_THUMBS)" = "1" ]; then
  FOUND=$((FOUND+1))
  say "TINGGI" "ZM_WEB_ANIMATE_THUMBS=1 -> thumbnail di console terus-menerus dibuat ulang (proses + CPU per thumbnail)"
  fix "UPDATE Config SET Value='0' WHERE Name='ZM_WEB_ANIMATE_THUMBS';"
fi
if [ "$(cv ZM_WEB_COMPACT_MONTAGE)" = "0" ]; then
  FOUND=$((FOUND+1))
  say "RENDAH" "ZM_WEB_COMPACT_MONTAGE=0 -> montage memuat elemen lebih berat"
  fix "UPDATE Config SET Value='1' WHERE Name='ZM_WEB_COMPACT_MONTAGE';"
fi
if [ "$(cv ZM_WEB_H_REFRESH_STATUS)" -le 3 ] 2>/dev/null; then
  FOUND=$((FOUND+1))
  say "SEDANG" "ZM_WEB_H_REFRESH_STATUS=$(cv ZM_WEB_H_REFRESH_STATUS) -> console polling status tiap detik"
  fix "UPDATE Config SET Value='10' WHERE Name='ZM_WEB_H_REFRESH_STATUS';"
fi

# --- 12.3 Analisa & frame ---
if [ "${N_NOAFPS:-0}" -gt 0 ] 2>/dev/null; then
  FOUND=$((FOUND+1))
  say "TINGGI" "$N_NOAFPS monitor dengan AnalysisFPSLimit kosong/0 -> motion analysis pada SETIAP frame"
  fix "UPDATE Monitors SET AnalysisFPSLimit=2 WHERE Function IN ('Modect','Mocord') AND IFNULL(AnalysisFPSLimit,0)=0;"
fi
if [ -n "${MISMATCH:-}" ]; then
  FOUND=$((FOUND+1))
  say "SEDANG" "resolusi monitor != resolusi yang dikirim kamera -> zmc men-scale tiap frame; decode tetap pada resolusi kamera"
  echo "        akibat: CPU decode (+RAM decoder, +bandwidth) dihitung pada resolusi KAMERA,"
  echo "                sedangkan RAM buffer dihitung pada resolusi MONITOR."
  fix "samakan resolusi di KAMERA dengan Width/Height monitor (main stream), atau pakai sub-stream (/Streaming/Channels/102)."
  fix "setelah restart: grep -c 'Monitor dimensions are' /var/log/zm/zmc_m*.log harus 0."
fi
if [ "${N_NOMAXFPS:-0}" -gt 0 ] 2>/dev/null; then
  FOUND=$((FOUND+1))
  say "TINGGI" "$N_NOMAXFPS monitor MaxFPS kosong -> ZM men-DECODE setiap frame yang dikirim kamera (terukur: CPU turun ~linear dengan MaxFPS)"
  fix "UPDATE Monitors SET MaxFPS=10 WHERE Function<>'None' AND IFNULL(MaxFPS,0)=0;   (uji terukur: MaxFPS 5 vs 25 -> 2.7% vs 12.0% CPU untuk 1 kamera 720p)"
fi
if [ "${N_JPEGALL:-0}" -gt 0 ] 2>/dev/null; then
  FOUND=$((FOUND+1))
  say "TINGGI" "$N_JPEGALL monitor SaveJPEGs=3 -> menyimpan JPEG untuk SETIAP frame alarm"
  fix "UPDATE Monitors SET SaveJPEGs=1 WHERE SaveJPEGs=3;   (1=frames alarm saja, 0=tidak sama sekali)"
fi
if [ "${N_VWOFF:-0}" -gt 0 ] 2>/dev/null; then
  FOUND=$((FOUND+1))
  say "SEDANG" "$N_VWOFF monitor VideoWriter=0 (nonaktif) padahal event tetap perlu video"
  fix "pertimbangkan VideoWriter=2 (passthrough) -> tidak re-encode, CPU hampir nol"
fi
if [ "$(cv ZM_OPT_FAST_DELETE)" = "0" ]; then
  FOUND=$((FOUND+1))
  say "TINGGI" "ZM_OPT_FAST_DELETE=0 -> hapus event baris-per-baris (DB + disk hammering saat PurgeWhenFull jalan)"
  fix "UPDATE Config SET Value='1' WHERE Name='ZM_OPT_FAST_DELETE';"
fi

# --- 12.4 Memori / disk ---
if printf '%s\n' "${MEMINFO:-}" | awk '/^SwapTotal:/{st=$2} /^SwapFree:/{sf=$2} END{exit !(st>0 && st-sf>0)}'; then
  FOUND=$((FOUND+1))
  say "KRITIS" "ada SWAP terpakai -> RAM benar-benar habis, sistem akan sangat lambat"
  fix "kurangi AnalysisFPSLimit / resolusi / jumlah kamera, atau tambah RAM"
fi
if [ "${APCNT:-0}" -gt 100 ] 2>/dev/null; then
  FOUND=$((FOUND+1))
  say "TINGGI" "ada $APCNT worker apache2 hidup -> hampir pasti stream MJPEG menggantung atau MaxSpareServers terlalu besar"
  fix "cek dengan: docker exec $CONTAINER ps -eo args= | grep -c nph-zms"
fi
if [ -n "${SHMTOT:-}" ] && [ "$SHMTOT" -gt 0 ] 2>/dev/null; then
  awk -v b="$SHMTOT" -v n="${MONN:-1}" 'BEGIN{ if(n>0 && b/n/1048576 > 200) \
    printf "\n  [SEDANG] shared memory per kamera %.0f MB (>200 MB) -> resolusi/ring buffer terlalu besar\n", b/n/1048576 }'
fi

if [ "$FOUND" -eq 0 ]; then
  echo "  Tidak ada temuan otomatis. Konfigurasi dasar sudah wajar."
  echo "  Kalau masih lambat, bandingkan fase 'closed' vs 'open' (lihat seksi 3 & 2)."
fi

echo
echo "  ------------------------------------------------------------------"
echo "  Skrip ini READ-ONLY. Semua blok 'perbaikan:' di atas hanya USULAN"
echo "  (perintah SQL/konfigurasi) — belum dijalankan."
echo "  ------------------------------------------------------------------"

printf '\n\033[1m### SELESAI (fase: %s). Tidak ada perubahan. ###\033[0m\n' "$PHASE"
