"""
Wazuh Overview Plugin — Centralized Configuration
Module-level constants for the IP-identified /api/v1/me/* API the Overview tab
consumes. Base URL is hardcoded here (not in settings.json) to keep the surface
small; flip to settings.get(...) when per-environment overrides are needed.
Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

# --- API Endpoint ---
API_BASE_URL = "http://dashboard.resisti.net:8899"

# --- Network ---
REQUEST_TIMEOUT = 10.0

# Per-host concurrency cap for per-device fan-out (vulnerabilities + inventory
# detail). Stays at/under urllib3's default pool_maxsize=10 so no Session
# tuning is needed. Empirically 8 is past the efficiency knee for this API
# without producing 5xx or queueing on the server.
MAX_PARALLEL_FETCHES = 8
