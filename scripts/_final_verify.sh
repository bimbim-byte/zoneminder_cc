#!/bin/bash
# Verifikasi akhir setelah normalisasi line ending.
set -u
cd /mnt/e/CodeFile/kemnaker/zoneminder_cc
BASE="http://127.0.0.1:8080"

echo "=== 1. SYNTAX PYTHON ==="
python3 scripts/_syntax_check.py html_dashboard/app.py

echo
echo "=== 2. KONTENA ==="
docker compose ps --format '{{.Name}}: {{.Status}}'

echo
echo "=== 3. ENDPOINT API ==="
printf '  groups  -> '; curl -s -o /tmp/v1.json -w "HTTP %{http_code}\n" "$BASE/api/cameras/groups"
printf '  wall    -> '; curl -s -o /tmp/v2.json -w "HTTP %{http_code}\n" "$BASE/api/cameras/wall?mode=all"
printf '  wall/g  -> '; curl -s -o /tmp/v3.json -w "HTTP %{http_code}\n" "$BASE/api/cameras/wall?mode=groups&groups=3,4"
printf '  /wall   -> '; curl -s -o /dev/null -w "HTTP %{http_code}\n" "$BASE/wall"
printf '  /wall/view -> '; curl -s -o /dev/null -w "HTTP %{http_code}\n" "$BASE/wall/view"

echo
echo "=== 4. ISI RINGKAS ==="
python3 - <<'PY'
import json
g = json.load(open('/tmp/v1.json'))
a = json.load(open('/tmp/v2.json'))
gr = json.load(open('/tmp/v3.json'))
print(f"  source group : {g['source']}")
print(f"  jumlah group : {len(g['groups'])}")
for x in g['groups']:
    print(f"     - {x['name']} ({x['camera_count']} kamera)")
print(f"  mode=all     : {a['count']} kamera")
print(f"  mode=groups  : {gr['count']} kamera")
PY

echo
echo "=== 5. UJI STREAM (5 detik) ==="
curl -s -o /tmp/vs.bin -w "  HTTP:%{http_code} type:%{content_type} bytes:%{size_download}\n" --max-time 6 "$BASE/api/cameras/stream/8?scale=320&maxfps=5"
echo "  frame JPEG: $(grep -c $'\xff\xd8' /tmp/vs.bin 2>/dev/null || echo '?')"
