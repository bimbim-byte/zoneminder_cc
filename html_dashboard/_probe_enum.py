import sys
sys.path.insert(0, "/app")
import app as d

data = d.zm_api_get("monitors.json")
ms = (data or {}).get("monitors", [])
print("total:", len(ms))
if ms:
    m = ms[0].get("Monitor", ms[0])
    for k in ("VideoWriter", "OutputCodec", "OutputCodecName", "Encoder",
              "OutputContainer", "EncoderParameters", "StorageId", "SaveJPEGs",
              "RecordingSource"):
        print(k, "=", repr(m.get(k)))
