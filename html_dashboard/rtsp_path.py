"""Normalisasi path RTSP dan batas laju analisa motion.

Modul ini sengaja TIDAK mengimpor Flask/requests, supaya:
  1. bisa diuji langsung (lihat _verify_rtsp_path.py) tanpa menjalankan app,
  2. bisa dipakai ulang oleh skrip perbaikan data lama.

Lihat docstring normalize_rtsp_path() untuk penjelasan bug yang diperbaiki.
"""

from urllib.parse import quote, unquote

# ==============================================================================
# BATAS LAJU ANALISA MOTION
# ==============================================================================
# Nilai ini mengisi Monitor[AnalysisFPSLimit] yang membatasi berapa frame per
# detik yang diproses zma. Untuk Modect 8 fps sudah cukup: deteksi gerakan
# tidak butuh 10-25 fps, dan setiap frame yang tidak dianalisa menghemat CPU
# dan I/O database secara linear.
#
# PENTING - jangan tertukar dengan Monitor[MaxFPS]:
#   AnalysisFPSLimit -> batas ANALISA (zma). Rekaman tetap penuh.
#   MaxFPS           -> batas CAPTURE; bila diisi zmc MEMBUANG frame kamera,
#                       sehingga event bisa kehilangan frame penting.
ANALYSIS_FPS_DEFAULT = 8
ANALYSIS_FPS_MIN = 1
ANALYSIS_FPS_MAX = 30

# Opsi input ffmpeg tambahan. Transport TIDAK diulang di sini karena sudah
# diatur Monitor[Method] -> rtsp_transport=tcp.
#
# Kenapa hanya "timeout" yang dipakai: zmc 1.38 meneruskan isi
# Monitor[Options] sebagai opsi DEMUXER. ffmpeg 7.1.5 di image ini punya
# "-timeout <int64> (microseconds)" pada demuxer RTSP, dan nilainya benar-benar
# diterapkan ke socket TCP:
#     $ ffmpeg -f rtsp -rtsp_transport tcp -timeout 5000000 -i rtsp://host/x
#     [tcp @ ...] Connection to tcp://host:554?timeout=5000000 ...
# Opsi alternatif "rw_timeout" TIDAK ikut ke socket (terbukti tetap
# "?timeout=0"), jadi jangan dipakai lewat Monitor[Options].
#
# Tanpa batas timeout, stream kamera yang mati membuat zmc menggantung dan
# monitor tampak "hidup" di dashboard padahal tidak mengirim frame.
ZM_FFMPEG_TIMEOUT_US = "5000000"
ZM_FFMPEG_OPTIONS = "timeout=%s" % ZM_FFMPEG_TIMEOUT_US


def normalize_analysis_fps(value):
    """Batas analisa yang aman dikirim ke ZoneMinder.

    Kosong/null -> ANALYSIS_FPS_DEFAULT. Angka di luar jangkauan di-clamp
    supaya satu sel Excel yang salah tidak mengirim nilai yang ditolak API.
    Nilai 0 sengaja TIDAK diteruskan: di ZoneMinder 0 berarti "analisa setiap
    frame", yaitu justru beban yang ingin dihindari.
    """
    if value is None:
        return ANALYSIS_FPS_DEFAULT
    text = str(value).strip().replace(",", ".")
    if text == "":
        return ANALYSIS_FPS_DEFAULT
    try:
        number = float(text)
    except (TypeError, ValueError):
        return ANALYSIS_FPS_DEFAULT
    if number <= 0:
        return ANALYSIS_FPS_DEFAULT
    number = int(round(number))
    return max(ANALYSIS_FPS_MIN, min(ANALYSIS_FPS_MAX, number))


# Batas CAPTURE (zmc), berbeda dari AnalysisFPSLimit yang membatasi zma.
#
# KOREKSI PENTING (terukur di server ini, ZM 1.38.6): catatan lama menyatakan
# MaxFPS "sengaja tidak dikirim karena zmc membuang frame". Itu KELIRU dan
# berakibat nyata — tanpa MaxFPS kolomnya NULL dan capture mengikuti laju asli
# kamera:
#     MaxFPS=NULL -> CaptureFPS 14.98 (CAM_SQ_01), 25.10 (CAM_SQ_02)
#     MaxFPS=10   -> CaptureFPS 10.00 (keduanya)
# Stream kamera memang 25 fps, sedangkan target arsitektur 10 fps agar 60
# kamera tetap muat. zmc mencatat "Changing fps to be < max %.2f" saat nilai
# ini dipakai, jadi pembatasan terjadi di sisi capture.
CAPTURE_FPS_DEFAULT = 10

# AlarmMaxFPS disamakan dengan MaxFPS supaya laju capture tidak melonjak saat
# alarm terpicu (default lama 0 = mengikuti laju capture saat alarm).
ALARM_MAX_FPS_DEFAULT = CAPTURE_FPS_DEFAULT


