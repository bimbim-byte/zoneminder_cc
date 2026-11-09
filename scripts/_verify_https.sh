#!/bin/bash
# Verifikasi jalur HTTPS via Caddy: /wall, /wall/view, API, dan stream.
set -u
BASE="https://127.0.0.1"

echo "=== 1. HALAMAN VIA CADDY (HTTPS) ==="
for p in / /wall /wall/view "/wall/view?mode=all"; do
  printf '  %-28s -> ' "$p"
  curl -sk -o /dev/null -w "HTTP %{http_code}\n" "$BASE$p"
done

echo
echo "=== 2. API VIA CADDY ==="
for p in /api/cameras/groups /api/cameras/wall?mode=all; do
  printf '  %-40s -> ' "$p"
  curl -sk -o /tmp/c.json -w "HTTP %{http_code} bytes=%{size_download}\n" "$BASE$p"
done

echo
echo "=== 3. ISI groups ==="
curl -sk "$BASE/api/cameras/groups" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('  source:', d['source'], '| group:', len(d['groups']), '| kamera:', d['total_cameras'])
for g in d['groups']:
    print('    -', g['name'], '->', g['camera_count'], 'kamera')
"

echo
echo "=== 4. STREAM VIA CADDY (5 detik) ==="
curl -sk -o /tmp/cs.bin -w "  HTTP:%{http_code} type:%{content_type} bytes:%{size_download}\n" \
  --max-time 6 "$BASE/api/cameras/stream/8?scale=320&maxfps=5"

echo
echo "=== 5. CEK ROUTE /zm VIA CADDY (harus tetap ke ZM) ==="
printf '  /zm/                    -> '; curl -sk -o /dev/null -w "HTTP %{http_code}\n" "$BASE/zm/"
printf '  /zm/api/monitors.json   -> '; curl -sk -o /dev/null -w "HTTP %{http_code}\n" "$BASE/zm/api/monitors.json"
printf '  /zm/cgi-bin/nph-zms     -> '; curl -sk -o /dev/null -w "HTTP %{http_code}\n" --max-time 6 "$BASE/zm/cgi-bin/nph-zms?mode=jpeg&monitor=8&scale=320&maxfps=5"
