#!/bin/bash
# Smoke test endpoint wall dashboard.
set -u
BASE="http://127.0.0.1:8080"

echo "=== /api/cameras/groups ==="
curl -s "$BASE/api/cameras/groups" > /tmp/sg.json
python3 - <<'PY'
import json
d = json.load(open('/tmp/sg.json'))
print("source:", d['source'], "| total_cameras:", d['total_cameras'], "| jml group:", len(d['groups']))
for g in d['groups']:
    print("  group", g['id'], "|", g['name'], "| kamera:", g['camera_count'])
PY

echo
echo "=== /api/cameras/wall?mode=all ==="
curl -s "$BASE/api/cameras/wall?mode=all" > /tmp/sw.json
python3 - <<'PY'
import json
d = json.load(open('/tmp/sw.json'))
print("mode:", d['mode'], "| count:", d['count'])
for c in d['cameras'][:3]:
    print("  ", c['id'], c['name'], "fn=", c['function'], "en=", c['enabled'], "grp=", c['group_ids'])
PY

echo
echo "=== /api/cameras/wall?mode=groups ==="
GIDS=$(python3 -c "import json;print(','.join(g['id'] for g in json.load(open('/tmp/sg.json'))['groups']))")
echo "groups=$GIDS"
curl -s "$BASE/api/cameras/wall?mode=groups&groups=$GIDS" > /tmp/swg.json
python3 - <<'PY'
import json
d = json.load(open('/tmp/swg.json'))
print("mode:", d['mode'], "| count:", d['count'])
for c in d['cameras']:
    print("  ", c['id'], c['name'])
PY

echo
echo "=== halaman HTML ==="
for p in /wall /wall/view; do
  code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE$p")
  echo "  $p -> HTTP $code"
done