def _monitor_fps_payload(analysis_fps=None):
    """Field FPS yang dikirim saat membuat/menyimpan monitor.

    Dua field diisi, keduanya punya peran berbeda: AnalysisFPSLimit membatasi
    ANALISA motion (zma), MaxFPS membatasi CAPTURE (zmc).
    AlarmMaxFPS disamakan dengan MaxFPS.
    Catatan lama skrip ini menyatakan MaxFPS harus dikosongkan —
    itu sudah dibuktikan keliru lewat pengukuran (lihat CAPTURE_FPS_DEFAULT).
    
    """
    fps = normalize_analysis_fps(analysis_fps)
    return {
        "Monitor[AnalysisFPSLimit]": str(fps),
        # MaxFPS membatasi CAPTURE (zmc). Tanpa ini kolomnya NULL dan zmc
        # menelan stream secepat laju asli kamera: terukur 14.98 dan 25.10 fps
        # pada kamera 25 fps, sementara target arsitektur 10 fps untuk 60
        # kamera. Dengan MaxFPS=10 keduanya turun tepat ke 10.00 fps.
        "Monitor[MaxFPS]": str(CAPTURE_FPS_DEFAULT),
        "Monitor[AlarmMaxFPS]": str(ALARM_MAX_FPS_DEFAULT),
    }


# ==============================================================================
# NORMALISASI PATH RTSP
# ==============================================================================
# BUG YANG PERNAH TERJADI (ZM 1.38.6, terverifikasi di database production):
#
#   URL dimasukkan operator : rtsp://t0r@10.121.10.145:554/Streaming/Channels/101
#   Username field          : operator
#   Password field          : 0p3r@t0r
#   Path TERSIMPAN          : rtsp://operator:0p3r@t0r@10.121.10.145:554/...
#                             ^^^^^^^^^^^^^^^^^^^ password terpotong di "@"
#
# Penyebabnya: dashboard dulu hanya menerima SATU kolom teks, sedangkan
# operator (dan antarmuka ZoneMinder sendiri) memisahkan username/password
# sebagai field tersendiri. Saat keduanya digabung secara naif - "user:pass" +
# "@" + host - password yang mengandung "@" (umum: "0p3r@t0r", "PT@2024")
# menghasilkan URL dengan dua "@".
#
# Akibatnya nyata, bukan teoretis. Parser yang memakai "@" TERAKHIR sebagai
# pemisah userinfo/host (seperti urllib) membaca URL di atas sebagai:
#     username = "operator"
#     password = "0p3r"                 <-- terpotong
#     host     = "t0r@10.121.10.145"    <-- bukan host yang valid
# ffmpeg lalu mencoba resolve host "t0r@10.121.10.145", gagal, monitor tidak
# pernah mengirim frame, dan UI tidak menampilkan sebabnya.
#
# ATURAN YANG DIPAKAI (jangan diubah tanpa memperbarui _verify_rtsp_path.py):
#   1. Batas userinfo/host adalah "@" TERAKHIR yang diikuti bentuk host[:port]
#      yang sah. Dengan aturan ini "rtsp://operator:0p3r@t0r@10.121.10.145:554/x"
#      terbaca benar: userinfo="operator:0p3r@t0r", host="10.121.10.145:554",
#      dan password "0p3r@t0r" TETAP UTUH (ffmpeg menerima bentuk ini apa
#      adanya, terbukti dari uji langsung ke kamera).
#   2. Di dalam userinfo, ":" PERTAMA memisahkan username dan password, jadi
#      password boleh mengandung ":" (mis. "pa:ss").
#   3. Bila URL sudah memuat kredensial, URL itu SUMBER KEBENARAN. Field
#      username/password terpisah diabaikan, dan pengguna diberi tahu.
#   4. Bila URL belum memuat kredensial, field terpisah digabung dengan
#      percent-encode (@ -> %40, : -> %3A, / -> %2F) sehingga tidak mungkin
#      memecah URL.
#   5. Bila kredensial di URL mengandung karakter yang membingungkan parser
#      lain, kredensial ditulis ulang dalam bentuk ter-encode (%40) tanpa
#      mengubah nilainya - monitor lama tetap tersambung.

# Karakter yang aman di dalam komponen userinfo tanpa encoding (@ WAJIB %40).
_RTSP_USERINFO_SAFE = "-._~!$&'()*+,"


def _rtsp_encode_userinfo(text):
    """Percent-encode satu komponen userinfo (username atau password)."""
    return quote(str(text), safe=_RTSP_USERINFO_SAFE)


def _rtsp_unquote_userinfo(text):
    """Kebalikan _rtsp_encode_userinfo: %40 -> @, %3A -> :."""
    return unquote(str(text))


