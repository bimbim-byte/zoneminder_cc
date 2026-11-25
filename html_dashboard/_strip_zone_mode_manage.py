"""Perbaiki kerusakan struktur zoneminder.html + buang sisa mode zone.

Dijalankan di container. Pemeriksaan struktur dilakukan per blok; skrip
gagal keras bila penanda tidak ditemukan.
"""
import io
import re
import sys

PATH = "/app/zoneminder.html"

with io.open(PATH, encoding="utf-8") as f:
    lines = f.readlines()

report = []


def find(pred, what, start=0):
    for i in range(start, len(lines)):
        if pred(lines[i]):
            return i
    return None


def drop(start, end, label):
    del lines[start:end + 1]
    report.append("%s: %d baris" % (label, end - start + 1))


# --- 1. Sisa toolbar zone massal yang rusak (baris '<div ...> ... </div>'     ---
# Cari pola: baris berisi '<div class="flex items-center gap-2 flex-wrap">'
# yang TIDAK diikuti toolbar lain, dengan isi sisa 'Buat Zone Semua'.
i = find(lambda l: "Buat Zone Semua" in l, "tombol Buat Zone Semua")
if i is not None:
    # blok rusak: dari baris sebelumnya sampai '</div>' sesudah tombol
    start = i
    while start > 0 and not lines[start].strip().startswith("<div"):
        start -= 1
    end = find(lambda l: l.strip() == "</div>", "penutup div", i)
    drop(start, end, "sisa toolbar zone massal")
else:
    report.append("sisa toolbar zone massal: sudah bersih")

# --- 2. Modal edit: label + select editCamZoneMode ---------------------------
i = find(lambda l: 'for="editCamZoneMode"' in l, "label editCamZoneMode")
if i is not None:
    j = find(lambda l: 'id="editCamZoneMode"' in l, "select editCamZoneMode", i)
    drop(i, j, "modal edit dropdown mode")
else:
    report.append("modal edit dropdown mode: sudah bersih")

# --- 3. Deklarasi ZONE_MODES -------------------------------------------------
i = find(lambda l: l.strip() == "let ZONE_MODES = [];", "deklarasi ZONE_MODES")
if i is not None:
    drop(i, i, "deklarasi ZONE_MODES")
else:
    report.append("deklarasi ZONE_MODES: sudah bersih")

# --- 4. Fungsi loadZoneModes() lengkap ---------------------------------------
i = find(lambda l: l.strip().startswith("async function loadZoneModes()"),
         "loadZoneModes()")
if i is not None:
    # cari penutup fungsi: baris '    }' lalu satu baris kosong
    j = i
    depth = 0
    while j < len(lines):
        depth += lines[j].count("{") - lines[j].count("}")
        if depth <= 0 and j > i:
            break
        j += 1
    # ikutkan baris kosong sesudahnya
    if j + 1 < len(lines) and lines[j + 1].strip() == "":
        j += 1
    drop(i, j, "loadZoneModes()")
else:
    report.append("loadZoneModes(): sudah bersih")

# --- 5. Fungsi bulkSetZoneMode() lengkap -------------------------------------
i = find(lambda l: l.strip().startswith("async function bulkSetZoneMode()"),
         "bulkSetZoneMode()")
if i is not None:
    j = i
    depth = 0
    while j < len(lines):
        depth += lines[j].count("{") - lines[j].count("}")
        if depth <= 0 and j > i:
            break
        j += 1
    if j + 1 < len(lines) and lines[j + 1].strip() == "":
        j += 1
    drop(i, j, "bulkSetZoneMode()")
else:
    report.append("bulkSetZoneMode(): sudah bersih")

# --- 6. Payload zoneMode -----------------------------------------------------
removed = 0
for i in range(len(lines) - 1, -1, -1):
    if "zoneMode: document.getElementById('editCamZoneMode').value," in lines[i]:
        del lines[i]
        removed += 1
report.append("payload zoneMode: %d baris" % removed if removed else "payload zoneMode: sudah bersih")

# --- 7. Pemanggilan loadZoneModes() -----------------------------------------
removed = 0
for i in range(len(lines) - 1, -1, -1):
    if lines[i].strip() == "loadZoneModes();":
        del lines[i]
        removed += 1
report.append("pemanggilan loadZoneModes(): %d baris" % removed if removed else "pemanggilan loadZoneModes(): sudah bersih")

src = "".join(lines)

with io.open(PATH, "w", encoding="utf-8", newline="") as f:
    f.write(src)

for r in report:
    print("  -", r)

leftovers = []
for i, line in enumerate(src.splitlines(), 1):
    if re.search(r"zoneMode|ZoneMode|ZONE_MODES|Mode Zone Deteksi|bulkSetZoneMode|"
                 r"bulkZoneModeSelect|loadZoneModes|editCamZoneMode|bulk-set-mode|"
                 r"/api/zones/modes|Buat Zone Semua", line):
        leftovers.append("%d: %s" % (i, line.strip()))

if leftovers:
    print("\nSISA REFERENSI (%d):" % len(leftovers))
    for line in leftovers:
        print("   ", line)
    sys.exit(1)

print("\nOK: zoneminder.html bersih.")
