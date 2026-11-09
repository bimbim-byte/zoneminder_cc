#!/bin/bash
# Buktikan ZM men-share stream: N klien ke kamera SAMA -> berapa proses zms?
set -u
OUT=/mnt/e/CodeFile/kemnaker/zoneminder_cc/scripts/_probe_result6.txt
BASE="http://127.0.0.1:8080"

count_zms() {
  docker exec zoneminder bash -c 'ps aux | grep "[n]ph-zms" | wc -l' 2>/dev/null | tr -d '\r'
}

{
echo "=== 1. zms SEBELUM ==="
echo "  jumlah proses nph-zms: $(count_zms)"

echo
echo "=== 2. BUKA 8 KLIEN KE KAMERA YANG SAMA (id=8) ==="
for i in 1 2 3 4 5 6 7 8; do
  curl -s -o /dev/null --max-time 10 "$BASE/api/cameras/stream/8?scale=320&maxfps=5" &
done
sleep 5
echo "  jumlah proses nph-zms (8 klien, 1 kamera): $(count_zms)"
wait

echo
echo "=== 3. zms SETELAH SEMUA KLIEN PUTUS ==="
sleep 4
echo "  jumlah proses nph-zms: $(count_zms)"

echo
echo "=== 4. BUKA 6 KLIEN KE 6 KAMERA BERBEDA ==="
for id in 8 10 21 22 23 24; do
  curl -s -o /dev/null --max-time 10 "$BASE/api/cameras/stream/$id?scale=320&maxfps=5" &
done
sleep 5
echo "  jumlah proses nph-zms (6 klien, 6 kamera): $(count_zms)"
wait

echo
echo "=== 5. CPU dashboard saat streaming ==="
docker stats --no-stream --format "{{.Name}}: CPU={{.CPUPerc}} RAM={{.MemUsage}}" camera-dashboard
} > "$OUT" 2>&1

echo DONE
