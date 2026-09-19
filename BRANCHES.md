# Resitine Desktop Branches

Here is the analysis and summary of all branches in the repository relative to `develop` (ignoring `main` - the release Branch).

### Summary Overview

| Branch | Status vs `develop` | Commits Ahead / Behind | Functional Area |
| :--- | :--- | :--- | :--- |
| `feature/i18n-extractor` | **Merged** | 0 ahead / 16 behind | Localization / Tooling |
| `weblate` | **Merged** | 0 ahead / 1 behind | Localization / Polish translations |
| `feature/i18n-languages` | **Merged** | 18 ahead / 30 behind | Localization / Full multi-language support |
| `windows/qualityoflife` | **Unmerged** | 11 ahead / 17 behind | UI / Scaling & styling |
| `features/pluginsystem` | **Unmerged** | 12 ahead / 17 behind | Plugin system & UI |
| `plugins/backup` | **Unmerged** | 16 ahead / 17 behind | Backup plugin |
| `feature/wazuh` | **Unmerged** | 9 ahead / 30 behind | Wazuh overview & UI overhaul |
| `fix/antivirus-fda-detection` | **Unmerged** | 10 ahead / 30 behind | macOS Full Disk Access detection |
| `feat/wazuh-arch-uninstall` | **Partially merged** | 10 ahead (4 merged) / 144 behind | Linux polkit & Wazuh re-registration |
| `endpoint/pyqtdesigntest` | **Unmerged** | 2 ahead / 212 behind | Wazuh layout test (older) |
| `endpoint/pyqt-wazuh` | **Unmerged** | 5 ahead / 212 behind | Wazuh layout & loading states (older) |
| `endpoint/design_test2` | **Unmerged / Orphan** | 482 ahead / 843 behind | Historical UI resizing experiment |
| `chore/sparkle-key-rotation` | **Unmerged** | 2 ahead / 17 behind | Sparkle auto-update key rotation |
| `feat/windows-sparkle-key-rotation`| **Unmerged** | 2 ahead / 17 behind | Windows Sparkle key rotation |
| `fix/nixos` | **Unmerged** | 3 ahead / 17 behind | NixOS flake & ClamAV cert |
| `linux/ubuntu-release` | **Unmerged** | 2 ahead / 17 behind | Release bump & Linux verification key |
| `feat/customer-experience` | **Unmerged** | 3 new ahead (1 merged) / 128 behind | Setup wizard & Windows guides |

---

### Detailed Breakdown

#### 1. Branches Merged into `develop`

- **`origin/feature/i18n-extractor`**
  - **Status:** Fully merged into `develop` (commit `b26f034`).
  - **Contents:** Added the `scripts/extract_i18n.py` utility to parse source files and catalog translatable strings into JSON dictionaries.
- **`origin/weblate`**
  - **Status:** Fully merged into `develop` via PRs #96 and #97.
  - **Contents:** Continuous localization sync from Weblate for the Polish catalog (`pl.json`).

##### A. Localization
- **`origin/feature/i18n-languages`** *(18 ahead, 30 behind)*
  - **Contents:** Massive localization rollout (102 files, ~12.5k additions). Catalogs and translates 185+ UI elements (sidebar labels, badges, status cards, dialogs) into 12 locales, fixes layout/freezing bugs during rapid language switching, and localizes dashboard descriptions.


#### 2. Branches Not Merged into `develop`

##### B. UI, Scaling, and Plugin Ecosystem (Stacked Hierarchy)
These three branches form a chain: `windows/qualityoflife` $\rightarrow$ `features/pluginsystem` $\rightarrow$ `plugins/backup`:
- **`origin/windows/qualityoflife`** *(11 ahead, 17 behind)*
  - **Contents:** UI refinements across Windows/PyQt: dashboard tile scaling, store page header sizing, VPN/antivirus uniform spacing, seasonal flavor text, and rounded banner styling.
- **`origin/features/pluginsystem`** *(12 ahead, 17 behind)*
  - **Contents:** Contains all 11 commits from `windows/qualityoflife` plus commit `86e944f` which restores the plugin template and cleans up stale plugin files.
- **`origin/plugins/backup`** *(16 ahead, 17 behind)*
  - **Contents:** Contains all commits from `features/pluginsystem` plus 4 commits implementing the Resistine Backup plugin (`plugins/backup`), protected directory mtime handling on Windows, repository closing logic, and UI polish.

##### C. Wazuh & Antivirus
- **`origin/feature/wazuh`** *(9 ahead, 30 behind)*
  - **Contents:** Wazuh module improvements: uniform cross-tab device selection dropdown, interactive threat timeline with event counts by date, status widget bug fixes, loading screens, and consolidation of the standalone "Endpoint" tab directly into the Wazuh tabs.
- **`origin/fix/antivirus-fda-detection`** *(10 ahead, 30 behind)*
  - **Contents:** Branched directly off `feature/wazuh`. Adds commit `c3103ec` which fixes macOS Full Disk Access (FDA) detection by checking the `ResistineClamAV` helper rather than the main app bundle.
- **`origin/feat/wazuh-arch-uninstall`** *(10 unmerged commits ahead, 4 already merged into develop)*
  - **Contents:** 4 commits relating to Linux app uninstallation were merged to `develop` earlier. The remaining 10 commits add passwordless VPN toggling via a Polkit helper, a Wazuh agent-manager connection monitor, auto re-registration when disconnected, a manual "Re-register now" UI button, and `<enrollment>` XML block generation for Linux.
- **`origin/endpoint/pyqtdesigntest`** & **`origin/endpoint/pyqt-wazuh`** *(2 and 5 ahead, 212 behind)*
  - **Contents:** Older design prototypes for PyQt Wazuh layouts from mid-July 2026. `pyqt-wazuh` extends `pyqtdesigntest` with progress indicators and loading screens. Largely superseded by `feature/wazuh`.
- **`origin/endpoint/design_test2`** *(482 ahead, 843 behind)*
  - **Contents:** A legacy, diverged branch from June/July 2026 testing dynamic window resizing and layout stacking. It originates from before a historical git rewrite/filter and shares no commit merge base with current `develop`.

##### D. Platform & Packaging Fixes
- **`origin/chore/sparkle-key-rotation`** & **`origin/feat/windows-sparkle-key-rotation`** *(2 ahead, 17 behind each)*
  - **Contents:** Key rotation for Sparkle auto-updates.
    - `chore/sparkle-key-rotation` updates the key generation script, adds `.gitignore` for `AGENTS.md`, and documents key rotation in `dev-docs/`.
    - `feat/windows-sparkle-key-rotation` updates Windows update verification in `utils/updates/windows.py` and documents the bridge release procedure.
- **`origin/fix/nixos`** *(3 ahead, 17 behind)*
  - **Contents:** Replaces the old Tkinter Nix flake with a working PyQt6 flake (`flake.nix`), locates the CVD signing certificate path on Linux, and exports the ClamAV package.
- **`origin/linux/ubuntu-release`** *(2 ahead, 17 behind)*
  - **Contents:** Bumps the release version to `2026.08.12` and embeds a Linux-specific public verification key for auto-updates.
- **`origin/feat/customer-experience`** *(3 new ahead, 128 behind)*
  - **Contents:** Fixes setup wizard fonts and full-width layout, supports bundled WireGuard installation on Windows, adds dictionary VPN config support, and adds Windows install/reinstall documentation guides.