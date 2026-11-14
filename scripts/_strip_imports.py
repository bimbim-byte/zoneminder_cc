from pathlib import Path

p = Path("html_dashboard/app.py")
t = p.read_text(encoding="utf-8")
before = t
t = t.replace("import hashlib\n", "", 1)
t = t.replace("from urllib.parse import urlsplit\n", "", 1)
p.write_text(t, encoding="utf-8", newline="")
print("changed" if t != before else "no change")
print("hashlib left:", t.count("hashlib"))
print("urlsplit left:", t.count("urlsplit"))
