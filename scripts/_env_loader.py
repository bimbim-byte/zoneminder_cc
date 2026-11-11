"""Pembaca file .env untuk skrip yang dijalankan di luar Docker.

Skrip di folder ini dipakai lewat `docker exec` atau langsung dari WSL, jadi
tidak mewarisi environment dari docker-compose. Helper ini membaca file .env
di root repo dan mengisinya ke os.environ tanpa menimpa variabel yang sudah ada
(environment asli selalu menang).

Tidak memakai python-dotenv supaya tidak menambah dependensi.
"""

import os
from pathlib import Path

# scripts/_env_loader.py -> root repo adalah satu level di atas scripts/
REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / ".env"


def load_env(env_file=None):
    """Baca .env dan isi os.environ. Kembalikan dict nilai yang dibaca.

    Variabel yang sudah ada di environment TIDAK ditimpa.
    """
    path = Path(env_file) if env_file else ENV_FILE
    values = {}

    if not path.is_file():
        return values

    with path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            # Buang komentar di akhir baris, lalu kutip pembungkus.
            val = val.split(" #", 1)[0].strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                val = val[1:-1]
            if not key:
                continue
            values[key] = val
            os.environ.setdefault(key, val)

    return values


def get(name, default=None):
    """Ambil variabel environment setelah memastikan .env sudah dimuat."""
    if name not in os.environ and ENV_FILE.is_file():
        load_env()
    return os.environ.get(name, default)


if __name__ == "__main__":
    data = load_env()
    print(f"[ENV] File  : {ENV_FILE}")
    print(f"[ENV] Status: {'ditemukan' if ENV_FILE.is_file() else 'TIDAK ADA'}")
    print(f"[ENV] Kunci : {', '.join(sorted(data)) if data else '(kosong)'}")
