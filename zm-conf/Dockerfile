# ============================================================================
# ZoneMinder dengan tuning produksi.
#
# Kenapa memakai image turunan, bukan bind mount?
# ZoneMinder (MySQL) MENOLAK file config yang world-writable
# ("World-writable config file is ignored"). Saat file config di-bind-mount
# dari filesystem Windows (9p/drvfs), permission dipaksa 777 dan chmod gagal
# karena mount read-only. Dengan COPY ke layer image, permission tersimpan
# benar (644) dan konsisten di host mana pun (Proxmox/ext4 maupun Windows).
#
# Update ZoneMinder: ganti tag di bawah lalu
#     docker compose build zoneminder
#     docker compose up -d zoneminder
# ============================================================================
FROM pppasantos/zoneminder:latest

# Tuning MySQL: buffer pool, koneksi, flush.
COPY mysql-tuning.cnf /etc/mysql/mysql.conf.d/zz-zm-tuning.cnf

# Tuning Apache: ServerLimit, worker, keepalive.
COPY apache-limit.conf /etc/apache2/conf-enabled/apache-limit.conf

# Permission 644 wajib untuk file config MySQL.
# chmod -x juga menghindari warning "world-writable".
RUN chmod 644 /etc/mysql/mysql.conf.d/zz-zm-tuning.cnf \
 && chmod 644 /etc/apache2/conf-enabled/apache-limit.conf
