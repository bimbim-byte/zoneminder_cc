"""
Verifikasi integrasi langsung ZoneMinder v1.38.6
(Capturing, Analysing, Recording, Decoder, MaxFPS, AnalysisFPSLimit, Username, Password).
"""
import sys
import json

sys.path.insert(0, "/app")
import app as dash

def get_client():
    c = dash.app.test_client()
    with c.session_transaction() as sess:
        sess["user"] = "tester"
    return c

c = get_client()

# ==============================================================================
# 1. Pendaftaran Kamera Tunggal via /api/zoneminder/add-camera
# ==============================================================================
cam_name = "TEST_ZM138_FULL"
add_res = c.post("/api/zoneminder/add-camera", json={
    "name": cam_name,
    "source": "rtsp://10.121.8.7/video2",
    "username": "admin",
    "password": "admin_password",
    "capturing": "Always",
    "analysing": "Always",
    "recording": "OnMotion",
    "width": "1280",
    "height": "720",
    "maxFps": "10.00",
    "analysisFps": "8.00",
    "decoder": "h264",
    "createZone": False,
})
assert add_res.status_code == 200, f"HTTP {add_res.status_code}: {add_res.get_data(as_text=True)}"
res_json = add_res.get_json()
assert res_json.get("status") == "success", f"Gagal add-camera: {res_json}"

mon_id = res_json.get("monitor_id")
print(f"[PASS] 1. Kamera dibuat dengan ID {mon_id}")

# 2. Check Monitor fields in ZM API
mon_get = c.get(f"/zm/api/monitors/{mon_id}.json")
mon_data = mon_get.get_json().get("monitor", {}).get("Monitor", {})

print(f"  Field Monitor di ZM 1.38:")
print(f"    Name             : {mon_data.get('Name')}")
print(f"    Capturing        : {mon_data.get('Capturing')}")
print(f"    Analysing        : {mon_data.get('Analysing')}")
print(f"    Recording        : {mon_data.get('Recording')}")
print(f"    Decoder          : {mon_data.get('Decoder')}")
print(f"    MaxFPS           : {mon_data.get('MaxFPS')}")
print(f"    AnalysisFPSLimit : {mon_data.get('AnalysisFPSLimit')}")
print(f"    User             : {mon_data.get('User')}")
print(f"    Width x Height   : {mon_data.get('Width')}x{mon_data.get('Height')}")
print(f"    OutputCodecName  : {mon_data.get('OutputCodecName')}")
print(f"    OutputContainer  : {mon_data.get('OutputContainer')}")
print(f"    Enabled          : {mon_data.get('Enabled')}")

assert mon_data.get("Capturing") == "Always", f"Expected Always, got {mon_data.get('Capturing')}"
assert mon_data.get("Analysing") == "Always", f"Expected Always, got {mon_data.get('Analysing')}"
assert mon_data.get("Recording") == "OnMotion", f"Expected OnMotion, got {mon_data.get('Recording')}"
assert mon_data.get("Decoder") == "h264", f"Expected h264, got {mon_data.get('Decoder')}"
assert float(mon_data.get("MaxFPS", 0)) == 10.0, f"Expected 10.0, got {mon_data.get('MaxFPS')}"
assert float(mon_data.get("AnalysisFPSLimit", 0)) == 8.0, f"Expected 8.0, got {mon_data.get('AnalysisFPSLimit')}"
assert mon_data.get("User") == "admin", f"Expected admin, got {mon_data.get('User')}"
assert str(mon_data.get("Enabled")) == "1", f"Expected 1, got {mon_data.get('Enabled')}"
print("[PASS] 2. Verifikasi field native ZM 1.38.6 LULUS!")

# ==============================================================================
# 3. Pengujian Granular Edit via /api/zones/save-camera (Ubah Decoder & Recording)
# ==============================================================================
edit_res = c.post("/api/zones/save-camera", json={
    "id": mon_id,
    "name": cam_name,
    "path": "rtsp://10.121.8.7/video2",
    "capturing": "Always",
    "analysing": "None",
    "recording": "Always",
    "maxFps": "12.00",
    "analysisFps": "6.00",
    "decoder": "hevc",
    "createZone": False,
})
assert edit_res.status_code == 200, f"HTTP {edit_res.status_code}: {edit_res.get_data(as_text=True)}"
mon_edit = c.get(f"/zm/api/monitors/{mon_id}.json").get_json().get("monitor", {}).get("Monitor", {})
assert mon_edit.get("Capturing") == "Always"
assert mon_edit.get("Analysing") == "None"
assert mon_edit.get("Recording") == "Always"
assert mon_edit.get("Decoder") == "hevc"
assert float(mon_edit.get("MaxFPS", 0)) == 12.0
assert float(mon_edit.get("AnalysisFPSLimit", 0)) == 6.0
print("[PASS] 3. Verifikasi Granular Edit (Cap=Always, Ana=None, Rec=Always, Decoder=hevc) LULUS!")

