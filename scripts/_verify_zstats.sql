-- Cek status pasca-upgrade skema 1.36.32 -> 1.38.6.
-- Dijalankan: docker exec -i zm_db sh /tmp/dbroot.sh -N -B zm < scripts/_verify_zstats.sql
SELECT CONCAT('db_version=', Value) FROM zm.Config WHERE Name='ZM_DYN_DB_VERSION';
SELECT CONCAT('auth=', Value) FROM zm.Config WHERE Name='ZM_OPT_USE_AUTH';
SELECT CONCAT('api=', Value) FROM zm.Config WHERE Name='ZM_OPT_USE_API';
SELECT CONCAT('monitors=', COUNT(*)) FROM zm.Monitors;
SELECT CONCAT('config_rows=', COUNT(*)) FROM zm.Config;
SELECT CONCAT('users=', COUNT(*)) FROM zm.Users;
SELECT CONCAT('events=', COUNT(*)) FROM zm.Events;
SELECT CONCAT('dir_events=', Value) FROM zm.Config WHERE Name='ZM_DIR_EVENTS';
SELECT CONCAT('opt=', Name, '=', Value) FROM zm.Config WHERE Name LIKE '%STAT%';
SELECT CONCAT('opt=', Name, '=', Value) FROM zm.Config WHERE Name LIKE '%SURVEY%';
