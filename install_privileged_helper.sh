#!/bin/bash
set -euo pipefail

# Installs and boots the privileged helper daemon: com.resistine.helper
# - Copies plist and helper from the app bundle to system locations
# - Fixes the Program path inside the installed plist
# - Sets required ownership/permissions
# - Bootstraps and enables the LaunchDaemon

# Author: Jackie and the Resistine Team
# Copyright: Resistine (c) 2024
# Licensed under the GNU General Public License v2 or later

# TODO: remove this, Jackie daslasldkjasdkljasdkasjdlkas
APP_DEFAULT="/Users/dhahabwhbbjshehaha/Desktop/Resistine/Rm/untitled folder/Resistine-Desktop/dist/Resistine.app"

APP_PATH="${1:-$APP_DEFAULT}"

PLIST_SRC="$APP_PATH/Contents/Resources/Library/LaunchDaemons/com.resistine.plist"
HELPER_SRC="$APP_PATH/Contents/Frameworks/Library/LaunchServices/ResistineHelper"

PLIST_DST="/Library/LaunchDaemons/com.resistine.helper.plist"
HELPER_DST="/Library/PrivilegedHelperTools/com.resistine.helper"

err() { echo "[error] $*" >&2; exit 1; }
log() { echo "[info] $*"; }

if [[ $EUID -ne 0 ]]; then
  err "Run as root: sudo $0 [path_to_Resistine.app]"
fi

if [[ ! -d "$APP_PATH" ]]; then
  err "App not found: $APP_PATH"
fi

if [[ ! -f "$PLIST_SRC" ]]; then
  err "Plist not found in app: $PLIST_SRC"
fi

if [[ ! -x "$HELPER_SRC" ]]; then
  err "Helper binary not found or not executable: $HELPER_SRC"
fi

log "Copying plist to $PLIST_DST"
cp "$PLIST_SRC" "$PLIST_DST"

log "Copying helper to $HELPER_DST"
cp "$HELPER_SRC" "$HELPER_DST"

log "Setting ownership and permissions"
chown root:wheel "$PLIST_DST" "$HELPER_DST"
chmod 644 "$PLIST_DST"
chmod 755 "$HELPER_DST"

log "Updating Program path inside plist to $HELPER_DST"
/usr/libexec/PlistBuddy -c "Set :Program $HELPER_DST" "$PLIST_DST" || err "Failed to update Program path"

log "(Re)loading launchd service com.resistine.helper"
launchctl bootout system/com.resistine.helper 2>/dev/null || true
launchctl bootstrap system "$PLIST_DST"
launchctl enable system/com.resistine.helper
launchctl kickstart -k system/com.resistine.helper

log "Verifying service"
launchctl print system/com.resistine.helper | sed -n '1,80p' | cat

echo "\nDone. If you see signature/approval errors, open System Settings → Privacy & Security → Login Items and enable the helper, or re-sign the app and helper with the same Team ID."


