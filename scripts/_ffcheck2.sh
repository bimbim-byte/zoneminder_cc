#!/bin/bash
# Uji apakah opsi "timeout" (dipakai ZM 1.38 untuk Monitor[Options]) benar-benar
# diterapkan ke socket TCP. Bukti: tampilan error "Connection to tcp://..?timeout=N".
export MSYS_NO_PATHCONV=1

probe () {
  echo "=== $1 ==="
  docker exec zoneminder ffmpeg -hide_banner -loglevel debug -f rtsp $2 \
    -i "rtsp://127.0.0.1:9/probe" -t 1 -f null - 2>&1 \
    | grep -a -E "Connection to tcp|not recognized" | head -2
}

probe "kontrol (tanpa opsi)"          "-rtsp_transport tcp"
probe "timeout=5000000"               "-rtsp_transport tcp -timeout 5000000"
probe "rw_timeout=5000000"            "-rtsp_transport tcp -rw_timeout 5000000"
probe "timeout=5000000,rtsp_flags"    "-rtsp_transport tcp -timeout 5000000 -rtsp_flags prefer_tcp"
