#!/bin/bash
# Ukur total bandwidth 6 stream bersamaan + beban CPU container ZoneMinder.
set -u
BASE="http://127.0.0.1:8080"

echo "=== MULAI 6 STREAM BERSAMAAN (12 detik) ==="
for id in 8 10 21 22 23 24; do
  curl -s -o /tmp/multi_$id.bin \
    -w "  id=$id HTTP:%{http_code} bytes=%{size_download} time=%{time_total}s\n" \
    --max-time 12 "$BASE/api/cameras/stream/$id?scale=320&maxfps=5" &
done
wait

echo
echo "=== TOTAL DATA ==="
python3 - <<'PY'
import glob, os
total = 0
for f in sorted(glob.glob('/tmp/multi_*.bin')):
    sz = os.path.getsize(f)
    total += sz
    print(f"  {os.path.basename(f)}: {sz/1024/1024:.2f} MB")
print(f"  TOTAL: {total/1024/1024:.2f} MB dalam 12 detik")
print(f"  Rata-rata: {total/12/1024/1024:.2f} MB/detik (~{total/12*8/1024/1024:.1f} Mbps)")
print(f"  Per kamera: ~{total/6/12/1024*8:.0f} kbps")
print(f"  Proyeksi 100 kamera @ maxfps=5, scale=320: ~{total/6/12*100/1024/1024*8:.0f} Mbps")
PY

echo
echo "=== BEBAN CPU/RAM ZONEMINDER ==="
docker stats --no-stream --format "{{.Name}}: CPU={{.CPUPerc}} RAM={{.MemUsage}}" zoneminder camera-dashboard
