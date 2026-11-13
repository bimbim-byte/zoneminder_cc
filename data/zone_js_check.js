// Pemeriksa sintaks JS untuk blok <script> inline pada halaman dashboard.
//
// html_dashboard/_zone_check.py hanya membandingkan JUMLAH kurung, sehingga
// tidak bisa melihat string/template literal yang menelan sisa berkas --
// persis penyebab halaman "diam" tanpa error yang terlihat. Skrip ini
// memakai parser V8 sungguhan lewat `vm.Script`, jadi ia adalah sumber
// kebenaran. Bila kedua pemeriksa berbeda pendapat, percayai skrip ini.
//
// Pemakaian (image dashboard hanya berisi Python, jadi jalankan lewat
// container Node dengan dua volume di bawah):
//
//   docker run --rm \
//     -v "<repo>/data:/data:ro" \
//     -v "<repo>/html_dashboard:/app:ro" \
//     node:20-alpine node /data/zone_js_check.js \
//     /app/add_camera.html /app/burst.html /app/zoneminder.html
//
// Tanpa argumen, ketiga halaman dashboard diperiksa.

const fs = require('fs');
const vm = require('vm');

const DEFAULT_PAGES = [
  '/app/add_camera.html',
  '/app/burst.html',
  '/app/zoneminder.html',
];

const SCRIPT_RE = /<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g;

const pages = process.argv.slice(2);
const targets = pages.length ? pages : DEFAULT_PAGES;

let problems = 0;
let checked = 0;

for (const file of targets) {
  let html;
  try {
    html = fs.readFileSync(file, 'utf8');
  } catch (err) {
    console.log('[GAGAL] ' + file + ' -- ' + err.message);
    problems++;
    continue;
  }

  const blocks = [...html.matchAll(SCRIPT_RE)];
  if (!blocks.length) {
    console.log('[LEWAT] ' + file + ' -- tidak ada blok script inline');
    continue;
  }

  checked += blocks.length;
  let bad = 0;

  blocks.forEach((match, index) => {
    const body = match[1];
    // Nomor baris HTML tempat isi <script> dimulai, supaya pesan galat
    // menunjuk baris berkas aslinya, bukan baris relatif blok.
    const offset = html
      .slice(0, match.index + match[0].indexOf('>') + 1)
      .split('\n').length;

    try {
      new vm.Script(body, { filename: file });
    } catch (err) {
      bad++;
      problems++;

      const first = String(err.stack).split('\n')[0] || '';
      const lineMatch = /:(\d+)$/.exec(first);
      const rel = lineMatch ? Number(lineMatch[1]) : 0;

      console.log('[RUSAK] ' + file + ' -- blok #' + (index + 1)
        + ' (mulai baris ' + offset + ')');
      console.log('        ' + err.message);

      if (rel) {
        console.log('        perkiraan baris HTML: ' + (offset + rel - 1));
        const lines = body.split('\n');
        const from = Math.max(0, rel - 3);
        const to = Math.min(lines.length - 1, rel + 1);
        for (let i = from; i <= to; i++) {
          const mark = (i + 1) === rel ? '>>' : '  ';
          console.log('        ' + mark + ' ' + lines[i]);
        }
      }
    }
  });

  if (!bad) {
    console.log('[OK]    ' + file + ' -- ' + blocks.length + ' blok script inline');
  }
}

console.log('');
if (problems) {
  console.log('HASIL: ' + problems + ' dari ' + checked
    + ' blok script gagal di-parse V8.');
  process.exit(1);
}
console.log('HASIL: ' + checked + ' blok script valid menurut parser V8.');
