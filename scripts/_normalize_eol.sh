#!/bin/bash
set -u
cd /mnt/e/CodeFile/kemnaker/zoneminder_cc

# Repo di-checkout di Windows sehingga semua file CRLF, sementara HEAD menyimpan LF.
# Normalisasi file yang kita ubah saja agar diff bersih.
for f in \
  html_dashboard/app.py \
  html_dashboard/index.html \
  html_dashboard/requirements.txt \
  html_dashboard/wall.html \
  html_dashboard/wall_view.html \
  README.md \
  PANDUAN_PENGGUNAAN.md \
  scripts/_syntax_check.py \
  ; do
  sed -i 's/\r$//' "$f"
  printf 'normalized: %s\n' "$f"
done

echo
echo "=== VERIFIKASI DIFF (harus hanya perubahan nyata) ==="
git --no-pager diff --numstat -- html_dashboard/app.py html_dashboard/index.html html_dashboard/requirements.txt README.md PANDUAN_PENGGUNAAN.md
