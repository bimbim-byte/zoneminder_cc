#!/bin/bash
# Probe ZoneMinder API: groups endpoint + GroupIds field availability
set -u

ZM="http://127.0.0.1:8082/zm/api"

echo "=== 1. LOGIN ==="
LOGIN=$(curl -s -X POST "$ZM/host/login.json" -d "user=admin&pass=admin")
echo "$LOGIN" | head -c 300
echo

TOKEN=$(echo "$LOGIN" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("access_token",""))' 2>/dev/null)
echo "TOKEN_LEN=${#TOKEN}"
if [ -z "$TOKEN" ]; then
  echo "[FATAL] Tidak dapat token. Coba pakai cookies session."
  exit 1
fi

echo
echo "=== 2. groups.json ==="
curl -s -o /tmp/zm_groups.json -w "HTTP:%{http_code}\n" "$ZM/groups.json?token=$TOKEN"
head -c 900 /tmp/zm_groups.json
echo

echo
echo "=== 3. monitors.json -> cek field Group* ==="
curl -s -o /tmp/zm_monitors.json "$ZM/monitors.json?token=$TOKEN"
python3 - <<'PY'
import json
d = json.load(open('/tmp/zm_monitors.json'))
ms = d.get('monitors', [])
print("JUMLAH MONITOR:", len(ms))
if ms:
    keys = sorted(ms[0]['Monitor'].keys())
    print("FIELD BER-NAMA GROUP:", [k for k in keys if 'roup' in k])
    for x in ms[:6]:
        m = x['Monitor']
        print(" ", m.get('Id'), m.get('Name'), "| GroupIds=", repr(m.get('GroupIds')), "| Groups=", repr(m.get('Groups')))
PY

echo
echo "=== 4. cek apakah ada monitor dengan GroupIds terisi ==="
python3 - <<'PY'
import json
d = json.load(open('/tmp/zm_monitors.json'))
ms = d.get('monitors', [])
filled = [x['Monitor'] for x in ms if x['Monitor'].get('GroupIds')]
print("MONITOR DENGAN GroupIds:", len(filled), "dari", len(ms))
for m in filled[:10]:
    print(" ", m.get('Id'), m.get('Name'), "->", m.get('GroupIds'))
PY
