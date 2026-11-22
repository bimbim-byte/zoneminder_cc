#!/bin/bash
# Menampilkan peringatan FFmpeg di log zmc beserta posisinya relatif terhadap
# proses capture terakhir. Tujuan: membedakan peringatan HISTORIS (sebelum
# Method/Options diperbaiki) dari peringatan yang masih hidup.
#
# Pemakaian: bash scripts/inspect_warnings.sh
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
export MSYS_NO_PATHCONV=1

PATTERN='Unknown method|rtsp_transport|Option .* not recognized|Unable to open input'

for f in /var/log/zm/zmc_m1.log /var/log/zm/zmc_m2.log; do
  echo "=== $(basename "$f") ==="

  last_start=$(docker exec zoneminder sh -c "grep -n 'Starting Capture' '$f' 2>/dev/null | tail -1" | cut -d: -f1)
  [ -z "$last_start" ] && last_start=0
  echo "baris 'Starting Capture' terakhir : $last_start"

  total=$(docker exec zoneminder sh -c "grep -c -i -E '$PATTERN' '$f' 2>/dev/null" | tr -d '\r')
  [ -z "$total" ] && total=0
  echo "total peringatan (semua waktu)  : $total"

  # tail -n +N mengambil baris mulai N, sehingga hanya peringatan SETELAH
  # capture terakhir yang terhitung.
  after=$(docker exec zoneminder sh -c "tail -n +$last_start '$f' 2>/dev/null | grep -c -i -E '$PATTERN'" | tr -d '\r')
  [ -z "$after" ] && after=0
  echo "peringatan SETELAH capture terakhir: $after"

  if [ "$after" -gt 0 ]; then
    echo "--- contoh (masih hidup) ---"
    docker exec zoneminder sh -c "tail -n +$last_start '$f' 2>/dev/null | grep -i -E '$PATTERN' | head -3"
  fi
  echo ""
done
