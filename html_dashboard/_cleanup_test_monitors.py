"""Hapus monitor uji (soft delete) dari ZoneMinder."""
import sys

sys.path.insert(0, "/app")
import app as dash  # noqa: E402

TEST_PREFIXES = ("EVF_SINGLE_TEST", "EVF_BURST_TEST", "E2E_TESTCAM", "PARITY_TEST")

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
