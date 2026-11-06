#!/bin/sh
# Wrapper entrypoint image pppasantos/zoneminder untuk 100+ kamera (montage).
# Semua langkah best-effort: startup ZM tidak pernah digagalkan oleh tuning.

log() {
    echo "[cctv-tuning] $*" >&2
}

apply_zm_config() {
    [ -f /etc/cctv-tuning.conf ] || return 0
    command -v mysql >/dev/null 2>&1 || {
        log "klien mysql tidak ada, tuning ZM dilewati."
        return 0
    }
    # DB lokal dibuat & di-seed oleh entrypoint ZM; tunggu sampai siap.
    i=0
    while [ "$i" -lt 90 ]; do
        out=$(mysql -u root -e "SELECT Id FROM zm.Config LIMIT 1" 2>&1) && break
        case "$out" in
            *"doesn't exist"*|*"Unknown database"*|*"denied"*)
                log "tuning ZM dilewati: $out"
                return 0
                ;;
        esac
        i=$((i + 1))
        sleep 2
    done
    [ "$i" -lt 90 ] || {
        log "MySQL belum siap, tuning ZM dilewati."
        return 0
    }

    log "menerapkan Config ZoneMinder dari cctv-tuning.conf"
    while IFS= read -r line; do
        k=${line%%=*}
        v=${line#*=}
        if sql="$(mysql -u root -e "UPDATE zm.Config SET Value = '$v' WHERE Name = '$k';" 2>&1)"; then
            log "ok $k=$v"
        else
            log "gagal set $k: $sql"
        fi
    done < /etc/cctv-tuning.active.conf
}

prepare_conf() {
    grep -Ev '^[[:space:]]*(#|$)' /etc/cctv-tuning.conf > /etc/cctv-tuning.active.conf 2>/dev/null ||
        : > /etc/cctv-tuning.active.conf
}

# Tunggu Apache benar-benar jalan (maks 90 detik), lalu terapkan tuning.
(
    i=0
    while [ "$i" -lt 90 ]; do
        pgrep -f apache2 >/dev/null 2>&1 && break
        i=$((i + 1))
        sleep 1
    done
    sleep 5
    prepare_conf
    apply_zm_config
    log "tuning selesai"
) >/dev/null 2>&1 &

exec /usr/local/bin/entrypoint.sh "$@"
