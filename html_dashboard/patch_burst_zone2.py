# -*- coding: utf-8 -*-
"""Sisipkan Zone Preset ke burst.html - operasi per baris."""
import io
import sys

PATH = 'burst.html'
with io.open(PATH, encoding='utf-8', newline='') as f:
    lines = f.readlines()


def find(pred, what, start=0):
    for i in range(start, len(lines)):
        if pred(lines[i]):
            return i
    print('GAGAL [%s] tidak ditemukan' % what)
    sys.exit(1)


# 1. Panel default: dropdown preset sebelum dropdown mode lama.
i = find(lambda l: 'for="zoneMode"' in l and 'text-xs' in l, 'panel zoneMode label')
lines[i:i + 1] = [
    '              <label class="form-label text-xs" for="zonePreset">'
    'Zone Preset (Zone "All" dibuat otomatis)</label>\r\n',
    '              <select id="zonePreset" class="form-select text-xs" '
    'data-zone-preset></select>\r\n',
    '            </div>\r\n',
    '            <div class="form-group" style="margin-bottom: 0;">\r\n',
    '              <label class="form-label text-xs" for="zoneMode">'
    'Mode Zone Deteksi (alternatif)</label>\r\n',
]

# 2. Variabel.
i = find(lambda l: l.strip() == 'let ZONE_MODES = [];', 'deklarasi ZONE_MODES')
lines.insert(i + 1, '    let ZONE_PRESETS = [];\r\n')

# 3. Loader preset + helper sebelum loadZoneModes().
i = find(lambda l: 'async function loadZoneModes()' in l, 'loadZoneModes')
lines[i:i] = [
    '    // Zone Preset native ZoneMinder 1.38.6: daftar & urutan dari server,\r\n',
    '    // sama dengan halaman tambah kamera satuan.\r\n',
    '    async function loadZonePresets() {\r\n',
    "      const select = document.getElementById('zonePreset');\r\n",
    '      if (!select) return;\r\n',
    '      try {\r\n',
    "        const res = await fetch('/api/zones/zone-presets');\r\n",
    '        const data = await res.json();\r\n',
    '        ZONE_PRESETS = data.presets || [];\r\n',
    '        select.innerHTML = ZONE_PRESETS\r\n',
    '          .map(p => `<option value="${p.name}" '
    "${p.name === data.default ? 'selected' : ''}>${p.name}</option>`)\r\n",
    "          .join('');\r\n",
    '      } catch (err) {\r\n',
    "        select.innerHTML = '<option value=\"Default\" selected>Default</option>';\r\n",
    '      }\r\n',
    '      renderTable();\r\n',
    '    }\r\n',
    '\r\n',
    '    function normalizePresetCell(value) {\r\n',
    '      // Kolom Excel "Zone Preset": kosong -> ikut panel default;\r\n',
    "      // nama tak dikenal -> 'Default' + peringatan di console.\r\n",
    "      if (value === undefined || value === null) return { value: '', warn: '' };\r\n",
    '      const raw = String(value).trim();\r\n',
    "      if (!raw) return { value: '', warn: '' };\r\n",
    "      if (raw.toLowerCase() === 'default') return { value: 'Default', warn: '' };\r\n",
    "      const key = s => s.toLowerCase().replace(/[^a-z0-9]/g, '');\r\n",
    '      const hit = (ZONE_PRESETS || []).find(p => key(p.name) === key(raw));\r\n',
    "      if (hit) return { value: hit.name, warn: '' };\r\n",
    "      return { value: 'Default', warn: raw };\r\n",
    '    }\r\n',
    '\r\n',
    '    function currentPanelPreset() {\r\n',
    "      const select = document.getElementById('zonePreset');\r\n",
    "      return select && select.value ? select.value : 'Default';\r\n",
    '    }\r\n',
    '\r\n',
]

# 4. Panggil loader.
i = find(lambda l: l.strip() == 'loadZoneModes();', 'panggilan loadZoneModes')
lines.insert(i, '    loadZonePresets();\r\n')

