#!/usr/bin/env bash
# ==============================================================================
# Script: purge_continue_history.sh
# Deskripsi: Menghapus SELURUH jejak folder .continue/ dari riwayat Git.
#
# KENAPA PERLU:
#   Folder .continue/ pernah ter-commit dan berisi API key dalam bentuk
#   plaintext. Walaupun sekarang sudah di-untrack, key tersebut MASIH ADA di
#   riwayat commit dan dapat diambil siapa pun lewat `git log -p`.
#
# PERINGATAN KERAS — BACA SEBELUM MENJALANKAN:
#   1. Skrip ini MENULIS ULANG riwayat. Semua commit hash akan BERUBAH.
#   2. Kolaborator harus clone ulang atau menjalankan `git reset --hard`.
#   3. Butuh force-push. Bila repo dipakai bersama, koordinasikan dulu.
#   4. SKRIP INI TIDAK MEMBUAT BACKUP. Jalankan backup manual dulu:
#          git clone --mirror . ../zoneminder_cc-backup.git
#   5. Setelah dijalankan, TETAP ROTATE API key di penyedia layanan.
#      Menghapus dari riwayat tidak membatalkan key yang sudah terlanjur
#      tersalin (fork, cache, arsip pihak ketiga).
#
# Pemakaian:
#     bash scripts/purge_continue_history.sh            # mode uji (dry-run)
#     bash scripts/purge_continue_history.sh --apply    # benar-benar jalankan
#
# Opsi lingkungan:
#     SECRET_PATTERNS="sk-aaa sk-bbb"   Daftar pecahan string rahasia untuk
#                                       diverifikasi hilang setelah --apply.
#                                       Dipisah spasi. Contoh:
#         SECRET_PATTERNS='sk-8be0da340bed370c sk-c6a37828f0625270' \
#           bash scripts/purge_continue_history.sh --apply
#
# CATATAN VERIFIKASI:
#   Setelah --apply, cek sisa jejak dengan pencarian string PERSIS, bukan
#   pola 'sk-'. Nama paket seperti 'flask-cors' mengandung substring 'sk-c'
#   sehingga menghasilkan positif palsu bila hanya mencari pola 'sk-'.
#       git log --all -p | grep -c 'sk-8be0da340bed370c-l88lnf-b7297d9d'
#
# CATATAN REF:
#   `git filter-repo` menulis ulang SEMUA ref, termasuk refs/agents/* (checkpoint
#   sesi) dan branch lain seperti versi_2. Verifikasi memakai `git log --all`
#   supaya branch non-aktif tidak luput dari pemeriksaan.
# ==============================================================================

set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR" || exit 1

TARGET=".continue"
APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

echo "========================================================"
echo " Pembersihan riwayat Git: '$TARGET/'"
echo " Lokasi : $REPO_DIR"
echo " Mode   : $([ "$APPLY" -eq 1 ] && echo 'APPLY (menulis ulang riwayat)' || echo 'DRY-RUN (hanya memeriksa)')"
echo "========================================================"
echo

# ---------------------------------------------------------------- 0. Deteksi
if ! command -v git >/dev/null 2>&1; then
    echo "[GAGAL] git tidak ditemukan."
    exit 1
fi

if ! git rev-parse --git-dir >/dev/null 2>&1; then
    echo "[GAGAL] Direktori ini bukan repositori Git."
    exit 1
fi

# ---------------------------------------------------------------- 1. Cakupan
echo "[1/5] Menghitung commit yang mengandung '$TARGET/'..."
COUNT="$(git log --all --oneline -- "$TARGET" 2>/dev/null | wc -l | tr -d ' ')"
echo "      Ditemukan $COUNT commit."
if [ "$COUNT" -eq 0 ]; then
    echo
    echo " Riwayat sudah bersih. Tidak ada yang perlu dilakukan."
    exit 0
fi

echo "      Contoh commit:"
git log --all --oneline -- "$TARGET" 2>/dev/null | head -5 | sed 's/^/        /'

# ---------------------------------------------------------------- 2. Tool
echo
echo "[2/5] Memeriksa alat yang tersedia..."
FILTER_REPO=""

# git filter-repo tersedia sebagai subcommand git?
if git filter-repo --version >/dev/null 2>&1; then
    FILTER_REPO="git filter-repo"

# ...atau terpasang sebagai executable mandiri (~/.local/bin, dst.)?
# Penting: ~/.local/bin sering TIDAK ada di PATH untuk shell non-interaktif
# (mis. `wsl -- bash script.sh`), karena ~/.bashrc keluar lebih awal untuk
# shell non-interaktif. Jadi cari langsung di lokasi umum.
elif command -v git-filter-repo >/dev/null 2>&1; then
    FILTER_REPO="git-filter-repo"
