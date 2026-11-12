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

# Operasikan pada repo DI MANA SKRIP DIJALANKAN, bukan pada lokasi skrip.
# Perbedaan ini penting saat menguji di mirror/clone: memakai lokasi skrip
# akan menulis ulang repo kerja, bukan salinan uji.
# Bila tidak berada di dalam repo Git, gunakan root repo skrip sebagai cadangan.
SCRIPT_REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if git rev-parse --git-dir >/dev/null 2>&1; then
    # Dukung repo bare/mirror: --show-toplevel kosong di bare repo.
    REPO_DIR="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
else
    REPO_DIR="$SCRIPT_REPO_DIR"
fi

cd "$REPO_DIR" || exit 1

GIT_DIR_ABS="$(git rev-parse --absolute-git-dir 2>/dev/null || echo '?')"

TARGET=".continue"
APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

echo "========================================================"
echo " Pembersihan riwayat Git: '$TARGET/'"
echo " Lokasi : $REPO_DIR"
echo " Git dir: $GIT_DIR_ABS"
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
#
# PENTING: `git log --all` TIDAK mencakup namespace ref non-standar seperti
# refs/agents/* (checkpoint sesi). Pada repo ini refs/agents/* memuat commit
# yang masih menyimpan berkas bocor, sehingga memakai --all saja membuat
# hasil verifikasi "bersih" padahal rahasia masih bisa diambil. Karena itu
# skrip mengumpulkan SELURUH ref lewat `git for-each-ref`.
ALL_REFS="$(git for-each-ref --format='%(refname)' 2>/dev/null)"

echo "[1/5] Menghitung commit yang mengandung '$TARGET/'..."
COUNT="$(git log --all --oneline -- "$TARGET" 2>/dev/null | wc -l | tr -d ' ')"

# Hitung ref (di luar --all) yang masih menyimpan $TARGET.
# CATATAN: `git log -- PATH REF` salah — git menganggap keduanya filter path.
# Pola yang benar adalah `git rev-list REF -- PATH`, karena -- memisahkan
# revisi dari pathspec.
OTHER_REFS=0
OTHER_LIST=""
for ref in $ALL_REFS; do
    n="$(git rev-list "$ref" -- "$TARGET" 2>/dev/null | wc -l | tr -d ' ')"
    if [ "${n:-0}" -gt 0 ]; then
        OTHER_REFS=$((OTHER_REFS + 1))
        OTHER_LIST="$OTHER_LIST$ref ($n commit)\n"
    fi
done
echo "      Ref ditemukan          : $(printf '%s\n' "$ALL_REFS" | grep -c .)"
echo "      Commit via --all       : $COUNT"
if [ "$OTHER_REFS" -gt 0 ]; then
    echo "      Ref lain menyentuh '$TARGET' : $OTHER_REFS"
    printf "        %b" "$OTHER_LIST"
    echo "        (ref di luar refs/heads|remotes|tags TIDAK masuk cakupan --all)"
fi
if [ "$COUNT" -eq 0 ] && [ "$OTHER_REFS" -eq 0 ]; then
    echo
    echo " Riwayat sudah bersih. Tidak ada yang perlu dilakukan."
    exit 0
fi

echo "      Contoh commit:"
git log --all --oneline -- "$TARGET" 2>/dev/null | head -5 | sed 's/^/        /'
for ref in $ALL_REFS; do
    git rev-list "$ref" -- "$TARGET" 2>/dev/null | head -3 | while read -r c; do
        echo "        [$ref] $(git log -1 --oneline "$c" 2>/dev/null)"
    done
done | head -5

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
#
# --refs wajib diberikan: tanpa itu filter-repo membuat "snapshot" dari
# refs/heads + refs/remotes saja, sementara refs/agents/* dibiarkan APA
# ADANYA. Akibatnya berkas bocor tetap bisa diambil lewat ref tersebut
# walau branch utama sudah bersih.
REFS_FILE="$(mktemp)"
trap 'rm -f "$REFS_FILE"' EXIT
printf '%s\n' $ALL_REFS > "$REFS_FILE"
echo "      Ref disertakan: $(wc -l < "$REFS_FILE" | tr -d ' ')"

if [ "$APPLY" -eq 1 ]; then
    # --refs MENOLAK path di luar direktori repo ("is outside repository").
    # Salin daftar ref ke dalam .git dengan nama yang tidak bentrok, jalankan,
    # lalu bersihkan.
    GIT_DIR_REAL="$(git rev-parse --absolute-git-dir)"
    REFS_IN_REPO="$GIT_DIR_REAL/purge-refs-$$.txt"
    cp "$REFS_FILE" "$REFS_IN_REPO"

    IFS=' ' read -r -a PURGE_CMD <<< "$FILTER_REPO"
    PURGE_CMD+=(--force --invert-paths --path "$TARGET" --refs "$REFS_IN_REPO")

    "${PURGE_CMD[@]}" >/dev/null 2>&1
    RC=$?
    rm -f "$REFS_IN_REPO"

    if [ "$RC" -eq 0 ]; then
        echo "      [ OK ] '$TARGET/' dihapus dari seluruh riwayat + ref."
    else
        echo "      [GAGAL] filter-repo melaporkan error (exit $RC)."
        echo "      Pulihkan dari backup: $BACKUP_DIR"
        exit 1
    fi
