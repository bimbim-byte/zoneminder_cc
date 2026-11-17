import io
import sys

SRC = "/app/app.py"
BLOCK = "/tmp/block.py"
OUT = "/tmp/app_new.py"

src = io.open(SRC, encoding="utf-8").read()
block = io.open(BLOCK, encoding="utf-8").read()

anchor = "def zone_modes_public():"
idx = src.find(anchor)
print("anchor index:", idx)
if idx == -1:
    sys.exit("ANCHOR MISSING: " + anchor)

if "MONITOR_ENCODING_DEFAULTS" in src:
    sys.exit("BLOCK ALREADY PRESENT - aborting to avoid double insert")

new = src[:idx] + block + src[idx:]
assert new.count("MONITOR_ENCODING_DEFAULTS = {") == 1, "block count wrong"

io.open(OUT, "w", encoding="utf-8", newline="\n").write(new)
print("old chars:", len(src))
print("new chars:", len(new))
print("OK")
