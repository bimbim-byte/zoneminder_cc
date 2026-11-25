"""Hapus monitor uji (soft delete) dari ZoneMinder.

Daftar prefix di bawah mencakup nama monitor uji dari seluruh sesi verifikasi:
triad/decoder, event fields, encoding, zone mode, dan zone preset
(VERIFY_*, ZTEST_*, CAM_LT1_*). Monitor produksi (Lest, Mest) tidak pernah
cocok dengan prefix mana pun, jadi aman dijalankan berulang.
"""
import sys

sys.path.insert(0, "/app")
import app as dash  # noqa: E402

TEST_PREFIXES = (
    "EVF_SINGLE_TEST", "EVF_BURST_TEST", "E2E_TESTCAM", "PARITY_TEST",
    # Monitor uji jalur encoding / Excel / burst.
    "XL_A_", "XL_B_", "XL_C_", "XL_D_", "Enc_Single_", "Enc_Burst_",
    "KW_PROBE", "BROWSER_PROBE", "BURST_TEST", "ZONE_TEST", "ZMFIELD",
    # Monitor uji probe skema & triad.
    "PROBE_ENUM", "TEST_138_TRIAD", "SQ_Cam",
    # Monitor uji zone mode (sesi sebelumnya).
    "ZTEST_PRESET_TMP", "ZTEST_BURST_TMP", "ZTEST_SAVE_TMP",
    "ZTEST_SAVE2_TMP", "ZTEST_SINGLE_TMP",
    # Monitor uji zone preset (sesi ini).
    "CAM_LT1_", "VERIFY_XL_", "VERIFY_SINGLE_",
)

data = dash.zm_api_get("monitors.json") or {}
removed = 0
for item in (data.get("monitors", []) or []):
    m = item.get("Monitor", item)
    name = str(m.get("Name", ""))
    if not name.startswith(TEST_PREFIXES):
        continue
    if m.get("Deleted") is True:
        print("  [skip] Id=%s %s sudah terhapus" % (m.get("Id"), name))
        continue
    rc = dash.zm_delete("monitors/%s.json" % m.get("Id"))
    print("  [del]  Id=%s %s -> HTTP %s" % (m.get("Id"), name, rc))
    removed += 1

print("")
print("Monitor uji dihapus: %d" % removed)