def _is_hostport_token(token):
    """True bila token berbentuk host atau host:port yang masuk akal.

    Dipakai untuk menentukan batas userinfo/host. Tanpa validasi DNS - hanya
    bentuk, karena kamera bisa memakai IP, hostname pendek ("nvr"), atau nama
    domain penuh.
    """
    if not token:
        return False
    if any(ch in token for ch in "/@ \\'\"<>"):
        return False
    if any(ch.isspace() for ch in token):
        return False
    host, sep, port = token.rpartition(":")
    if not sep:
        return bool(token)
    if not host:
        return False
    return port.isdigit() and 0 < int(port) <= 65535


def _find_userinfo_boundary(rest):
    """Tentukan batas userinfo/host dari sisa URL setelah "rtsp://".

    Mengembalikan (userinfo, hostpart, confident):
        userinfo  -> None bila URL tidak membawa kredensial
        hostpart  -> authority tanpa userinfo (host[:port] saja)
        confident -> False bila batas hanya bisa ditebak (host tidak sah)
    """
    authority = rest.split("/", 1)[0]
    if "@" not in authority:
        return None, authority, True

    positions = [idx for idx, ch in enumerate(authority) if ch == "@"]
    for idx in reversed(positions):
        candidate = authority[idx + 1:]
        userinfo = authority[:idx]
        if userinfo and _is_hostport_token(candidate):
            return userinfo, candidate, True

    # Tidak ada batas yang sah. Jangan menyerah: pakai "@" terakhir supaya
    # pengguna tetap mendapat URL yang bisa diperbaiki, plus peringatan.
    idx = positions[-1]
    return authority[:idx] or None, authority[idx + 1:], False


def _split_rtsp_userinfo(url):
    """Pisahkan URL menjadi (skema, userinfo, sisa).

    userinfo = None bila URL tidak membawa kredensial. Pemisah yang dipakai
    adalah "@" terakhir yang diikuti host[:port] yang sah (lihat ATURAN 1).
    """
    scheme, sep, rest = url.partition("://")
    if not sep:
        return url, None, ""
    userinfo, hostpart, confident = _find_userinfo_boundary(rest)
    if not userinfo:
        return scheme + "://", None, rest
    path = rest.split("/", 1)[1] if "/" in rest else ""
    tail = hostpart + ("/" + path if path else "")
    result = [scheme + "://", userinfo, tail]
    if not confident:
        result.append("unconfident")
    return tuple(result)


def _describe_credentials(userinfo):
    """Pecah userinfo menjadi (username, password) yang sudah di-decode."""
    user_raw, _, pass_raw = userinfo.partition(":")
    return _rtsp_unquote_userinfo(user_raw), _rtsp_unquote_userinfo(pass_raw)


def _build_credentials(username, password):
    """Susun komponen userinfo ter-encode dari username/password mentah."""
    cred = _rtsp_encode_userinfo(username)
    if password:
        cred += ":" + _rtsp_encode_userinfo(password)
    return cred


def normalize_rtsp_path(url, username=None, password=None):
    """Kembalikan (path_bersih, peringatan) untuk disimpan ke Monitor[Path].

    Lihat blok "NORMALISASI PATH RTSP" di atas untuk alasan tiap aturan.
    Peringatan berupa list string siap tampil di UI. Path yang tidak dapat
    diperbaiki dikembalikan apa adanya agar kamera lama tidak rusak hanya
    karena halaman edit dibuka.
    """
    warnings = []
    text = (url or "").strip()
    if not text:
        return "", warnings

    if not text.lower().startswith("rtsp://"):
        warnings.append("URL bukan RTSP; path dibiarkan apa adanya.")
        return text, warnings

    user_field = (username or "").strip()
    pass_field = (password or "").strip()

    scheme, userinfo, rest, confident = _split_rtsp_userinfo(text) + (True,)

    if userinfo:
        # URL membawa kredensial -> URL adalah sumber kebenaran.
        if not confident:
            # Batas userinfo/host tidak yakin: beri tahu operator.
            warnings.append(
                "Host pada URL RTSP tidak dapat dikenali dengan pasti; "
                "periksa penulisan kredensial."
            )
        if user_field or pass_field:
            warnings.append(
                "URL sudah memuat kredensial; field username/password "
                "terpisah diabaikan agar tidak menimpa kredensial di URL."
            )
        user, pw = _describe_credentials(userinfo)
        cleaned = _build_credentials(user, pw)
        if cleaned != userinfo:
            warnings.append(
                "Path rusak diperbaiki: karakter khusus pada kredensial "
                "(mis. '@' atau ':') ditulis sebagai %40 / %3A sehingga "
                "host terbaca benar oleh ffmpeg."
            )
        return scheme + cleaned + "@" + rest, warnings

    # Tidak ada kredensial di URL: pakai field terpisah bila diisi.
    if not user_field and not pass_field:
        return text, warnings
    if not rest:
        warnings.append("Host pada URL RTSP tidak terbaca.")
        return text, warnings
    return scheme + _build_credentials(user_field, pass_field) + "@" + rest, warnings
