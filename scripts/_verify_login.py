"""Bukti + pemicu deterministik error 'Unable to authenticate user from auth hash'.

Mekanisme (terverifikasi dari sumber ZoneMinder 1.36):
  ZM_AUTH_RELAY=hashed -> setiap URL internal ZM membawa ?auth=<md5>, dengan
      md5( secret . Username . Users.Password . remoteAddr . jam . hari . bulan . tahun )
  IP klien hanya diikutkan bila ZM_AUTH_HASH_IPS=1.

  ZM_AUTH_HASH_LOGINS=1 membuat userFromSession() memvalidasi ulang hash itu.
  Bila hash di sesi sudah basi (pergantian jam / password berubah / IP berubah),
  getAuthUser() tidak menemukan kecocokan dan menulis:
      ERR Unable to authenticate user from auth hash '<md5>'  auth.php:217
  setelah itu ZM jatuh ke jalur session (login tetap berhasil, log kotor).

Script ini:
  1) menghitung sendiri hash untuk kombinasi yang mungkin, mencocokkannya
     dengan hash yang muncul di log  -> membuktikan mekanisme,
  2) mengirim ?auth=<hash palsu> ke ZM -> memicu error yang sama, sehingga
     kita punya cara menguji perbaikan tanpa menunggu pergantian jam.
"""
import hashlib
import os
import re
import sys
import time

import requests

ZM_HOST = os.environ.get("ZM_HOST", "http://zoneminder:80")
ZM_WEB = ZM_HOST + "/zm"


def calc(secret, user, pwhash, remote, when):
    lt = time.localtime(when)
    return hashlib.md5(
        ("%s%s%s%s%d%d%d%d" % (
            secret, user, pwhash, remote, lt.tm_hour, lt.tm_mday, lt.tm_mon, lt.tm_year,
        )).encode()
    ).hexdigest()


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "calc"

    if mode == "calc":
        secret = os.environ.get("T_SECRET", "")
        user = os.environ.get("T_USER", "admin")
        pwhash = os.environ.get("T_PWHASH", "")
        target = os.environ.get("T_TARGET", "")
        print("secret=%r len=%d" % (secret, len(secret)))
        print("pwhash=%r" % pwhash)
        print("target=%s" % target)
        for remote in ("", "172.18.0.6", "172.18.0.5"):
            hits = 0
            for back in range(0, 24 * 400):
                when = time.time() - back * 3600
                if calc(secret, user, pwhash, remote, when) == target:
                    print("  MATCH remote=%r -%dh" % (remote, back))
                    hits += 1
                    break
            if not hits:
                print("  no match remote=%r" % remote)
        return 0

    if mode == "trigger":
        # Kirim hash palsu untuk memaksa jalur getAuthUser() -> error log.
        before = count_errors()
        res = requests.get(
            ZM_WEB + "/index.php",
            params={"auth": "00000000000000000000000000000000", "view": "console"},
            timeout=15,
            verify=False,
            allow_redirects=True,
        )
        time.sleep(1)
        after = count_errors()
        print("HTTP %s" % res.status_code)
        print("errors before=%s after=%s" % (before, after))
        return 0

    print("mode tidak dikenal: %s" % mode)
    return 2


def count_errors():
    import subprocess
    try:
        out = subprocess.run(
            ["grep", "-c", "Unable to authenticate user from auth hash",
             "/var/log/zm/web_php.log"],
            capture_output=True, text=True, timeout=10,
        )
        return (out.stdout or "0").strip()
    except Exception as exc:
        return "err:%s" % exc


if __name__ == "__main__":
    sys.exit(main())
