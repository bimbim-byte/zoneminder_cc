-- Verifikasi tuning MariaDB setelah migrasi ke arsitektur ZoneMinder resmi.
-- Dijalankan: docker exec -i zm_db sh /tmp/dbroot.sh -N -B < scripts/_verify_db.sql
SELECT CONCAT('pool_gb=', @@innodb_buffer_pool_size/1024/1024/1024);
SELECT CONCAT('max_connections=', @@max_connections);
SELECT CONCAT('isolation=', @@transaction_isolation);
SELECT CONCAT('time_zone=', @@time_zone);
SELECT CONCAT('charset=', @@character_set_server, '/', @@collation_server);
SELECT CONCAT('flush_trx=', @@innodb_flush_log_at_trx_commit);
SELECT CONCAT('log_bin=', @@log_bin);
SELECT CONCAT('tables_zm=', COUNT(*)) FROM information_schema.tables WHERE table_schema='zm';
SELECT CONCAT('config_rows=', COUNT(*)) FROM zm.Config;
SELECT CONCAT('monitors=', COUNT(*)) FROM zm.Monitors;
SELECT CONCAT('db_version=', Value) FROM zm.Config WHERE Name='ZM_DYN_DB_VERSION';
SELECT CONCAT('auth=', Value) FROM zm.Config WHERE Name='ZM_OPT_USE_AUTH';
