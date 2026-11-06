#!/usr/bin/env python3
"""Sinkron daftar kamera ZoneMinder ke streams go2rtc (WebRTC/HLS montage).

go2rtc tidak punya API reload config, jadi file config ditulis lalu container
go2rtc di-restart. Untuk 100 kamera, restart per perubahan cukup.
"""
import json
import os
import shutil
import sys
import time

import requests
import urllib3
import yaml

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ZM_HOST = os.environ.get("ZM_HOST", "http://zoneminder:80")
ZM_USER = os.environ.get("ZM_USER", "admin")
ZM_PASS = os.environ.get("ZM_PASS", "admin")
GO2RTC_CONFIG = os.environ.get("GO2RTC_CONFIG", "/config/go2rtc.yaml")
GO2RTC_BASE = os.environ.get("GO2RTC_BASE", "/app/go2rtc.base.yaml")
GO2RTC_API = os.environ.get("GO2RTC_API", "http://go2rtc:1984")
SYNC_INTERVAL = int(os.environ.get("SYNC_INTERVAL", 60))

# Tuning montage: turunkan resolusi/fps transcode agar 100 stream bisa jalan.
GO2RTC_FFMPEG = (
    "ffmpeg:{input}#video=h264#width=320#height=180#fps=5"
)

session = requests.Session()
token = None


def zm_login():
    global token
    try:
        res = session.post(
            f"{ZM_HOST}/zm/api/host/login.json",
            data={"user": ZM_USER, "pass": ZM_PASS},
            verify=False, timeout=10,
        )
        if res.status_code == 200:
            token = res.json().get("access_token")
            return True
    except Exception as exc:
        print(f"[sync] login gagal: {exc}", flush=True)
    return False


def fetch_monitors():
    global token
    for attempt in (1, 2):
        try:
            res = session.get(
                f"{ZM_HOST}/zm/api/monitors.json",
                params={"token": token} if token else {},
                verify=False, timeout=15,
            )
            if res.status_code == 200:
                return [m["Monitor"] for m in res.json().get("monitors", []) if "Monitor" in m]
            if res.status_code in (401, 403) and attempt == 1:
                zm_login()
                continue
        except Exception as exc:
            print(f"[sync] ambil monitor gagal: {exc}", flush=True)
        break
    return []


def build_streams(monitors):
    streams = {}
    for mon in monitors:
        name = mon.get("Name") or f"monitor_{mon.get('Id')}"
        path = str(mon.get("Path") or "").strip()
        if not path.lower().startswith("rtsp://"):
            continue
        streams[name] = GO2RTC_FFMPEG.format(input=path)
    return streams


def write_base_config(monitors):
    """Tulis config awal ke volume go2rtc sebelum container go2rtc start."""
    if not os.path.exists(GO2RTC_BASE):
        return 0
    with open(GO2RTC_BASE, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    cfg["streams"] = build_streams(monitors)
    tmp = GO2RTC_CONFIG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg, fh, sort_keys=False)
    if os.path.exists(GO2RTC_CONFIG):
        os.remove(GO2RTC_CONFIG)
    shutil.copyfile(tmp, GO2RTC_CONFIG)
    os.remove(tmp)
    return len(cfg["streams"])


def push_streams(streams):
    """go2rtc API: semua stream didaftarkan tanpa menulis file."""
    added = 0
    for name, src in streams.items():
        try:
            res = session.put(
                f"{GO2RTC_API}/api/streams",
                params={"name": name, "src": src},
                timeout=5,
            )
            if res.status_code == 200:
                added += 1
        except Exception:
            return added
    return added


def main():
    last_signature = None
    while True:
        if not token:
            zm_login()
        monitors = fetch_monitors()
        signature = json.dumps(
            [(m.get("Id"), m.get("Name"), m.get("Path")) for m in monitors],
            sort_keys=True,
        )
        if signature != last_signature:
            streams = build_streams(monitors)
            try:
                if not os.path.exists(GO2RTC_CONFIG):
                    print(f"[sync] {write_base_config(monitors)} stream ditulis ke file awal", flush=True)
                print(f"[sync] {push_streams(streams)}/{len(streams)} stream didaftarkan ke go2rtc", flush=True)
                last_signature = signature
            except Exception as exc:
                print(f"[sync] gagal sinkron: {exc}", flush=True)
        else:
            print(f"[sync] tidak ada perubahan ({len(monitors)} monitor)", flush=True)
        time.sleep(SYNC_INTERVAL)


if __name__ == "__main__":
    sys.exit(main())
