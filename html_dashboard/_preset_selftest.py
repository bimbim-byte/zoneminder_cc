"""Uji cepat builder payload preset di dalam container (read-only)."""
import json

import app

print('jumlah preset:', len(app.zone_presets_public()))
print('normalisasi:', app.normalize_zone_preset('best_high'),
      app.normalize_zone_preset('FAST, MEDIUM SENSITIVITY'),
      app.normalize_zone_preset('Default'),
      app.normalize_zone_preset('tak-dikenal'))

payload, name = app.build_zone_preset_payload(38, 'Best, high sensitivity', 1280, 720)
print('preset:', name)
print(json.dumps(payload, indent=1))

# 'Best, high sensitivity': MinAlarm 8% dari Area 919601 = 73568
assert payload['Zone[MinAlarmPixels]'] == str(int(8 * 919601 / 100))
assert payload['Zone[CheckMethod]'] == 'Blobs'
assert payload['Zone[MinPixelThreshold]'] == '20'
assert 'Zone[MaxAlarmPixels]' not in payload, 'blank harus tidak dikirim'
assert 'Zone[MaxBlobs]' not in payload
assert payload['Zone[Coords]'] == '0,0 1279,0 1279,719 0,719'
print('ASSERT OK')
