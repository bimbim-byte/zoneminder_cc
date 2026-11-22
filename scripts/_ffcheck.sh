#!/bin/bash
export MSYS_NO_PATHCONV=1

test_opts () {
  local opts="$1"
  local raw_opts="$2"
  echo "=== Options: $raw_opts ==="
  docker exec zoneminder ffmpeg -hide_banner -loglevel warning -f rtsp \
    $opts -i "rtsp://127.0.0.1:9/probe" -t 1 -f null - 2>&1 \
    | grep -a -E "not recognized|Connection refused|No route|Invalid|Error" | head -4
  echo "--- end ---"
}

# 1) hanya rtsp_transport di level demuxer
test_opts "-rtsp_transport tcp" "rtsp_transport=tcp (demuxer, via Method)"

# 2) timeout sebagai opsi demuxer, dikirim lewat Monitor[Options]
test_opts "-rtsp_transport tcp -timeout 5000000" "timeout=5000000 (us)"

# 3) rw_timeout level protokol (harus lewat -rw_timeout, bukan Options)
test_opts "-rtsp_transport tcp -rw_timeout 5000000" "rw_timeout=5000000"

# 4) nilai salah sengaja untuk memastikan pesan 'not recognized' terdeteksi
test_opts "-rtsp_transport tcp -timeoutzzz 5" "timeoutzzz=5 (kontrol negatif)"
