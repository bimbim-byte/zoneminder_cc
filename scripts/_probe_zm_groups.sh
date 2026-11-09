#!/bin/bash
# Verifikasi: apakah Group ZM berfungsi (create -> list -> monitor GroupIds -> delete)
set -u
ZM="http://127.0.0.1:8082/zm/api"
J=/tmp/zm_cookies.txt
rm -f $J

curl -s -c $J -X POST "$ZM/host/login.json" -d "user=admin&pass=admin" > /dev/null

echo "=== BUAT GROUP TEST ==="
curl -s -b $J -c $J -X POST "$ZM/groups.json" \
  -d "Group[Name]=ZZ_Test_Group" -d "Group[MonitorIds][]=1" -d "Group[MonitorIds][]=2"
echo

echo "=== LIST GROUPS ==="
curl -s -b $J "$ZM/groups.json"
echo

echo "=== GROUPS recursive=1 ==="
curl -s -b $J "$ZM/groups.json?recursive=1" | head -c 700
echo

echo "=== MONITOR GroupIds setelah group dibuat ==="
curl -s -b $J "$ZM/monitors.json" > /tmp/m.json
python3 - <<'PY'
import json
d=json.load(open('/tmp/m.json'))
ms=d.get('monitors',[])
for x in ms[:4]:
    m=x['Monitor']
    print(" ", m.get('Id'), m.get('Name'), "| GroupIds=", repr(m.get('GroupIds')))
PY

echo
echo "=== GROUP MONITORS endpoint (id hasil di atas) ==="
GID=$(curl -s -b $J "$ZM/groups.json" | python3 -c 'import sys,json;g=json.load(sys.stdin).get("groups",[]);print(g[0]["Group"]["Id"] if g else "")')
echo "GID=$GID"
if [ -n "$GID" ]; then
  curl -s -b $J "$ZM/groups/$GID/monitors.json" | head -c 400
  echo
  echo "=== HAPUS GROUP TEST ==="
  curl -s -b $J -X DELETE "$ZM/groups/$GID.json" -w "HTTP:%{http_code}\n"
fi
echo "=== VERIFIKASI BERSIH ==="
curl -s -b $J "$ZM/groups.json"
echo