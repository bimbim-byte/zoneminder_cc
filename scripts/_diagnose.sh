#!/usr/bin/env bash
# Diagnostic probe: WSL/CCTV stack readiness. Read-only.
echo "=== RAM ==="
free -h
echo "=== CPU ==="
nproc
echo "=== DISK /mnt/e ==="
df -h /mnt/e | tail -1
echo "=== .wslconfig ==="
for f in /mnt/c/Users/*/.wslconfig; do
  [ -f "$f" ] || continue
  echo "-- $f"
  cat "$f"
done
echo "=== WIN PORTS (80/443/8080/8082/1883/9001) ==="
if command -v netstat.exe >/dev/null 2>&1; then
  netstat.exe -ano 2>/dev/null | grep -E ':(80|443|8080|8082|1883|9001)[[:space:]]' | head -30
else
  echo "(netstat.exe unavailable)"
fi
echo "=== ZM STATE ==="
cat scripts/zm_monitor_state.json 2>/dev/null || echo "(no state file)"
echo "=== MOSQUITTO PASSWD ==="
ls -la mosquitto.passwd mosquitto/acl 2>/dev/null || echo "(no auth files)"