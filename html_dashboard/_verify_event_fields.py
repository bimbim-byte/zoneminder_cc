"""Verifikasi tipe & normalisasi 8 field event/analisis ZM 1.38.6.

Dijalankan di container:
    docker exec camera-dashboard python3 /app/_verify_event_fields.py

Memastikan:
  1. Nilai dari form (string) dinormalisasi menjadi int/enum yang sah.
  2. Nilai kosong / tak valid jatuh ke default 1.38.6 (300/60/system/0/0/250/Normal/0).
  3. Nilai 0 dari pengguna DIHORMATI (tidak tergeser ke default).
"""
import sys

from zm_triad import (
    build_zm138_full_payload,
    normalize_event_close_mode,
    normalize_importance,
    normalize_int_field,
)

FAILS = []

INT_FIELDS = [
    ("SectionLength", 300),
    ("MinSectionLength", 60),
    ("FrameSkip", 0),
    ("AnalysisUpdateDelay", 0),
    ("FPSReportInterval", 250),
    ("StartupDelay", 0),
]

ENUM_FIELDS = [
    ("EventCloseMode", "system"),
    ("Importance", "Normal"),
]


def check(label, got, want):
    if got != want:
        FAILS.append("%s: harap %r, dapat %r" % (label, want, got))
        print("[FAIL] %-52s %r (harap %r)" % (label, got, want))
    else:
        print("[OK]   %-52s %r" % (label, got))


def payload(**kwargs):
    return build_zm138_full_payload(name="VERIFY", path="rtsp://10.0.0.1/s", **kwargs)


print("== 1. Default saat argumen tidak diberikan ==")
p = payload()
for name, default in INT_FIELDS:
    check("%s default" % name, p["Monitor[%s]" % name], str(default))
for name, default in ENUM_FIELDS:
    check("%s default" % name, p["Monitor[%s]" % name], default)

print()
print("== 2. Override string/angka dinormalisasi benar ==")
p = payload(section_length="90", min_section_length=45, frame_skip="3",
            analysis_update_delay=7, fps_report_interval="100", startup_delay=9,
            event_close_mode="Duration", importance="less")
check("SectionLength override 90", p["Monitor[SectionLength]"], "90")
check("MinSectionLength override 45", p["Monitor[MinSectionLength]"], "45")
check("FrameSkip override 3", p["Monitor[FrameSkip]"], "3")
check("AnalysisUpdateDelay override 7", p["Monitor[AnalysisUpdateDelay]"], "7")
check("FPSReportInterval override 100", p["Monitor[FPSReportInterval]"], "100")
check("StartupDelay override 9", p["Monitor[StartupDelay]"], "9")
check("EventCloseMode Duration", p["Monitor[EventCloseMode]"], "duration")
check("Importance less -> Less", p["Monitor[Importance]"], "Less")

print()
print("== 3. Nilai 0 dari pengguna DIPERTAHANKAN (bukan default) ==")
p = payload(section_length=0, min_section_length=0, frame_skip=0,
            analysis_update_delay=0, fps_report_interval=0, startup_delay=0)
for name, _ in INT_FIELDS:
    check("%s eksplisit 0" % name, p["Monitor[%s]" % name], "0")

print()
print("== 4. Nilai kosong / tak valid jatuh ke default ==")
p = payload(section_length="", min_section_length="abc", frame_skip=None,
            analysis_update_delay="", fps_report_interval="x", startup_delay="",
            event_close_mode="xyz", importance="??")
for name, default in INT_FIELDS:
    check("%s invalid -> default" % name, p["Monitor[%s]" % name], str(default))
for name, default in ENUM_FIELDS:
    check("%s invalid -> default" % name, p["Monitor[%s]" % name], default)

print()
print("== 5. Normalizer langsung ==")
check("int -5 clamp ke batas bawah 0", normalize_int_field("-5", "FrameSkip", 300), 0)
check("int '0' dipertahankan", normalize_int_field("0", "FrameSkip", 300), 0)
check("int '' -> default", normalize_int_field("", "FrameSkip", 300), 300)
check("int None -> default", normalize_int_field(None, "FrameSkip", 300), 300)
check("int '90' -> 90", normalize_int_field("90", "SectionLength", 300), 90)
check("int '90.9' -> 90 (truncate)", normalize_int_field("90.9", "SectionLength", 300), 90)
if not isinstance(normalize_int_field("90", "SectionLength", 300), int):
    FAILS.append("normalize_int_field tidak mengembalikan int")
check("int overflow clamp ke batas kolom",
      normalize_int_field("99999999999", "SectionLength", 300), 4294967295)
check("close SYS", normalize_event_close_mode("SYS"), "system")
check("close alarm", normalize_event_close_mode("alarm"), "alarm")
check("close junk", normalize_event_close_mode("xyz"), "system")
check("imp Less Important", normalize_importance("Less Important"), "Less")
check("imp Not Important", normalize_importance("Not Important"), "Not")
check("imp junk", normalize_importance("zzz"), "Normal")

print()
if FAILS:
    print("[RESULT] %d KEGAGALAN" % len(FAILS))
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("[RESULT] 8 field event/analisis ZM 1.38.6 TERVERIFIKASI")
