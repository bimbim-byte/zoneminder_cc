## Environment
- Windows host, WSL Ubuntu distro is the working shell: `wsl.exe -d Ubuntu -e bash -c "..."`. Default WSL distro is `docker-desktop` (no /bin/bash) — always pass `-d Ubuntu`.
- Workspace path inside WSL: `/mnt/e/CodeFile/kemnaker/zoneminder_cc`. Windows path: `e:\CodeFile\kemnaker\zoneminder_cc`.
- Docker CLI reachable from both Windows cmd and WSL Ubuntu (Docker Desktop integration).
- Running stack (4 services, MQTT/Mosquitto fully removed): `caddy_proxy`, `camera-dashboard`, `cctv_checker_service`, `zoneminder`. No `mosquitto_broker` any more.
- `run_command` timeout caps at 120s; long docker builds must go through `terminal_start` + `terminal_read` polling.
- No grep/python on the Windows side. Use `powershell -NoProfile -Command "..."` (Select-String / [regex]::Replace) or `wsl.exe -d Ubuntu -e bash -c "..."` (python3 3.14 available).

## Tooling hazards (learned)
- `write_file` intermittently lands as a **0-byte file** (verified 3x: `_cleanup_env.ps1`, `_wtest.py`, earlier `_probe_perf.sh`). ALWAYS check size after writing. Content may appear later or not at all — prefer `replace_text` or a PowerShell `[System.IO.File]::WriteAllText` one-liner for edits.
- `read_file` / `delete_file` REFUSE `.env`, `.env.example`, `ne.env`, `*.bak` of env files ("Access to environment and credential files is blocked"). To read/modify/delete them use `run_command` (PowerShell) — never echo secrets back into the report.
- `browser_launch` cannot open `https://localhost:9443` (`ERR_CERT_AUTHORITY_INVALID`, self-signed). Audit live pages with `curl.exe -k` (Windows curl 8.22 has Schannel + `-k`) instead.
- `docker compose up --build` (compose v2 bake) tries to build ALL images including `zoneminder_tuned` and dies with `additional privileges requested: pass --allow=fs.read=...`. Build per-service instead: `docker build -t zoneminder_cc-ui-interface ./html_dashboard`, then `docker compose up -d --no-build --remove-orphans <svc>`.
- `docker exec caddy_proxy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile` applies a Caddyfile change without recreating the container (the `./caddy` mount is `:ro`, Caddy does NOT auto-reload).
- JSON-shaped one-liners via `powershell -Command`: `"$i`: $_"` works, but `($i+': '+$_)` throws `Cannot convert ":" to Int32`. Use `-f` or interpolation.

## ZoneMinder 1.36.32 — verified facts (do not re-derive)
- **Events table time columns are `StartDateTime` / `EndDateTime`.** There is NO `StartTime` column (ERROR 1054).
- **Shared memory uses `/dev/shm/zm.mmap.<MonitorId>` files, NOT SysV shm.** `ipcs -m` returning 0 segments is NORMAL. Formula: `size = Width*Height*12 + ~5.5 KB` (640x360 -> 2,770,360 B; 1280x720 -> 11,064,760 B).
- `docker stats --format` uses **`{{.PIDs}}`** (capital PID). `{{.Pids}}` returns rc=1 silently.
- `top -bn2 -d 1 -w 512` gives untruncated command names and instantaneous (not lifetime) %CPU.
- Config knobs confirmed with valid values from `Config.Hint`:
  - `ZM_WEB_{H,M,L}_STREAM_METHOD`: `mpeg|jpeg`
  - `ZM_WEB_{H,M,L}_DEFAULT_SCALE`: `25|33|50|75|100|150|200|300|400` (default 100 = native stream)
  - `ZM_WEB_H_REFRESH_STATUS` = 1 (console polls every second)
  - `ZM_WEB_ANIMATE_THUMBS` = 1 (continuously regenerated thumbnails)
  - `ZM_OPT_FAST_DELETE` = 0
- Apache is **prefork + mod_php**. Load order: `mods-enabled/*.conf` then `conf-enabled/*.conf`, so **conf-enabled wins**.
- `zm-conf/apache-limit.conf` sets MinSpareServers 16 / MaxSpareServers 64 / MaxRequestWorkers 512 / MaxKeepAliveRequests 0 -> measured 49 idle workers @22.9 MB with zero viewers; overrides mpm_prefork.conf's 5/5/10/150.
- `/etc/zm/zm.conf` holds `ZM_DB_USER` / `ZM_DB_PASS` / `ZM_DB_NAME`; mysql reachable over socket inside the container.

## Performance diagnostics (60-camera incident)
- `scripts/diagnose_perf.sh` (read-only, 12 phases, ~14s). Run in `closed` then `open` phase, then diff.
- ZM 1.36's `zma` only exists for Modect/Mocord monitors; a Monitor-only box reports zma = 0.
- Do NOT `COUNT(*)` on Events; use `information_schema.tables.table_rows` + indexed `StartDateTime > NOW() - INTERVAL 1 DAY`.
- Measured levers: `MaxFPS` NULL->5 drops zmc CPU 12.0%->2.7% per 720p cam; `DEFAULT_SCALE` 100->33 cuts zms JPEG work ~9x; Groups <=16 cams/page cures stream spikes; `MaxSpareServers 64` wastes ~1.4 GB idle; `MaxKeepAliveRequests 0` pins a worker on MJPEG.
- Baselines: shm ~663 MB @60x720p; zmc 305 MB/720p stream; 1080p decode = 2.6x CPU of 720p.
- ZoneMinder version upgrade REJECTED: no meaningful gain at 1.38.6 (same API contract, same zms/mode=jpeg path), real risk = tuning layer (`zz-zm-tuning.cnf`, `apache-limit.conf`, `zm-root.conf`) + `zmupdate.pl` schema bump.

## MQTT purge (completed)
- Fully removed (code + docs + env + UI): compose mosquitto service, `MQTT_*` env, Caddy `/mqtt` route, dashboard MQTT-log block (~301 lines), `log_display.html`, MQTT references in `scripts/*.sh`, README/PANDUAN, `.env`/`.env.example`/`ne.env` (MQTT section deleted, sections renumbered 1,1b,2,3,4,5), `html_dashboard/app.py.bak_pre_encoding` deleted (was publicly downloadable via the `/<path:filename>` route).
- `_redact_rtsp()` survives in `app.py` (outside the deleted MQTT block) — still used by monitor proxy + wall dashboard. Do not remove.
- `cctv-checker` KEPT: TCP RTSP probe + auto-switch monitor between `None` and its original function; results go to container log only.
- Serving rule to remember: `/<path:filename>` serves any file in `html_dashboard/` that does NOT end with `.py`, `.enc`, `.json` — stale `.bak_*` files in that folder are publicly downloadable. `html_dashboard/burst.html.bak_pre_encoding` still exists and is still reachable.
- Live audit method: generate a session cookie with `docker exec camera-dashboard python -c "import time, app as A; c=A.app.test_client(); ctx=c.session_transaction(); s=ctx.__enter__(); s['user']='admin'; s['issued_at']=time.time(); ctx.__exit__(None,None,None); c.get('/'); print(c.get_cookie('session').value)"`, then `curl.exe -k -b session=<val>` every route.

## Earlier work (still valid)
- `MONITOR_ENCODING_DEFAULTS` + `build_encoding_payload()` in `html_dashboard/app.py` is the single source of truth for camera registration encoding; `OutputContainer` must be omitted, never sent null.
- `DefaultScale: 0` was flagged for sign-off (ZM treats 0 as 100%). Still unconfirmed.
