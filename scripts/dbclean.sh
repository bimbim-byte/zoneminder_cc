#!/bin/bash
# Membersihkan SEMUA monitor uji (E2E_* dan PROBE_*) dari database.
# Trigger ZoneMinder menolak subquery pada tabel Monitors, jadi ID
# dikumpulkan dulu lalu dipakai sebagai daftar literal.
# Pemakaian: bash scripts/dbclean.sh
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
export MSYS_NO_PATHCONV=1

P="$(docker exec zm_db cat /run/secrets/mariadb_root_pass)"
Q() { docker exec zm_db mariadb -uroot -p"$P" zm -e "$1"; }

IDS="$(docker exec zm_db mariadb -uroot -p"$P" -N -B zm -e "SELECT Id FROM Monitors WHERE Name LIKE 'E2E_%' OR Name LIKE 'PROBE_%' OR Name LIKE 'BURST_%' OR Name LIKE 'CAM_E2E_%' OR Name LIKE 'ZZ_%' OR Name LIKE 'TEST_%_TRIAD' OR Name LIKE 'TEST_ZM138_%'" | tr '\n' ',' | sed 's/,$//')"

if [ -z "$IDS" ]; then
  echo "tidak ada monitor uji."
else
  echo "menghapus monitor: $IDS"
  Q "DELETE FROM Zones WHERE MonitorId IN ($IDS)"
  Q "DELETE FROM Monitors WHERE Id IN ($IDS)"
fi

echo "--- sisa monitor ---"
Q "SELECT Id,Name,Deleted,Enabled FROM Monitors"