else
    echo "      Perintah yang AKAN dijalankan:"
    echo "        $FILTER_REPO --force --invert-paths --path $TARGET \\"
    echo "          --refs <daftar-ref-di-dalam-.git>"
    echo "        (daftar berisi $(wc -l < "$REFS_FILE" | tr -d ' ') ref)"
    echo
    echo "      Jalankan ulang dengan --apply untuk mengeksekusi."
fi

# ---------------------------------------------------------------- 5. Verifikasi
if [ "$APPLY" -eq 1 ]; then
    echo
    echo "[5/5] Verifikasi..."
    # Verifikasi harus memakai SELURUH ref, bukan `--all` saja.
    # `git log --all` melewatkan refs/agents/* sehingga berkas bocor bisa
    # lolos pemeriksaan walau branch utama sudah bersih.
    ALL_REFS_NOW="$(git for-each-ref --format='%(refname)' 2>/dev/null)"
    REMAIN=0
    REMAIN_LIST=""
    for ref in $ALL_REFS_NOW; do
        n="$(git rev-list "$ref" -- "$TARGET" 2>/dev/null | wc -l | tr -d ' ')"
        if [ "${n:-0}" -gt 0 ]; then
            REMAIN=$((REMAIN + 1))
            REMAIN_LIST="$REMAIN_LIST          $ref ($n commit)\n"
        fi
    done
    if [ "$REMAIN" -eq 0 ]; then
        echo "      [ OK ] Tidak ada ref yang mengandung '$TARGET/'."
    else
        echo "      [GAGAL] Masih ada $REMAIN ref yang mengandung '$TARGET/':"
        printf "        %b" "$REMAIN_LIST"
        echo "      Pulihkan dari backup: $BACKUP_DIR"
        exit 1
    fi

    # Sisa objek yang tidak lagi terjangkau (dangling) masih bisa dibaca
    # lewat `git fsck` sampai di-prune. Buang agar benar-benar hilang.
    # reflog expire dijalankan per-ref karena refs/agents/* tidak tercakup
    # oleh '--all' pada beberapa versi git.
    for ref in $ALL_REFS_NOW; do
        git reflog expire --expire=now --all "$ref" >/dev/null 2>&1 || true
    done
    git reflog expire --expire=now --all >/dev/null 2>&1 || true
    git gc --prune=now --aggressive --quiet >/dev/null 2>&1 || git gc --prune=now --quiet >/dev/null 2>&1 || true
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

    # Kumpulkan commit dari SEMUA ref (termasuk refs/agents/*).
    ALL_COMMITS_FILE="$(mktemp)"
    for ref in $ALL_REFS_NOW; do
        git rev-list "$ref" 2>/dev/null
    done | sort -u > "$ALL_COMMITS_FILE"
    echo "        (memindai $(wc -l < "$ALL_COMMITS_FILE" | tr -d ' ') commit dari semua ref)"

    if [ -n "${SECRET_PATTERNS:-}" ]; then
        for pat in $SECRET_PATTERNS; do
            hits="$(while read -r commit; do
                        git grep -l -- "$pat" "$commit" 2>/dev/null
                    done < "$ALL_COMMITS_FILE" \
                 | sed 's/^[0-9a-f]*://' \
                 | sort -u \
                 | grep -v -F "$SELF_PATH" || true)"
            c="$(printf '%s\n' "$hits" | grep -c . || true)"
            c="${c:-0}"
            if [ "$c" -gt 0 ]; then
                echo "        [GAGAL] '$pat' masih ditemukan di $c berkas:"
                printf '%s\n' "$hits" | sed 's/^/          /'
                FOUND=1
            else
                echo "        [ OK ] '$pat' tidak ditemukan."
            fi
        done
        rm -f "$ALL_COMMITS_FILE"
    else
        rm -f "$ALL_COMMITS_FILE"
        echo "        (dilewati) Set SECRET_PATTERNS untuk memeriksa eksplisit, mis.:"
        echo "        SECRET_PATTERNS='potongan-string-rahasia' \\"
        echo "          bash scripts/purge_continue_history.sh --apply"
        echo "        Atau cek manual dengan string PERSIS:"
        echo "          git log --all -p | grep -c 'potongan-string-rahasia'"
    fi

    # Objek terjangkau yang masih menyebut target, diperiksa dari SEMUA ref.
    # Kecualikan skrip ini sendiri karena path-nya muncul di dokumentasi.
    OBJ_FILE="$(mktemp)"
    for ref in $ALL_REFS_NOW; do
        git rev-list "$ref" --objects 2>/dev/null
    done | sort -u > "$OBJ_FILE"
    DANGLING="$(grep -F "$TARGET" "$OBJ_FILE" | grep -v -F "$SELF_PATH" | wc -l | tr -d ' ')"
    if [ "${DANGLING:-0}" -eq 0 ]; then
        echo "        [ OK ] Tidak ada objek terjangkau yang menyebut '$TARGET'."
    else
        echo "        [GAGAL] Masih ada $DANGLING objek menyebut '$TARGET':"
        grep -F "$TARGET" "$OBJ_FILE" | grep -v -F "$SELF_PATH" | sed 's/^/          /'
        FOUND=1
    fi
    rm -f "$OBJ_FILE"

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
