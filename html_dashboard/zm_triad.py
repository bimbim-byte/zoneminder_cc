"""Sinkronisasi model kontrol fungsi dan parameter ZoneMinder v1.38.6.

Di ZoneMinder 1.38, kontrol operasi monitor dipecah menjadi triad kontrol native:
  1. Capturing: 'None' | 'Always' | 'Ondemand'
     (mengendalikan langsung daemon zmc & zmwatch.pl; jika 'None', capture mati)
  2. Analysing: 'None' | 'Always'
     (mengendalikan analisis motion detection di dalam proses zmc)
  3. Recording: 'None' | 'OnMotion' | 'Always'
     (mengendalikan apakah event/rekaman disimpan ke disk)
  4. Enabled: '0' | '1'

Decoder yang didukung:
  'Auto', 'h264', 'h264_cuvid', 'h264_vaapi', 'h264_qsv', 'hevc', 'hevc_cuvid', 'hevc_vaapi'

Modul ini menyediakan template monitor ZM 1.38.6 lengkap yang identik dengan
hasil ekspor API ZoneMinder 1.38.6 native, pemetaan dua arah, normalisasi,
dan pembuatan payload yang kompatibel 100%.
"""
import re

VALID_CAPTURING = ("None", "Always", "Ondemand")
VALID_ANALYSING = ("None", "Always")
VALID_RECORDING = ("None", "OnMotion", "Always")

# Daftar decoder = daftar dropdown native ZoneMinder 1.38.6
# (lihat skins/classic/views/monitor.php pada blok $decoders).
# Kunci memakai huruf kecil karena itulah nilai yang disimpan ZM; 'auto'
# berarti tanpa akselerasi eksplisit.
# ------------------------------------------------------------------------------
# Konfigurasi event & analisis (Monitor ZM 1.38.6)
# ------------------------------------------------------------------------------
# Nilai di bawah HARUS sama dengan yang diterima ZoneMinder. Sumber kebenaran
# adalah skema database (MariaDB) dan form native:
#
#   Muncul di /usr/share/zoneminder/www/skins/classic/views/monitor.php:
#     SectionLength, MinSectionLength, EventCloseMode, FrameSkip,
#     AnalysisUpdateDelay, FPSReportInterval, Importance, StartupDelay
#
#   Tipe kolom di tabel Monitors (SHOW COLUMNS FROM Monitors):
#     SectionLength        int(10) unsigned      default 600
#     MinSectionLength     int(10) unsigned      default 10
#     FrameSkip            smallint(5) unsigned  default 0
#     AnalysisUpdateDelay  smallint(5) unsigned  default 0
#     FPSReportInterval    smallint(5) unsigned  default 250
#     StartupDelay         int(11)               default 0
#     EventCloseMode       enum('system','time','duration','idle','alarm')
#     Importance           enum('Normal','Less','Not')
#
# PENTING: nilai enum ENUM di MySQL bersifat case-sensitive. ZM menyimpan
# 'system' (huruf kecil) dan 'Normal' (huruf besar). Mengirim 'System' pada
# EventCloseMode akan ditolak/di-kosongkan, karena itu normalize_event_close_mode()
# memetakan label UI ('System', 'Time', ...) ke nilai kanonik.
EVENT_CLOSE_MODES = ("system", "time", "duration", "idle", "alarm")
EVENT_CLOSE_MODE_LABELS = {
    "system": "System",
    "time": "Time",
    "duration": "Duration",
    "idle": "Idle",
    "alarm": "Alarm",
}

IMPORTANCE_VALUES = ("Normal", "Less", "Not")

# Batas atas mengikuti tipe kolom di atas. smallint(5) unsigned = 65535.
# Nilai di atas batas akan ditolak MariaDB dengan error "Out of range value",
# sehingga dipotong di sini dan tidak dibiarkan menggagalkan seluruh simpan.
_FIELD_LIMITS = {
    "SectionLength": (0, 4294967295),
    "MinSectionLength": (0, 4294967295),
    "FrameSkip": (0, 65535),
    "AnalysisUpdateDelay": (0, 65535),
    "FPSReportInterval": (0, 65535),
    "StartupDelay": (-2147483648, 2147483647),
}

