"""Uji bahwa KEGAGALAN validasi ZoneMinder TIDAK lagi terlihat sebagai sukses.

    docker exec camera-dashboard python /app/error_path_test.py

Bug aslinya: ZM 1.38 membalas HTTP 200 untuk dua kondisi berbeda —
{"message":"Saved"} dan {"message":{...error...}}. Kode lama hanya memeriksa
status code, jadi kamera yang DITOLAK dilaporkan "berhasil" ke operator.
"""
import sys

sys.path.insert(0, "/app")
import app as dash  # noqa: E402

PASS, FAIL = 0, 0


def ok(m):
    global PASS
    PASS += 1
    print("  [OK]   " + m)


def bad(m):
    global FAIL
    FAIL += 1
    print("  [FAIL] " + m)


print("=" * 66)
print("Uji jalur error: kegagalan ZM harus terlihat sebagai kegagalan")
print("=" * 66)


class FakeRes:
    def __init__(self, payload, code=200):
        self._p = payload
        self.status_code = code
        self.text = str(payload)

    def json(self):
        return self._p


print("")
print("[1] _zm_explain_response() membaca empat bentuk respons")

cases = [
    ({"message": "Saved"}, True, "sukses dikenali"),
    ({"message": {"Device": ["Invalid device path."]}}, False, "error validasi dikenali"),
    ({"success": False, "data": {"message": "Invalid monitor"}}, False, "gagal eksplisit dikenali"),
    ({"message": "Error <pre>boom</pre>"}, False, "pesan edit gagal dikenali"),
]

for payload, want_ok, label in cases:
    got_ok, msg = dash._zm_explain_response(FakeRes(payload))
    if got_ok == want_ok:
        ok(label + " -> " + repr(msg)[:70])
    else:
        bad(label + " -> got_ok=" + str(got_ok) + " (harus " + str(want_ok) + ")")

print("")
print("[2] Burst dengan nama kosong tidak boleh dilaporkan sukses")

c = dash.app.test_client()
with c.session_transaction() as sess:
    sess["user"] = "tester"

r = c.post("/api/zoneminder/burst-add", json={
    "monitors": [{"Name": "", "Path": "rtsp://10.0.0.1/x"}],
    "createZone": False,
})
body = r.get_json() or {}
print("     HTTP " + str(r.status_code) + " success_count=" + str(body.get("success_count")))
if body.get("success_count", 0) == 0:
    ok("kamera tanpa nama TIDAK dilaporkan sukses")
else:
    bad("kamera tanpa nama dilaporkan sukses (palsu)")

print("")
print("=" * 66)
print("LULUS: " + str(PASS) + "   GAGAL: " + str(FAIL))
print("SEMUA PEMERIKSAAN JALUR ERROR LULUS" if FAIL == 0 else "ADA YANG GAGAL")
sys.exit(0 if FAIL == 0 else 1)
