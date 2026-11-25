"""Hapus seluruh sisa "Mode Zone Deteksi (alternatif)" dari burst.html.

Dijalankan di container (bind mount /app = html_dashboard). Idempotent.
"""
import io
import re
import sys

PATH = "/app/burst.html"

with io.open(PATH, encoding="utf-8") as f:
    src = f.read()

original = src
report = []

for line in ('          "Zone": "medium",\n',
             '          "Zone": "light",\n',
             '          "Zone": "",\n'):
    if line in src:
        src = src.replace(line, "", 1)
        report.append("hapus kolom template: %s" % line.strip())

pattern_reader = re.compile(
    r"[ \t]*const rawZone = r\['Zone'\].*?\n"
    r"[ \t]*const zone = normalizeZoneCell\(rawZone\);\n", re.S)
src, n = pattern_reader.subn("", src)
report.append("hapus pembaca rawZone: %d" % n)

pattern_block = re.compile(
    r"[ \t]*const ZONE_ALIASES = \{.*?\n[ \t]*\}\n\n"
    r"[ \t]*function normalizeZoneCell\(value\) \{.*?\n[ \t]*\}\n\n", re.S)
src, n = pattern_block.subn("", src)
report.append("hapus blok ZONE_ALIASES: %d" % n)

src, n = re.subn(r"[ \t]*ZoneMode: zone,\n", "", src)
report.append("hapus ZoneMode baris Excel: %d" % n)
src, n = re.subn(r"[ \t]*ZoneMode: c\.ZoneMode \|\| '',\n", "", src)
report.append("hapus ZoneMode payload: %d" % n)
src, n = re.subn(r"[ \t]*zoneMode: document\.getElementById\('zoneMode'\)\.value,\n", "", src)
report.append("hapus zoneMode body POST: %d" % n)

if src != original:
    with io.open(PATH, "w", encoding="utf-8", newline="") as f:
        f.write(src)

for line in report:
    print("  -", line)

leftovers = [ln for ln in src.splitlines()
             if re.search(r"zoneMode|ZoneMode|ZONE_MODES|ZONE_ALIASES|"
                          r"normalizeZoneCell|Mode Zone Deteksi|rawZone", ln)]
if leftovers:
    print("\nSISA REFERENSI: %d" % len(leftovers))
    for ln in leftovers:
        print("   ", ln.strip())
    sys.exit(1)

print("\nOK: burst.html bersih dari mode zone alternatif.")