else
    for candidate in \
        "$HOME/.local/bin/git-filter-repo" \
        "/usr/local/bin/git-filter-repo" \
        "/usr/bin/git-filter-repo"
    do
        if [ -x "$candidate" ] && "$candidate" --version >/dev/null 2>&1; then
            FILTER_REPO="$candidate"
            break
        fi
    done
fi

if [ -z "$FILTER_REPO" ]; then
    echo "      [GAGAL] 'git filter-repo' tidak terpasang."
    echo "      Pasang dulu, lalu jalankan ulang skrip ini:"
    echo "          sudo apt install git-filter-repo"
    echo "        atau (pip):"
    echo "          pip install git-filter-repo"
    echo
    echo "      Tanpa sudo (Ubuntu/Debian, terverifikasi):"
    echo "          cd /tmp"
    echo "          apt-get download git-filter-repo"
    echo "          mkdir -p gfrx && dpkg-deb -x git-filter-repo_*.deb gfrx"
    echo "          mkdir -p ~/.local/bin ~/.local/lib/pylib"
    echo "          cp gfrx/usr/lib/python3/dist-packages/git_filter_repo.py ~/.local/lib/pylib/"
    echo "          { echo '#!/usr/bin/env python3';"
    echo "            echo 'import os, sys';"
    echo "            echo 'sys.path.insert(0, os.path.join(os.path.expanduser(\"~\"), \".local\", \"lib\", \"pylib\"))';"
    echo "            tail -n +2 gfrx/usr/bin/git-filter-repo;"
    echo "          } > ~/.local/bin/git-filter-repo"
    echo "          chmod +x ~/.local/bin/git-filter-repo"
    echo
    echo "      Skrip ini mencari executable langsung, jadi PATH tidak wajib."
    echo "      Alternatif tanpa filter-repo (jalankan manual):"
    echo "          git filter-branch --force --index-filter \\"
    echo "            \"git rm -r --cached --ignore-unmatch $TARGET\" \\"
    echo "            --prune-empty --tag-name-filter cat -- --all"
    exit 1
fi
echo "      [ OK ] git filter-repo tersedia ($FILTER_REPO)."

# ---------------------------------------------------------------- 3. Backup
echo
echo "[3/5] Pemeriksaan keamanan..."
if [ "$APPLY" -eq 1 ]; then
    BACKUP_DIR="../$(basename "$REPO_DIR")-backup-$(date +%Y%m%d-%H%M%S).git"
    if [ -e "$BACKUP_DIR" ]; then
        echo "      [GAGAL] Folder backup sudah ada: $BACKUP_DIR"
        exit 1
    fi
    echo "      Membuat backup mirror di: $BACKUP_DIR"
    if git clone --mirror . "$BACKUP_DIR" >/dev/null 2>&1; then
        echo "      [ OK ] Backup dibuat."
    else
        echo "      [GAGAL] Backup gagal. Proses dihentikan demi keamanan."
        exit 1
    fi
else
    echo "      (dry-run) Backup akan dibuat di langkah ini saat --apply dipakai."
fi

# ---------------------------------------------------------------- 4. Jalankan
echo
echo "[4/5] Menjalankan pembersihan..."
IFS=' ' read -r -a PURGE_CMD <<< "$FILTER_REPO"
PURGE_CMD+=(--force --invert-paths --path "$TARGET")

if [ "$APPLY" -eq 1 ]; then
    "${PURGE_CMD[@]}" >/dev/null 2>&1
    if [ $? -eq 0 ]; then
        echo "      [ OK ] '$TARGET/' dihapus dari seluruh riwayat."
    else
        echo "      [GAGAL] filter-repo melaporkan error."
        echo "      Pulihkan dari backup: $BACKUP_DIR"
        exit 1
    fi
else
    echo "      Perintah yang AKAN dijalankan:"
    echo "        ${PURGE_CMD[*]}"
    echo
    echo "      Jalankan ulang dengan --apply untuk mengeksekusi."
fi

