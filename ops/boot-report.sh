#!/usr/bin/env bash
#
# Runs once per boot. Decides whether the PREVIOUS boot ended cleanly and, if it
# did not, assembles everything that is known about how it ended into one file.
#
# The 2026-08-31 and 2026-09-01 lock-ups were only noticed because someone
# happened to look: `last -x reboot` showed three boots and no shutdown records
# for two of them, and `journalctl -b -1` ended mid-sentence. This makes that
# determination automatically, every boot, and leaves it where a human will see
# it -- there is no MTA on this host, so anything mailed goes nowhere.
#
# Environment-agnostic: it reports on the machine, not on prod or dev, so it
# deliberately does NOT call assert_env_consistent(). That guard is for
# destructive per-environment work.
set -uo pipefail
. "$(dirname "$(readlink -f "$0")")/lib.sh"

REPORT_DIR=/var/log/rate-site/boot-reports
STATUS=/var/log/rate-site/STATUS
MEMWATCH=/var/log/rate-site/memwatch.log
mkdir -p "$REPORT_DIR"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$REPORT_DIR/$STAMP.txt"

# A clean shutdown always logs a shutdown/reboot/poweroff target and
# systemd-shutdown. Neither appeared before 2026-08-31 11:20:43 or
# 2026-09-01 12:05:28 -- which is what makes those two hard terminations.
PREV_TAIL="$(journalctl -b -1 --no-pager -n 200 2>/dev/null || true)"
if [ -z "$PREV_TAIL" ]; then
    VERDICT="UNKNOWN (no previous boot in the journal)"
elif printf '%s' "$PREV_TAIL" | grep -qE \
        'Reached target.*(Shutdown|Power-Off|Reboot|Halt)|systemd-shutdown|Unmounting /'; then
    VERDICT="CLEAN"
else
    VERDICT="UNCLEAN -- previous boot ended without a shutdown sequence"
fi

PREV_LAST="$(printf '%s' "$PREV_TAIL" | tail -1 | cut -c1-15)"
# `journalctl -b -0 -n 1` returns the LATEST entry, not the first -- use the
# kernel's own boot time instead.
THIS_START="$(uptime -s 2>/dev/null || echo unknown)"

{
    echo "boot report $STAMP"
    echo "verdict:                 $VERDICT"
    echo "prev boot last log line: $PREV_LAST"
    echo "this boot started:       $THIS_START"
    echo "kernel:                  $(uname -r)"
    echo "pv spinlocks:            $(dmesg 2>/dev/null | grep -o 'PV spinlocks [a-z]*' | head -1 || echo '?')"
    echo "steal ticks (this boot): $(awk '/^cpu /{print $9}' /proc/stat)"
    echo "uptime:                  $(cut -d' ' -f1 /proc/uptime)s"
    echo "swap:                    $(awk '/^SwapTotal:/ {print int($2/1024)}' /proc/meminfo) MiB"
    echo
    echo "--- oom / earlyoom evidence in the previous boot ---"
    journalctl -b -1 --no-pager 2>/dev/null \
        | grep -iE 'out of memory|oom-kill|killed process|earlyoom' | tail -20 \
        || true
    journalctl -b -1 --no-pager 2>/dev/null \
        | grep -qiE 'out of memory|oom-kill|killed process|earlyoom' \
        || echo "(none. Rules OUT a classic OOM kill; does not distinguish a
 reclaim livelock from CPU starvation via lock-holder preemption -- for that,
 read steal_pct / psi_cpu / psi_mem_full in the memwatch samples below.)"
    echo
    echo "--- container state carried over from the previous boot ---"
    docker ps -a --format '{{.Names}}\t{{.Status}}' 2>/dev/null || echo "(docker not up yet)"
    echo
    echo "--- last 60 memwatch samples before this boot ---"
    if [ -f "$MEMWATCH" ]; then
        # Everything above the newest '# boot' marker belongs to the previous boot.
        awk '/^# boot /{n=NR} {a[NR]=$0} END{
                 if(!n){print "(no boot marker yet)"; exit}
                 if(n==1){print "(sampler was not running before this boot)"; exit}
                 s=(n>61)?n-60:1; for(i=s;i<n;i++) print a[i]}' "$MEMWATCH"
    else
        echo "(memwatch log not present -- installed after this crash?)"
    fi
    echo
    echo "--- last 40 journal lines of the previous boot ---"
    printf '%s\n' "$PREV_TAIL" | tail -40
} > "$OUT"

case "$VERDICT" in
    CLEAN*) write_status "OK clean boot, previous shutdown was clean" ;;
    *)      write_status "ALARM unclean previous shutdown -- see $OUT" ;;
esac

log "boot report: $VERDICT -> $OUT"
find "$REPORT_DIR" -type f -mtime +90 -delete 2>/dev/null || true
