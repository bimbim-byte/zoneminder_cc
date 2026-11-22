#!/bin/sh
# ============================================================================
# Helper sementara migrasi ZoneMinder 1.36 -> 1.38.
#
# Menjalankan client mariadb sebagai root di dalam container "db" TANPA
# menaruh password di command line atau di environment milik host.
# Password dibaca dari docker secret yang sudah dimount container:
#   /run/secrets/mariadb_root_pass
#
# Dipakai oleh:
#   docker cp scripts/_db_root.sh zm_db:/tmp/dbroot.sh
#   docker exec -i zm_db sh /tmp/dbroot.sh zm < backups/zm_pre_138.sql
#
# Tidak dipakai oleh stack produksi; boleh dihapus setelah migrasi selesai.
# ============================================================================
MYSQL_PWD=$(cat /run/secrets/mariadb_root_pass) exec mariadb -uroot "$@"
