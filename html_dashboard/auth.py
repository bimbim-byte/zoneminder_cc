"""Autentikasi dashboard + brankas kredensial ZoneMinder.

Dua tanggung jawab, sengaja dipisah dari app.py agar mudah diaudit:

1. AUTH DASHBOARD
   Login berbasis cookie session Flask (HttpOnly + SameSite=Lax) dengan
   password yang di-hash PBKDF2-HMAC-SHA256. Akun pertama dibuat otomatis
   dengan kredensial `admin` / `admin` dan ditandai WAJIB ganti password.
   Petunjuk (hint) password disimpan bersama hash-nya dan HANYA ditampilkan
   sebagai halaman petunjuk setelah password default berhasil dipakai.

2. BRANKAS KREDENSIAL ZONEMINDER
   ZM_USER / ZM_PASS tidak lagi dibaca dari environment setiap request.
   Nilai efektif diambil dari data/zm_credentials.enc (AES-GCM, lihat
   token_crypto.py). Environment hanya dipakai sebagai nilai AWAL saat
   brankas belum ada, sehingga instalasi lama tetap hidup tanpa setup ulang.

Catatan penting: menaruh password ZM (global) dan user dashboard (lokal)
di satu sistem itu sengaja dibuat eksplisit di UI. Dashboard TIDAK pernah
mengirim password ZM ke browser lagi (endpoint lama /api/config dihapus).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from functools import wraps
from pathlib import Path

from flask import jsonify, redirect, request, session, url_for

import token_crypto

log = logging.getLogger("dashboard.auth")

# ---------------------------------------------------------------------------
# Konfigurasi
# ---------------------------------------------------------------------------
DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "admin"
DEFAULT_HINT = "Password awal bawaan sistem (ganti sekarang)."

PBKDF2_ITERATIONS = 260_000
SESSION_TTL_SECONDS = int(os.environ.get("SESSION_TTL_SECONDS", 12 * 3600))
MAX_LOGIN_ATTEMPTS = int(os.environ.get("MAX_LOGIN_ATTEMPTS", 8))
LOGIN_LOCKOUT_SECONDS = int(os.environ.get("LOGIN_LOCKOUT_SECONDS", 300))

# Halaman yang boleh diakses tanpa login.
PUBLIC_ENDPOINTS = {"login", "logout", "healthz", "static", "favicon"}

_users_lock = threading.Lock()
_attempts: dict[str, list[float]] = {}
_attempts_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Util kriptografi password
# ---------------------------------------------------------------------------
def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Kembalikan (salt_hex, hash_hex) memakai PBKDF2-HMAC-SHA256."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS
    )
    return salt, digest.hex()


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    if not salt or not expected_hash:
        return False
    try:
        _, actual = hash_password(password, salt)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected_hash)


# ---------------------------------------------------------------------------
# Penyimpanan user dashboard (data/dashboard_users.json)
# ---------------------------------------------------------------------------
class DashboardAuth:
    def __init__(self, users_file: str):
        self.users_file = Path(users_file)

    # ----- baca / tulis -------------------------------------------------
    def _read(self) -> dict:
        if not self.users_file.is_file():
            return {}
        try:
            data = json.loads(self.users_file.read_text(encoding="utf-8"))
        except Exception as exc:
            log.error("Gagal membaca %s: %s", self.users_file, exc)
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict) -> None:
        self.users_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.users_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self.users_file)

    # ----- siklus hidup -------------------------------------------------
    def bootstrap(self) -> bool:
        """Membuat akun awal bila belum ada. True bila akun baru dibuat."""
        with _users_lock:
            data = self._read()
            if data.get("users"):
                return False

            salt, digest = hash_password(DEFAULT_PASSWORD)
            data = {
                "version": 1,
                "users": {
                    DEFAULT_USERNAME: {
                        "salt": salt,
                        "hash": digest,
                        "iterations": PBKDF2_ITERATIONS,
                        "hint": DEFAULT_HINT,
                        "must_change_password": True,
                        "created_at": int(time.time()),
                        "password_changed_at": None,
                        "last_login": None,
                    }
                },
            }
            self._write(data)
            log.warning(
                "Akun dashboard awal dibuat: %s / %s (WAJIB diganti saat login pertama).",
                DEFAULT_USERNAME,
                DEFAULT_PASSWORD,
            )
            return True

    # ----- kueri --------------------------------------------------------
    def user(self, username: str) -> dict | None:
        return self._read().get("users", {}).get(username)

    def hint(self, username: str) -> str:
        entry = self.user(username) or {}
        return str(entry.get("hint") or "")

    def display_name(self, username: str) -> str:
        entry = self.user(username) or {}
        return str(entry.get("display_name") or username)

    # ----- autentikasi --------------------------------------------------
    def authenticate(self, username: str, password: str) -> tuple[bool, str]:
        entry = self.user(username)
        if not entry:
            # Tetap jalankan PBKDF2 sekali agar waktu respons tidak membocorkan
            # apakah username ada atau tidak.
            hash_password(password)
            return False, "Username atau password salah."

        if not entry.get("enabled", True):
            return False, "Akun dinonaktifkan."

        if not verify_password(password, entry.get("salt", ""), entry.get("hash", "")):
            return False, "Username atau password salah."

        with _users_lock:
            data = self._read()
            target = data.get("users", {}).get(username)
            if target is not None:
                target["last_login"] = int(time.time())
                self._write(data)
        return True, ""

    # ----- perubahan ----------------------------------------------------
    def change_password(
        self,
        username: str,
        current_password: str,
        new_password: str,
        hint: str | None = None,
    ) -> tuple[bool, str]:
        ok, _ = self.authenticate(username, current_password)
        if not ok:
            return False, "Password saat ini salah."

        problem = validate_password_strength(new_password)
        if problem:
            return False, problem

        with _users_lock:
            data = self._read()
            entry = data.get("users", {}).get(username)
            if entry is None:
                return False, "User tidak ditemukan."

            salt, digest = hash_password(new_password)
            entry.update(
                {
                    "salt": salt,
                    "hash": digest,
                    "iterations": PBKDF2_ITERATIONS,
                    "must_change_password": False,
                    "password_changed_at": int(time.time()),
                }
            )
            if hint is not None:
                entry["hint"] = hint.strip()[:200]
            self._write(data)

        log.info("Password dashboard untuk '%s' diperbarui.", username)
        return True, ""


def validate_password_strength(password: str) -> str | None:
    """Kembalikan pesan kesalahan, atau None bila password memenuhi syarat."""
    if len(password or "") < 8:
        return "Password baru minimal 8 karakter."
    if password.isdigit():
        return "Password tidak boleh hanya berisi angka."
    if password.lower() in {"password", "admin123", "12345678"}:
        return "Password terlalu mudah ditebak."
    return None


# ---------------------------------------------------------------------------
# Rate limiting login (per IP)
# ---------------------------------------------------------------------------
def record_attempt(ip: str) -> None:
    now = time.time()
    with _attempts_lock:
        history = [t for t in _attempts.get(ip, []) if now - t < LOGIN_LOCKOUT_SECONDS]
        history.append(now)
        _attempts[ip] = history


def is_locked_out(ip: str) -> tuple[bool, int]:
    """Kembalikan (terkunci, sisa_detik)."""
    now = time.time()
    with _attempts_lock:
        history = [t for t in _attempts.get(ip, []) if now - t < LOGIN_LOCKOUT_SECONDS]
        _attempts[ip] = history
        if len(history) < MAX_LOGIN_ATTEMPTS:
            return False, 0
        remaining = int(LOGIN_LOCKOUT_SECONDS - (now - history[0])) + 1
        return True, max(remaining, 0)


def clear_attempts(ip: str) -> None:
    with _attempts_lock:
        _attempts.pop(ip, None)


# ---------------------------------------------------------------------------
# Brankas kredensial ZoneMinder
# ---------------------------------------------------------------------------
class ZMCredentials:
    """Sumber tunggal kredensial ZoneMinder untuk dashboard & checker.

    Prioritas nilai:
      1. data/zm_credentials.enc  (dikelola dari halaman Pengaturan)
      2. environment ZM_USER / ZM_PASS (nilai awal / kompatibilitas)
      3. default "admin" / "" (hanya bila keduanya kosong)
    """

    def __init__(self, path: str, secret: str):
        self.path = Path(path)
        self.secret = secret or ""

    # ----- baca ---------------------------------------------------------
    def _from_env(self) -> dict:
        return {
            "user": os.environ.get("ZM_USER", "admin"),
            "pass": os.environ.get("ZM_PASS", ""),
            "source": "env",
        }

    def load(self) -> dict:
        if not token_crypto.crypto_available():
            data = self._from_env()
            data["source"] = "env (enkripsi tidak tersedia)"
            return data

        if not self.path.is_file():
            return self._from_env()

        try:
            data = token_crypto.load_file(self.path, self.secret) or {}
        except token_crypto.CredentialError as exc:
            log.error("Brankas kredensial tidak dapat dibuka: %s", exc)
            fallback = self._from_env()
            fallback["source"] = "env (brankas gagal dibuka)"
            fallback["error"] = str(exc)
            return fallback

        if not data.get("user"):
            return self._from_env()

        from_cfg = {
            "user": str(data.get("user", "")),
            "pass": str(data.get("pass", "")),
            "source": "encrypted",
            "updated_at": data.get("updated_at"),
            "updated_by": data.get("updated_by"),
        }
        # Panggilan dari dashboard selalu boleh memakai kredensial tersimpan.
        # Bila ada konsumen lain (mis. checker) yang butuh, tambahkan opsi di sini.
        return from_cfg

    @property
    def user(self) -> str:
        return self.load()["user"]

    @property
    def password(self) -> str:
        return self.load()["pass"]

    # ----- tulis --------------------------------------------------------
    def save(self, user: str, password: str, updated_by: str = "") -> None:
        if not token_crypto.crypto_available():
            raise token_crypto.CredentialError(
                "Enkripsi tidak tersedia. Rebuild image: docker compose build ui-interface"
            )
        payload = {
            "version": 1,
            "user": user,
            "pass": password,
            "updated_at": int(time.time()),
            "updated_by": updated_by,
        }
        token_crypto.save_file(self.path, payload, self.secret)

    def status(self) -> dict:
        """Ringkasan aman untuk ditampilkan di UI (tanpa password)."""
        try:
            data = self.load()
        except Exception as exc:  # pragma: no cover
            return {"ok": False, "error": str(exc)}
        return {
            "ok": True,
            "source": data.get("source", "unknown"),
            "user": data.get("user", ""),
            "has_password": bool(data.get("pass")),
            "password_preview": token_crypto.mask(data.get("pass", "")),
            "updated_at": data.get("updated_at"),
            "updated_by": data.get("updated_by", ""),
            "encryption": token_crypto.crypto_available(),
            "file_exists": self.path.is_file(),
            "error": data.get("error", ""),
        }


# ---------------------------------------------------------------------------
# Middleware Flask
# ---------------------------------------------------------------------------
def install_auth(app, auth: DashboardAuth, credentials: ZMCredentials):
    """Pasang before_request guard + endpoint login/logout pada app Flask."""

    app.secret_key = os.environ.get("DASH_SECRET_KEY", "") or secrets.token_hex(32)

    @app.before_request
    def _require_login():
        # OPTIONS (preflight) selalu diizinkan; tidak membawa cookie sesi.
        if request.method == "OPTIONS":
            return None
        if request.endpoint in PUBLIC_ENDPOINTS or request.endpoint is None:
            return None

        # Streaming MJPEG memakai <img src>, sehingga cookie sesi ikut terkirim
        # dan tetap wajib login. Tidak ada pengecualian di sini.
        username = session.get("user")
        if not username:
            if is_api_request():
                return jsonify({"error": "Sesi berakhir. Silakan login ulang."}), 401
            return redirect(url_for("login", next=request.full_path if request.query_string else request.path))

        # Sesi kedaluwarsa berdasarkan waktu login.
        issued = float(session.get("issued_at") or 0)
        if issued and (time.time() - issued) > SESSION_TTL_SECONDS:
            session.clear()
            if is_api_request():
                return jsonify({"error": "Sesi berakhir. Silakan login ulang."}), 401
            return redirect(url_for("login"))

        # Paksa ganti password default sebelum halaman lain boleh dibuka.
        entry = auth.user(username) or {}
        if entry.get("must_change_password") and request.endpoint not in {
            "login",
            "logout",
            "change_password",
            "settings",
            "settings_credentials",
            "settings_test",
            "healthz",
        }:
            if is_api_request():
                return jsonify({
                    "error": "Password default masih dipakai. Ganti password terlebih dahulu.",
                    "must_change_password": True,
                }), 403
            return redirect(url_for("settings") + "?force=1")

        return None

    def is_api_request() -> bool:
        return request.path.startswith("/api/") or "application/json" in (
            request.headers.get("Accept") or ""
        )

    app.extensions["dashboard_auth"] = auth
    app.extensions["zm_credentials"] = credentials
    app.extensions["is_api_request"] = is_api_request
    return app


def login_required_api(view):
    """Dekorator untuk endpoint API yang butuh sesi login aktif."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            return jsonify({"error": "Sesi berakhir. Silakan login ulang."}), 401
        return view(*args, **kwargs)

    return wrapper
