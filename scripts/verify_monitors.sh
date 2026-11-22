#!/bin/bash
# =============================================================================
# Verifikasi konfigurasi monitor ZoneMinder 1.38 setelah normalisasi RTSP.
#
# Memeriksa EMPAT hal yang menjadi sumber bug sebelumnya:
#   1. Path tersimpan bersih (tidak ada '@' mentah kedua di dalam password).
#   2. AnalysisFPSLimit = 8 (default dashboard).
#   3. Method = rtpRtsp (bukan 'rtsp' legacy yang memicu "Unknown method").
#   4. Options tidak memuat opsi demuxer seperti rtsp_transport.
#   5. Log zmc tidak memuat peringatan "Unknown method" / "rtsp_transport".
#
# Pemakaian (Git Bash, root repo):
#   bash scripts/verify_monitors.sh
# =============================================================================
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
export MSYS_NO_PATHCONV=1

PASS=0
FAIL=0
ok()   { echo "  [OK]   $1"; PASS=$((PASS+1)); }
bad()  { echo "  [FAIL] $1"; FAIL=$((FAIL+1)); }

echo "== 1. Baris Monitors di database =="
ROWS="$(bash scripts/dbq.sh "SELECT CONCAT_WS('|',Id,Name,Method,IFNULL(Options,'-'),IFNULL(AnalysisFPSLimit,'-'),IFNULL(MaxFPS,'-'),Path) FROM Monitors ORDER BY Id" 2>&1)"

echo "$ROWS"
echo

# Setiap baris data diawali angka (Id); baris header dibuang.
DATA="$(printf '%s\n' "$ROWS" | grep -E '^[0-9]' || true)"
if [ -z "$DATA" ]; then
  bad "tidak ada baris monitor yang terbaca"
else
  ok "terbaca $(printf '%s\n' "$DATA" | wc -l | tr -d ' ') monitor"
fi

echo
echo "== 2. Pemeriksaan per monitor =="
while IFS='|' read -r id name method options fps maxfps path; do
  [ -z "${id:-}" ] && continue
  echo "Monitor #$id ($name)"

  # --- Method ---
  if [ "$method" = "rtpRtsp" ]; then
    ok "Method=rtpRtsp"
  else
    bad "Method='$method' (harus rtpRtsp)"
  fi

  # --- Options ---
  case "$options" in
    *rtsp_transport*) bad "Options memuat rtsp_transport (opsi demuxer, bukan input)" ;;
    -) ok "Options kosong" ;;
    *) ok "Options='$options' (tanpa rtsp_transport)" ;;
  esac

  # --- AnalysisFPSLimit ---
  case "$fps" in
    8|8.0|8.00) ok "AnalysisFPSLimit=8" ;;
    -)          bad "AnalysisFPSLimit NULL (harus 8)" ;;
    *)          bad "AnalysisFPSLimit=$fps (harus 8)" ;;
  esac

  # --- Path ---
  # Path yang benar memuat tepat SATU '@' yang berfungsi sebagai pemisah
  # userinfo/host. Password boleh memuat '@', tetapi harus sudah di-encode
  # menjadi %40 supaya tidak ambigu.
  raw_at=$(printf '%s' "$path" | tr -cd '@' | wc -c | tr -d ' ')
  if [ "$raw_at" -eq 1 ]; then
    ok "Path punya tepat 1 '@' (batas userinfo/host jelas)"
  else
    bad "Path punya $raw_at '@' -> kredensial korup: $path"
  fi

  case "$path" in
    rtsp://*|rtsps://*) ok "skema RTSP valid" ;;
    *)                  bad "skema bukan RTSP: $path" ;;
  esac

  echo
done <<< "$DATA"

echo "== 3. Log zmc: peringatan FFmpeg sejak capture terakhir =="
# PENTING: peringatan lama (sebelum Method/Options diperbaiki) sengaja TIDAK
# dihitung. Yang menentukan sehat/tidaknya konfigurasi SEKARANG adalah ada
# tidaknya peringatan setelah baris 'Starting Capture' yang terakhir.
#
# Kenapa "Option timeout not recognized by ffmpeg" TIDAK ikut dihitung:
#   zmc 1.38 punya daftar opsi ffmpeg internal (thread_count, probesize,
#   reorder_queue_size, buffer_size, rtsp_transport, ...). Nama "timeout"
#   tidak ada di daftar itu, jadi zmc memperingatkan — padahal opsi tersebut
#   TETAP diteruskan ke av_dict dan ffmpeg 7.1 memakainya sebagai timeout
#   socket RTSP. Bukti: `ffmpeg -rtsp_transport tcp -timeout 5000000 -i ...`
#   benar-benar mencoba koneksi (kamera membalas 401) tanpa error "option not
#   found". Jadi peringatan ini kosmetik; kalau ikut dihitung, pemeriksaan
#   akan SELALU gagal untuk konfigurasi yang justru sehat.
PATTERN='Unknown method|rtsp_transport|Unable to open input'

# ID monitor TIDAK boleh di-hardcode: setelah tabel Monitors dibuat ulang,
# ID bergeser (1,2 -> 16,17) dan log lama (zmc_m1/m2) berisi sisa uji lama
# yang membuat pemeriksaan gagal padahal konfigurasi sekarang benar.
MON_IDS="$(bash scripts/dbq.sh "SELECT Id FROM Monitors ORDER BY Id" 2>/dev/null | grep -E '^[0-9]+$' || true)"
if [ -z "$MON_IDS" ]; then
  bad "tidak ada ID monitor untuk diperiksa log-nya"
fi

for mid in $MON_IDS; do
  f="/var/log/zm/zmc_m${mid}.log"
  last_start=$(docker exec zoneminder sh -c "grep -n 'Starting Capture' '$f' 2>/dev/null | tail -1" | cut -d: -f1)
  [ -z "$last_start" ] && last_start=0

  total=$(docker exec zoneminder sh -c "grep -c -i -E '$PATTERN' '$f' 2>/dev/null" | tr -d '\r')
  [ -z "$total" ] && total=0

  after=$(docker exec zoneminder sh -c "tail -n +$last_start '$f' 2>/dev/null | grep -c -i -E '$PATTERN'" | tr -d '\r')
  [ -z "$after" ] && after=0

  name=$(basename "$f")
  if [ "$after" -eq 0 ]; then
    ok "$name: 0 peringatan aktif (historis: $total, diabaikan)"
  else
    bad "$name: $after peringatan AKTIF setelah capture terakhir"
    docker exec zoneminder sh -c "tail -n +$last_start '$f' 2>/dev/null | grep -i -E '$PATTERN' | head -3"
  fi
done

echo
echo "== 4. Status capture terakhir =="
for mid in $MON_IDS; do
  docker exec zoneminder sh -c "grep -h 'Capturing at' /var/log/zm/zmc_m${mid}.log 2>/dev/null | tail -1" 2>&1
done
echo
echo "   Metrik langsung dari Monitor_Status (lebih andal daripada log):"
bash scripts/dbq.sh "SELECT MonitorId,Status,CaptureFPS,AnalysisFPS,CaptureBandwidth FROM Monitor_Status ORDER BY MonitorId" 2>&1 \
  | sed 's/^/   /'

echo
echo "=========================================="
echo "LULUS: $PASS   GAGAL: $FAIL"
[ "$FAIL" -eq 0 ] && echo "SEMUA PEMERIKSAAN LULUS" || echo "ADA YANG GAGAL"
exit $([ "$FAIL" -eq 0 ] && echo 0 || echo 1)
