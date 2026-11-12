# ============================================================================
# ZoneMinder with production tuning.
#
# Why a derived image instead of bind mounts?
# ZoneMinder (MySQL) REFUSES world-writable config files
# ("World-writable config file is ignored"). When config files are bind-mounted
# from a Windows filesystem (9p/drvfs), permissions are forced to 777 and chmod
# fails because the mount is read-only. With COPY into the image layer,
# permissions are stored correctly (644) and behave identically on any host
# (Proxmox/ext4 as well as Windows).
#
# Updating ZoneMinder: change the tag below, then
#     docker compose build zoneminder
#     docker compose up -d zoneminder
# ============================================================================
FROM pppasantos/zoneminder:latest

# MySQL tuning: buffer pool, connections, flush policy.
COPY mysql-tuning.cnf /etc/mysql/mysql.conf.d/zz-zm-tuning.cnf

# Apache tuning: ServerLimit, workers, keepalive.
COPY apache-limit.conf /etc/apache2/conf-enabled/apache-limit.conf

# Serve ZoneMinder at the domain root (/) without breaking its internal /zm/
# links. Read the header of zm-root.conf for the full rationale.
COPY zm-root.conf /etc/apache2/conf-enabled/zm-root.conf

# Apache tuning: ServerLimit, workers, keepalive.
# Permissions 644 are mandatory for MySQL config files.
# chmod -x also avoids the "world-writable" warning.
RUN chmod 644 /etc/mysql/mysql.conf.d/zz-zm-tuning.cnf \
 && chmod 644 /etc/apache2/conf-enabled/apache-limit.conf \
 && chmod 644 /etc/apache2/conf-enabled/zm-root.conf
