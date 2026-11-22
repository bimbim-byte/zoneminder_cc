"""Audit sisa warna hexa inline di halaman dashboard. Sekali pakai."""
import os

BASE = os.path.dirname(os.path.abspath(__file__))
FILES = ["index.html", "status.html", "checker.html", "zoneminder.html",
         "add_camera.html", "burst.html", "settings.html", "login.html"]

for name in FILES:
    path = os.path.join(BASE, name)
    if not os.path.exists(path):
        print("%s: (tidak ada)" % name)
        continue
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    hits = [(i + 1, l.strip()[:100]) for i, l in enumerate(lines)
            if 'style="background: #' in l]
    print("%s: %d" % (name, len(hits)))
    for ln, txt in hits:
        print("   %d: %s" % (ln, txt))