VALID_DECODERS = (
    "auto",
    "h264",
    "h264_cuvid",
    "h264_vaapi",
    "h264_qsv",
    "hevc",
    "hevc_cuvid",
    "hevc_vaapi",
    "hevc_qsv",
    "libx264",
    "libx265",
    "h264_nvmpi",
    "h264_mmal",
    "h264_omx",
    "h264_v4l2m2m",
    "hevc_nvmpi",
    "vp8_nvmpi",
    "libvpx-vp9",
    "vp9_qsv",
    "vp9_cuvid",
    "vp9_nvmpi",
    "vp9_v4l2m2m",
    "libsvtav1",
    "libaom-av1",
    "libdav1d",
    "av1",
    "av1_qsv",
    "av1_cuvid",
)

ZM_OFF_FUNCTION = "None"
ZM_ACTIVE_FUNCTIONS = ("Monitor", "Modect", "Record", "Mocord", "Nodect")

ZM_TRIAD_DEFAULTS = {
    "None":    {"Capturing": "None",   "Analysing": "None",   "Recording": "None",     "Enabled": "0"},
    "Monitor": {"Capturing": "Always", "Analysing": "None",   "Recording": "None",     "Enabled": "1"},
    "Modect":  {"Capturing": "Always", "Analysing": "Always", "Recording": "OnMotion", "Enabled": "1"},
    "Record":  {"Capturing": "Always", "Analysing": "None",   "Recording": "Always",   "Enabled": "1"},
    "Mocord":  {"Capturing": "Always", "Analysing": "Always", "Recording": "Always",   "Enabled": "1"},
    "Nodect":  {"Capturing": "Always", "Analysing": "None",   "Recording": "OnMotion", "Enabled": "1"},
}

# Nilai default lengkap untuk Monitor ZM 1.38.6 (disamakan dengan API ZM 1.38.6)
ZM138_BASE_DEFAULTS = {
    "Type": "Ffmpeg",
    "ServerId": "0",
    "StorageId": "0",
    "Method": "rtpRtsp",
    "Options": "",
    "AnalysisSource": "Primary",
    "AnalysisImage": "FullColour",
    "DecodingEnabled": "1",
    "Decoding": "Always",
    "RTSP2WebEnabled": "0",
    "RTSP2WebType": "WebRTC",
    "StreamChannel": "CameraDirectPrimary",
    "Go2RTCEnabled": "0",
    "JanusEnabled": "0",
    "JanusAudioEnabled": "0",
    "Janus_Profile_Override": "",
    "Restream": "0",
    "Janus_RTSP_Session_Timeout": "0",
    "Triggers": "",
    "EventStartCommand": "",
    "EventEndCommand": "",
    "ONVIF_URL": "",
    "ONVIF_Events_Path": "/Events",
    "ONVIF_Username": "",
    "ONVIF_Password": "",
    "ONVIF_Options": "",
    "ONVIF_Event_Listener": "0",
    "ONVIF_Alarm_Text": "MotionAlarm",
    "use_Amcrest_API": "0",
    "Device": "",  # WAJIB string kosong agar validasi allowEmpty CakePHP tidak gagal
    "Channel": "0",
    "Format": "0",
    "Port": "",
    "SubPath": "",
    "Colours": "4",
    "TargetColorspace": "4",
    "Palette": "0",
    "Orientation": "ROTATE_0",
    "Deinterlacing": "0",
    "SaveJPEGs": "0",
    "VideoWriter": "1",
    "OutputCodec": "27",
    "OutputCodecName": "h264",
    "Encoder": "libx264",
    "OutputContainer": "mp4",
    "EncoderParameters": "crf=23",
    "WallClockTimestamps": "0",
    "RecordAudio": "0",
    "RecordingSource": "Primary",
    "Brightness": "-1",
    "Contrast": "-1",
    "Hue": "-1",
    "Colour": "-1",
    "EventPrefix": "Event-",
    "LabelX": "0",
    "LabelY": "0",
    "LabelSize": "1",
    "ImageBufferCount": "3",
    "MaxImageBufferCount": "0",
    "WarmupCount": "0",
    "PreEventCount": "50",
    "PostEventCount": "50",
    "StreamReplayBuffer": "0",
    "AlarmFrameCount": "1",
    "SectionLength": "300",
    "SectionLengthWarn": "0",
    "EventCloseMode": "system",
    "MinSectionLength": "60",
    "FrameSkip": "0",
    "MotionFrameSkip": "0",
    "AnalysisUpdateDelay": "0",
    "FPSReportInterval": "250",
    "RefBlendPerc": "6",
    "AlarmRefBlendPerc": "6",
    "Controllable": "0",
    "TrackMotion": "0",
    "ReturnLocation": "-1",
    "ModectDuringPTZ": "0",
    "DefaultRate": "100",
    "DefaultScale": "0",
    "DefaultCodec": "auto",
    "SignalCheckPoints": "0",
    "SignalCheckColour": "#0000be",
    "WebColour": "#ff0000",
    "Exif": "0",
    "SOAP_wsa_compl": "1",
    "Importance": "Normal",
    "MQTT_Enabled": "0",
    "MQTT_Subscriptions": "",
    "StartupDelay": "0",
}


