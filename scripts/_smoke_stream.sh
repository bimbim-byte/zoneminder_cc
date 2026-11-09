#!/bin/bash
# Test stream MJPEG proxy dari wall dashboard.
set -u
BASE="http://127.0.0.1:8080"

for id in 8 10; do
  echo "=== stream kamera id=$id (scale=320) ==="
  curl -s -o /tmp/frame_$id.bin \
    -w "  HTTP:%{http_code} | type:%{content_type} | bytes:%{size_download} | time:%{time_total}s\n" \
    --max-time 12 "$BASE/api/cameras/stream/$id?scale=320"

  if [ -s /tmp/frame_$id.bin ]; then
    echo "  magic: $(head -c 60 /tmp/frame_$id.bin | tr -d '\0' | head -1)"
    echo "  jumlah boundary JPEG: $(grep -c $'\xff\xd8' /tmp/frame_$id.bin 2>/dev/null || echo '?')"
  else
    echo "  (kosong)"
  fi
done

echo
echo "=== cek container ZM masih sehat ==="
docker ps --filter name=zoneminder --format "{{.Names}} {{.Status}}"
