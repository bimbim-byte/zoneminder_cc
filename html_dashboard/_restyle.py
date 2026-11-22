"""Ganti palet hexa inline pada ikon stat dengan kelas bersama app_ui.css.

Sekali pakai, bukan bagian runtime aplikasi. Dijalankan di dalam container:
    docker exec camera-dashboard python3 /app/_restyle.py
"""
import os

REPL = [
    ("background: #e0f2fe; color: #0284c7;", "stat-icon--info"),
    ("background: #f0f9ff; color: #0284c7;", "stat-icon--info"),
    ("background: #f0fdf4; color: #16a34a;", "stat-icon--success"),
    ("background: #ecfdf5; color: #059669;", "stat-icon--success"),
    ("background: #fef3c7; color: #d97706;", "stat-icon--warning"),
    ("background: #f3e8ff; color: #7c3aed;", "stat-icon--purple"),
    ("background: #f5f3ff; color: #7c3aed;", "stat-icon--purple"),
]

FILES = ["status.html", "checker.html", "index.html"]
BASE = os.path.dirname(os.path.abspath(__file__))


def main():
    for name in FILES:
        path = os.path.join(BASE, name)
        with open(path, encoding="utf-8") as f:
            src = f.read()
        total = 0
        for old, cls in REPL:
            for kind in ("stat-icon", "card-icon"):
                pat = 'class="%s" style="%s"' % (kind, old)
                n = src.count(pat)
                if n:
                    src = src.replace(pat, 'class="%s %s"' % (kind, cls))
                    total += n
        if total:
            with open(path, "w", encoding="utf-8") as f:
                f.write(src)
        print("%s: %d ikon dirapikan" % (name, total))


if __name__ == "__main__":
    main()
