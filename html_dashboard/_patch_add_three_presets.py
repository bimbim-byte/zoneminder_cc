"""Tambah 3 preset ZoneMinder baru ke ZONE_PRESETS / ZONE_PRESET_ORDER di app.py.

Dijalankan di container:
    docker exec camera-dashboard python3 /app/_patch_add_three_presets.py

Idempoten: bila preset sudah ada, tidak menulis apa pun.

Preset baru mengikuti spesifikasi operator apa adanya, TERMASUK nilai 0 pada
field Min/Max. Ini berbeda dari 7 preset lama yang memakai None (field tidak
dikirim sehingga tersimpan NULL). Nilai 0 diverifikasi berlaku lewat
_probe_zone_zero.py: ZoneMinder menyimpan 0 apa adanya dan zone terbaca sah.
"""
import re
import sys

PATH = "/app/app.py"

NEW_ORDER = '''ZONE_PRESET_ORDER = (
    "Default",
    "Fast, low sensitivity",
    "Fast, medium sensitivity",
    "Fast, high sensitivity",
    "Fast, ultra sensitivity",
    "Best, low sensitivity",
    "Best, medium sensitivity",
    "Best, high sensitivity",
    "Best, balanced high sensitivity",
    "Ultra, high sensitivity",
)'''

NEW_ENTRIES = '''    # --- Preset tambahan ------------------------------------------------
    # Preset di bawah memakai 0 (bukan None) pada field yang di UI
    # ZoneMinder dibiarkan kosong. Nilainya TETAP dikirim ke API dan
    # tersimpan sebagai 0, bukan NULL — lihat _probe_zone_zero.py.
    "Fast, ultra sensitivity": {
        "CheckMethod": "AlarmedPixels",
        "MinPixelThreshold": 16, "MaxPixelThreshold": 0,
        "MinAlarmPixels": 3, "MaxAlarmPixels": 0,
        "FilterX": 0, "FilterY": 0,
        "MinFilterPixels": 0, "MaxFilterPixels": 0,
        "MinBlobPixels": 0, "MaxBlobPixels": 0,
        "MinBlobs": 0, "MaxBlobs": 0,
        "OverloadFrames": 0, "ExtendAlarmFrames": 0,
    },
    "Best, balanced high sensitivity": {
        "CheckMethod": "Blobs",
        "MinPixelThreshold": 18, "MaxPixelThreshold": 0,
        "MinAlarmPixels": 5, "MaxAlarmPixels": 0,
        "FilterX": 4, "FilterY": 4,
        "MinFilterPixels": 4, "MaxFilterPixels": 0,
        "MinBlobPixels": 3, "MaxBlobPixels": 0,
        "MinBlobs": 1, "MaxBlobs": 0,
        "OverloadFrames": 0, "ExtendAlarmFrames": 0,
    },
    "Ultra, high sensitivity": {
        "CheckMethod": "Blobs",
        "MinPixelThreshold": 15, "MaxPixelThreshold": 0,
        "MinAlarmPixels": 2, "MaxAlarmPixels": 85,
        "FilterX": 3, "FilterY": 3,
        "MinFilterPixels": 2, "MaxFilterPixels": 85,
        "MinBlobPixels": 1, "MaxBlobPixels": 0,
        "MinBlobs": 1, "MaxBlobs": 0,
        "OverloadFrames": 0, "ExtendAlarmFrames": 0,
    },
}'''

OLD_ORDER = '''ZONE_PRESET_ORDER = (
    "Default",
    "Fast, low sensitivity",
    "Fast, medium sensitivity",
    "Fast, high sensitivity",
    "Best, low sensitivity",
    "Best, medium sensitivity",
    "Best, high sensitivity",
)'''

OLD_TAIL = '''        "MinBlobPixels": 5, "MaxBlobPixels": None,
        "MinBlobs": 1, "MaxBlobs": None,
        "OverloadFrames": 0, "ExtendAlarmFrames": 0,
    },
}'''

NEW_TAIL = '''        "MinBlobPixels": 5, "MaxBlobPixels": None,
        "MinBlobs": 1, "MaxBlobs": None,
        "OverloadFrames": 0, "ExtendAlarmFrames": 0,
    },
''' + NEW_ENTRIES


def main():
    src = open(PATH, encoding="utf-8").read()

    if '"Ultra, high sensitivity":' in src:
        print("SKIP: preset baru sudah ada di app.py")
        return 0

    n_order = src.count(OLD_ORDER)
    n_tail = src.count(OLD_TAIL)
    print("anchor ZONE_PRESET_ORDER:", n_order)
    print("anchor ekor ZONE_PRESETS :", n_tail)
    if n_order != 1 or n_tail != 1:
        print("GAGAL: anchor tidak unik - tidak menulis apa pun")
        return 1

    out = src.replace(OLD_ORDER, NEW_ORDER, 1)
    out = out.replace(OLD_TAIL, NEW_TAIL, 1)

    order = re.search(r"ZONE_PRESET_ORDER = \((.*?)\)", out, re.S).group(1)
    names = re.findall(r'"([^"]+)"', order)
    print("urutan hasil:", names)
    if len(names) != 10:
        print("GAGAL: jumlah preset != 10")
        return 1

    open(PATH, "w", encoding="utf-8", newline="").write(out)
    print("OK: app.py diperbarui (%d byte -> %d byte)" % (len(src), len(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
