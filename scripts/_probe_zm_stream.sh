#!/bin/bash
# Cari path CGI ZoneMinder yang benar untuk stream. Output ke file agar mudah dibaca.
set -u
OUT=/mnt/e/CodeFile/kemnaker/zoneminder_cc/scripts/_probe_result.txt
J=/tmp/zm_stream_probe.txt
rm -f $J
curl -s -c $J -X POST "http://127.0.0.1:8082/zm/api/host/login.json" -d "user=admin&pass=admin" >/dev/null

{
echo "=== KANDIDAT PATH STREAM (kamera id=8) ==="
for entry in \
  "nph-zms direct|http://127.0.0.1:8082/cgi-bin/nph-zms?mode=jpeg&monitor=8&scale=320" \
  "zm/cgi-bin|http://127.0.0.1:8082/zm/cgi-bin/nph-zms?mode=jpeg&monitor=8&scale=320" \
  "zm nph-zms|http://127.0.0.1:8082/zm/nph-zms?mode=jpeg&monitor=8&scale=320" \
  "single frame|http://127.0.0.1:8082/cgi-bin/nph-zms?mode=single&monitor=8&scale=320" \
  "zms alias|http://127.0.0.1:8082/cgi-bin/zms?mode=jpeg&monitor=8&scale=320" \
  ; do
  label="${entry%%|*}"
  url="${entry#*|}"
  info=$(curl -s -b $J -o /tmp/sprobe.out -w "%{http_code} type=%{content_type} bytes=%{size_download}" --max-time 8 "$url")
  echo "[$label] $info"
  echo "   $url"
done
} > "$OUT" 2>&1

{
echo
echo "=== ISI /usr/lib/zoneminder/cgi-bin/ ==="
docker exec zoneminder bash -lc 'ls -la /usr/lib/zoneminder/cgi-bin/ 2>&1'
echo
echo "=== SYMLINK /var/www/html ==="
docker exec zoneminder bash -lc 'ls -la /var/www/html/ 2>&1 | head -20'
echo
echo "=== KONFIG CGI APACHE ==="
docker exec zoneminder bash -lc 'grep -rn "cgi-bin\|ScriptAlias" /etc/apache2/ 2>/dev/null | grep -v "^Binary" | head -20'
} >> "$OUT" 2>&1

echo "SELESAI"
