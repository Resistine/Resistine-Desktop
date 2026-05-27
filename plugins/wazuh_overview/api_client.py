"""
Wazuh Overview API Client — thin sync wrapper around requests for the
IP-identified /api/v1/me/* endpoints. Identity is resolved server-side from
the caller's source IP, so these calls carry no auth headers.

Each fetch_* returns (data, error). On success error is None. On failure data
is None and error is a short string suitable for logging or for a "Couldn't
load" badge on the UI. The functions also normalize a few known response-shape
variants (flat vs basic_info-wrapped, cves vs data.affected_items) so callers
in main.py don't have to repeat the destructuring.

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import json

import requests

from plugins.wazuh_overview.config import (
    API_BASE_URL,
    REQUEST_TIMEOUT,
    VULN_FETCH_LIMIT,
)
from utils.logger import logger


def _get(path, params=None):
    """Shared GET. Returns (parsed_json, error_str)."""
    url = f"{API_BASE_URL}{path}"
    try:
        logger.info(f"[WAZUH-OVERVIEW] GET {url} params={params}")
        resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.Timeout:
        return None, "timeout"
    except requests.exceptions.RequestException as e:
        return None, f"network: {e}"

    if not resp.ok:
        return None, f"http {resp.status_code}"

    try:
        return resp.json(), None
    except json.JSONDecodeError:
        return None, "bad json"


def _affected_items(payload):
    """Pull an affected_items list from a Wazuh-style response wrapper, if present."""
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if isinstance(data, dict):
        items = data.get("affected_items")
        if isinstance(items, list):
            return items
    return None


def fetch_agent():
    """GET /api/v1/me/agent. Returns the basic_info dict (or None on error).

    The backend wraps the agent record under an "agent" key alongside
    caller_ip/user_id metadata. Some variants nest under "basic_info"; some
    return the fields flat. Unwrap whichever shape arrives so callers always
    receive the basic_info dict directly.
    """
    payload, err = _get("/api/v1/me/agent")
    if err:
        return None, err
    if not isinstance(payload, dict):
        return None, "bad shape"
    for key in ("agent", "basic_info"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            return nested, None
    return payload, None


def fetch_vulnerabilities():
    """GET /api/v1/me/vulnerabilities. Returns the list of CVE dicts."""
    payload, err = _get(
        "/api/v1/me/vulnerabilities",
        params={"limit": VULN_FETCH_LIMIT, "offset": 0},
    )
    if err:
        return None, err
    if isinstance(payload, dict):
        cves = payload.get("cves")
        if not isinstance(cves, list):
            cves = _affected_items(payload)
        return list(cves or []), None
    return None, "bad shape"


def fetch_sca():
    """GET /api/v1/me/sca. Returns the list of SCA policy items.

    Translates the API's `not_applicable` field to `invalid` so the
    Compliance · SCA card (which reads `invalid`) renders the right count.
    """
    payload, err = _get("/api/v1/me/sca")
    if err:
        return None, err
    if isinstance(payload, dict):
        # Live API returns "policies"; some Wazuh-wrapped variants use
        # "affected_items" or the {"data": {"affected_items": ...}} envelope.
        items = payload.get("policies")
        if not isinstance(items, list):
            items = payload.get("affected_items")
        if not isinstance(items, list):
            items = _affected_items(payload)
        items = list(items or [])
        for it in items:
            if isinstance(it, dict) and "invalid" not in it and "not_applicable" in it:
                it["invalid"] = it["not_applicable"]
        return items, None
    return None, "bad shape"


def fetch_inventory_summary():
    """GET /api/v1/me/inventory. Returns {"total": int, "items": list}."""
    payload, err = _get("/api/v1/me/inventory", params={"limit": 1, "offset": 0})
    if err:
        return None, err
    if not isinstance(payload, dict):
        return None, "bad shape"

    # Live API returns total_devices + devices; older shapes used total+items
    # or the Wazuh-wrapped data.{total_affected_items, affected_items}.
    total = payload.get("total_devices")
    if total is None:
        total = payload.get("total")
    items = payload.get("devices")
    if not isinstance(items, list):
        items = payload.get("items")
    if total is None or not isinstance(items, list):
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        if total is None:
            total = data.get("total_affected_items")
        if not isinstance(items, list):
            items = data.get("affected_items")

    if not isinstance(items, list):
        items = []
    if total is None:
        total = len(items)

    try:
        total = int(total)
    except (TypeError, ValueError):
        total = len(items)

    return {"total": total, "items": list(items)}, None


def fetch_inventory_full(page_size=200):
    """Paginate through /api/v1/me/inventory and return every device summary.

    The list endpoint caps results per response; walk pages until either
    has_more is False or the cumulative count meets the reported total.
    Capped at 5000 devices to avoid runaway loops if the server omits both
    signals."""
    all_devices = []
    offset = 0
    while True:
        payload, err = _get(
            "/api/v1/me/inventory",
            params={"limit": page_size, "offset": offset},
        )
        if err:
            return None, err
        if not isinstance(payload, dict):
            return None, "bad shape"

        devices = payload.get("devices")
        if not isinstance(devices, list):
            devices = payload.get("items")
        if not isinstance(devices, list):
            devices = _affected_items(payload) or []
        all_devices.extend(devices)

        if payload.get("has_more") is False:
            break
        if payload.get("has_more") is None:
            total = payload.get("total_devices") or payload.get("total")
            if total is None or len(all_devices) >= int(total or 0):
                break
        if len(all_devices) >= 5000:
            break
        offset += page_size

    return all_devices, None


def fetch_device_inventory(agent_id):
    """GET /api/v1/me/inventory/{agent_id}. Returns the full per-device record
    with os/hardware/packages/ports/processes/network."""
    payload, err = _get(f"/api/v1/me/inventory/{agent_id}")
    if err:
        return None, err
    if not isinstance(payload, dict):
        return None, "bad shape"
    return payload, None


def fetch_hotfixes():
    """GET /api/v1/me/hotfixes. Returns the list of hotfix dicts (empty on non-Windows)."""
    payload, err = _get("/api/v1/me/hotfixes")
    if err:
        return None, err
    if isinstance(payload, list):
        return list(payload), None
    if isinstance(payload, dict):
        items = payload.get("hotfixes")
        if not isinstance(items, list):
            items = _affected_items(payload)
        return list(items or []), None
    return None, "bad shape"
