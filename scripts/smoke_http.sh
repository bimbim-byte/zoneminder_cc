#!/bin/bash
# =============================================================================
# Smoke test HTTP untuk stack CCTV (Caddy -> dashboard & ZoneMinder).
#
# Diuji dari DALAM network cctv_net (lewat container caddy) supaya tidak
# terpengaruh sertifikat self-signed di sisi host.
#
# Pemakaian: bash scripts/smoke_http.sh
# =============================================================================
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
export MSYS_NO_PATHCONV=1

probe() {
  label="$1"
  url="$2"
  out="$(docker exec caddy_proxy sh -c "wget -q -S -O /dev/null --no-check-certificate '$url' 2>&1 | head -1" 2>&1)"
  printf '%-24s %s\n' "$label" "${out:-NO-RESPONSE}"
}

echo "== Dashboard (port 9443) =="
probe "GET /"        "https://127.0.0.1:9443/"
probe "GET /login"   "https://127.0.0.1:9443/login"

echo ""
echo "== ZoneMinder lewat Caddy (port 443) =="
probe "GET /zm/"     "https://127.0.0.1/zm/"

echo ""
echo "== Status container =="
docker ps --format '{{.Names}}  {{.Status}}'
