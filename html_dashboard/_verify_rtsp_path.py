"""Verifikasi normalize_rtsp_path() dan normalize_analysis_fps() (lokal, tanpa Flask).

Dijalankan DI DALAM container dashboard:
    docker exec camera-dashboard python /app/_verify_rtsp_path.py

Kenapa file ini ada: bug "rtsp://operator:0p3r@t0r@host" tidak terlihat di UI.
Path tersimpan, monitor dibuat, tetapi ffmpeg membaca host "t0r@10.121.10.145"
dan tidak pernah mengirim frame. Uji ini mengunci perilaku yang benar.

Fungsi yang diuji diimpor dari modul kecil tanpa dependensi Flask, sehingga uji
ini tetap bisa jalan walau paket web belum terpasang.
"""

import sys

from rtsp_path import (
    ANALYSIS_FPS_DEFAULT,
    ZM_FFMPEG_OPTIONS,
    _monitor_fps_payload,
    normalize_analysis_fps,
    normalize_rtsp_path,
)

FAILED = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + label)
    if not ok:
        print("        got : %r" % (got,))
        print("        want: %r" % (want,))
        FAILED.append(label)


def check_has(label, text, needle):
    ok = needle in (text or "")
    print(("  OK   " if ok else "  FAIL ") + label)
    if not ok:
        print("        %r tidak ada di %r" % (needle, text))
        FAILED.append(label)


print("=== 1. Path rusak dari production dipulihkan ===")
broken = "rtsp://operator:0p3r@t0r@10.121.10.145:554/Streaming/Channels/101"
fixed, warns = normalize_rtsp_path(broken)
check(
    "password berisi '@' di-encode jadi %40, host utuh",
    fixed,
    "rtsp://operator:0p3r%40t0r@10.121.10.145:554/Streaming/Channels/101",
)
check_has("ada peringatan perbaikan", " ".join(warns), "diperbaiki")

print("\n=== 2. Bentuk kanonik (sudah ter-encode) stabil: tidak berubah, tanpa peringatan ===")
good = "rtsp://operator:0p3r%40t0r@10.121.10.145:554/Streaming/Channels/101"
got_good, warns_good = normalize_rtsp_path(good)
check("path kanonik lewat apa adanya", got_good, good)

print("\n=== 2b. Idempotensi: normalisasi dua kali hasilnya sama ===")
_once = normalize_rtsp_path(broken)[0]
_twice = normalize_rtsp_path(_once)[0]
check("normalize(normalize(x)) == normalize(x)", _twice, _once)
check("tanpa peringatan", warns_good, [])

print("\n=== 3. Tanpa kredensial di URL ===")
plain = "rtsp://10.121.10.145:554/Streaming/Channels/101"
check("URL polos tidak diubah", normalize_rtsp_path(plain)[0], plain)
check(
    "username+password terpisah digabung dengan encoding",
    normalize_rtsp_path(plain, "operator", "0p3r@t0r")[0],
    "rtsp://operator:0p3r%40t0r@10.121.10.145:554/Streaming/Channels/101",
)
check(
    "password berisi ':' dan '/' juga di-encode",
    normalize_rtsp_path(plain, "admin", "a:b/c")[0],
    "rtsp://admin:a%3Ab%2Fc@10.121.10.145:554/Streaming/Channels/101",
)

print("\n=== 4. Kredensial di URL menang atas field terpisah ===")
withcred = "rtsp://cam:rahasia@10.0.0.5:554/s1"
got_c, warns_c = normalize_rtsp_path(withcred, "operator", "lain")
check("URL ber-kredensial tidak ditimpa field terpisah", got_c, withcred)
check_has("diberi tahu field diabaikan", " ".join(warns_c), "diabaikan")

print("\n=== 5. Password tanpa '@' tidak diubah bentuknya ===")
check(
    "user:pass biasa tetap sama",
    normalize_rtsp_path("rtsp://admin:pass123@10.0.0.9:554/ch1")[0],
    "rtsp://admin:pass123@10.0.0.9:554/ch1",
)

print("\n=== 6. Password berisi ':' tetap utuh, host tetap terbaca ===")
bad = "rtsp://user:pa%3Ass@10.0.0.9:554/ch1"
got_bad, warns_bad = normalize_rtsp_path("rtsp://user:pa:ss@10.0.0.9:554/ch1")
check(
    "password 'pa:ss' di-encode jadi pa%3Ass, host tidak berubah",
    got_bad,
    "rtsp://user:pa%3Ass@10.0.0.9:554/ch1",
)
print("  input : %s" % bad)
print("  output: %s" % got_bad)
print("  warn  : %s" % warns_bad)

