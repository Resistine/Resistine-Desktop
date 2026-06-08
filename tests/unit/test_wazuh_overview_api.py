"""
Unit tests for plugins.wazuh_overview.api_client.

Covers each fetch_* function:
- Happy-path JSON parsing across flat and Wazuh-wrapped response shapes
- HTTP error responses (4xx/5xx)
- Network timeout and request-exception paths
- JSON decode failure
- Empty / missing keys
"""
import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from plugins.wazuh_overview import api_client


def _mock_response(ok=True, status_code=200, body=None, raise_json=False):
    resp = MagicMock()
    resp.ok = ok
    resp.status_code = status_code
    if raise_json:
        resp.json.side_effect = json.JSONDecodeError("bad", "", 0)
        resp.text = body or ""
    else:
        resp.json.return_value = body if body is not None else {}
        resp.text = json.dumps(body or {})
    return resp


# ===========================================================================
# fetch_agent
# ===========================================================================
class TestFetchAgent:
    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_flat_response_returns_dict(self, mock_get):
        mock_get.return_value = _mock_response(body={"name": "host-1", "status": "connected"})
        data, err = api_client.fetch_agent()
        assert err is None
        assert data == {"name": "host-1", "status": "connected"}

    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_basic_info_wrapped_response_unwraps(self, mock_get):
        mock_get.return_value = _mock_response(body={"basic_info": {"name": "host-2"}})
        data, err = api_client.fetch_agent()
        assert err is None
        assert data == {"name": "host-2"}

    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_http_error_returns_error(self, mock_get):
        mock_get.return_value = _mock_response(ok=False, status_code=503)
        data, err = api_client.fetch_agent()
        assert data is None
        assert "503" in err

    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_timeout_returns_timeout_error(self, mock_get):
        mock_get.side_effect = requests.exceptions.Timeout()
        data, err = api_client.fetch_agent()
        assert data is None
        assert err == "timeout"

    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_network_exception_returns_network_error(self, mock_get):
        mock_get.side_effect = requests.exceptions.ConnectionError("refused")
        data, err = api_client.fetch_agent()
        assert data is None
        assert err.startswith("network:")

    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_bad_json_returns_error(self, mock_get):
        mock_get.return_value = _mock_response(body="<html/>", raise_json=True)
        data, err = api_client.fetch_agent()
        assert data is None
        assert err == "bad json"

    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_non_dict_response_returns_shape_error(self, mock_get):
        mock_get.return_value = _mock_response(body=["unexpected", "list"])
        data, err = api_client.fetch_agent()
        assert data is None
        assert err == "bad shape"


# ===========================================================================
# fetch_sca
# ===========================================================================
class TestFetchSca:
    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_affected_items_top_level(self, mock_get):
        mock_get.return_value = _mock_response(
            body={"affected_items": [{"name": "CIS_macOS", "score": 87}]}
        )
        data, err = api_client.fetch_sca()
        assert err is None
        assert data[0]["score"] == 87

    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_wazuh_wrapped_unwraps(self, mock_get):
        mock_get.return_value = _mock_response(
            body={"data": {"affected_items": [{"score": 72}]}}
        )
        data, err = api_client.fetch_sca()
        assert err is None
        assert data == [{"score": 72}]

    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_empty_response_returns_empty_list(self, mock_get):
        mock_get.return_value = _mock_response(body={})
        data, err = api_client.fetch_sca()
        assert err is None
        assert data == []

    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_bad_json(self, mock_get):
        mock_get.return_value = _mock_response(raise_json=True)
        data, err = api_client.fetch_sca()
        assert data is None
        assert err == "bad json"


# ===========================================================================
# fetch_inventory_summary
# ===========================================================================
class TestFetchInventorySummary:
    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_explicit_total_and_items(self, mock_get):
        mock_get.return_value = _mock_response(body={"total": 5, "items": [{"id": "1"}]})
        data, err = api_client.fetch_inventory_summary()
        assert err is None
        assert data == {"total": 5, "items": [{"id": "1"}]}

    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_wazuh_wrapped_uses_total_affected_items(self, mock_get):
        mock_get.return_value = _mock_response(
            body={"data": {"total_affected_items": 12, "affected_items": [{"id": "a"}]}}
        )
        data, err = api_client.fetch_inventory_summary()
        assert err is None
        assert data["total"] == 12
        assert len(data["items"]) == 1

    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_missing_total_falls_back_to_len_items(self, mock_get):
        mock_get.return_value = _mock_response(body={"items": [{}, {}, {}]})
        data, err = api_client.fetch_inventory_summary()
        assert err is None
        assert data["total"] == 3

    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_non_int_total_falls_back_to_len_items(self, mock_get):
        mock_get.return_value = _mock_response(body={"total": "huge", "items": [{}]})
        data, err = api_client.fetch_inventory_summary()
        assert err is None
        assert data["total"] == 1

    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_http_404(self, mock_get):
        mock_get.return_value = _mock_response(ok=False, status_code=404)
        data, err = api_client.fetch_inventory_summary()
        assert data is None
        assert "404" in err


