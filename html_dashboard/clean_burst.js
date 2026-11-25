// Bersihkan sisa variabel mode zone lama di burst.html setelah sel tabel
// diganti menjadi pemilih Zone Preset per baris.
const fs = require('fs');
const path = 'burst.html';
let d = fs.readFileSync(path, 'utf8');
const before = d.length;

const rowModeDecl = "        const rowMode = cam.ZoneMode || '';\r\n";
if (d.includes(rowModeDecl)) d = d.replace(rowModeDecl, '');
else console.log('WARN: rowModeDecl tidak ditemukan');

const oldBlock =
  "        const presetInherited = !cam.ZonePreset;\r\n" +
  "        const zoneOptions = ZONE_MODES.map(m =>\r\n" +
  "          `<option value=\"${m.key}\" ${rowMode === m.key ? 'selected' : ''}>${m.short || m.label}</option>`\r\n" +
  "        ).join('');\r\n" +
  "        const inherited = !rowMode;\r\n";
if (d.includes(oldBlock)) {
  d = d.replace(oldBlock, "        const presetInherited = !cam.ZonePreset;\r\n");
} else {
  console.log('WARN: blok zoneOptions tidak ditemukan');
}

fs.writeFileSync(path, d);
console.log('panjang', before, '->', d.length);
console.log('rowMode', (d.match(/rowMode/g) || []).length,
            'zoneOptions', (d.match(/zoneOptions/g) || []).length,
            'presetOptions', (d.match(/presetOptions/g) || []).length);
