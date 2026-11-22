#!/bin/sh
# Sumber kredensial DB untuk skrip tuning (tidak berisi password).
# Pemakaian dari bash (healthcheck di compose mengheredok bentuk ini):
#   docker exec -i zm_db sh -c '. /tmp/dbroot.sh; exec mariadb -uzmuser zm' < q.sql
# Password dibaca dari docker secret saat dijalankan, jadi tidak pernah
# tersimpan di file ini maupun di command line host.
#
# Catatan: skrip INI harus mengisi MYSQL_PWD lalu mengeksekusi mariadb lewat
# `exec`, sehingga penggilan di atas cukup '. /tmp/dbroot.sh; exec mariadb ...'
# dan password tidak muncul di argumen proses.

MYSQL_PWD="$(cat /run/secrets/zm_db_pass 2>/dev/null || cat /run/secrets/zm_db_pass.txt 2>/dev/null)"
export MYSQL_PWD
ZM_USER="${ZM_USER:-zmuser}"
ZM_DB="${ZM_DB:-zm}"