# ===========================================================================
# fetch_hotfixes
# ===========================================================================
class TestFetchHotfixes:
    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_top_level_list(self, mock_get):
        mock_get.return_value = _mock_response(body=[{"hotfix": "KB1"}, {"hotfix": "KB2"}])
        data, err = api_client.fetch_hotfixes()
        assert err is None
        assert len(data) == 2

    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_hotfixes_key(self, mock_get):
        mock_get.return_value = _mock_response(body={"hotfixes": [{"hotfix": "KB5"}]})
        data, err = api_client.fetch_hotfixes()
        assert err is None
        assert data == [{"hotfix": "KB5"}]

    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_empty_list_non_windows_agent(self, mock_get):
        # Empty list is a valid successful response for non-Windows agents;
        # main.py distinguishes empty vs error via the err value being None.
        mock_get.return_value = _mock_response(body=[])
        data, err = api_client.fetch_hotfixes()
        assert err is None
        assert data == []

    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_wazuh_wrapped(self, mock_get):
        mock_get.return_value = _mock_response(
            body={"data": {"affected_items": [{"hotfix": "KB9"}]}}
        )
        data, err = api_client.fetch_hotfixes()
        assert err is None
        assert data == [{"hotfix": "KB9"}]

    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_network_error(self, mock_get):
        mock_get.side_effect = requests.exceptions.ConnectionError("refused")
        data, err = api_client.fetch_hotfixes()
        assert data is None
        assert err.startswith("network:")


# ===========================================================================
# fetch_device_vulnerability_events_page
# ===========================================================================
class TestFetchDeviceVulnerabilityEventsPage:
    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_events_key_returns_list(self, mock_get):
        mock_get.return_value = _mock_response(
            body={"events": [{"_id": "a"}, {"_id": "b"}]}
        )
        data, err = api_client.fetch_device_vulnerability_events_page("001")
        assert err is None
        assert len(data) == 2
        assert data[0]["_id"] == "a"

    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_opensearch_hits_hits_unwraps(self, mock_get):
        mock_get.return_value = _mock_response(
            body={"hits": {"hits": [{"_id": "x", "_source": {"timestamp": "t"}}]}}
        )
        data, err = api_client.fetch_device_vulnerability_events_page("001")
        assert err is None
        assert data == [{"_id": "x", "_source": {"timestamp": "t"}}]

    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_wazuh_wrapped_affected_items_unwraps(self, mock_get):
        mock_get.return_value = _mock_response(
            body={"data": {"affected_items": [{"_id": "z"}]}}
        )
        data, err = api_client.fetch_device_vulnerability_events_page("001")
        assert err is None
        assert data == [{"_id": "z"}]

    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_missing_key_returns_empty_list(self, mock_get):
        mock_get.return_value = _mock_response(body={})
        data, err = api_client.fetch_device_vulnerability_events_page("001")
        assert err is None
        assert data == []

    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_severity_limit_offset_propagated(self, mock_get):
        mock_get.return_value = _mock_response(body={"events": []})
        api_client.fetch_device_vulnerability_events_page(
            "001", severity="critical", limit=50, offset=100,
        )
        _, kwargs = mock_get.call_args
        assert kwargs["params"] == {"severity": "critical", "limit": 50, "offset": 100}

    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_no_severity_omits_param(self, mock_get):
        mock_get.return_value = _mock_response(body={"events": []})
        api_client.fetch_device_vulnerability_events_page("001", limit=50, offset=0)
        _, kwargs = mock_get.call_args
        assert "severity" not in kwargs["params"]

    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_http_500_returns_error(self, mock_get):
        mock_get.return_value = _mock_response(ok=False, status_code=500)
        data, err = api_client.fetch_device_vulnerability_events_page("001")
        assert data is None
        assert "500" in err

    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_timeout(self, mock_get):
        mock_get.side_effect = requests.exceptions.Timeout()
        data, err = api_client.fetch_device_vulnerability_events_page("001")
        assert data is None
        assert err == "timeout"

    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_non_dict_payload_returns_shape_error(self, mock_get):
        mock_get.return_value = _mock_response(body=["unexpected"])
        data, err = api_client.fetch_device_vulnerability_events_page("001")
        assert data is None
        assert err == "bad shape"