def normalize_capturing(val, default="Always"):
    """Normalisasi Capturing ZM 1.38: None | Always | Ondemand."""
    v = str(val or "").strip().lower()
    if v in ("none", "off", "0", "false"):
        return "None"
    if v in ("ondemand", "demand"):
        return "Ondemand"
    if v in ("always", "on", "1", "true"):
        return "Always"
    return default


def normalize_analysing(val, default="None"):
    """Normalisasi Analysing ZM 1.38: None | Always."""
    v = str(val or "").strip().lower()
    if v in ("always", "on", "1", "true", "yes", "modect", "mocord"):
        return "Always"
    if v in ("none", "off", "0", "false", "no"):
        return "None"
    return default


def normalize_recording(val, default="None"):
    """Normalisasi Recording ZM 1.38: None | OnMotion | Always."""
    v = str(val or "").strip().lower()
    if v in ("always", "record", "mocord"):
        return "Always"
    if v in ("onmotion", "motion", "modect", "nodect"):
        return "OnMotion"
    if v in ("none", "off", "0", "false"):
        return "None"
    return default


def normalize_event_close_mode(val, default="system"):
    """Normalisasi EventCloseMode ZM 1.38: system|time|duration|idle|alarm.

    Nilai enum MySQL bersifat case-sensitive — harus huruf kecil. Label UI
    seperti 'System' atau 'Duration' yang dikirim browser dipetakan ke bentuk
    kanonik. Input tidak dikenal jatuh ke `default`.
    """
    v = str(val or "").strip().lower()
    return v if v in EVENT_CLOSE_MODES else default


def normalize_importance(val, default="Normal"):
    """Normalisasi Importance ZM 1.38: Normal|Less|Not.

    Enum MySQL case-sensitive dengan huruf pertama kapital. Label UI seperti
    'normal' atau 'NOT IMPORTANCE' dipetakan ke bentuk kanonik. Input tidak
    dikenal jatuh ke `default`.
    """
    v = str(val or "").strip().capitalize()
    if v in IMPORTANCE_VALUES:
        return v
    lv = v.lower()
    if lv in ("not", "not important", "none"):
        return "Not"
    if lv in ("less", "less important"):
        return "Less"
    return default


def normalize_int_field(val, key, default=0):
    """Normalisasi field numerik integer monitor ZM.

    Konversi string dari form/Excel -> int, potong ke batas kolom MySQL
    (lihat _FIELD_LIMITS), dan jatuh ke `default` bila kosong/tidak valid.
    Mengembalikan nilai bertipe int (bukan str) supaya payload JSON yang
    dikirim ke ZM API berisi angka, bukan string — konsisten dengan tipe
    kolom di tabel Monitors.
    """
    lo, hi = _FIELD_LIMITS.get(key, (0, 2147483647))
    try:
        n = int(float(str(val).strip()))
    except (ValueError, TypeError):
        return int(default)
    return max(lo, min(hi, n))


