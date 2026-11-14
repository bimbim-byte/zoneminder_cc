from pathlib import Path

NEEDLES = ("index.php", "nph-zms", "ZM_HOST}/zm/")

for f in ("cctv_checker/main.py", "scripts/zm_automate.py", "html_dashboard/app.py"):
    print("==", f)
    for i, line in enumerate(Path(f).read_text(encoding="utf-8").split("\n"), 1):
        if any(n in line for n in NEEDLES):
            print("   ", i, line.strip())
