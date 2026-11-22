## Environment
- Windows host. Shell for `run_command` is **cmd.exe** (no `head`/`grep`). Git Bash: `"C:\Program Files\Git\bin\bash.exe" -c "..."`. Use `bash scripts/*.sh` for shell logic.
- Workspace: `e:\CodeFile\kemnaker\zoneminder_cc`. Docker 29.9.2, Compose **v5.7.0**, buildx v0.38.1, Desktop 4.98.0.
- `run_command` caps at 120s. cmd.exe mangles single quotes — use a script file.
- `docker exec` has no `curl` in camera-dashboard; use `python -c "import requests; ..."`.
- Files in the repo are **CRLF** — `replace_text` multi-line oldText often fails. Anchor on ONE line, or use PowerShell `[IO.File]::ReadAllText` + `.Replace()`.

## ZM 1.38 API TRAP — kamera "tidak muncul" walau dashboard bilang sukses (FIXED 2026-11-19)
Two independent causes, both silent:
1. **`Monitor[Device]` MUST be sent even when empty.** `api/app/Model/Monitor.php` validates Device with `#^(/dev/[\w/.\-]+)?$#` + `allowEmpty=>true`. `allowEmpty` only applies when the KEY IS PRESENT; if omitted, NULL hits the regex and validation FAILS even though the column is `NOT NULL DEFAULT ''`. Symptom: `{"message":{"Device":["Invalid device path. Must be a valid /dev/ path ..."]}}`.
2. **Success = `message`, not HTTP status.** `POST /monitors.json` returns **HTTP 200 for BOTH** `{"message":"Saved"}` and `{"message":{...validation errors...}}`. Edit path returns `"Error <pre>...</pre>"` on failure.

Fixes in `html_dashboard/app.py`:
- `Monitor[Device]: ""` at all 3 payload sites (add-camera ~725, burst ~880, `/api/zones/save-camera` ~2403). Documented as `DEVICE_REQUIRED` block.
- `_zm_explain_response(res)` → `(ok, message)`; `zm_post_monitor(path, data)` → `(ok, message, body)`. ALL monitor/zone/function writes use it.
- `get_monitor_zones()` prefers global `zones.json` (nested `/monitors/{id}/zones.json` is 404 on 1.38).
- Zone Id read from `{"zone":{"Zone":{"Id":N}}}`.

**MUST restart container after editing app.py** — old code stays in memory.

## MaxFPS CAPTURE CAP (KEY FINDING, 2026-11-19)
`AnalysisFPSLimit` caps **zma** (analysis); `MaxFPS` caps **zmc** (capture). Different things.
- `MaxFPS = NULL` (old default) → zmc ingests at native stream rate: measured **14.98 fps** (CAM_SQ_01) and **25.10 fps** (CAM_SQ_02).
- `MaxFPS = 10` → **10.00 fps** both. Verified by setting value + `zmdc.pl restart zmc -m N`.
- Old comment in `rtsp_path.py` claiming "MaxFPS sengaja tidak dikirim karena zmc membuang frame" was **WRONG** — corrected. Payload now sends `Monitor[MaxFPS]` + `Monitor[AlarmMaxFPS]` (=10) via `CAPTURE_FPS_DEFAULT` / `ALARM_MAX_FPS_DEFAULT`.
- Backfill for pre-fix cameras: `UPDATE Monitors SET MaxFPS=10, AlarmMaxFPS=10 WHERE MaxFPS IS NULL` then restart zmc.

## `Option timeout not recognized by ffmpeg` — COSMETIC, ignore
zmc 1.38 has its OWN whitelist (`thread_count`, `probesize`, `reorder_queue_size`, `buffer_size`, `rtsp_transport`, `udp_multicast`) — confirmed by grepping binary strings. `timeout` is NOT in it, so zmc warns, but the value IS forwarded to `av_dict` and ffmpeg 7.1.5 applies it (proved: `ffmpeg -rtsp_transport tcp -timeout 5000000 -i rtsp://...` reaches the camera, returns 401, no "option not found"). `verify_monitors.sh` therefore EXCLUDES this pattern.

