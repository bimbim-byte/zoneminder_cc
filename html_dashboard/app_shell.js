/* ==========================================================================
 * app_shell.js - Header Navigasi Bersama & Utilitas Global Dashboard.
 * Minimalis, Rapi, dan Konsisten untuk Seluruh Halaman.
 * ========================================================================== */

(function () {
    'use strict';

    var ZM_ROOT = window.location.protocol + '//' + window.location.hostname + '/zm/';

    /* Daftar decoder FFmpeg native ZoneMinder 1.38.6.
       Satu sumber untuk semua halaman supaya pilihan di UI tidak pernah
       berbeda antar jalur (satuan, burst, Excel, edit).
       Urutan: pilihan yang dipakai sehari-hari lebih dulu, sisanya mengikuti
       daftar asli ZM (lihat getDecodingOptions / dropdown monitor.php). */
    var ZM_DECODERS = [
        'auto', 'h264', 'h264_cuvid', 'h264_vaapi', 'h264_qsv',
        'hevc', 'hevc_cuvid', 'hevc_vaapi', 'hevc_qsv',
        'libx264', 'libx265', 'h264_nvmpi', 'h264_mmal', 'h264_omx',
        'h264_v4l2m2m', 'hevc_nvmpi', 'vp8_nvmpi', 'libvpx-vp9',
        'vp9_qsv', 'vp9_cuvid', 'vp9_nvmpi', 'vp9_v4l2m2m',
        'libsvtav1', 'libaom-av1', 'libdav1d', 'av1', 'av1_qsv', 'av1_cuvid'
    ];

    /* Label ramah untuk nilai Decoder. Nilai tak dikenal ditampilkan apa
       adanya supaya konfigurasi lama (mis. 'av1') tidak tampak kosong. */
    function decoderLabel(value) {
        var v = String(value || '').trim();
        if (!v) return 'Auto';
        if (v.toLowerCase() === 'auto') return 'Auto (deteksi otomatis)';
        return v;
    }

    /* Pastikan sebuah nilai Decoder punya <option> di select, lalu pilih.
       Dipakai saat membuka form edit agar nilai lama tidak ter-reset hanya
       karena belum ada di daftar. */
    function setDecoderValue(select, value) {
        if (!select) return;
        var v = String(value || '').trim() || 'auto';
        var exists = false;
        for (var i = 0; i < select.options.length; i++) {
            if (select.options[i].value === v) { exists = true; break; }
        }
        if (!exists) {
            var opt = document.createElement('option');
            opt.value = v;
            opt.textContent = decoderLabel(v);
            select.appendChild(opt);
        }
        select.value = v;
    }

    /* Isi select Decoder dengan daftar bersama (dipakai halaman tambah). */
    function fillDecoderOptions(select) {
        if (!select) return;
        var current = select.value;
        select.innerHTML = '';
        ZM_DECODERS.forEach(function (d) {
            var opt = document.createElement('option');
            opt.value = d;
            opt.textContent = decoderLabel(d);
            select.appendChild(opt);
        });
        if (current) setDecoderValue(select, current);
    }

    /* ======================================================================
       ENCODING VIDEO ZM 1.38.6 — DAFTAR BERSAMA
       Nilai di bawah mengikuti konsol ZoneMinder 1.38.6 apa adanya. Halaman
       hanya mengisinya, tidak menyalin, supaya pilihan di jalur satuan,
       burst, dan impor Excel tidak pernah berbeda.
       ====================================================================== */

    /* VideoWriter: 0=Disabled, 1=Encode, 2=Camera Passthrough (Ffmpeg). */
    var ZM_VIDEO_WRITERS = [
        { value: '1', label: 'Encode (Rekam & Encode Video)' },
        { value: '0', label: 'Disabled (Tanpa Penulisan Video)' },
        { value: '2', label: 'Camera Passthrough (Simpan Stream Asli)' }
    ];

    /* OutputCodec dikirim BERPASANGAN dengan OutputCodecName: API ZM
       memvalidasi kode int, sedangkan UI ZM membaca nama. */
    var ZM_OUTPUT_CODECS = [
        { value: 'auto', label: 'Auto (mengikuti sumber)', code: '0' },
        { value: 'h264', label: 'H.264 / AVC (paling kompatibel)', code: '27' },
        { value: 'hevc', label: 'H.265 / HEVC (lebih hemat bitrate)', code: '173' },
        { value: 'vp9', label: 'VP9 (WebM-friendly)', code: '167' },
        { value: 'av1', label: 'AV1 (paling efisien, CPU berat)', code: '226' }
    ];

    /* OutputContainer: HANYA auto/mp4/mkv yang diterima API ZM 1.38.6.
       'webm' ditolak dan menggagalkan SELURUH penyimpanan monitor. */
    var ZM_OUTPUT_CONTAINERS = [
        { value: 'mp4', label: 'MP4 (disarankan)' },
        { value: 'mkv', label: 'MKV (Matroska)' },
        { value: 'auto', label: 'Auto (biarkan ZM)' }
    ];

    var ZM_ENCODERS = [
        'auto', 'libx264', 'h264', 'h264_nvenc', 'h264_omx', 'h264_qsv',
        'h264_vaapi', 'h264_v4l2m2m', 'libx265', 'hevc_nvenc', 'hevc_qsv',
        'hevc_vaapi', 'libvpx-vp9', 'vp9-qsv', 'libsvtav1', 'libaom-av1',
        'av1_qsv', 'av1_vaapi', 'av1_nvenc'
    ];

    var ZM_ENCODER_PARAMETERS_DEFAULT = 'crf=23';

    /* Isi sebuah <select> dari daftar {value,label}. Nilai yang sedang aktif
       dipertahankan bila masih ada; nilai lama yang tidak ada di daftar
       ditambahkan sebagai opsi agar form edit tidak merusak konfigurasi. */
    function fillSelect(select, items, preferred) {
        if (!select) return;
        var current = preferred !== undefined ? preferred : select.value;
        select.innerHTML = '';
        items.forEach(function (item) {
            var opt = document.createElement('option');
            opt.value = String(item.value);
            opt.textContent = item.label;
            select.appendChild(opt);
        });
        if (current !== undefined && current !== null && String(current) !== '') {
            var found = false;
            for (var i = 0; i < select.options.length; i++) {
                if (select.options[i].value === String(current)) { found = true; break; }
            }
            if (!found) {
                var extra = document.createElement('option');
                extra.value = String(current);
                extra.textContent = String(current);
                select.appendChild(extra);
            }
            select.value = String(current);
        }
    }

    function fillVideoWriterOptions(select, preferred) {
        fillSelect(select, ZM_VIDEO_WRITERS, preferred);
    }

    function fillOutputCodecOptions(select, preferred) {
        fillSelect(select, ZM_OUTPUT_CODECS, preferred);
    }

    function fillOutputContainerOptions(select, preferred) {
        fillSelect(select, ZM_OUTPUT_CONTAINERS, preferred);
    }

    function fillEncoderOptions(select, preferred) {
        fillSelect(select, ZM_ENCODERS.map(function (e) {
            return { value: e, label: e === 'auto' ? 'auto (pilih otomatis)' : e };
        }), preferred);
    }

    /* Blok encoding (Codec/Encoder/Parameters/Container) hanya relevan saat
       VideoWriter = Encode (1). Saat Disabled/Passthrough, ZM mengabaikan
       nilai di dalamnya — jadi kontrolnya disembunyikan supaya operator
       tidak menyetel sesuatu yang tidak akan dipakai. */
    function toggleEncodingBlock(writerSelect, blockEl) {
        if (!blockEl) return;
        var isEncode = String(writerSelect && writerSelect.value) === '1';
        blockEl.style.display = isEncode ? '' : 'none';
    }

    /* Isi semua kontrol encoding pada satu wadah (form tunggal atau panel
       default burst). Setiap id diberi awalan yang sama supaya halaman bisa
       memakai satu fungsi untuk beberapa lokasi. */
    function fillEncodingControls(root, values) {
        if (!root) return;
        var v = values || {};
        fillVideoWriterOptions(root.querySelector('[data-encoding="videoWriter"]'), v.videoWriter);
        fillOutputCodecOptions(root.querySelector('[data-encoding="outputCodec"]'), v.outputCodec);
        fillEncoderOptions(root.querySelector('[data-encoding="encoder"]'), v.encoder);
        fillOutputContainerOptions(root.querySelector('[data-encoding="outputContainer"]'), v.outputContainer);

        var params = root.querySelector('[data-encoding="encoderParameters"]');
        if (params) params.value = v.encoderParameters || ZM_ENCODER_PARAMETERS_DEFAULT;

        var storage = root.querySelector('[data-encoding="storageId"]');
        if (storage && v.storageId !== undefined && v.storageId !== null) {
            storage.value = String(v.storageId);
        }

        var writer = root.querySelector('[data-encoding="videoWriter"]');
        toggleEncodingBlock(writer, root.querySelector('[data-encoding-block="encode"]'));
    }

    /* Baca nilai encoding dari satu wadah menjadi objek siap kirim ke API.
       Field yang tidak ada di DOM (blok tersembunyi) sengaja dikirim dengan
       nilai default yang SAH agar backend tidak pernah menerima enum kosong
       — nilai enum kosong membuat ZM menolak seluruh simpan. */
    function readEncodingControls(root) {
        if (!root) return {};
        var out = {};
        var writer = root.querySelector('[data-encoding="videoWriter"]');
        out.videoWriter = writer ? writer.value : '1';

        var storage = root.querySelector('[data-encoding="storageId"]');
        if (storage && storage.value !== '') out.storageId = storage.value;

        var isEncode = String(out.videoWriter) === '1';
        var codec = root.querySelector('[data-encoding="outputCodec"]');
        var encoder = root.querySelector('[data-encoding="encoder"]');
        var params = root.querySelector('[data-encoding="encoderParameters"]');
        var container = root.querySelector('[data-encoding="outputContainer"]');

        out.outputCodec = (isEncode && codec && codec.value) ? codec.value : 'auto';
        out.encoder = (isEncode && encoder && encoder.value) ? encoder.value : 'auto';
        out.encoderParameters = (params && params.value.trim())
            ? params.value.trim() : ZM_ENCODER_PARAMETERS_DEFAULT;
        out.outputContainer = (container && container.value) ? container.value : 'mp4';
        return out;
    }

    /* Muat area penyimpanan ZoneMinder (endpoint dashboard, bukan ZM
       langsung, supaya kredensial tetap di server). Kegagalan tidak pernah
       memblokir pendaftaran: dropdown diisi Default/1 sebagai fallback. */
    function loadStorageAreas(select, preferred) {
        if (!select) return Promise.resolve([]);
        var fallback = [{ id: '1', name: 'Default' }];

        function apply(items) {
            var current = preferred !== undefined && preferred !== null && String(preferred) !== ''
                ? String(preferred) : select.value;
            select.innerHTML = '';
            items.forEach(function (s) {
                var opt = document.createElement('option');
                opt.value = String(s.id);
                opt.textContent = s.name + ' (ID ' + s.id + ')' + (s.path ? ' — ' + s.path : '');
                select.appendChild(opt);
            });
            if (!select.options.length) {
                var opt2 = document.createElement('option');
                opt2.value = '1';
                opt2.textContent = 'Default (ID 1)';
                select.appendChild(opt2);
            }
            select.value = current && select.querySelector('option[value="' + current + '"]')
                ? current : select.options[0].value;
            return items;
        }

        return fetch('/api/zm/storageareas')
            .then(function (r) { return r.json(); })
            .then(function (d) {
                var items = (d && Array.isArray(d.storages)) ? d.storages : [];
                return apply(items.length ? items : fallback);
            })
            .catch(function () { return apply(fallback); });
    }

    var NAV = [
        { href: '/',                 label: 'Portal',            icon: '&#127968;' },
        { href: '/zoneminder.html',  label: 'Kelola Kamera',     icon: '&#128737;&#65039;' },
        { href: '/add_camera.html',  label: 'Tambah Kamera',     icon: '&#10133;' },
        { href: '/burst.html',       label: 'Burst Add',         icon: '&#128640;' },
        { href: '/status.html',      label: 'Status Server',     icon: '&#128202;' },
        { href: '/checker.html',     label: 'Health Checker',    icon: '&#9878;&#65039;' },
        { href: '/settings',         label: 'Pengaturan',        icon: '&#9881;&#65039;' }
    ];

    var CSS = [
        '.dash-hdr {',
        '  background: #0f172a;',
        '  color: #f8fafc;',
        '  padding: 10px 24px;',
        '  display: flex;',
        '  align-items: center;',
        '  gap: 16px;',
        '  flex-wrap: wrap;',
        '  border-bottom: 1px solid #1e293b;',
        '  position: sticky;',
        '  top: 0;',
        '  z-index: 900;',
        '  font-family: var(--font-sans, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif);',
        '}',
        '.dash-hdr .brand {',
        '  font-size: 14.5px;',
        '  font-weight: 700;',
        '  display: flex;',
        '  align-items: center;',
        '  gap: 8px;',
        '  color: #ffffff;',
        '  letter-spacing: -0.01em;',
        '  text-decoration: none;',
        '}',
        '.dash-hdr nav {',
        '  display: flex;',
        '  gap: 4px;',
        '  flex-wrap: wrap;',
        '  align-items: center;',
        '}',
        '.dash-hdr nav a {',
        '  color: #94a3b8;',
        '  text-decoration: none;',
        '  font-size: 13px;',
        '  font-weight: 500;',
        '  padding: 6px 12px;',
        '  border-radius: 6px;',
        '  transition: all 0.15s ease;',
        '  display: inline-flex;',
        '  align-items: center;',
        '  gap: 6px;',
        '}',
        '.dash-hdr nav a:hover {',
        '  background: rgba(255, 255, 255, 0.08);',
        '  color: #f8fafc;',
        '}',
        '.dash-hdr nav a.active {',
        '  background: #2563eb;',
        '  color: #ffffff;',
        '  font-weight: 600;',
        '}',
        '.dash-hdr .spacer { margin-left: auto; }',
        '.dash-hdr .actions {',
        '  display: flex;',
        '  align-items: center;',
        '  gap: 10px;',
        '}',
        '.dash-hdr .zm-btn {',
        '  display: inline-flex;',
        '  align-items: center;',
        '  gap: 6px;',
        '  text-decoration: none;',
        '  font-size: 12.5px;',
        '  font-weight: 600;',
        '  padding: 6px 12px;',
        '  border-radius: 6px;',
        '  color: #065f46;',
        '  background: #10b981;',
        '  border: 1px solid #059669;',
        '  color: #ffffff;',
        '  transition: all 0.15s ease;',
        '}',
        '.dash-hdr .zm-btn:hover {',
        '  background: #059669;',
        '  box-shadow: 0 2px 8px rgba(16, 185, 129, 0.3);',
        '}',
        '.dash-hdr .logout-btn {',
        '  display: inline-flex;',
        '  align-items: center;',
        '  gap: 5px;',
        '  text-decoration: none;',
        '  font-size: 12.5px;',
        '  font-weight: 500;',
        '  padding: 5px 10px;',
        '  border-radius: 6px;',
        '  color: #cbd5e1;',
        '  background: rgba(255, 255, 255, 0.05);',
        '  border: 1px solid rgba(255, 255, 255, 0.12);',
        '  transition: all 0.15s ease;',
        '}',
        '.dash-hdr .logout-btn:hover {',
        '  background: rgba(239, 68, 68, 0.2);',
        '  border-color: rgba(239, 68, 68, 0.4);',
        '  color: #fca5a5;',
        '}',
        '@media (max-width: 860px) {',
        '  .dash-hdr { padding: 10px 14px; gap: 10px; }',
        '  .dash-hdr .brand span { display: none; }',
        '}'
    ].join('\n');

    function injectStyles() {
        if (document.getElementById('dashHdrStyles')) return;
        var style = document.createElement('style');
        style.id = 'dashHdrStyles';
        style.textContent = CSS;
        document.head.appendChild(style);
    }

    function currentPath() {
        var p = window.location.pathname;
        if (p === '/settings.html') return '/settings';
        if (p === '/status') return '/status.html';
        return p;
    }

    function buildHeader() {
        var here = currentPath();
        var html = '';

        html += '<a href="/" class="brand">&#128737;&#65039; <span>ZoneMinder CC</span></a>';
        html += '<nav>';
        NAV.forEach(function (item) {
            var active = (item.href === here)
                || (item.href === '/status.html' && here === '/status')
                || (item.href === '/checker.html' && here === '/checker');
            var cls = active ? ' class="active"' : '';
            html += '<a href="' + item.href + '"' + cls + '>' + item.icon + ' ' + item.label + '</a>';
        });
        html += '</nav>';
        html += '<div class="spacer"></div>';
        html += '<div class="actions">';
        html += '<a class="zm-btn" href="' + ZM_ROOT + '" target="_blank" rel="noopener" title="Buka web konsol ZoneMinder NVR bawaan">'
              + '&#128421;&#65039; Konsol ZoneMinder &rarr;</a>';
        html += '<a class="logout-btn" href="/logout" title="Keluar dari sesi dashboard">'
              + 'Logout</a>';
        html += '</div>';

        return html;
    }

    function mount() {
        injectStyles();

        var target = document.getElementById('dashHeader')
            || document.querySelector('header-bar')
            || document.querySelector('header');

        if (!target) return;

        var bar = document.createElement('div');
        bar.className = 'dash-hdr';
        bar.innerHTML = buildHeader();

        target.replaceWith(bar);
    }

    /* Utilitas Toast Global untuk Notifikasi Modern */
    window.showToast = function (message, type, title) {
        type = type || 'info'; // 'success', 'error', 'warning', 'info'
        var container = document.getElementById('globalToastContainer');
        if (!container) {
            container = document.createElement('div');
            container.id = 'globalToastContainer';
            container.className = 'toast-container';
            document.body.appendChild(container);
        }

        var toast = document.createElement('div');
        toast.className = 'toast toast-' + type;

        var iconMap = {
            success: '&#9989;',
            error: '&#10060;',
            warning: '&#9888;&#65039;',
            info: '&#8505;&#65039;'
        };

        var titleHtml = title ? '<div class="toast-title">' + title + '</div>' : '';
        toast.innerHTML = 
            '<div>' + (iconMap[type] || '&#8505;&#65039;') + '</div>' +
            '<div class="toast-content">' +
                titleHtml +
                '<div class="toast-msg">' + message + '</div>' +
            '</div>' +
            '<button class="toast-close" onclick="this.parentElement.remove()">&times;</button>';

        container.appendChild(toast);

        setTimeout(function () {
            if (toast.parentElement) {
                toast.style.opacity = '0';
                toast.style.transform = 'translateX(100%)';
                setTimeout(function () { if (toast.parentElement) toast.remove(); }, 200);
            }
        }, 4000);
    };

    /* Utilitas Decoder Global — satu daftar untuk semua halaman.
       Halaman memakai ini agar pilihan decoder identik di jalur satuan,
       burst, Excel, dan form edit. Nilai lama yang belum ada di daftar
       (mis. 'av1' dari konfigurasi ZoneMinder sebelumnya) tetap
       dipertahankan lewat setDecoderValue(). */
    window.ZM_DECODERS = ZM_DECODERS;
    window.decoderLabel = decoderLabel;
    window.setDecoderValue = setDecoderValue;
    window.fillDecoderOptions = fillDecoderOptions;

    /* Utilitas Encoding Video ZM 1.38.6 — satu daftar untuk semua halaman. */
    window.ZM_VIDEO_WRITERS = ZM_VIDEO_WRITERS;
    window.ZM_OUTPUT_CODECS = ZM_OUTPUT_CODECS;
    window.ZM_OUTPUT_CONTAINERS = ZM_OUTPUT_CONTAINERS;
    window.ZM_ENCODERS = ZM_ENCODERS;
    window.ZM_ENCODER_PARAMETERS_DEFAULT = ZM_ENCODER_PARAMETERS_DEFAULT;
    window.fillVideoWriterOptions = fillVideoWriterOptions;
    window.fillOutputCodecOptions = fillOutputCodecOptions;
    window.fillOutputContainerOptions = fillOutputContainerOptions;
    window.fillEncoderOptions = fillEncoderOptions;
    window.toggleEncodingBlock = toggleEncodingBlock;
    window.fillEncodingControls = fillEncodingControls;
    window.readEncodingControls = readEncodingControls;
    window.loadStorageAreas = loadStorageAreas;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', mount);
    } else {
        mount();
    }
})();
