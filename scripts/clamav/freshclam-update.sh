#!/bin/bash
#
# freshclam-update.sh — Resistine ClamAV signature auto-updater (macOS)
#
# Run by the root LaunchDaemon com.resistine.desktop.freshclam via /bin/bash.
# Updates ClamAV signature databases on a rolling "since last check" cadence
# of 4h + random(0-60min), so signatures stay fresh even when the app is
# closed. launchd KeepAlive relaunches this script if it ever exits.
#
# This script is bundled (SIP-protected, code-signed) at
# Contents/Helpers/freshclam-update.sh and invoked by absolute path — it must
# NEVER call a bare `freshclam` (a Homebrew ClamAV may sit in PATH with a
# different binary and DB dir).
#
# Author: Resistine Team
# Copyright (c) Resistine 2025
# Licensed under the GNU General Public License v2 or later

set -u

FRESHCLAM="/Applications/Resistine.app/Contents/Helpers/freshclam"
CONF="/Library/Application Support/Resistine/clamav/freshclam.conf"

# Base interval between update cycles, in seconds (4 hours). Overridable via
# RESISTINE_FRESHCLAM_INTERVAL for testing only — production uses 14400.
BASE_INTERVAL="${RESISTINE_FRESHCLAM_INTERVAL:-14400}"

log() {
    # Timestamped line to stdout (captured by the daemon's StandardOutPath).
    printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1"
}

# Bail out gracefully (no hot-loop) until postinstall has set things up.
# Sleep ~1h then exit 0; KeepAlive relaunches us to retry.
if [ ! -x "$FRESHCLAM" ] || [ ! -f "$CONF" ]; then
    log "freshclam binary or conf missing — retrying in 1h ($FRESHCLAM / $CONF)"
    sleep 3600
    exit 0
fi

# Initial jitter (0-15min) so a fleet of machines booting/logging in together
# doesn't hammer the mirrors at the same instant.
sleep $((RANDOM % 900))

while true; do
    if "$FRESHCLAM" --config-file="$CONF"; then
        log "freshclam update OK"
    else
        # Never exit on failure — network/cert hiccups self-heal next cycle.
        log "freshclam update FAILED (will retry next cycle)"
    fi
    # Rolling cadence: base + 0-60min jitter, always >= base spacing.
    INTERVAL=$((BASE_INTERVAL + RANDOM % 3600))
    log "next freshclam update in ${INTERVAL}s"
    sleep "$INTERVAL"
done