# ==============================================================================
# 4. Turn OFF & Turn ON
# ==============================================================================
off_res = c.post("/api/cameras/bulk-function", json={
    "action": "off",
    "ids": [mon_id],
})
assert off_res.status_code == 200
mon_off = c.get(f"/zm/api/monitors/{mon_id}.json").get_json().get("monitor", {}).get("Monitor", {})
assert mon_off.get("Capturing") == "None"
assert mon_off.get("Analysing") == "None"
assert mon_off.get("Recording") == "None"
assert str(mon_off.get("Enabled")) == "0"
print("[PASS] 4. Verifikasi Turn OFF -> Triad (None, None, None, Enabled=0) LULUS!")

on_res = c.post("/api/cameras/bulk-function", json={
    "action": "on",
    "ids": [mon_id],
})
assert on_res.status_code == 200
mon_on = c.get(f"/zm/api/monitors/{mon_id}.json").get_json().get("monitor", {}).get("Monitor", {})
assert mon_on.get("Capturing") == "Always"
print("[PASS] 5. Verifikasi Restore ON -> Pulih LULUS!")

# Hapus kamera uji tunggal
del_res = c.delete(f"/zm/api/monitors/{mon_id}.json")
assert del_res.status_code in [200, 204]
print("[PASS] 6. Monitor uji tunggal dibersihkan.")

# ==============================================================================
# 5. Pendaftaran Massal via /api/zoneminder/burst-add
# ==============================================================================
burst_payload = {
    "monitors": [
        {
            "Monitor": {
                "Name": "BURST_TEST_ZM138_1",
                "Path": "rtsp://10.121.8.10/video1",
                "User": "admin",
                "Pass": "admin",
                "Capturing": "Always",
                "Analysing": "Always",
                "Recording": "OnMotion",
                "Width": "1280",
                "Height": "720",
                "MaxFPS": "10.00",
                "AnalysisFPS": "8.00",
                "Decoder": "h264_cuvid",
            }
        },
        {
            "Monitor": {
                "Name": "BURST_TEST_ZM138_2",
                "Path": "rtsp://10.121.8.11/video2",
                "User": "operator",
                "Pass": "0p3r@t0r",
                "Capturing": "Always",
                "Analysing": "None",
                "Recording": "Always",
                "Width": "1920",
                "Height": "1080",
                "MaxFPS": "10.00",
                "AnalysisFPS": "8.00",
                "Decoder": "Auto",
            }
        }
    ],
    "createZone": False,
}
burst_res = c.post("/api/zoneminder/burst-add", json=burst_payload)
assert burst_res.status_code == 200, f"HTTP {burst_res.status_code}: {burst_res.get_data(as_text=True)}"
burst_json = burst_res.get_json()
assert burst_json.get("success_count") == 2, f"Burst failed: {burst_json}"
print(f"[PASS] 7. Burst Add 2 kamera berhasil: {burst_json.get('success_count')} sukses!")

# Periksa burst monitor 1
b1_id = dash.find_monitor_id_by_name("BURST_TEST_ZM138_1")
assert b1_id is not None
b1_get = c.get(f"/zm/api/monitors/{b1_id}.json").get_json().get("monitor", {}).get("Monitor", {})
assert b1_get.get("Decoder") == "h264_cuvid"
assert b1_get.get("Capturing") == "Always"
assert b1_get.get("Recording") == "OnMotion"
c.delete(f"/zm/api/monitors/{b1_id}.json")

# Periksa burst monitor 2
b2_id = dash.find_monitor_id_by_name("BURST_TEST_ZM138_2")
assert b2_id is not None
b2_get = c.get(f"/zm/api/monitors/{b2_id}.json").get_json().get("monitor", {}).get("Monitor", {})
assert b2_get.get("Capturing") == "Always"
assert b2_get.get("Recording") == "Always"
assert b2_get.get("Width") == 1920 or b2_get.get("Width") == "1920"
c.delete(f"/zm/api/monitors/{b2_id}.json")

print("[PASS] 8. Verifikasi detail Burst Monitors dan pembersihan LULUS!")

print("\n==================================================================")
print("SELURUH FITUR REGISTRASI ZM v1.38.6 TRIAD & PARAMETER SUKSES 100%!")
print("==================================================================")
