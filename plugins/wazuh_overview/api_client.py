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
from requests.adapters import HTTPAdapter

from plugins.wazuh_overview.config import (
    API_BASE_URL,
    MAX_PARALLEL_FETCHES,
    REQUEST_TIMEOUT,
)
from utils.logger import logger


# Module-level Session so every _get() reuses TCP connections via Keep-Alive
# instead of opening a fresh socket per request. Pool sized for our actual
# peak fan-out: the eager preloader's per-device CVE fetch caps at
# MAX_PARALLEL_FETCHES=8 (plus a handful of sibling tasks), and the lazy
# events Phase 2 caps at another 8. 16 covers either path with headroom.
_SESSION = requests.Session()
_ADAPTER = HTTPAdapter(pool_connections=16, pool_maxsize=16)
_SESSION.mount("http://", _ADAPTER)
_SESSION.mount("https://", _ADAPTER)


def _get(path, params=None):
    """Shared GET. Returns (parsed_json, error_str)."""
    url = f"{API_BASE_URL}{path}"
    try:
        logger.info(f"[WAZUH-OVERVIEW] GET {url} params={params}")
        resp = _SESSION.get(url, params=params, timeout=REQUEST_TIMEOUT)
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


def fetch_agent(agent_id=None):
    """GET /api/v1/me/agent. Returns the basic_info dict (or None on error).

    The backend wraps the agent record under an "agent" key alongside
    caller_ip/user_id metadata. Some variants nest under "basic_info"; some
    return the fields flat. Unwrap whichever shape arrives so callers always
    receive the basic_info dict directly.

    Pass `agent_id` to look up a specific agent in the caller's group instead
    of the source-IP-resolved default. Server still enforces group membership.
    """
    params = {"agent_id": agent_id} if agent_id else None
    payload, err = _get("/api/v1/me/agent", params=params)
    if err:
        return None, err
    if not isinstance(payload, dict):
        return None, "bad shape"
    for key in ("agent", "basic_info"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            return nested, None
    return payload, None


def _normalize_cve(raw, detected_at=None):
    """Map a raw /me/vulnerabilities CVE record to the UI's expected shape.

    The live API uses Wazuh-Indexer-shaped fields (cve / cvss3_score / package
    / version / published / updated). The Vulnerabilities pane reads id /
    cvss_score / package_name / package_version / first_detected_at /
    published_date / modified_date / severity (lowercase) — so remap here
    once instead of touching every UI call site. Each fallback also accepts
    the UI-name so a future API change to those names keeps working without
    a client update.

    `detected_at` is the scan-time timestamp the per-device endpoint reports
    at the top level (it's no longer repeated on every CVE). Caller passes
    the page-level value so it lands on each CVE as `first_detected_at` —
    the timeline chart buckets on that key. It's scan-time, not true
    first-sighting; true first-sighting only lives in /events."""
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
        "published_date": raw.get("published"),
        "modified_date": raw.get("updated") or raw.get("modified_date"),
        "first_detected_at": raw.get("first_detected_at") or detected_at,
    }