# ---------------------------------------------------------------- 5. Verifikasi
if [ "$APPLY" -eq 1 ]; then
    echo
    echo "[5/5] Verifikasi..."
    REMAIN="$(git log --all --oneline -- "$TARGET" 2>/dev/null | wc -l | tr -d ' ')"
    if [ "$REMAIN" -eq 0 ]; then
        echo "      [ OK ] Tidak ada lagi commit yang mengandung '$TARGET/'."
    else
        echo "      [GAGAL] Masih ada $REMAIN commit tersisa."
        echo "      Pulihkan dari backup: $BACKUP_DIR"
        exit 1
    fi

    # Sisa objek yang tidak lagi terjangkau (dangling) masih bisa dibaca
    # lewat `git fsck` sampai di-prune. Buang agar benar-benar hilang.
    git reflog expire --expire=now --all >/dev/null 2>&1 || true
    git gc --prune=now --quiet >/dev/null 2>&1 || true
    echo "      [ OK ] Reflog dibersihkan + object garbage-collected."

    # Cari string rahasia secara PERSIS, bukan pola 'sk-'.
    # Nama paket 'flask-cors' mengandung substring 'sk-c' -> positif palsu.
    #
    # Skrip ini SENDIRI memuat contoh string rahasia di komentar dokumentasi,
    # jadi kecualikan path-nya. Tanpa pengecualian ini, verifikasi akan selalu
    # melaporkan gagal walau riwayat sudah bersih.
    SELF_PATH="scripts/$(basename "${BASH_SOURCE[0]}")"
    echo
    echo "      Pemeriksaan string rahasia (butuh daftar; lewati bila kosong):"
    FOUND=0
    if [ -n "${SECRET_PATTERNS:-}" ]; then
        for pat in $SECRET_PATTERNS; do
            c="$(git rev-list --all \
                 | while read -r commit; do
                       git grep -l -- "$pat" "$commit" 2>/dev/null
                   done \
                 | sed 's/^[0-9a-f]*://' \
                 | sort -u \
                 | grep -v -F "$SELF_PATH" \
                 | wc -l | tr -d ' ')"
            c="${c:-0}"
            if [ "$c" -gt 0 ]; then
                echo "        [GAGAL] '$pat' masih ditemukan di $c berkas:"
                git rev-list --all \
                  | while read -r commit; do
                        git grep -l -- "$pat" "$commit" 2>/dev/null
                    done \
                  | sed 's/^[0-9a-f]*://' | sort -u \
                  | grep -v -F "$SELF_PATH" | sed 's/^/          /'
                FOUND=1
            else
                echo "        [ OK ] '$pat' tidak ditemukan."
            fi
        done
    else
        echo "        (dilewati) Set SECRET_PATTERNS untuk memeriksa eksplisit, mis.:"
        echo "        SECRET_PATTERNS='sk-8be0da340bed370c sk-c6a37828f0625270' \\"
        echo "          bash scripts/purge_continue_history.sh --apply"
        echo "        Atau cek manual dengan string PERSIS:"
        echo "          git log --all -p | grep -c 'sk-8be0da340bed370c'"
    fi

    # Objek terjangkau yang masih menyebut target. Kecualikan skrip ini sendiri
    # karena path-nya muncul di komentar/dokumentasi.
    DANGLING="$(git rev-list --all --objects 2>/dev/null \
                | grep -F "$TARGET" \
                | grep -v -F "$SELF_PATH" \
                | wc -l | tr -d ' ')"
    if [ "${DANGLING:-0}" -eq 0 ]; then
        echo "        [ OK ] Tidak ada objek terjangkau yang menyebut '$TARGET'."
    else
        echo "        [GAGAL] Masih ada $DANGLING objek menyebut '$TARGET':"
        git rev-list --all --objects 2>/dev/null \
          | grep -F "$TARGET" | grep -v -F "$SELF_PATH" | sed 's/^/          /'
        FOUND=1
    fi

    if [ "$FOUND" -eq 1 ]; then
        echo
        echo "      [GAGAL] Verifikasi tidak lolos. Pulihkan dari: $BACKUP_DIR"
        exit 1
    fi

    if [ -d "$TARGET" ]; then
        echo
        echo "      Catatan: folder '$TARGET/' masih ada di working tree"
        echo "               (diabaikan git, jadi tidak akan ter-commit lagi)."
    fi

    echo
    echo "========================================================"
    echo " SELESAI. Langkah manual yang masih WAJIB:"
    echo "========================================================"
    echo " 1. Periksa hasil:      git log --oneline -10"
    echo " 2. Push paksa SEMUA ref (termasuk branch lain):"
    echo "        git push --force --all"
    echo "        git push --force --tags"
    echo " 3. Beri tahu kolaborator untuk clone ulang."
    echo " 4. ROTATE API key di penyedia layanan — menghapus dari"
    echo "    riwayat TIDAK membatalkan key yang sudah tersalin."
    echo " 5. Hapus backup bila sudah yakin: $BACKUP_DIR"
    echo "========================================================"
else
    echo
    echo "========================================================"
    echo " DRY-RUN selesai. Tidak ada perubahan yang dibuat."
    echo " Untuk benar-benar menjalankan:"
    echo "     bash scripts/purge_continue_history.sh --apply"
    echo "========================================================"
fi
