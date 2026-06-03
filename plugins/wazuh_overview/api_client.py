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
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from plugins.wazuh_overview.config import (
    API_BASE_URL,
    MAX_PARALLEL_FETCHES,
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


def _normalize_cve(raw):
    """Map a raw /me/vulnerabilities CVE record to the UI's expected shape.

    The live API uses Wazuh-Indexer-shaped fields (cve / cvss3_score / package
    / version / published / updated / first_detected_at). The Vulnerabilities
    pane reads id / cvss_score / package_name / package_version /
    first_detected_at / published_date / modified_date / severity (lowercase)
    — so remap here once instead of touching every UI call site. Each fallback
    also accepts the UI-name so a future API change to those names keeps
    working without a client update."""
    if not isinstance(raw, dict):
        return {}
    score = raw.get("cvss3_score")
    if score is None:
        score = raw.get("cvss2_score")
    if score is None:
        score = raw.get("cvss_score")
    return {
        "id": raw.get("cve") or raw.get("id") or "",
        "severity": (raw.get("severity") or "").lower(),
        "cvss_score": score,
        "epss": raw.get("epss"),
        "package_name": raw.get("package") or raw.get("package_name") or "",
        "package_version": raw.get("version") or raw.get("package_version") or "",
        "description": raw.get("description") or "",
        "status": raw.get("status"),
        # first_detected_at is the immutable first sighting of this CVE on
        # this device (sourced from the alerts index when the per-device
        # endpoint is called with with_first_seen=true). When the alerts
        # index has no record (server returns null — empirically the common
        # case today), fall back to detected_at (last full scan) so the
        # timeline chart + detail panel still render meaningful dates. Once
        # the server backfills the alerts index, the field naturally
        # becomes true first-sighting without a code change.
        "first_detected_at": raw.get("first_detected_at") or raw.get("detected_at"),
        "published_date": raw.get("published"),
        "modified_date": raw.get("updated") or raw.get("modified_date"),
    }


def fetch_vulnerabilities(agent_id=None):
    """GET /api/v1/me/vulnerabilities. Returns the list of CVE dicts in the
    UI's normalized shape (see _normalize_cve). When `agent_id` is provided
    the server returns only that device's CVEs; without it, the API falls
    back to the calling machine's own agent."""
    params = {"limit": VULN_FETCH_LIMIT, "offset": 0}
    if agent_id:
        params["agent_id"] = agent_id
    payload, err = _get("/api/v1/me/vulnerabilities", params=params)
    if err:
        return None, err
    if isinstance(payload, dict):
        # Live API key is "vulnerabilities"; "cves" and the Wazuh-wrapped
        # affected_items envelope are kept as fallbacks for older shapes.
        items = payload.get("vulnerabilities")
        if not isinstance(items, list):
            items = payload.get("cves")
        if not isinstance(items, list):
            items = _affected_items(payload)
        return [_normalize_cve(c) for c in (items or [])], None
    return None, "bad shape"


def fetch_vulnerabilities_summary():
    """GET /api/v1/me/vulnerabilities (group-level summary).

    Returns the raw response dict — kept un-normalized because consumers
    read the top-level `by_severity` map directly to drive the Overview
    Vulnerabilities card and the donut. Single indexer aggregation
    server-side; cheap (~370ms vs ~1.5s for the full per-device fan-out)
    so the Overview card can paint long before per-device data lands.

    Caveats baked into the response:
      - per-device `top_cves` is capped at 50 even when `top` is larger,
        so this isn't a drop-in replacement for `fetch_all_vulnerabilities`
        when callers need the full row set (e.g. the table).
      - `first_detected_at` is NOT in the summary payload — the timeline
        chart still requires per-device fetches.

    Response shape (relevant keys):
      total_devices: int
      total_vulnerabilities: int
      by_severity: {critical, high, medium, low: int}
      devices: [{agent_id, total, by_severity, top_cves: [...]}]"""
    payload, err = _get("/api/v1/me/vulnerabilities", params={"top": 5})
    if err:
        return None, err
    if not isinstance(payload, dict):
        return None, "bad shape"
    return payload, None


def fetch_device_vulnerabilities(agent_id, with_first_seen=True):
    """GET /api/v1/me/vulnerabilities/{agent_id}. Returns the full per-device
    CVE list in the UI's normalized shape (see _normalize_cve).

    `with_first_seen=True` (default) asks the server to enrich each CVE with
    `first_detected_at` from the alerts index — the immutable first sighting
    on this device, used by both the detail panel and the timeline chart.
    Costs one extra indexer query per device per the API spec; cheap enough
    relative to the per-device fetch baseline."""
    params = {"with_first_seen": "true"} if with_first_seen else None
    payload, err = _get(f"/api/v1/me/vulnerabilities/{agent_id}", params=params)
    if err:
        return None, err
    if isinstance(payload, dict):
        items = payload.get("vulnerabilities")
        if not isinstance(items, list):
            items = payload.get("cves")
        if not isinstance(items, list):
            items = _affected_items(payload)
        return [_normalize_cve(c) for c in (items or [])], None
    return None, "bad shape"


def fetch_all_vulnerabilities(devices=None):
    """Fetch CVEs across every device on the caller's account by calling
    `fetch_device_vulnerabilities(agent_id)` per device IN PARALLEL and
    stamping each returned CVE with its origin `agent_id` + `agent_name`.

    Pass `devices` to skip the internal `fetch_inventory_full()` call when
    the caller already has the device list cached (the preloader does — see
    main.py:_load_overview_early_async). When omitted, the device list is
    fetched here for self-contained use.

    Per-device fan-out runs through a ThreadPoolExecutor capped at
    `MAX_PARALLEL_FETCHES` (see config.py) so wall-clock = max(per-device
    time) instead of sum. The cap is well under urllib3's default
    pool_maxsize and past the efficiency knee on this API.

    Partial-success contract: returns (merged_list, None) when at least one
    per-device fetch succeeded; returns (None, "all device fetches failed")
    only when every device errored."""
    if devices is None:
        devices, err = fetch_inventory_full()
        if err:
            return None, err

    by_id = {
        d.get("agent_id"): d
        for d in (devices or [])
        if d.get("agent_id")
    }
    if not by_id:
        return [], None

    workers = min(len(by_id), MAX_PARALLEL_FETCHES)
    merged = []
    failures = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        future_to_aid = {
            ex.submit(fetch_device_vulnerabilities, aid): aid
            for aid in by_id
        }
        for future in as_completed(future_to_aid):
            aid = future_to_aid[future]
            cves, derr = future.result()
            if derr:
                failures += 1
                logger.warning(f"Vulnerabilities: fetch for agent {aid} failed: {derr}")
                continue
            name = by_id[aid].get("agent_name") or ""
            for c in cves or []:
                c["agent_id"] = aid
                c["agent_name"] = name
            merged.extend(cves or [])

    if failures == len(by_id):
        return None, "all device fetches failed"
    return merged, None


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