## ZM API verified facts (1.38.6)
- Login: `POST /zm/api/host/login.json` `user=admin&pass=P@ssw0rd` → `{version:"1.38.6", apiversion:"2.0", access_token(JWT), ...}`.
- Zone create: `Zone[MonitorId]`, `Zone[Name]`, `Zone[Type]=Active`, `Zone[Units]=Pixels`, `Zone[Coords]="0,0 1279,0 1279,719 0,719"`, `Zone[NumCoords]`, `Zone[Area]`, `Zone[AlarmRGB]`, `Zone[CheckMethod]=Blobs`, `MinPixelThreshold=25`, `MinBlobs=1`, `OverloadFrames=0`. Returns `{"message":"Saved","zone":{"Zone":{...Id}}}`.
- **DELETE = SOFT delete**: `Deleted=1`, row stays, API still lists it. Tests must assert the `Deleted` flag, NOT row absence.
- MariaDB trigger blocks subqueries on `Monitors` inside DELETE (`ERROR 1442`) → collect IDs first.
- Called `DELETE monitors/{id}.json` leaves orphan rows in `Monitor_Status`/`Zones` — clean with `WHERE MonitorId NOT IN (SELECT Id FROM Monitors)`.

## Helper scripts (`scripts/`)
- `dbq.sh "<SQL>"` — root SQL into `zm_db`; MSYS_NO_PATHCONV + password handled. **Root has no password via `docker exec ... mariadb -uroot` directly — use this script.**
- `dbclean.sh` — removes `E2E_%`, `PROBE_%`, `BURST_%`, `CAM_E2E_%` test monitors.
- `verify_monitors.sh` — 13 assertions. **Monitor IDs are now discovered from DB** (was hardcoded `zmc_m1/m2` → broke after table was rebuilt with IDs 16/17). Also prints live `Monitor_Status`.
- `recreate_cameras.py` — re-registers CAM_SQ_01/CAM_SQ_02 **through the fixed dashboard API** (not raw SQL). Run: `docker cp scripts\recreate_cameras.py camera-dashboard:/app/` then `docker exec -e CAM_PASS=0p3r@t0r camera-dashboard python /app/recreate_cameras.py`.
- `smoke_http.sh` — probes dashboard `:9443` and ZM `:443` from inside caddy.

## Real camera sources (from `backups/zm_pre_138.sql`)
- `CAM_SQ_01` → `rtsp://operator:0p3r%40t0r@10.121.10.145:554/Streaming/Channels/101`
- `CAM_SQ_02` → `rtsp://operator:0p3r%40t0r@10.121.10.148:554/Streaming/Channels/101`
- User `operator`, pass `0p3r@t0r`. Current Ids **16** and **17** (table was rebuilt; old rows had `Method='rtsp'` + `Options='rtsp_transport=tcp'`).

## Test suites (in `html_dashboard/`, run in container) — ALL EXIT 0 as of 2026-11-19
- `http_api_test.py` (2), `error_path_test.py` (5), `e2e_api_test.py` (10), `burst_api_test.py` (5), `_verify_maxfps.py` (4, NEW), `_verify_encoding.py` (all paths), `_verify_rtsp_path.py` (40+).
- `_e2e_rtsp_payload.py` stubs `zm_post_monitor` AND `ensure_zone_for_monitor` (else creates REAL monitors).
- `_verify_encoding.py` hand-builds payloads → **must include `Monitor[Device]": ""`** or it reproduces the Device trap.
- Full-suite one-liner: `docker exec camera-dashboard sh -c "python /app/http_api_test.py >/tmp/a 2>&1; echo $?; ..."`

**`write_file` intermittently lands a 0-byte file.** ALWAYS `dir <path>` to verify; rewrite. Never write in parallel with another call.

## `docker compose build` / `up --build` BROKEN on this host
- Symptom `error getting credentials - err: exit status 1, out: ``` is a **misleading message**. Real cause = bake entitlement gate.
- NOT credentials: `docker-credential-desktop list` → `{}` rc=0 is normal. Do NOT delete `credsStore`.
- **WORKS:** `docker buildx bake --allow=fs.read=. -f docker-compose.yml --set zoneminder.tags=zoneminder_tuned:1.38.6 --set ui-interface.tags=zoneminder_cc-ui-interface:latest --set cctv-checker.tags=zoneminder_cc-cctv-checker:latest` then `docker compose up -d`.
- **Images already exist locally** — `docker compose up -d` alone starts the stack with NO rebuild. Try this FIRST when compose build errors.
- `docker compose build` has NO `--allow` flag → `up -d --build` can never work.

