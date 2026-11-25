// Tambahkan badge status zone per baris pada tabel pratinjau burst.html.
const fs = require('fs');
const p = 'burst.html';
let d = fs.readFileSync(p, 'utf8');

const anchor =
  "          : (isUrlOk ? '<span class=\"badge badge-neutral\">Siap</span>' : '<span class=\"badge badge-danger\">URL Salah</span>');\r\n";

if (!d.includes(anchor)) {
  console.log('ANCHOR NOT FOUND');
  process.exit(1);
}
if (d.includes('zonePresetResult ||')) {
  console.log('ALREADY PATCHED');
  process.exit(0);
}

const addition =
  "\r\n" +
  "        // Status zone per baris: dibuat / dilewati / gagal, beserta preset\r\n" +
  "        // yang benar-benar dipakai. Ditampilkan terpisah dari status monitor\r\n" +
  "        // karena keduanya bisa berbeda (monitor tersimpan, zone gagal).\r\n" +
  "        if (cam.zoneStatus === 'created') {\r\n" +
  "          badgeStatus += '<div class=\"text-xs\" style=\"margin-top:4px;\"><span class=\"badge badge-success\" title=\"' + (cam.zonePresetResult || '') + '\">Zone dibuat</span></div>';\r\n" +
  "        } else if (cam.zoneStatus === 'failed') {\r\n" +
  "          badgeStatus += '<div class=\"text-xs\" style=\"margin-top:4px;\"><span class=\"badge badge-danger\" title=\"' + (cam.zoneReason || '') + '\">Zone GAGAL</span></div>';\r\n" +
  "        } else if (cam.zoneStatus === 'skipped') {\r\n" +
  "          badgeStatus += '<div class=\"text-xs\" style=\"margin-top:4px;\"><span class=\"badge badge-neutral\" title=\"' + (cam.zoneReason || '') + '\">Zone dilewati</span></div>';\r\n" +
  "        }";

d = d.replace(anchor, anchor + addition);
fs.writeFileSync(p, d);
console.log('patched, length', d.length);
