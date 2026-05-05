#!/bin/bash
# Wazuh Agent Post-Install Script for macOS
# Runs as root (via osascript with administrator privileges), detached from
# the Resistine UI process.  Survives app quit.
#
# Author: Resistine Team
# Copyright (c) Resistine 2025
# Licensed under the GNU General Public License v2 or later

set -euo pipefail

# --- Argument Parsing ---
PKG_PATH=""
AGENT_NAME=""
AGENT_GROUP=""
MANAGER=""
STATUS_FILE=""
LOG_FILE=""
RESTORE_KEYS="false"

while [ $# -gt 0 ]; do
    case "$1" in
        --pkg-path)
            PKG_PATH="$2"
            shift 2
            ;;
        --agent-name)
            AGENT_NAME="$2"
            shift 2
            ;;
        --agent-group)
            AGENT_GROUP="$2"
            shift 2
            ;;
        --manager)
            MANAGER="$2"
            shift 2
            ;;
        --status-file)
            STATUS_FILE="$2"
            shift 2
            ;;
        --log-file)
            LOG_FILE="$2"
            shift 2
            ;;
        --restore-keys)
            RESTORE_KEYS="true"
            shift
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

# --- Validation ---
if [ -z "$PKG_PATH" ] || [ -z "$AGENT_NAME" ] || [ -z "$AGENT_GROUP" ] \
    || [ -z "$MANAGER" ] || [ -z "$STATUS_FILE" ] || [ -z "$LOG_FILE" ]; then
    echo "Missing required arguments" >&2
    exit 1
fi

if ! [[ "$AGENT_NAME" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "Invalid agent name: $AGENT_NAME" >&2
    exit 1
fi

if ! [[ "$AGENT_GROUP" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "Invalid agent group: $AGENT_GROUP" >&2
    exit 1
fi

if [ ! -f "$PKG_PATH" ]; then
    echo "Package not found: $PKG_PATH" >&2
    exit 1
fi

# --- Helpers ---
write_status() {
    local tmp="${STATUS_FILE}.tmp"
    printf '%s' "$1" > "$tmp"
    mv "$tmp" "$STATUS_FILE"
}

CURRENT_STEP="init"

# --- Logging ---
exec 2>>"$LOG_FILE"
set -x

# --- Error Trap ---
trap 'write_status "{\"status\":\"failed\",\"step\":\"$CURRENT_STEP\",\"error\":\"unexpected error on line $LINENO\"}"' ERR

# --- Step 1: Install Package ---
CURRENT_STEP="install_pkg"
write_status '{"status":"running","step":"install_pkg","pid":'"$$"'}'
installer -pkg "$PKG_PATH" -target /

# --- Step 2: Patch ossec.conf ---
CURRENT_STEP="patch_config"
write_status '{"status":"running","step":"patch_config","pid":'"$$"'}'
OSSEC_CONF="/Library/Ossec/etc/ossec.conf"
sed -i '' "s|<agent_name>.*</agent_name>|<agent_name>${AGENT_NAME}</agent_name>|" "$OSSEC_CONF"

# --- Step 3: Key Restore or Enrollment ---
CURRENT_STEP="enrollment"
write_status '{"status":"running","step":"enrollment","pid":'"$$"'}'

CLIENT_KEYS="/Library/Ossec/etc/client.keys"
KEY_BACKUP="/Library/Application Support/Resistine/wazuh_client.keys"
KEYCHAIN="/Library/Keychains/System.keychain"
KC_SERVICE="com.resistine.wazuh.agent"
KC_ACCOUNT="client_key"
ENROLLMENT_RESULT="none"

if [ "$RESTORE_KEYS" = "true" ]; then
    # Try Keychain first (encrypted at rest)
    KC_VALUE=$(security find-generic-password -k "$KEYCHAIN" -s "$KC_SERVICE" -a "$KC_ACCOUNT" -w 2>/dev/null || true)
    if [ -n "$KC_VALUE" ]; then
        printf '%s' "$KC_VALUE" > "$CLIENT_KEYS"
        ENROLLMENT_RESULT="restored"
    elif [ -s "$KEY_BACKUP" ]; then
        cp "$KEY_BACKUP" "$CLIENT_KEYS"
        ENROLLMENT_RESULT="restored"
    fi

    if [ "$ENROLLMENT_RESULT" = "restored" ] && [ -s "$CLIENT_KEYS" ]; then
        chmod 640 "$CLIENT_KEYS"
        if dscl . -read /Groups/wazuh PrimaryGroupID &>/dev/null; then
            chown root:wazuh "$CLIENT_KEYS"
        else
            chown root:wheel "$CLIENT_KEYS"
        fi
    else
        ENROLLMENT_RESULT="none"
    fi
fi

if [ "$ENROLLMENT_RESULT" = "none" ]; then
    rm -f "$CLIENT_KEYS"
    if /Library/Ossec/bin/agent-auth -m "$MANAGER" -A "$AGENT_NAME" -G "$AGENT_GROUP"; then
        ENROLLMENT_RESULT="enrolled"
    else
        ENROLLMENT_RESULT="enroll_failed"
    fi
fi

# --- Step 4: Back Up Key ---
CURRENT_STEP="key_backup"
write_status '{"status":"running","step":"key_backup","pid":'"$$"'}'
if [ -s "$CLIENT_KEYS" ]; then
    mkdir -p "$(dirname "$KEY_BACKUP")"
    cp "$CLIENT_KEYS" "$KEY_BACKUP"
    security add-generic-password -U \
        -k "$KEYCHAIN" -s "$KC_SERVICE" -a "$KC_ACCOUNT" \
        -w "$(cat "$CLIENT_KEYS")" 2>/dev/null || true
fi

# --- Step 5: Bootstrap Launchd ---
CURRENT_STEP="launchd"
write_status '{"status":"running","step":"launchd","pid":'"$$"'}'
PLIST="/Library/LaunchDaemons/com.wazuh.agent.plist"
launchctl bootout system "$PLIST" 2>/dev/null || true
if ! launchctl bootstrap system "$PLIST"; then
    write_status "{\"status\":\"failed\",\"step\":\"launchd\",\"error\":\"launchctl bootstrap failed\"}"
    exit 1
fi

# --- Done ---
write_status "{\"status\":\"success\",\"step\":\"done\",\"enrollment\":\"${ENROLLMENT_RESULT}\"}"
