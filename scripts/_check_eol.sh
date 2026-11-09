#!/bin/bash
set -u
cd /mnt/e/CodeFile/kemnaker/zoneminder_cc

echo "=== Line ending di working tree vs HEAD ==="
for f in html_dashboard/app.py html_dashboard/index.html html_dashboard/requirements.txt README.md PANDUAN_PENGGUNAAN.md html_dashboard/wall.html html_dashboard/wall_view.html; do
  wt_crlf=$(grep -c $'\r' "$f" 2>/dev/null || echo 0)
  head_crlf=$(git show "HEAD:$f" 2>/dev/null | grep -c $'\r' || echo "N/A")
  printf '%-40s working-tree-CRLF=%-6s HEAD-CRLF=%s\n' "$f" "$wt_crlf" "$head_crlf"
done

echo
echo "=== Ukuran diff TANPA line-ending noise ==="
git --no-pager diff --stat --ignore-cr-at-eol -- html_dashboard/app.py html_dashboard/index.html html_dashboard/requirements.txt README.md PANDUAN_PENGGUNAAN.md
