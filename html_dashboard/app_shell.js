/* ==========================================================================
 * app_shell.js - Header navigasi bersama untuk seluruh halaman dashboard.
 *
 * Tujuan:
 *   1. Satu markup header untuk semua halaman (tidak lagi disalin per file).
 *   2. Tautan ke ZoneMinder selalu DITONJOLKAN, karena ZM kini berada di
 *      alamat utama (https://<host>/) sedangkan dashboard ada di port 9443.
 *      Tautan disusun dari window.location.hostname sehingga tidak ada IP
 *      hardcoded yang perlu diubah saat server berpindah.
 *   3. Tombol Logout selalu tersedia di kanan header.
 *
 * Halaman yang memakainya cukup menaruh <header id="dashHeader"></header>
 * (atau <header-bar></header>) lalu memuat skrip ini.
 *
 * Catatan encoding: berkas ini sengaja ASCII murni (emoji memakai HTML entity
 * numerik, bukan karakter langsung) supaya tidak rusak saat diedit dari
 * Windows maupun WSL.
 * ========================================================================== */
(function () {
    'use strict';

    var ZM_ROOT = window.location.protocol + '//' + window.location.hostname + '/zm/';

    var NAV = [
        { href: '/',                 label: 'Portal',        icon: '&#127968;' },
        { href: '/zoneminder.html',  label: 'Kelola Kamera', icon: '&#128737;&#65039;' },
        { href: '/add_camera.html',  label: 'Tambah Kamera', icon: '&#10133;' },
        { href: '/burst.html',       label: 'Burst Add',     icon: '&#128640;' },
        { href: '/log_display.html', label: 'Log MQTT',      icon: '&#128225;' },
        { href: '/settings',         label: 'Pengaturan',    icon: '&#9881;&#65039;' }
    ];

    var CSS = [
        '.dash-hdr{background:linear-gradient(135deg,#0f172a,#1e293b);color:#fff;',
        'padding:12px 22px;display:flex;align-items:center;gap:14px;flex-wrap:wrap;',
        'box-shadow:0 4px 15px rgba(0,0,0,.18);flex-shrink:0;',
        'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;}',
        '.dash-hdr .brand{font-size:15px;font-weight:700;display:flex;align-items:center;gap:8px;white-space:nowrap;}',
        '.dash-hdr nav{display:flex;gap:4px;flex-wrap:wrap;align-items:center;}',
        '.dash-hdr nav a{color:#cbd5e1;text-decoration:none;font-size:12.5px;font-weight:600;',
        'padding:6px 10px;border-radius:7px;transition:.16s;white-space:nowrap;}',
        '.dash-hdr nav a:hover{background:rgba(255,255,255,.12);color:#fff;}',
        '.dash-hdr nav a.active{background:rgba(37,99,235,.9);color:#fff;}',
        '.dash-hdr .spacer{margin-left:auto;}',
        '.dash-hdr .zm-link{display:inline-flex;align-items:center;gap:7px;text-decoration:none;',
        'font-size:13px;font-weight:700;padding:8px 15px;border-radius:9px;color:#052e16;',
        'background:linear-gradient(135deg,#4ade80,#22c55e);',
        'box-shadow:0 3px 12px rgba(34,197,94,.42);border:1px solid #16a34a;',
        'animation:zmPulse 2.4s ease-in-out infinite;white-space:nowrap;}',
        '.dash-hdr .zm-link:hover{filter:brightness(1.08);}',
        '@keyframes zmPulse{0%,100%{box-shadow:0 3px 12px rgba(34,197,94,.42);}',
        '50%{box-shadow:0 3px 20px rgba(34,197,94,.85);}}',
        '.dash-hdr .logout{display:inline-flex;align-items:center;gap:6px;text-decoration:none;',
        'font-size:12.5px;font-weight:600;padding:7px 13px;border-radius:8px;color:#fecaca;',
        'background:rgba(220,38,38,.18);border:1px solid rgba(248,113,113,.42);white-space:nowrap;}',
        '.dash-hdr .logout:hover{background:rgba(220,38,38,.34);color:#fff;}',
        '@media(max-width:820px){.dash-hdr{padding:10px 14px;}.dash-hdr .brand{font-size:14px;}}'
    ].join('');

    function injectStyles() {
        if (document.getElementById('dashHdrStyles')) return;
        var style = document.createElement('style');
        style.id = 'dashHdrStyles';
        style.textContent = CSS;
        document.head.appendChild(style);
    }

    function currentPath() {
        var p = window.location.pathname;
        // /settings.html dan /settings sama-sama menandai menu Pengaturan.
        if (p === '/settings.html') return '/settings';
        return p;
    }

    function buildHeader() {
        var here = currentPath();
        var html = '';

        html += '<div class="brand">&#128737;&#65039; CCTV Dashboard</div>';
        html += '<nav>';
        NAV.forEach(function (item) {
            var cls = (item.href === here) ? ' class="active"' : '';
            html += '<a href="' + item.href + '"' + cls + '>' + item.icon + ' ' + item.label + '</a>';
        });
        html += '</nav>';
        html += '<div class="spacer"></div>';
        html += '<a class="zm-link" href="' + ZM_ROOT + '" target="_blank" rel="noopener" '
              + 'title="Buka antarmuka ZoneMinder di alamat utama">'
              + '&#128421;&#65039; Buka ZoneMinder</a>';
        html += '<a class="logout" href="/logout" title="Keluar dari dashboard">'
              + '&#9211; Logout</a>';

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

        // Header lama digantikan seluruhnya supaya tidak ada dua bar navigasi.
        target.replaceWith(bar);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', mount);
    } else {
        mount();
    }
})();
