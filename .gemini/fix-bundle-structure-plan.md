# Implementation Plan: Fix macOS Bundle Structure

## Problem Summary

The VPN network extension fails to load with error:
```
Did not find any extension in .../ResistineVPNXPC.xpc 
that implements a provider for com.apple.networkextension.packet-tunnel
```

**Root Cause**: Bundle structure violates Apple's placement requirements. XPC service is nested inside `wireguard-apple.app`, so macOS looks for the network extension relative to that bundle instead of the main `Resistine.app`.

## Apple Bundle Requirements (from documentation)

| Content Type | Required Location |
|-------------|-------------------|
| App Extensions (.appex) | `Contents/PlugIns/` |
| XPC Services (.xpc) | `Contents/XPCServices/` |
| Helper Tools / CLI | `Contents/MacOS/` or `Contents/Helpers/` |
| Frameworks | `Contents/Frameworks/` |

**Critical Rule**: *"Don't group your nested code... Although it might work in some situations, it might fail later in hard-to-debug ways."*

## Current vs Target Structure

### Current (Broken)
```
Resistine.app/
├── Contents/
│   ├── MacOS/Resistine                    ← Python UI
│   ├── PlugIns/
│   │   └── network-extension.appex        ← Correct, but orphaned
│   └── Resources/
│       └── wireguard-apple.app/           ← Nested bundle (wrong!)
│           └── Contents/
│               ├── MacOS/resistine-vpn-cli
│               └── XPCServices/
│                   └── ResistineVPNXPC.xpc  ← Looks here for extension!
```

### Target (Correct)
```
Resistine.app/
├── Contents/
│   ├── MacOS/
│   │   └── Resistine                      ← Python UI (unchanged)
│   ├── Helpers/
│   │   └── resistine-vpn-cli              ← CLI tool (moved)
│   ├── PlugIns/
│   │   └── network-extension.appex        ← Network Extension (unchanged)
│   ├── XPCServices/
│   │   └── ResistineVPNXPC.xpc            ← XPC Service (moved to main app)
│   ├── Frameworks/                         ← PyInstaller frameworks
│   └── Resources/                          ← Assets only (no nested apps)
```

## Implementation Tasks

### Task 1: Update build-distribution.sh
**File**: `/Users/dhahabwhbbjshehaha/Documents/Resistine/Resistine-Desktop/build-distribution.sh`

Changes needed:
1. Remove the nested `wireguard-apple.app` embedding
2. Copy components directly to correct locations:
   - `resistine-vpn-cli` → `Resistine.app/Contents/Helpers/`
   - `ResistineVPNXPC.xpc` → `Resistine.app/Contents/XPCServices/`
   - `network-extension.appex` → `Resistine.app/Contents/PlugIns/` (already working)
3. Update signing order (innermost first, outermost last)
4. Update verification checks

### Task 2: Update Python CLI Path Resolution
**File**: `/Users/dhahabwhbbjshehaha/Documents/Resistine/Resistine-Desktop/plugins/vpn/wireguard/vpn_functions_darwin.py`

Changes needed:
1. Update `_find_cli_path()` to look in new location:
   - Old: `Contents/Resources/wireguard-apple.app/Contents/MacOS/resistine-vpn-cli`
   - New: `Contents/Helpers/resistine-vpn-cli`

### Task 3: Update Documentation
**Files**: 
- `docs/mac-app-architecture.md`
- `docs/mac-vpn-architecture.md`

Changes needed:
1. Update bundle structure diagrams
2. Update file location references

### Task 4: Update build-installer.sh (consistency)
**File**: `/Users/dhahabwhbbjshehaha/Documents/Resistine/Resistine-Desktop/build-installer.sh`

Same changes as build-distribution.sh for consistency.

## Verification Steps

After implementation:
1. Run `./build-distribution.sh`
2. Verify bundle structure with `find /Applications/Resistine.app -type d \( -name "*.appex" -o -name "*.xpc" \)`
3. Test VPN connection
4. Check Console.app for any extension discovery errors
5. Verify notarization passes

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| CLI path change breaks Python | Update path in vpn_functions_darwin.py |
| XPC service can't find extension | Verify both are in same parent bundle |
| Code signing breaks | Sign innermost first, maintain signing order |
| Existing users have old version | Notarization ensures clean install |

## Estimated Changes

- `build-distribution.sh`: ~50 lines modified ✅
- `build-installer.sh`: ~50 lines modified ✅
- `vpn_functions_darwin.py`: ~5 lines modified ✅
- Documentation: diagram updates

---

## 📚 Adding Future Privileged Modules (Reference)

When adding new privileged components like network extensions, system extensions, or XPC services, place them in the correct Apple-standard directories:

### Bundle Structure Reference

```
Resistine.app/
├── Contents/
│   ├── MacOS/                                 ← Main executable only
│   │   └── Resistine                          ← Python app
│   │
│   ├── Helpers/                               ← CLI tools, helper binaries
│   │   └── resistine-vpn-cli                  ← VPN CLI
│   │   └── future-helper-tool                 ← Add new helpers here
│   │
│   ├── PlugIns/                               ← App Extensions (.appex)
│   │   └── network-extension.appex            ← VPN Network Extension
│   │   └── future-extension.appex             ← Add new extensions here
│   │
│   ├── XPCServices/                           ← XPC Services (.xpc)
│   │   └── ResistineVPNXPC.xpc                ← VPN XPC Service
│   │   └── FutureXPC.xpc                      ← Add new XPC services here
│   │
│   ├── Library/
│   │   ├── SystemExtensions/                  ← System Extensions (.systemextension)
│   │   │   └── com.resistine.firewall.sysext  ← Example: Firewall extension
│   │   │
│   │   └── LoginItems/                        ← Login Items (.bundle)
│   │       └── ResistineHelper.bundle         ← Example: Launch-at-login helper
│   │
│   ├── Frameworks/                            ← Frameworks and dynamic libraries
│   │   └── Python.framework                   ← PyInstaller Python framework
│   │
│   └── Resources/                             ← Assets only (NO nested bundles!)
│       ├── icon.icns
│       └── assets/
```

### Component Type → Directory Mapping

| Component Type | Directory | Example |
|---------------|-----------|---------|
| CLI / Helper Tool | `Contents/Helpers/` | `resistine-vpn-cli` |
| App Extension (.appex) | `Contents/PlugIns/` | Network Extension, Share Extension |
| XPC Service (.xpc) | `Contents/XPCServices/` | Background service |
| System Extension (.systemextension) | `Contents/Library/SystemExtensions/` | DNS Proxy, Content Filter |
| Login Item (.bundle) | `Contents/Library/LoginItems/` | Launch-at-login helper |
| Framework (.framework) | `Contents/Frameworks/` | Shared libraries |

### ⚠️ Critical Rules

1. **NEVER nest bundles inside `Contents/Resources/`** — macOS extension discovery will fail
2. **Sign innermost → outermost** — Sign binaries inside bundles before signing the bundle
3. **Preserve provisioning profiles** — Don't re-sign .appex/.xpc that have embedded profiles
4. **Match entitlements to profiles** — Entitlements must match what's in the provisioning profile

### Adding a New Extension Checklist

1. Create the extension target in Xcode with proper bundle ID
2. Set up provisioning profile in Apple Developer Portal
3. Add to build script:
   - Copy to correct `Contents/` subdirectory
   - Embed provisioning profile
   - Sign with correct entitlements
4. Update Python code if it needs to locate the new component
5. Register with `pluginkit -a` (extensions) or `systemextensionsctl` (system extensions)
