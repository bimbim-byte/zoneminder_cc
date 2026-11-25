"""zoneminder.html: buang mode zone alternatif, tambahkan Zone Preset.

Pendekatan potong-per-baris dengan penanda unik. Tidak memakai regex DOTALL
supaya tidak pernah menghapus bagian berkas lain. Gagal keras bila penanda
tidak ditemukan.
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


# 1) Toolbar "Buat Zone Semua" (select + button + pembungkusnya).
i = find(lambda l: 'id="bulkZoneModeSelect"' in l, "bulkZoneModeSelect")
if i is not None:
    start = i
    while start > 0:
        if 'class="flex items-center gap-2 flex-wrap"' in lines[start - 1]:
            start -= 1
            break
        start -= 1
    j = find(lambda l: l.strip() == "</div>", "penutup toolbar", i)
    del lines[start:j + 1]
    report.append("toolbar Buat Zone Semua: %d baris" % (j - start + 1))
else:
    report.append("toolbar Buat Zone Semua: sudah bersih")

# 2) Label + select mode di modal edit -> diganti Zone Preset.
i = find(lambda l: 'for="editCamZoneMode"' in l, "label editCamZoneMode")
if i is not None:
    j = find(lambda l: 'id="editCamZoneMode"' in l, "select editCamZoneMode", i)
    lines[i:j + 1] = [
        '            <label class="form-label" for="editCamZonePreset">Zone Preset (untuk kamera baru)</label>\n',
        '            <select id="editCamZonePreset" class="form-select"></select>\n',
    ]
    report.append("modal edit: mode -> preset: diganti")
else:
    report.append("modal edit: mode -> preset: sudah bersih")

# 3) Deklarasi ZONE_MODES -> ZONE_PRESETS.
i = find(lambda l: l.strip() == "let ZONE_MODES = [];", "deklarasi ZONE_MODES")
if i is not None:
    lines[i] = "    let ZONE_PRESETS = [];\n"
    report.append("deklarasi: ZONE_PRESETS")
else:
    report.append("deklarasi ZONE_MODES: sudah bersih")

# 4) loadZoneModes() -> loadZonePresets().
i = find(lambda l: l.strip().startswith("async function loadZoneModes()"),
         "loadZoneModes()")
if i is not None:
    j = i
    depth = 0
    started = False
    while j < len(lines):
        depth += lines[j].count("{") - lines[j].count("}")
        if "{" in lines[j]:
            started = True
        if started and depth == 0:
            break
        j += 1
    new = [
        "    async function loadZonePresets() {\n",
        "      try {\n",
        "        const res = await fetch('/api/zones/zone-presets');\n",
        "        const data = await res.json();\n",
        "        ZONE_PRESETS = data.presets || [];\n",
        "        const select = document.getElementById('editCamZonePreset');\n",
        "        if (select) {\n",
        "          select.innerHTML = ZONE_PRESETS\n",
        "            .map(p => `<option value=\"${p.name}\" ${p.name === data.default ? 'selected' : ''}>${p.name}</option>`)\n",
        "            .join('');\n",
        "        }\n",
        "      } catch (e) {\n",
        "        console.error('Gagal memuat zone presets:', e);\n",
        "      }\n",
        "    }\n",
    ]
    lines[i:j + 1] = new
    report.append("loadZoneModes -> loadZonePresets")
else:
    report.append("loadZoneModes(): sudah bersih")

# 5) bulkSetZoneMode() dihapus seluruhnya.
i = find(lambda l: l.strip().startswith("async function bulkSetZoneMode()"),
         "bulkSetZoneMode()")
if i is not None:
    j = i
    depth = 0
    started = False
    while j < len(lines):
        depth += lines[j].count("{") - lines[j].count("}")
        if "{" in lines[j]:
            started = True
        if started and depth == 0:
            break
        j += 1
    while j + 1 < len(lines) and lines[j + 1].strip() == "":
        j += 1
    del lines[i:j + 1]
    report.append("bulkSetZoneMode(): %d baris" % (j - i + 1))
else:
    report.append("bulkSetZoneMode(): sudah bersih")

# 6) Payload: zoneMode -> zonePreset.
removed = 0
for i in range(len(lines) - 1, -1, -1):
    if "zoneMode: document.getElementById('editCamZoneMode').value," in lines[i]:
        indent = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
        lines[i] = indent + "zonePreset: (document.getElementById('editCamZonePreset') || {}).value || 'Default',\n"
        removed += 1
report.append("payload zoneMode -> zonePreset: %d" % removed if removed else "payload: sudah bersih")

# 7) Pemanggilan loadZoneModes() -> loadZonePresets().
removed = 0
for i in range(len(lines) - 1, -1, -1):
    if lines[i].strip() == "loadZoneModes();":
        indent = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
        lines[i] = indent + "loadZonePresets();\n"
        removed += 1
report.append("pemanggilan -> loadZonePresets(): %d" % removed if removed else "pemanggilan: sudah bersih")

src = "".join(lines)

with io.open(PATH, "w", encoding="utf-8", newline="") as f:
    f.write(src)

for r in report:
    print("  -", r)

leftovers = []
for i, line in enumerate(src.splitlines(), 1):
    if re.search(r"zoneMode|ZoneMode|ZONE_MODES|bulkSetZoneMode|bulkZoneModeSelect|"
                 r"loadZoneModes|editCamZoneMode|bulk-set-mode|/api/zones/modes|"
                 r"Buat Zone Semua", line):
        leftovers.append("%d: %s" % (i, line.strip()))

if leftovers:
    print("\nSISA REFERENSI (%d):" % len(leftovers))
    for line in leftovers:
        print("   ", line)
    sys.exit(1)

for tag in ("<script", "</script>", "<table", "</table>"):
    print("  %-12s %d" % (tag, src.count(tag)))

print("\nOK: zoneminder.html preset-only, tanpa mode zone alternatif.")