def normalize_decoder(val, default="auto"):
    """Normalisasi pilihan decoder FFmpeg ke nilai kanonik ZoneMinder 1.38.6.

    ZoneMinder menyimpan Monitor[Decoder] sebagai varchar bebas dan daftar
    bawaannya memakai huruf kecil ('auto', 'h264', 'h264_cuvid', ...). Nilai
    yang tidak ada di daftar sengaja DITERUSKAN apa adanya: monitor lama bisa
    memakai decoder sah yang tidak ada di daftar (mis. 'av1'), dan menimpanya
    menjadi 'auto' akan mengubah perilaku dekode tanpa sepengetahuan operator.
    """
    v = str(val or "").strip()
    if not v:
        return default
    for dec in VALID_DECODERS:
        if dec.lower() == v.lower():
            return dec
    return v


def derive_function_from_triad(capturing, analysing, recording):
    """Menentukan Function legacy yang paling cocok dari kombinasi triad ZM 1.38.

    Dibutuhkan untuk skema tabel Monitors database MariaDB di mana kolom Function
    masih memiliki NOT NULL constraint dan enum legacy.
    """
    cap = normalize_capturing(capturing)
    ana = normalize_analysing(analysing)
    rec = normalize_recording(recording)

    if cap == "None":
        return "None"
    if ana == "Always" and rec == "Always":
        return "Mocord"
    if ana == "Always" and rec == "OnMotion":
        return "Modect"
    if ana == "None" and rec == "Always":
        return "Record"
    if ana == "None" and rec == "OnMotion":
        return "Nodect"
    return "Monitor"


def build_zm138_triad(function=None, capturing=None, analysing=None, recording=None, enabled=None):
    """
    Menyelaraskan nilai Function dan Triad native (Capturing, Analysing, Recording).

    Mengembalikan dictionary:
      {
        "Function": str,
        "Capturing": str,
        "Analysing": str,
        "Recording": str,
        "Enabled": str ("0" atau "1")
      }
    """
    has_triad_input = (capturing is not None or analysing is not None or recording is not None)

    if has_triad_input:
        cap = normalize_capturing(capturing, default="Always")
        ana = normalize_analysing(analysing, default="None")
        rec = normalize_recording(recording, default="None")
        derived_fn = derive_function_from_triad(cap, ana, rec)
        effective_fn = derived_fn
        en = "0" if cap == "None" else "1"
    else:
        fn_raw = str(function or "Monitor").strip().capitalize()
        if fn_raw == "None":
            effective_fn = "None"
            cap, ana, rec, en = "None", "None", "None", "0"
        elif fn_raw in ZM_ACTIVE_FUNCTIONS:
            effective_fn = fn_raw
            if effective_fn == "Modect":
                cap, ana, rec, en = "Always", "Always", "OnMotion", "1"
            elif effective_fn == "Record":
                cap, ana, rec, en = "Always", "None", "Always", "1"
            elif effective_fn == "Mocord":
                cap, ana, rec, en = "Always", "Always", "Always", "1"
            elif effective_fn == "Nodect":
                cap, ana, rec, en = "Always", "None", "OnMotion", "1"
            else:
                cap, ana, rec, en = "Always", "None", "None", "1"
        else:
            effective_fn = "Monitor"
            cap, ana, rec, en = "Always", "None", "None", "1"

    if enabled is not None:
        en = "1" if str(enabled).lower() in ("1", "true", "yes", "on") else "0"

    return {
        "Function": effective_fn,
        "Capturing": cap,
        "Analysing": ana,
        "Recording": rec,
        "Enabled": en,
    }


