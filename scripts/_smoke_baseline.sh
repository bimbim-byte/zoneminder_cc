#!/bin/bash
# Bandingkan beban ZM tanpa stream dashboard vs dengan stream.
set -u
OUT=/mnt/e/CodeFile/kemnaker/zoneminder_cc/scripts/_probe_result5.txt
BASE="http://127.0.0.1:8080"

{
echo "=== 1. BASELINE (tidak ada klien dashboard) ==="
sleep 5
docker stats --no-stream --format "{{.Name}}: CPU={{.CPUPerc}} RAM={{.MemUsage}}" zoneminder

echo
echo "=== 2. FUNGSI MONITOR ZM (apakah sedang merekam?) ==="
J=/tmp/zmb.txt
rm -f $J
curl -s -c $J -X POST "http://127.0.0.1:8082/zm/api/host/login.json" -d "user=admin&pass=admin" >/dev/null
curl -s -b $J "http://127.0.0.1:8082/zm/api/monitors.json" > /tmp/zm_mon_all.json
python3 - <<'PY'
import json
from collections import Counter
d = json.load(open('/tmp/zm_mon_all.json'))
ms = [x['Monitor'] for x in d.get('monitors', [])]
fn = Counter(m.get('Function') for m in ms)
print("  Distribusi Function:", dict(fn))
print("  Total monitor:", len(ms))
w = [m for m in ms if m.get('Width') and m.get('Height')]
if w:
    res = Counter(f"{m['Width']}x{m['Height']}" for m in w)
    print("  Distribusi resolusi:", dict(res))
PY

echo
echo "=== 3. JUMLAH PROSES zms/zmc DI ZM ==="
docker exec zoneminder bash -c 'ps aux | grep -E "zms|zmc|zmf" | grep -v grep | awk "{print \$11, \$12, \$13}" | sort | uniq -c | sort -rn | head -15' 2>&1

echo
echo "=== 4. JUMLAH CORE ==="
docker exec zoneminder bash -c 'nproc' 2>&1

echo
echo "=== 5. DENGAN 6 STREAM DASHBOARD ==="
for id in 8 10 21 22 23 24; do
  curl -s -o /dev/null --max-time 10 "$BASE/api/cameras/stream/$id?scale=320&maxfps=5" &
done
sleep 6
docker stats --no-stream --format "{{.Name}}: CPU={{.CPUPerc}} RAM={{.MemUsage}}" zoneminder
wait
} > "$OUT" 2>&1

echo DONE