# ===========================================================================
# _paginate_events_for_severity
# ===========================================================================
class TestPaginateEventsForSeverity:
    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_stops_on_short_page(self, mock_get):
        # First page returns 50 (full); second returns 10 (short → stop).
        mock_get.side_effect = [
            _mock_response(body={"events": [{"_id": f"e{i}"} for i in range(50)]}),
            _mock_response(body={"events": [{"_id": f"e{i}"} for i in range(50, 60)]}),
        ]
        data, err = api_client._paginate_events_for_severity(
            "001", "high", page_size=50, max_events=2000,
        )
        assert err is None
        assert len(data) == 60
        assert mock_get.call_count == 2

    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_stops_on_empty_first_page(self, mock_get):
        mock_get.return_value = _mock_response(body={"events": []})
        data, err = api_client._paginate_events_for_severity(
            "001", "low", page_size=50, max_events=2000,
        )
        assert err is None
        assert data == []
        assert mock_get.call_count == 1

    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_stops_at_max_events_cap(self, mock_get):
        # Every page returns a full 50-row page. With max_events=100 the
        # loop should stop after collecting 100 rows.
        mock_get.return_value = _mock_response(
            body={"events": [{"_id": "x"} for _ in range(50)]}
        )
        data, err = api_client._paginate_events_for_severity(
            "001", "critical", page_size=50, max_events=100,
        )
        assert err is None
        assert len(data) == 100
        assert mock_get.call_count == 2

    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_propagates_page_error(self, mock_get):
        mock_get.return_value = _mock_response(ok=False, status_code=503)
        data, err = api_client._paginate_events_for_severity(
            "001", "medium", page_size=50, max_events=2000,
        )
        assert data is None
        assert "503" in err

    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_offset_increments_each_page(self, mock_get):
        mock_get.side_effect = [
            _mock_response(body={"events": [{"_id": f"a{i}"} for i in range(50)]}),
            _mock_response(body={"events": [{"_id": f"b{i}"} for i in range(50)]}),
            _mock_response(body={"events": []}),
        ]
        api_client._paginate_events_for_severity(
            "001", "high", page_size=50, max_events=2000,
        )
        offsets = [call.kwargs["params"]["offset"] for call in mock_get.call_args_list]
        assert offsets == [0, 50, 100]


# ===========================================================================
# fetch_device_vulnerability_events (parallel severity fan-out)
# ===========================================================================
class TestFetchDeviceVulnerabilityEvents:
    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_all_severities_succeed(self, mock_get):
        # Single short page per call → each severity makes exactly 1 request.
        mock_get.return_value = _mock_response(
            body={"events": [{"_id": "e"}]}
        )
        data, err = api_client.fetch_device_vulnerability_events(
            "001", page_size=50, max_per_severity=50,
        )
        assert err is None
        # 4 severities × 1 event each = 4 events merged.
        assert len(data) == 4
        assert mock_get.call_count == 4

    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_partial_failure_returns_merged_success(self, mock_get):
        # Three severities return a row; the fourth returns 500.
        # The merged list contains whatever did succeed; err stays None.
        def side_effect(*args, **kwargs):
            sev = kwargs.get("params", {}).get("severity")
            if sev == "critical":
                return _mock_response(ok=False, status_code=500)
            return _mock_response(body={"events": [{"_id": f"{sev}-1"}]})

        mock_get.side_effect = side_effect
        data, err = api_client.fetch_device_vulnerability_events(
            "001", page_size=50, max_per_severity=50,
        )
        assert err is None
        assert len(data) == 3
        assert all(e["_id"] != "critical-1" for e in data)

    @pytest.mark.unit
    @patch("plugins.wazuh_overview.api_client.requests.get")
    def test_all_severities_fail(self, mock_get):
        mock_get.return_value = _mock_response(ok=False, status_code=500)
        data, err = api_client.fetch_device_vulnerability_events(
            "001", page_size=50, max_per_severity=50,
        )
        assert data is None
        assert err == "all severities failed"
