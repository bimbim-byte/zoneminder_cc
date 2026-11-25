"""Pembersihan sisa mode zone di app.py (tahap 2 — idempotent)."""
import ast
import io
import re
import sys

PATH = "/app/app.py"

with io.open(PATH, encoding="utf-8") as f:
    lines = f.readlines()

report = []

# --- endpoint bulk-set-mode: dibuang seluruhnya ------------------------------
start = None
for i, line in enumerate(lines):
    if line.strip().startswith("@app.route") and "/api/zones/bulk-set-mode\"" in line:
        start = i
        break
if start is None:
    report.append("bulk-set-mode: sudah bersih")
else:
    end = None
    for k in range(start + 1, len(lines)):
        if "MAIN ENTRYPOINT" in lines[k]:
            end = k
            while end > start and not lines[end].startswith("# ="):
                end -= 1
            break
    if end is None:
        raise SystemExit("TIDAK DITEMUKAN: batas akhir bulk-set-mode")
    del lines[start:end]
    report.append("bulk-set-mode: %d baris dihapus" % (end - start))

src = "".join(lines)

repl = [
    ("#    build_zone_payload() mengalikannya dengan Area zone yang sebenarnya.",
     "#    nilai ambang dikonversi dari persen ke piksel sesuai luas zone."),
    ("# di build_zone_payload() dari ZONE_MODES + luas zone sebenarnya.",
     "# dikonversi dari persen ke piksel sesuai luas zone sebenarnya."),
    ('"DUA JEBAKAN FORMAT" di atas ZONE_MODES.',
     '"DUA JEBAKAN FORMAT" pada komentar sejarah zone di atas.'),
    ("Aturan sama dengan ensure_zone_for_monitor():",
     "Aturan perlindungan zone manual sama dengan jalur registrasi:"),
    ("      zoneMode  : lightest | light | medium | heavy | heaviest\n", ""),
]
for old, new in repl:
    if old in src:
        src = src.replace(old, new)
        report.append("ganti komentar: %r" % old[:46])
    else:
        report.append("tidak ada (sudah bersih): %r" % old[:46])

try:
    ast.parse(src)
except SyntaxError as exc:
    print("\nGAGAL: hasil patch tidak valid Python: %s" % exc)
    sys.exit(1)

with io.open(PATH, "w", encoding="utf-8", newline="") as f:
    f.write(src)

leftovers = []
for i, line in enumerate(src.splitlines(), 1):
    if re.search(r"zone_mode|zoneMode|ZoneMode|ZONE_MODES|ZONE_MODE_DEFAULT|"
                 r"normalize_zone_mode|zone_modes_public|build_zone_payload|"
                 r"ensure_zone_for_monitor|effective_mode|row_mode", line):
        leftovers.append("%d: %s" % (i, line.strip()))

for r in report:
    print("  -", r)

if leftovers:
    print("\nSISA REFERENSI (%d):" % len(leftovers))
    for line in leftovers:
        print("   ", line)
    sys.exit(1)

print("\nOK: app.py bersih dari mode zone alternatif (sintaks valid).")
