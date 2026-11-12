"""Penyimpanan kredensial terenkripsi untuk dashboard.

Kredensial ZoneMinder tidak lagi disimpan sebagai password mentah di berkas
teks biasa. Berkas `data/zm_credentials.enc` berisi paket terenkripsi
AES-256-GCM dengan format:

    ZMENC1\\n<b64(salt)>\\n<b64(nonce)>\\n<b64(ciphertext+tag)>

Kunci enkripsi diturunkan dari DASH_SECRET_KEY memakai scrypt, sehingga:
  * mengubah DASH_SECRET_KEY membuat berkas lama TIDAK dapat dibuka
    (perilaku yang disengaja: kunci baru = brankas baru);
  * tidak ada kunci enkripsi yang ikut tersimpan di repo atau di berkas data.

Modul ini sengaja hanya memakai pustaka standar Python (tanpa `cryptography`)
supaya tidak ada dependensi biner tambahan di image Docker.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

try:  # pragma: no cover - bergantung pada OpenSSL yang tersedia
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    _AESGCM_AVAILABLE = True
except Exception:  # pragma: no cover
    AESGCM = None
    _AESGCM_AVAILABLE = False

# Header versi format. Kenaikan versi harus disertai migrasi.
_MAGIC = "ZMENC1"

SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
KEY_LEN = 32
SALT_LEN = 16
NONCE_LEN = 12


class CredentialError(Exception):
    """Kesalahan yang dapat ditampilkan ke operator (bukan stack trace)."""


def crypto_available() -> bool:
    """True bila enkripsi sungguhan (AES-GCM) tersedia."""
    return _AESGCM_AVAILABLE


def _b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def _derive_key(secret: str, salt: bytes) -> bytes:
    if not secret:
        raise CredentialError("DASH_SECRET_KEY kosong.")
    return __import__("hashlib").scrypt(
        secret.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=KEY_LEN,
        maxmem=64 * 1024 * 1024,
    )


def seal(payload: dict, secret: str) -> bytes:
    """Mengenkripsi dict menjadi bytes siap tulis ke berkas."""
    if not _AESGCM_AVAILABLE:
        raise CredentialError(
            "Library 'cryptography' tidak tersedia di image dashboard. "
            "Jalankan: docker compose build ui-interface"
        )
    salt = os.urandom(SALT_LEN)
    nonce = os.urandom(NONCE_LEN)
    key = _derive_key(secret, salt)
    blob = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(nonce, blob, _MAGIC.encode("ascii"))
    return "\n".join([_MAGIC, _b64e(salt), _b64e(nonce), _b64e(ciphertext)]).encode("utf-8")


def unseal(raw: bytes, secret: str) -> dict:
    """Membuka bytes hasil seal(). Melempar CredentialError bila gagal."""
    if not _AESGCM_AVAILABLE:
        raise CredentialError("Library 'cryptography' tidak tersedia di image dashboard.")

    try:
        text = raw.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise CredentialError("Berkas kredensial rusak (bukan teks UTF-8).") from exc

    parts = text.splitlines()
    if len(parts) != 4 or parts[0] != _MAGIC:
        raise CredentialError("Format berkas kredensial tidak dikenali.")

    try:
        salt = _b64d(parts[1])
        nonce = _b64d(parts[2])
        ciphertext = _b64d(parts[3])
    except Exception as exc:
        raise CredentialError("Berkas kredensial rusak (bagian base64 tidak valid).") from exc

    key = _derive_key(secret, salt)
    try:
        blob = AESGCM(key).decrypt(nonce, ciphertext, _MAGIC.encode("ascii"))
    except Exception as exc:
        raise CredentialError(
            "Gagal membuka kredensial. DASH_SECRET_KEY berbeda dari saat berkas dibuat, "
            "atau berkas rusak. Isi ulang kredensial lewat halaman Pengaturan."
        ) from exc

    try:
        data = json.loads(blob.decode("utf-8"))
    except Exception as exc:
        raise CredentialError("Isi kredensial tidak valid.") from exc

    if not isinstance(data, dict):
        raise CredentialError("Isi kredensial tidak valid (bukan objek).")
    return data


def save_file(path: str | Path, payload: dict, secret: str) -> None:
    """Menulis brankas kredensial dengan permission ketat (0600)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    blob = seal(payload, secret)

    tmp = target.with_suffix(target.suffix + ".tmp")
    with tmp.open("wb") as fh:
        fh.write(blob)

    try:
        os.chmod(tmp, 0o600)
    except OSError:
        # Filesystem Windows (9p/drvfs) sering menolak chmod. Bukan kegagalan
        # fatal untuk fungsi, hanya kehilangan penguatan permission.
        pass

    os.replace(tmp, target)


def load_file(path: str | Path, secret: str) -> dict | None:
    """Membaca brankas. None bila berkas belum ada."""
    target = Path(path)
    if not target.is_file():
        return None
    return unseal(target.read_bytes(), secret)


def mask(value: str) -> str:
    """Menyamarkan nilai rahasia untuk ditampilkan di UI/log."""
    if not value:
        return ""
    if len(value) <= 2:
        return "*" * len(value)
    return value[0] + "*" * (len(value) - 2) + value[-1]