def zm138_monitor_payload(triad_dict):
    """Bungkus field triad untuk POST ke ZM API."""
    return {
        "Monitor[Function]": triad_dict["Function"],
        "Monitor[Capturing]": triad_dict["Capturing"],
        "Monitor[Analysing]": triad_dict["Analysing"],
        "Monitor[Recording]": triad_dict["Recording"],
        "Monitor[Enabled]": triad_dict["Enabled"],
        "Monitor[Device]": "",
    }


def build_zm138_full_payload(
    name,
    path,
    username=None,
    password=None,
    capturing="Always",
    analysing="None",
    recording="None",
    width="1280",
    height="720",
    max_fps="10.00",
    analysis_fps_limit="8.00",
    decoder="auto",
    enabled="1",
    function=None,
    overrides=None,
    section_length=300,
    min_section_length=60,
    event_close_mode="system",
    frame_skip=0,
    analysis_update_delay=0,
    fps_report_interval=250,
    importance="Normal",
    startup_delay=0,
):
    """
    Membangun dictionary payload POST ke ZM API v1.38.6 ('Monitor[Key]': Value)
    yang persis cocok dengan struktur monitor native ZoneMinder 1.38.6.
    """
    clean_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(name or "CCTV").strip())

    triad = build_zm138_triad(
        function=function,
        capturing=capturing,
        analysing=analysing,
        recording=recording,
        enabled=enabled,
    )

    dec_val = normalize_decoder(decoder)

    # Format FPS
    try:
        max_fps_val = f"{float(max_fps):.2f}"
    except (ValueError, TypeError):
        max_fps_val = "10.00"

    try:
        analysis_fps_val = f"{float(analysis_fps_limit):.2f}"
    except (ValueError, TypeError):
        analysis_fps_val = "8.00"

    # Normalisasi field event & analisis. Nilai di sini WAJIB berupa angka
    # (bukan string) agar payload JSON sesuai tipe kolom di tabel Monitors
    # dan tidak ditolak MariaDB saat ZM menyimpan monitor.
    event_fields = {
        "SectionLength": normalize_int_field(section_length, "SectionLength", 300),
        "MinSectionLength": normalize_int_field(min_section_length, "MinSectionLength", 60),
        "FrameSkip": normalize_int_field(frame_skip, "FrameSkip", 0),
        "AnalysisUpdateDelay": normalize_int_field(analysis_update_delay, "AnalysisUpdateDelay", 0),
        "FPSReportInterval": normalize_int_field(fps_report_interval, "FPSReportInterval", 250),
        "StartupDelay": normalize_int_field(startup_delay, "StartupDelay", 0),
        "EventCloseMode": normalize_event_close_mode(event_close_mode),
        "Importance": normalize_importance(importance),
    }

    # Salin default dasar
    monitor_fields = dict(ZM138_BASE_DEFAULTS)

    # Isi field utama
    monitor_fields.update({
        "Name": clean_name,
        "Path": str(path or "").strip(),
        "User": str(username or "").strip(),
        "Pass": str(password or "").strip(),
        "Capturing": triad["Capturing"],
        "Analysing": triad["Analysing"],
        "Recording": triad["Recording"],
        "Function": triad["Function"],
        "Enabled": triad["Enabled"],
        "Width": str(width or "1280").strip(),
        "Height": str(height or "720").strip(),
        "MaxFPS": max_fps_val,
        "AlarmMaxFPS": max_fps_val,
        "AnalysisFPSLimit": analysis_fps_val,
        "Decoder": dec_val,
    })

    # Field event & analisis (SectionLength, EventCloseMode, FrameSkip, ...).
    # Diterapkan setelah field utama, sebelum overrides, sehingga nilai dari
    # form selalu menang atas default ZM138_BASE_DEFAULTS.
    monitor_fields.update(event_fields)

    # Terapkan overrides jika ada
    if isinstance(overrides, dict):
        for k, v in overrides.items():
            if v is not None:
                monitor_fields[k] = str(v)

    # Bungkus menjadi format form-encoded CakePHP: Monitor[Field]
    payload = {}
    for k, v in monitor_fields.items():
        payload[f"Monitor[{k}]"] = str(v)

    return payload
