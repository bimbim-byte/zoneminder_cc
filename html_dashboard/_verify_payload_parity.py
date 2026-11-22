"""Verifikasi payload POST ZM 1.38.6 mencakup seluruh field contoh API.

Dijalankan di container:
    docker exec camera-dashboard python3 /app/_verify_payload_parity.py

Membandingkan kunci pada contoh respons API ZoneMinder 1.38.6 dengan kunci
yang dibangun build_zm138_full_payload(). Field read-only/turunan memang tidak
dikirim saat POST dan sengaja dikecualikan. Field Opsional mengikuti sample
(Opstions dikirim kosong dsb.).
"""
import sys

from zm_triad import build_zm138_full_payload

API_SAMPLE_KEYS = [
    "Id", "Name", "Deleted", "Notes", "ServerId", "StorageId", "ManufacturerId",
    "ModelId", "Type", "Function", "Capturing", "Analysing", "AnalysisSource",
    "AnalysisImage", "Recording", "Enabled", "DecodingEnabled", "Decoding",
    "RTSP2WebEnabled", "RTSP2WebType", "DefaultPlayer", "StreamChannel",
    "Go2RTCEnabled", "JanusEnabled", "JanusAudioEnabled", "Janus_Profile_Override",
    "Restream", "RTSP_User", "Janus_RTSP_Session_Timeout", "LinkedMonitors",
    "Triggers", "EventStartCommand", "EventEndCommand", "ONVIF_URL",
    "ONVIF_Events_Path", "ONVIF_Username", "ONVIF_Password", "ONVIF_Options",
    "ONVIF_Event_Listener", "ONVIF_Alarm_Text", "use_Amcrest_API", "Device",
    "Channel", "Format", "V4LMultiBuffer", "V4LCapturesPerFrame", "Protocol",
    "Method", "Host", "Port", "SubPath", "Path", "SecondPath", "Options",
    "User", "Pass", "Width", "Height", "Colours", "Palette", "Orientation",
    "Deinterlacing", "Decoder", "DecoderHWAccelName", "DecoderHWAccelDevice",
    "SaveJPEGs", "VideoWriter", "OutputCodec", "OutputCodecName", "Encoder",
    "EncoderHWAccelName", "EncoderHWAccelDevice", "OutputContainer",
    "EncoderParameters", "WallClockTimestamps", "RecordAudio", "RecordingSource",
    "RTSPDescribe", "Brightness", "Contrast", "Hue", "Colour", "EventPrefix",
    "LabelFormat", "LabelX", "LabelY", "LabelSize", "ImageBufferCount",
    "MaxImageBufferCount", "WarmupCount", "PreEventCount", "PostEventCount",
    "StreamReplayBuffer", "AlarmFrameCount", "SectionLength", "SectionLengthWarn",
    "EventCloseMode", "MinSectionLength", "FrameSkip", "MotionFrameSkip",
    "AnalysisFPSLimit", "AnalysisUpdateDelay", "MaxFPS", "AlarmMaxFPS",
    "FPSReportInterval", "RefBlendPerc", "AlarmRefBlendPerc", "Controllable",
    "ControlId", "ControlDevice", "ControlAddress", "AutoStopTimeout",
    "TrackMotion", "TrackDelay", "ReturnLocation", "ReturnDelay",
    "ModectDuringPTZ", "DefaultRate", "DefaultScale", "DefaultCodec",
    "SignalCheckPoints", "SignalCheckColour", "WebColour", "Exif", "Sequence",
    "ZoneCount", "Refresh", "Latitude", "Longitude", "RTSPServer",
    "RTSPStreamName", "SOAP_wsa_compl", "Importance", "MQTT_Enabled",
    "MQTT_Subscriptions", "StartupDelay",
]

READ_ONLY = {
    "Id", "Deleted", "Notes", "ManufacturerId", "ModelId", "DefaultPlayer",
    "RTSP_User", "LinkedMonitors", "Protocol", "Host", "SecondPath",
    "V4LMultiBuffer", "V4LCapturesPerFrame", "DecoderHWAccelName",
    "DecoderHWAccelDevice", "EncoderHWAccelName", "EncoderHWAccelDevice",
    "RTSPDescribe", "LabelFormat", "ControlId", "ControlDevice",
    "ControlAddress", "AutoStopTimeout", "TrackDelay", "ReturnDelay",
    "Sequence", "ZoneCount", "Refresh", "Latitude", "Longitude",
    "RTSPServer", "RTSPStreamName",
}

EXTRA_SENT = ["Function"]  # Kolom DB NOT NULL — tetap dikirim demi skema MariaDB

PAYLOAD = build_zm138_full_payload(
    name="PARITY_TEST",
    path="rtsp://10.121.8.7/video2",
    username="admin",
    password="admin",
    capturing="Always",
    analysing="Always",
    recording="OnMotion",
)
SENT = {k[len("Monitor["):-1] for k in PAYLOAD}

required = [k for k in API_SAMPLE_KEYS if k not in READ_ONLY]
missing = [k for k in required if k not in SENT]
extra = sorted(SENT - set(required))

print("Field contoh API    : %d" % len(API_SAMPLE_KEYS))
print("Field read-only     : %d" % len(READ_ONLY))
print("Field wajib dikirim : %d" % len(required))
print("Field terkirim      : %d" % len(SENT))
if extra:
    print("Field tambahan (OK) : %s" % ", ".join(extra))

if PAYLOAD.get("Monitor[Device]") != "":
    print("[FAIL] Monitor[Device] harus string kosong")
    sys.exit(1)
print("[OK]   Monitor[Device]='' hadir (validasi CakePHP allowEmpty)")

if missing:
    print("[FAIL] field wajib belum terkirim: %s" % ", ".join(sorted(missing)))
    sys.exit(1)

print("[OK]   seluruh field wajib ZM 1.38.6 terkirim")
print("[OK]   Method=%s Options=%r" % (PAYLOAD.get("Monitor[Method]"),
                                      PAYLOAD.get("Monitor[Options]")))
print("[OK]   triad Cap=%s Ana=%s Rec=%s" % (
    PAYLOAD["Monitor[Capturing]"], PAYLOAD["Monitor[Analysing]"],
    PAYLOAD["Monitor[Recording]"]))