# 5. renderTable: opsi preset per baris.
i = find(lambda l: "const rowMode = cam.ZoneMode || '';" in l, 'rowMode')
lines[i:i] = [
    '        const presetOptions = (ZONE_PRESETS || []).map(p =>\r\n',
    '          `<option value="${p.name}" '
    "${(cam.ZonePreset || '') === p.name ? 'selected' : ''}>${p.name}</option>`\r\n",
    "        ).join('');\r\n",
    '        const presetInherited = !cam.ZonePreset;\r\n',
]

# 6. renderTable: label panel -> preset.
i = find(lambda l: "const globalMode = document.getElementById('zoneMode').value;" in l, 'globalMode')
del lines[i:i + 2]
lines.insert(i, '      const globalPreset = currentPanelPreset();\r\n')

# 7. renderTable: sel preset menggantikan sel mode lama.
i = find(lambda l: 'min-width:110px' in l and 'ZoneMode' in l, 'sel ZoneMode')
j = find(lambda l: '</select>' in l, 'penutup select', start=i)
lines[i:j + 1] = [
    '              <select class="form-select text-xs" style="min-width:130px;" '
    "onchange=\"updateCamField(${idx}, 'ZonePreset', this.value)\">\r\n",
    '                <option value="" '
    "${presetInherited ? 'selected' : ''}>&#8627; Panel (${globalPreset})</option>\r\n",
    '                ${presetOptions}\r\n',
    '              </select>\r\n',
]

# 8. parseQuickList: preset baris.
i = find(lambda l: l.strip() == 'Name: `${prefix}${num}`,', 'push quick list')
lines.insert(i + 1, '          ZonePreset: currentPanelPreset(),\r\n')

# 9. Excel: baca kolom "Zone Preset".
i = find(lambda l: 'normalizeZoneCell(rawZone)' in l, 'normalizeZoneCell')
lines[i + 1:i + 1] = [
    "          const rawPreset = r['Zone Preset'] ?? r['ZonePreset'] ?? "
    "r['zone preset'] ?? r['zonePreset'];\r\n",
    '          const presetCell = normalizePresetCell(rawPreset);\r\n',
    "          if (presetCell.warn) console.warn('Preset zone tidak dikenal pada "
    "baris Excel:', presetCell.warn, '-> memakai Default');\r\n",
]

# 10. Excel: simpan ke objek baris.
i = find(lambda l: l.strip() == 'ZoneMode: zone,', 'object ZoneMode excel')
lines.insert(i + 1, '            ZonePreset: presetCell.value,\r\n')

# 11. Template Excel: contoh kolom.
for zone_literal, preset_literal in (
        ('"Zone": "medium",', '"Zone Preset": "Best, low sensitivity",'),
        ('"Zone": "light",', '"Zone Preset": "",'),
        ('"Zone": "",', '"Zone Preset": "Fast, high sensitivity",')):
    i = find(lambda l, z=zone_literal: z in l, 'template ' + zone_literal)
    lines.insert(i + 1, '          %s\r\n' % preset_literal)

# 12. Submit body: preset panel.
i = find(lambda l: "zoneMode: document.getElementById('zoneMode').value," in l, 'submit zoneMode')
lines.insert(i, '            zonePreset: currentPanelPreset(),\r\n')

# 13. Payload per monitor: preset baris.
i = find(lambda l: "ZoneMode: c.ZoneMode || ''," in l, 'payload ZoneMode')
lines.insert(i + 1, "            ZonePreset: c.ZonePreset || '',\r\n")

# 14. Ringkasan hasil per baris.
i = find(lambda l: 'zoneReason = det.zone_reason' in l, 'hasil zoneReason')
lines[i + 1:i + 1] = [
    '                cameraList[idx].zonePresetResult = det.zone_preset\r\n',
    "                  ? (det.zone === 'created' ? "
    "`created (Id=${det.zone_id || '?'})` : det.zone_preset)\r\n",
    "                  : '';\r\n",
]

with io.open(PATH, 'w', encoding='utf-8', newline='') as f:
    f.writelines(lines)

data = ''.join(lines)
print('OK preset-select=%d loader=%d helper=%d ZonePreset=%d col=%d'
      % (data.count('id="zonePreset"'), data.count('loadZonePresets'),
         data.count('normalizePresetCell'), data.count('ZonePreset'),
         data.count('"Zone Preset"')))
