#!/bin/sh
# Cari opsi timeout yang valid untuk protokol rtsp/tcp pada ffmpeg di container.
export MSYS_NO_PATHCONV=1
docker exec zoneminder ffmpeg -hide_banner -h full 2>/dev/null > /tmp/ffopts.txt
echo "== rtsp generic options (baris yang menyebut timeout) =="
grep -n "rw_timeout" /tmp/ffopts.txt | head -20
echo "== daftar protokol =="
ffmpeg -hide_banner -protocols 2>/dev/null | head -5
