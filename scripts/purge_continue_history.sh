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
# CATATAN VERIFIKASI:
#   Setelah --apply, cek sisa jejak dengan pencarian string PERSIS, bukan
#   pola 'sk-'. Nama paket seperti 'flask-cors' mengandung substring 'sk-c'
#   sehingga menghasilkan positif palsu bila hanya mencari pola 'sk-'.
#       git log --all -p | grep -c 'sk-8be0da340bed370c-l88lnf-b7297d9d'
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
if ! git filter-repo --version >/dev/null 2>&1; then
    echo "      [GAGAL] 'git filter-repo' tidak terpasang."
    echo "      Pasang dulu, lalu jalankan ulang skrip ini:"
    echo "          pip install git-filter-repo"
    echo "        atau (Ubuntu/Debian):"
    echo "          sudo apt install git-filter-repo"
    echo
    echo "      Alternatif tanpa filter-repo (jalankan manual):"
    echo "          git filter-branch --force --index-filter \\"
    echo "            \"git rm -r --cached --ignore-unmatch $TARGET\" \\"
    echo "            --prune-empty --tag-name-filter cat -- --all"
    exit 1
fi
echo "      [ OK ] git filter-repo tersedia."

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
PURGE_CMD=(git filter-repo --force --invert-paths --path "$TARGET")

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
        exit 1
    fi

    if [ -d "$TARGET" ]; then
        echo "      Catatan: folder '$TARGET/' masih ada di working tree"
        echo "               (diabaikan git, jadi tidak akan ter-commit lagi)."
    fi

    echo
    echo "========================================================"
    echo " SELESAI. Langkah manual yang masih WAJIB:"
    echo "========================================================"
    echo " 1. Periksa hasil:      git log --oneline -10"
    echo " 2. Push paksa:         git push --force --all"
    echo "                        git push --force --tags"
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
