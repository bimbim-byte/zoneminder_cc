-- Status monitor ZoneMinder 1.38 (dibaca langsung dari DB, bukan dari UI).
-- Dijalankan: docker exec -i zm_db sh /tmp/dbroot.sh -N -B zm < scripts/_mon_status.sql
SELECT CONCAT('monitor_status_rows=', COUNT(*)) FROM zm.Monitor_Status;
SELECT CONCAT('id=', MonitorId, ' status=', IFNULL(Status,'?'),
              ' capture_fps=', IFNULL(CaptureFPS,'0'),
              ' analysis_fps=', IFNULL(AnalysisFPS,'0'))
FROM zm.Monitor_Status;
