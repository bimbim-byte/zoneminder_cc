"""Perbaiki label "(blank)" pada hint preset di add_camera.html.

renderZonePresetHint() selalu menempelkan " (blank)" setelah MaxPixelThreshold
tanpa melihat nilainya. Sejak 3 preset baru memakai 0 sebagai nilai SUNGGUHAN,
label itu menyesatkan. Sekarang " (blank)" hanya muncul bila null/undefined.

Dijalankan di container:
    docker exec camera-dashboard python3 /app/_patch_hint_blank.py
"""
import sys

PATH = "/app/add_camera.html"

OLD = """      const blank = v => (v === null || v === undefined) ? 'blank' : v;
      hint.innerHTML = '<b>Efektif:</b> CheckMethod=' + preset.check_method
        + ', MinPixelThreshold=' + preset.min_pixel_threshold
        + ', MaxPixelThreshold=' + blank(preset.max_pixel_threshold) + ' (blank)'"""

NEW = """      const blank = v => (v === null || v === undefined) ? 'blank' : v;
      const isBlankValue = v => (v === null || v === undefined);
      hint.innerHTML = '<b>Efektif:</b> CheckMethod=' + preset.check_method
        + ', MinPixelThreshold=' + preset.min_pixel_threshold
        + ', MaxPixelThreshold=' + blank(preset.max_pixel_threshold)
        + (isBlankValue(preset.max_pixel_threshold) ? ' (blank)' : '')"""


def main():
    src = open(PATH, encoding="utf-8").read()
    if "isBlankValue" in src:
        print("SKIP: hint sudah diperbaiki")
        return 0
    if src.count(OLD) != 1:
        print("GAGAL: anchor tidak unik (%d)" % src.count(OLD))
        return 1
    out = src.replace(OLD, NEW, 1)
    open(PATH, "w", encoding="utf-8", newline="").write(out)
    print("OK: add_camera.html diperbarui (%d -> %d byte)" % (len(src), len(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