print("\n=== 6b. Matriks kasus nyata dari lapangan ===")
MATRIX_CASES = [
    # (label, url, username, password, expected_path)
    ("IP+port, password berisi '@'",
     "rtsp://oper:0p3r@t0r@10.121.10.145:554/Streaming/Channels/101", None, None,
     "rtsp://oper:0p3r%40t0r@10.121.10.145:554/Streaming/Channels/101"),
    ("hostname tanpa port",
     "rtsp://admin:pw@nvr.local/Streaming/Channels/101", None, None,
     "rtsp://admin:pw@nvr.local/Streaming/Channels/101"),
    ("hostname pendek tanpa port, password '@'",
     "rtsp://admin:a@b@nvr/ch1", None, None,
     "rtsp://admin:a%40b@nvr/ch1"),
    ("password berisi '@' dua kali",
     "rtsp://u:p@x@y@10.0.0.1:554/ch1", None, None,
     "rtsp://u:p%40x%40y@10.0.0.1:554/ch1"),
    ("tanpa path",
     "rtsp://admin:pw@10.0.0.2:554", None, None,
     "rtsp://admin:pw@10.0.0.2:554"),
    ("user tanpa password",
     "rtsp://admin@10.0.0.3:554/ch1", None, None,
     "rtsp://admin@10.0.0.3:554/ch1"),
    ("field terpisah tanpa password",
     "rtsp://10.0.0.4:554/ch1", "admin", "", "rtsp://admin@10.0.0.4:554/ch1"),
    ("field terpisah, password '@: /'",
     "rtsp://10.0.0.4:554/ch1", "admin", "p@ss:w/rd",
     "rtsp://admin:p%40ss%3Aw%2Frd@10.0.0.4:554/ch1"),
]
for label, m_url, m_user, m_pass, want in MATRIX_CASES:
    check(label, normalize_rtsp_path(m_url, m_user, m_pass)[0], want)

print("\n=== 6c. Bukan RTSP: tidak diubah, hanya diberi peringatan ===")
http_url = "http://10.0.0.9/ch1"
got_http, warns_http = normalize_rtsp_path(http_url)
check("URL non-RTSP tidak diubah", got_http, http_url)
check_has("ada peringatan", " ".join(warns_http), "bukan RTSP")

print("\n=== 7. Analysis FPS ===")
check("kosong -> 8", normalize_analysis_fps(None), ANALYSIS_FPS_DEFAULT)
check("string kosong -> 8", normalize_analysis_fps(""), 8)
check("'8' -> 8", normalize_analysis_fps("8"), 8)
check("'5' -> 5", normalize_analysis_fps("5"), 5)
check("0 -> 8 (bukan analisa setiap frame)", normalize_analysis_fps("0"), 8)
check("negatif -> 8", normalize_analysis_fps("-3"), 8)
check("di atas batas di-clamp ke 30", normalize_analysis_fps("99"), 30)
check("teks sampah -> 8", normalize_analysis_fps("abc"), 8)
check("desimal dibulatkan", normalize_analysis_fps("7.6"), 8)

print("\n=== 8. Payload monitor: AnalysisFPSLimit (analisa) + MaxFPS (capture) ===")
payload = _monitor_fps_payload("8")
check("tiga field FPS dikirim", sorted(payload.keys()),
      ["Monitor[AlarmMaxFPS]", "Monitor[AnalysisFPSLimit]", "Monitor[MaxFPS]"])
check("nilainya 8", payload["Monitor[AnalysisFPSLimit]"], "8")
#
# MaxFPS WAJIB dikirim. Catatan lama menyatakan sebaliknya, tetapi sudah
# dibuktikan keliru: dengan MaxFPS NULL, zmc menelan stream secepat laju asli
# kamera (terukur 14.98 dan 25.10 fps); dengan MaxFPS=10 turun tepat 10.00.
check("MaxFPS dikirim (batas capture)", payload.get("Monitor[MaxFPS]"), "10")
check("AlarmMaxFPS dikirim", payload.get("Monitor[AlarmMaxFPS]"), "10")

print("\n=== 9. Opsi ffmpeg memuat timeout (bukan rtsp_transport) ===")
check("Options berisi timeout", ZM_FFMPEG_OPTIONS, "timeout=5000000")
check("Options tidak mengulang rtsp_transport",
      "rtsp_transport" in ZM_FFMPEG_OPTIONS, False)

print()
if FAILED:
    print("GAGAL: %d pemeriksaan tidak sesuai:" % len(FAILED))
    for name in FAILED:
        print("  - " + name)
    sys.exit(1)
print("SEMUA PEMERIKSAAN LULUS")