## RTSP credential normalisation (DONE)
- `html_dashboard/rtsp_path.py` single source of truth: `ANALYSIS_FPS_DEFAULT=8`, `CAPTURE_FPS_DEFAULT=10`, `ALARM_MAX_FPS_DEFAULT=10`, `ZM_FFMPEG_OPTIONS="timeout=5000000"`, `normalize_analysis_fps()`, `_monitor_fps_payload()` (sends `AnalysisFPSLimit` + `MaxFPS` + `AlarmMaxFPS`), `normalize_rtsp_path()`.
- Rule: userinfo = before LAST `@` followed by valid `host[:port]`; first `:` inside userinfo splits user:password. Output canonical `%40`/`%3A`/`%2F`, idempotent.

## Live stack — 5 services (all healthy)
`caddy_proxy` (80/443/9443), `zm_db` (mariadb:11.8), `zoneminder` (`zoneminder_tuned:1.38.6`, healthcheck), `camera-dashboard` (internal 8080), `cctv_checker_service`.

## ZM 1.38.6 facts
- No mysqld in image; DB external. Debian + s6-overlay. `/run` tmpfs must be `exec`.
- Method mapping: `rtpRtsp`→tcp, `rtpUni`→udp, `rtpMulti`→udp_multicast, `rtpRtspHttp`→http; else `Unknown method`.
- zmc reads config only at start → `zmdc.pl restart zmc -m N` or `zmpkg.pl restart`.
- `Monitors` FPS columns: `AnalysisFPSLimit decimal(5,2)`, `MaxFPS`, `AlarmMaxFPS` (all nullable), `FPSReportInterval=250`.
- `Monitor_Status` columns: `MonitorId, Status enum, CaptureFPS, CaptureBandwidth, AnalysisFPS, UpdatedOn`. **No `Connected` column — Status='Connected'.** This is the reliable live-metrics source, better than log scraping.
- Zones columns: `Type` enum(Active/Inclusive/Exclusive/Preclusive/Inactive/Privacy), `Units` enum(Pixels/Percent), `Coords` tinytext, `CheckMethod` enum(AlarmedPixels/FilteredPixels/Blobs).
- `zm.Logs` has no MonitorId (component `zmc_mN`); 0=INFO, -1=WAR, -2=ERR.
- Apache prefork + **mod_php**; PHP-FPM tuning = no-op. ffmpeg **7.1.5** ships in image.
- MariaDB `innodb_buffer_pool_size=2G` pinned deliberately; 8G risks OOM-killing zmc/zma. `shm_size:16g`.
- Caddy doesn't auto-reload `:ro` mount → `docker compose restart caddy-proxy`.

## Current live state (2026-11-19, verified)
2 monitors, both `Connected`, both **10.00 fps** capture, AnalysisFPS ~5 (zma throttles under load):
```
Id Name       Method  Options          AnalysisFPSLimit MaxFPS
16 CAM_SQ_01  rtpRtsp timeout=5000000  8.00             10.00
17 CAM_SQ_02  rtpRtsp timeout=5000000  8.00             10.00
```
`verify_monitors.sh` = 13/13 PASS.

## Open items
- Zone `All` still a single full-frame zone → `zma` false positives. Biggest remaining perf win = multi-zone layout.
- Intermittent `error -541478725 (End of file)` — camera flakiness, self-recovers.
- `KeepAliveTimeout` / `MaxKeepAliveRequests` untouched (suspected "dashboard loading forever").
- `html_dashboard/burst.html.bak_pre_encoding` still present.
- `diagnose_perf.sh` not yet exercised on the 60-camera host.
- Comments in `app.py` still say "ZM 1.36" in places — cosmetic.
- Rollback path never exercised end-to-end.
- Scale validation (60 cams @ 10 FPS): `Max_used_connections`, `Innodb_buffer_pool_reads` — NOT yet done.
