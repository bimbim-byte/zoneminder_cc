# ============================================================================
# ZoneMinder with production tuning — image RESMI (ZM 1.38.6).
#
# Riwayat:
#   Sebelumnya image ini diturunkan dari pppasantos/zoneminder:latest (ZM
#   1.36.32, Ubuntu 18.04, MySQL 5.7 di dalam container). Sejak migrasi ke
#   arsitektur resmi, base image menjadi zoneminder/zoneminder:1.38.6 (Debian
#   stable) dan mysqld TIDAK lagi ada di dalam container ini, sehingga:
#     - mysql-tuning.cnf  -> pindah ke zm-conf/db-tuning.cnf (service "db")
#     - zm-root.conf      -> DIHAPUS. Image resmi sudah menangani root URL
#                            sendiri lewat /etc/apache2/conf-enabled/zm-docker.conf
#                            ("RedirectMatch ^/$ /zm/"). Menyalin alias root lama
#                            hanya menambah konflik Alias tanpa manfaat.
#   Salinan konfigurasi 1.36 disimpan di backups/ untuk keperluan rollback.
#
# Kenapa tetap image turunan (bukan bind mount)?
#   Tuning Apache perlu file di /etc/apache2/conf-enabled dengan permission
#   normal. Bind mount dari Windows (9p/drvfs) memaksa permission 777 dan
#   chmod gagal karena mount read-only; COPY ke layer image menyimpan 644
#   dengan benar di host mana pun (Proxmox/ext4 maupun Windows).
#
# Update ZoneMinder:
#   1. ganti tag di bawah, DAN tag "image:" di docker-compose.yml.
#   2. docker compose build zoneminder
#   3. docker compose up -d zoneminder
#
# Tag yang dipakai: versi eksplisit (bukan "latest", bukan "-es").
#   - "latest" bisa loncat ke 1.40/1.42 kapan saja -> upgrade skema tak terjadwal.
#   - "-es" membawa zmeventnotificationNg (push, WebSocket, MQTT); stack ini
#     sudah bersih dari MQTT, jadi varian itu tidak dipakai.
# ============================================================================
ARG ZM_BASE_IMAGE=zoneminder/zoneminder:1.38.6
FROM ${ZM_BASE_IMAGE}

# Tuning Apache: ServerLimit, worker prefork, keepalive untuk streaming MJPEG
# (wall dashboard 60+ kamera). Path ini diverifikasi ada di image 1.38.6
# (/etc/apache2/conf-enabled, berisi zm-docker.conf + zoneminder.conf).
COPY apache-limit.conf /etc/apache2/conf-enabled/apache-limit.conf

# 644 supaya Apache tidak mengabaikan file, dan chmod eksplisit menghindari
# warning "world-writable" bila context build berasal dari filesystem Windows.
RUN chmod 644 /etc/apache2/conf-enabled/apache-limit.conf \
 && apache2ctl -t 2>&1 | tail -3