def fetch_vulnerabilities_summary(severity=None, top=5):
    """GET /api/v1/me/vulnerabilities (group-level summary).

    Returns the raw response dict — kept un-normalized because consumers
    read the top-level `by_severity` map directly to drive the Overview
    Vulnerabilities card and the donut. Single indexer aggregation
    server-side; cheap (~370ms vs ~1.5s for the full per-device fan-out)
    so the Overview card can paint long before per-device data lands.

    `severity` filters the aggregation server-side (critical/high/medium/low).
    `top` sets the per-device preview size for `top_cves` (API default 5).

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
    params = {"top": top}
    if severity:
        params["severity"] = severity
    payload, err = _get("/api/v1/me/vulnerabilities", params=params)
    if err:
        return None, err
    if not isinstance(payload, dict):
        return None, "bad shape"
    return payload, None


def _device_vulnerabilities_page(agent_id, severity=None, limit=500, offset=0):
    """Single page of /me/vulnerabilities/{agent_id}. Returns
    (raw_items, detected_at, err).

    Unwraps the response envelope but does NOT normalize — pagination needs the
    raw list length to decide whether to fetch another page. `detected_at` is
    the top-level scan timestamp the API reports once per response (it's no
    longer per-CVE); we surface it so the caller can stamp every CVE with it."""
    params = {"limit": limit, "offset": offset}
    if severity:
        params["severity"] = severity
    payload, err = _get(f"/api/v1/me/vulnerabilities/{agent_id}", params=params)
    if err:
        return None, None, err
    if not isinstance(payload, dict):
        return None, None, "bad shape"
    items = payload.get("vulnerabilities")
    if not isinstance(items, list):
        items = payload.get("cves")
    if not isinstance(items, list):
        items = _affected_items(payload)
    return list(items or []), payload.get("detected_at"), None


def fetch_device_vulnerabilities(agent_id, severity=None, page_size=500, max_cves=5000):
    """GET /api/v1/me/vulnerabilities/{agent_id}. Returns the full per-device
    CVE list in the UI's normalized shape (see _normalize_cve).

    Paginates with limit=page_size + offset until the server returns a short
    page (last page) or the cumulative count hits max_cves (safety cap).
    Optional `severity` filter (critical/high/medium/low) is forwarded to the
    server.

    Top-level `detected_at` (scan time) is stamped onto every CVE as
    `first_detected_at` — that's what the timeline chart buckets on. It's
    scan-time, not true first-sighting; the true per-CVE first-sighting
    timestamps live in /me/vulnerabilities/{agent_id}/events. We keep the
    first non-null `detected_at` we see across pages, since the field is
    response-level and should match across pages of the same scan."""
    merged_raw = []
    detected_at = None
    offset = 0
    while True:
        page, page_detected_at, err = _device_vulnerabilities_page(
            agent_id, severity=severity, limit=page_size, offset=offset,
        )
        if err:
            return None, err
        if detected_at is None and page_detected_at:
            detected_at = page_detected_at
        if not page:
            break
        merged_raw.extend(page)
        if len(page) < page_size:
            break
        if len(merged_raw) >= max_cves:
            break
        offset += page_size
    return [_normalize_cve(c, detected_at=detected_at) for c in merged_raw], None


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


def fetch_device_vulnerability_events_page(
    agent_id, severity=None, limit=50, offset=0, hours=24,
):
    """Single page of GET /api/v1/me/vulnerabilities/{agent_id}/events.

    `hours` controls the server-side time window. Default matches the API's
    own default (24h); pass 0 to disable the cap and pull every event the
    API will return — that's what the timeline chart wants when it's drawing
    full history.

    Returns (events_list, err). Defensive envelope unwrap: the events live
    under "events" in the live API; OpenSearch-shaped `hits.hits` and the
    Wazuh `data.affected_items` envelope are kept as fallbacks for shape
    variants."""
    params = {"limit": limit, "offset": offset, "hours": hours}
    if severity:
        params["severity"] = severity
    payload, err = _get(
        f"/api/v1/me/vulnerabilities/{agent_id}/events",
        params=params,
    )
    if err:
        return None, err
    if not isinstance(payload, dict):
        return None, "bad shape"
    items = payload.get("events")
    if not isinstance(items, list):
        hits = payload.get("hits")
        if isinstance(hits, dict):
            inner = hits.get("hits")
            if isinstance(inner, list):
                items = inner
    if not isinstance(items, list):
        items = _affected_items(payload)
    return list(items or []), None


def fetch_device_vulnerability_events(
    agent_id, page_size=50, max_events=2000, hours=24,
):
    """All vulnerability detection events for ONE device, paginated.

    Calls the endpoint without a `severity` filter so a single pagination
    stream returns events of every severity (the API returns newest-first
    regardless). Previously this fanned out four severity-filtered streams
    in parallel, which cost 4× the request count and pushed concurrent
    requests past urllib3's pool_maxsize when combined with the per-device
    fan-out in main.py's _load_vuln_events_phase2_async.

    `hours` is the server-side time window. Defaults to 24 to match the API
    spec and the Events tab's fixed 24-hour timeline chart. Pass a larger
    value (or 0 for unlimited) for historical investigation that needs to
    look beyond the visible chart window.

    All-or-nothing per device: any page error fails the whole fetch. The
    outer fan-out (main.py) already tolerates per-device failures, so this
    is acceptable — and the previous per-severity partial-success contract
    rarely fired anyway, since all severities hit the same backend index."""
    out = []
    offset = 0
    while True:
        page, err = fetch_device_vulnerability_events_page(
            agent_id, limit=page_size, offset=offset, hours=hours,
        )
        if err:
            return None, err
        if not page:
            break
        out.extend(page)
        if len(page) < page_size:
            break
        if len(out) >= max_events:
            break
        offset += page_size
    return out, None


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
