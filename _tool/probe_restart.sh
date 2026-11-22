#!/bin/sh
# Mencari bentuk perintah restart daemon ZM yang benar (stderr dibiarkan tampil).
set -x
docker exec zoneminder zmdc.pl restart "zmc -m 2"
echo "exit=$?"
docker exec -u www-data zoneminder zmdc.pl restart "zmc -m 2"
echo "exit_wwwdata=$?"
docker exec zoneminder ls -l /run/zm
docker exec zoneminder zmdc.pl status
