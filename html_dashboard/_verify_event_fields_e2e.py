"""E2E: 8 field event/analisis ZM 1.38.6 tiba utuh di database Monitors.

Dijalankan DI DALAM container camera-dashboard:
    docker exec camera-dashboard python3 /app/_verify_event_fields_e2e.py

Menguji dua jalur pendaftaran lewat endpoint dashboard sungguhan:
  1. Single add  : POST /api/zones/save-camera
  2. Burst add   : POST /api/zoneminder/burst-add

Setiap jalur memverifikasi nilai yang TERSIMPAN di ZM (bukan respons HTTP),
lalu menghapus monitor uji.
"""
import sys

sys.path.insert(0, "/app")
import app as dash  # noqa: E402

PASS, FAIL = 0, 0
NAME_SINGLE = "EVF_SINGLE_TEST"
NAME_BURST = "EVF_BURST_TEST"
PATH = "rtsp://10.121.10.145:554/Streaming/Channels/101"


def ok(msg):
    global PASS
    PASS += 1
    print("  [OK]   " + msg)


def bad(msg):
    global FAIL
    FAIL += 1
    print("  [FAIL] " + msg)


def check(label, got, want):
    if str(got) == str(want):
        ok("%s = %s" % (label, got))
    else:
        bad("%s = %r (harap %r)" % (label, got, want))


def client():
    c = dash.app.test_client()
    with c.session_transaction() as sess:
        sess["user"] = "tester"
    return c


def find_monitor(name):
    data = dash.zm_api_get("monitors.json")
    found = None
    for item in (data.get("monitors", []) or []):
        m = item.get("Monitor", item)
        if str(m.get("Name")) != name:
            continue
        if m.get("Deleted") is True or str(m.get("Deleted", "0")).lower() in ("1", "true"):
            continue
        if found is None or int(m.get("Id", 0)) > int(found.get("Id", 0)):
            found = m
    return found


def delete_monitor(mid):
    try:
        dash.zm_delete("monitors/%s.json" % mid)
    except Exception:
        pass


def cleanup():
    for m in list((dash.zm_api_get("monitors.json").get("monitors", []) or [])):
        mm = m.get("Monitor", m)
        if str(mm.get("Name")) in (NAME_SINGLE, NAME_BURST):
            delete_monitor(mm.get("Id"))


print("=" * 66)
print("E2E: 8 field event/analisis ZM 1.38.6 -> database Monitors")
print("=" * 66)
cleanup()

EXPECTED_FIELDS = [
    "SectionLength", "MinSectionLength", "EventCloseMode", "FrameSkip",
    "AnalysisUpdateDelay", "FPSReportInterval", "Importance", "StartupDelay",
]

print("")
print("[1] Jalur SINGLE ADD: POST /api/zones/save-camera")
c = client()
r = c.post("/api/zones/save-camera", json={
    "name": NAME_SINGLE,
    "path": PATH,
    "width": "1280",
    "height": "720",
    "function": "Monitor",
    "sectionLength": 120,
    "minSectionLength": 30,
    "eventCloseMode": "time",
    "frameSkip": 2,
    "analysisUpdateDelay": 3,
    "fpsReportInterval": 150,
    "importance": "Less",
    "startupDelay": 4,
    "createZone": False,
})
body = r.get_json() or {}
print("     HTTP %s status=%s" % (r.status_code, body.get("status")))
if r.status_code == 200 and body.get("status") == "success":
    ok("endpoint melaporkan sukses")
else:
    bad("endpoint gagal: " + str(body.get("message")))

mon = find_monitor(NAME_SINGLE)
if mon:
    ok("monitor ada di ZM (Id=%s)" % mon.get("Id"))
    check("SectionLength", mon.get("SectionLength"), 120)
    check("MinSectionLength", mon.get("MinSectionLength"), 30)
    check("EventCloseMode", mon.get("EventCloseMode"), "time")
    check("FrameSkip", mon.get("FrameSkip"), 2)
    check("AnalysisUpdateDelay", mon.get("AnalysisUpdateDelay"), 3)
    check("FPSReportInterval", mon.get("FPSReportInterval"), 150)
    check("Importance", mon.get("Importance"), "Less")
    check("StartupDelay", mon.get("StartupDelay"), 4)
    check("Method", mon.get("Method"), "rtpRtsp")
else:
    bad("monitor TIDAK ADA di ZM")
    for f in EXPECTED_FIELDS:
        bad("%s = tidak terverifikasi" % f)

print("")
print("[2] Jalur BURST: POST /api/zoneminder/burst-add")
r = c.post("/api/zoneminder/burst-add", json={
    "monitors": [{
        "Monitor": {
            "Name": NAME_BURST,
            "Type": "Ffmpeg",
            "Path": PATH,
            "User": "",
            "Pass": "",
            "Capturing": "Always",
            "Analysing": "Always",
            "Recording": "OnMotion",
            "Width": "1280",
            "Height": "720",
            "MaxFPS": "10.00",
            "AnalysisFPS": "8.00",
            "Decoder": "Auto",
            "SectionLength": 600,
            "MinSectionLength": 90,
            "EventCloseMode": "duration",
            "FrameSkip": 1,
            "AnalysisUpdateDelay": 6,
            "FPSReportInterval": 400,
            "Importance": "Not",
            "StartupDelay": 5,
        }
    }],
    "zoneMode": "",
    "createZone": False,
    "overwriteZone": False,
})
body = r.get_json() or {}
print("     HTTP %s status=%s success=%s fail=%s" % (
    r.status_code, body.get("status"), body.get("success_count"), body.get("fail_count")))
if r.status_code == 200 and body.get("success_count") == 1:
    ok("burst endpoint melaporkan sukses")
else:
    bad("burst gagal: " + str(body)[:300])

mon = find_monitor(NAME_BURST)
if mon:
    ok("monitor ada di ZM (Id=%s)" % mon.get("Id"))
    check("SectionLength", mon.get("SectionLength"), 600)
    check("MinSectionLength", mon.get("MinSectionLength"), 90)
    check("EventCloseMode", mon.get("EventCloseMode"), "duration")
    check("FrameSkip", mon.get("FrameSkip"), 1)
    check("AnalysisUpdateDelay", mon.get("AnalysisUpdateDelay"), 6)
    check("FPSReportInterval", mon.get("FPSReportInterval"), 400)
    check("Importance", mon.get("Importance"), "Not")
    check("StartupDelay", mon.get("StartupDelay"), 5)
else:
    bad("monitor TIDAK ADA di ZM")
    for f in EXPECTED_FIELDS:
        bad("%s = tidak terverifikasi" % f)

print("")
print("[3] Bersih-bersih monitor uji")
cleanup()
left1 = find_monitor(NAME_SINGLE)
left2 = find_monitor(NAME_BURST)
if not left1 and not left2:
    ok("kedua monitor uji sudah dihapus")
else:
    bad("masih tersisa: %s / %s" % (bool(left1), bool(left2)))

print("")
print("=" * 66)
print("LULUS: %d   GAGAL: %d" % (PASS, FAIL))
print("SEMUA PEMERIKSAAN E2E LULUS" if FAIL == 0 else "ADA YANG GAGAL")
sys.exit(0 if FAIL == 0 else 1)
