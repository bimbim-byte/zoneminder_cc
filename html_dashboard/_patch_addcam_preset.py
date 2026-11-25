# -*- coding: utf-8 -*-
"""Sisipkan logika Zone Preset ke add_camera.html — versi penuh."""
import io, sys

PATH = 'add_camera.html'

with io.open(PATH, encoding='utf-8', newline='') as f:
    src = f.read()

def rep(src, old, new, what):
    n = src.count(old)
    if n != 1:
        print('GAGAL [%s]: ditemukan %d kemunculan' % (what, n))
        sys.exit(1)
    return src.replace(old, new)

# 1. deklarasi variabel
src = rep(src, "    let ZONE_MODES = [];\r\n",
          "    let ZONE_MODES = [];\r\n    let ZONE_PRESETS = [];\r\n",
          'deklarasi')

# 2. loader + hint
anchor = "    async function loadZoneModes() {\r\n"
preset_js = (
"    // ----------------------------------------------------------------\r\n"
"    // Zone Preset native ZoneMinder 1.38.6. Daftar dan urutannya datang\r\n"
"    // dari server (/api/zones/zone-presets) supaya pilihan di halaman ini\r\n"
"    // tidak pernah menyimpang dari nilai yang benar-benar dikirim ke ZM.\r\n"
"    // ----------------------------------------------------------------\r\n"
"    async function loadZonePresets() {\r\n"
"      const select = document.getElementById('zonePreset');\r\n"
"      if (!select) return;\r\n"
"      try {\r\n"
"        const res = await fetch('/api/zones/zone-presets');\r\n"
"        const data = await res.json();\r\n"
"        ZONE_PRESETS = data.presets || [];\r\n"
"        select.innerHTML = ZONE_PRESETS\r\n"
"          .map(p => `<option value=\"${p.name}\" ${p.name === data.default ? 'selected' : ''}>${p.name}</option>`)\r\n"
"          .join('');\r\n"
"        renderZonePresetHint();\r\n"
"      } catch (err) {\r\n"
"        select.innerHTML = '<option value=\"Default\" selected>Default</option>';\r\n"
"        const hint = document.getElementById('zonePresetHint');\r\n"
"        if (hint) hint.innerText = 'Gagal memuat preset dari server. Memakai preset Default.';\r\n"
"      }\r\n"
"    }\r\n"
"\r\n"
"    function renderZonePresetHint() {\r\n"
"      const select = document.getElementById('zonePreset');\r\n"
"      const hint = document.getElementById('zonePresetHint');\r\n"
"      if (!select || !hint) return;\r\n"
"      const preset = ZONE_PRESETS.find(p => p.name === select.value);\r\n"
"      if (!preset) return;\r\n"
"      const blank = v => (v === null || v === undefined) ? 'blank' : v;\r\n"
"      hint.innerHTML = '<b>Efektif:</b> CheckMethod=' + preset.check_method\r\n"
"        + ', MinPixelThreshold=' + preset.min_pixel_threshold\r\n"
"        + ', MaxPixelThreshold=' + blank(preset.max_pixel_threshold) + ' (blank)'\r\n"
"        + ' &bull; Alarm Area ' + preset.min_alarm_pct + '/' + blank(preset.max_alarm_pct)\r\n"
"        + ' &bull; Filter ' + blank(preset.filter_x) + 'x' + blank(preset.filter_y)\r\n"
"        + ' &bull; Filter Area ' + blank(preset.min_filter_pct) + '/' + blank(preset.max_filter_pct)\r\n"
"        + ' &bull; Blob Area ' + blank(preset.min_blob_pct) + '/' + blank(preset.max_blob_pct)\r\n"
"        + ' &bull; Min Blobs ' + blank(preset.min_blobs)\r\n"
"        + '. Angka area = persen luas zone; dikonversi ke piksel oleh server.';\r\n"
"    }\r\n"
"\r\n"
"    function currentZonePreset() {\r\n"
"      const select = document.getElementById('zonePreset');\r\n"
"      return select && select.value ? select.value : 'Default';\r\n"
"    }\r\n"
"\r\n"
)
src = rep(src, anchor, preset_js + anchor, 'loader')

# 3. listener
src = rep(src,
"    document.getElementById('zoneMode').addEventListener('change', renderZoneHint);\r\n",
"    document.getElementById('zoneMode').addEventListener('change', renderZoneHint);\r\n"
"    document.getElementById('zonePreset').addEventListener('change', renderZonePresetHint);\r\n",
'listener')

# 4. panggilan loader
src = rep(src, "    loadZoneModes();\r\n",
          "    loadZonePresets();\r\n    loadZoneModes();\r\n", 'panggilan')

# 5. kirim preset saat submit
src = rep(src,
"            zoneMode: document.getElementById('zoneMode').value,\r\n",
"            zonePreset: currentZonePreset(),\r\n"
"            zoneMode: document.getElementById('zoneMode').value,\r\n",
'submit')

# 6. log hasil zone per preset
old_log = (
"          if (zone.created) {\r\n"
"            addLog(`[ZONE] Zone \"${zone.name || 'All'}\" dibuat (${zone.label || zone.mode}) @ ${zone.width}x${zone.height}.`, 'success');\r\n"
)
new_log = (
"          if (zone.created) {\r\n"
"            if (zone.preset) {\r\n"
"              addLog(`[ZONE] Zone \"${zone.zone_name || 'All'}\" dibuat dengan preset '${zone.preset}'` + (zone.zone_id ? ` (Zone Id=${zone.zone_id})` : '') + '.', 'success');\r\n"
"            } else {\r\n"
"              addLog(`[ZONE] Zone \"${zone.name || 'All'}\" dibuat (${zone.label || zone.mode}) @ ${zone.width}x${zone.height}.`, 'success');\r\n"
"            }\r\n"
)
src = rep(src, old_log, new_log, 'log')

# 7. reset form -> Default
src = rep(src,
"          document.getElementById('createZone').checked = true;\r\n",
"          document.getElementById('createZone').checked = true;\r\n"
"          const presetSelect = document.getElementById('zonePreset');\r\n"
"          if (presetSelect) {\r\n"
"            presetSelect.value = 'Default';\r\n"
"            renderZonePresetHint();\r\n"
"          }\r\n",
'reset')

with io.open(PATH, 'w', encoding='utf-8', newline='') as f:
    f.write(src)

print('OK loadZonePresets=%d currentZonePreset=%d zonePreset:=%d hint=%d'
      % (src.count('loadZonePresets'), src.count('currentZonePreset'),
         src.count('zonePreset:'), src.count('renderZonePresetHint')))
