import os
import sys

import pymysql

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _env_loader import load_env  # noqa: E402

load_env()

# Konfigurasi Database ZoneMinder.
# Kredensial diambil dari file .env di root repo (lihat .env.example).
# ZM_DB_* dipakai bila ada; kalau tidak, jatuh ke ZM_USER/ZM_PASS.
ZM_DB_CONFIG = {
    "host": os.environ.get("ZM_DB_HOST", "localhost"),
    "user": os.environ.get("ZM_DB_USER", os.environ.get("ZM_USER", "zmuser")),
    "password": os.environ.get("ZM_DB_PASS", os.environ.get("ZM_PASS", "")),
    "database": os.environ.get("ZM_DB_NAME", "zm"),
    "port": int(os.environ.get("ZM_DB_PORT", 3306)),
    "autocommit": True,
}

def test_database():
    conn = None

    try:
        print("[DB] Mencoba koneksi ke database...")

        # Koneksi
        conn = pymysql.connect(**ZM_DB_CONFIG)

        print("[DB] Koneksi berhasil!")

        with conn.cursor() as cursor:

            # Test sederhana
            cursor.execute("SELECT 1")
            result = cursor.fetchone()

            print(f"[DB] SELECT 1 berhasil: {result}")

            # Ambil data dari tabel Monitors
            print("\n[DB] Mengambil data dari tabel Monitors...")

            cursor.execute("""
                SELECT Id, Name, Function, Enabled
                FROM Monitors
                LIMIT 10
            """)

            rows = cursor.fetchall()

            if rows:
                print(f"[DB] Ditemukan {len(rows)} data:\n")

                for row in rows:
                    print(
                        f"ID       : {row[0]}\n"
                        f"Name     : {row[1]}\n"
                        f"Function : {row[2]}\n"
                        f"Enabled  : {row[3]}\n"
                        f"{'-' * 40}"
                    )
            else:
                print("[DB] Tabel Monitors kosong.")

        return True

    except pymysql.MySQLError as e:
        print(f"[DB ERROR] {e}")
        return False

    except Exception as e:
        print(f"[ERROR] {e}")
        return False

    finally:
        if conn:
            conn.close()
            print("\n[DB] Koneksi ditutup.")


if __name__ == "__main__":
    test_database()