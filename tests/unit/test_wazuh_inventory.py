"""
Unit tests for the Wazuh Overview Inventory pane's pure helpers.

Scope is deliberately the module-level functions and the class-level column
specs — no widgets are constructed, so no QApplication is needed. Fixture data
below mirrors real responses from /api/v1/me/inventory/{agent_id} for a Windows
and a macOS agent, including their quirks (pid as a string while ppid is an
int, whitespace-only placeholders, ram_* reported in KB despite the _mb name).

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

import pytest

from plugins.wazuh_overview.main import (
    Plugin,
    _as_int,
    _cell_text,
    _cpu_ram_text,
    _format_bytes,
    _format_ram,
    _interfaces_with_addresses,
    _join_host_port,
    _shape_inventory_agent,
    _top_value,
)


class TestFormatRam:
    """hardware.ram_total_mb is reported in KB despite its name."""

    @pytest.mark.unit
    def test_windows_32gb_machine(self):
        # Read as MB this would claim ~32 TB.
        assert _format_ram(33469492) == "31.9 GB"

    @pytest.mark.unit
    def test_macbook_16gb_machine(self):
        assert _format_ram(16777216) == "16.0 GB"

    @pytest.mark.unit
    @pytest.mark.parametrize("bad", [None, "", " ", 0, -1, "abc"])
    def test_missing_or_nonsense_reads_as_absent(self, bad):
        assert _format_ram(bad) == "—"


class TestFormatBytes:
    @pytest.mark.unit
    def test_zero_is_a_real_value_not_absent(self):
        # A down interface legitimately has zero traffic; that is not "unknown".
        assert _format_bytes(0) == "0 B"

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "value,expected",
        [(512, "512 B"), (1536, "1.5 KB"), (1048576, "1.0 MB"),
         (1610612736, "1.5 GB")],
    )
    def test_scales(self, value, expected):
        assert _format_bytes(value) == expected

    @pytest.mark.unit
    @pytest.mark.parametrize("bad", [None, "abc", -5])
    def test_unparseable(self, bad):
        assert _format_bytes(bad) == "—"


class TestJoinHostPort:
    @pytest.mark.unit
    def test_ipv4(self):
        assert _join_host_port("0.0.0.0", 445) == "0.0.0.0:445"

    @pytest.mark.unit
    def test_ipv6_is_bracketed(self):
        # The API reports the v6 wildcard as '::'; naive concatenation would
        # produce ':::135'.
        assert _join_host_port("::", 135) == "[::]:135"

    @pytest.mark.unit
    def test_missing_host_becomes_wildcard(self):
        assert _join_host_port("", 22) == "*:22"

    @pytest.mark.unit
    def test_fully_empty(self):
        assert _join_host_port("", None) == ""


class TestCellText:
    @pytest.mark.unit
    @pytest.mark.parametrize("blank", [None, "", "   "])
    def test_blank_and_whitespace_placeholders_collapse(self, blank):
        # macOS returns ' ' for package architecture and process state.
        assert _cell_text(blank) == "—"

    @pytest.mark.unit
    def test_zero_is_preserved(self):
        # A pid or port of 0 must not read as missing data.
        assert _cell_text(0) == "0"

    @pytest.mark.unit
    def test_strips(self):
        assert _cell_text("  svchost.exe ") == "svchost.exe"


class TestAsInt:
    @pytest.mark.unit
    def test_coerces_string_pids(self):
        # processes report pid as a string but ppid as an int.
        assert _as_int("1304") == 1304

    @pytest.mark.unit
    def test_unparseable_sorts_last(self):
        assert _as_int(None) > 10**12
        assert _as_int("nope") > 10**12


class TestInterfacesWithAddresses:
    @pytest.mark.unit
    def test_joins_addresses_onto_matching_interface(self):
        interfaces = [{"name": "Ethernet", "mac": "aa:bb"}, {"name": "Wi-Fi"}]
        addresses = [
            {"interface": "Ethernet", "address": "10.49.65.18", "proto": "ipv4"},
            {"interface": "Wi-Fi", "address": "10.0.0.9", "proto": "ipv4"},
        ]
        out = _interfaces_with_addresses(interfaces, addresses)
        assert out[0]["ip_addresses"] == ["10.49.65.18"]
        assert out[1]["ip_addresses"] == ["10.0.0.9"]

    @pytest.mark.unit
    def test_ipv4_sorts_ahead_of_ipv6(self):
        interfaces = [{"name": "en0"}]
        addresses = [
            {"interface": "en0", "address": "fe80::1", "proto": "ipv6"},
            {"interface": "en0", "address": "192.168.1.5", "proto": "ipv4"},
        ]
        out = _interfaces_with_addresses(interfaces, addresses)
        assert out[0]["ip_addresses"] == ["192.168.1.5", "fe80::1"]

    @pytest.mark.unit
    def test_interface_without_addresses_gets_empty_list(self):
        out = _interfaces_with_addresses([{"name": "lo"}], [])
        assert out[0]["ip_addresses"] == []

    @pytest.mark.unit
    def test_does_not_mutate_the_api_payload(self):
        # The caller's list() copy is shallow, so writing to the inner dicts
        # would edit the response objects in place.
        original = {"name": "en0"}
        _interfaces_with_addresses(
            [original], [{"interface": "en0", "address": "1.2.3.4", "proto": "ipv4"}]
        )
        assert "ip_addresses" not in original

    @pytest.mark.unit
    def test_tolerates_none_and_malformed_entries(self):
        out = _interfaces_with_addresses(
            [{"name": "en0"}, "not-a-dict", None],
            [{"no_interface_key": 1}, None, {"interface": "en0"}],
        )
        assert len(out) == 1
        assert out[0]["ip_addresses"] == []

    @pytest.mark.unit
    def test_both_sides_none(self):
        assert _interfaces_with_addresses(None, None) == []


class TestShapeInventoryAgent:
    SUMMARY = {
        "agent_id": "364",
        "agent_name": "Thomas-PC",
        "agent_ip": "10.49.65.18",
        "status": "active",
        "os": {"name": "Microsoft Windows 11 Home", "version": "10.0.26200.8875",
               "last_scan": "2026-08-05T13:57:39+00:00"},
        "hardware": {"cpu_name": "Intel(R) Core(TM) i7-9700K", "cpu_cores": 8,
                     "ram_total_mb": 33469492},
    }

    @pytest.mark.unit
    def test_network_addresses_reach_the_interfaces(self):
        detail = {
            "processes": [{"name": "lsass.exe"}],
            "ports": [{"local_port": 135}],
            "packages": [{"name": "3D Viewer"}],
            "network": {
                "interfaces": [{"name": "Ethernet"}],
                "addresses": [{"interface": "Ethernet", "address": "10.49.65.18",
                               "proto": "ipv4"}],
            },
        }
        agent = _shape_inventory_agent(self.SUMMARY, detail)
        ifaces = agent["syscollector"]["network"]["interfaces"]["affected_items"]
        assert ifaces[0]["ip_addresses"] == ["10.49.65.18"]

    @pytest.mark.unit
    def test_all_four_collections_are_carried(self):
        detail = {
            "processes": [{"name": "a"}, {"name": "b"}],
            "ports": [{"local_port": 1}],
            "packages": [{"name": "p"}],
            "network": {"interfaces": [{"name": "en0"}], "addresses": []},
        }
        sc = _shape_inventory_agent(self.SUMMARY, detail)["syscollector"]
        assert len(sc["processes"]["affected_items"]) == 2
        assert len(sc["network"]["ports"]["affected_items"]) == 1
        assert len(sc["packages"]["affected_items"]) == 1
        assert len(sc["network"]["interfaces"]["affected_items"]) == 1

    @pytest.mark.unit
    def test_failed_detail_fetch_yields_empty_syscollector(self):
        # Documented contract: such devices render 0 counts rather than raising.
        agent = _shape_inventory_agent(self.SUMMARY, None)
        assert agent["syscollector"] == {}
        assert agent["basic_info"]["name"] == "Thomas-PC"

    @pytest.mark.unit
    def test_os_and_hardware_are_preserved_for_the_devices_columns(self):
        agent = _shape_inventory_agent(self.SUMMARY, None)
        assert agent["basic_info"]["os"]["name"] == "Microsoft Windows 11 Home"
        assert agent["hardware"]["cpu_cores"] == 8

    @pytest.mark.unit
    def test_last_seen_falls_back_to_hardware_scan(self):
        summary = {"agent_id": "1", "agent_name": "x",
                   "os": {}, "hardware": {"last_scan": "2026-08-05T13:57:39+00:00"}}
        agent = _shape_inventory_agent(summary, None)
        assert agent["basic_info"]["lastKeepAlive"] == "2026-08-05T13:57:39+00:00"


class TestItemColumnSpecs:
    """Every non-Devices view must offer exactly the agreed 5 columns, and its
    getters must survive the null-heavy fields seen in the live payloads."""

    VIEWS = ("Processes", "Ports", "Network", "Packages")

    @pytest.mark.unit
    @pytest.mark.parametrize("view", VIEWS)
    def test_five_columns(self, view):
        assert len(Plugin._INVENTORY_ITEM_COLUMNS[view]) == 5

    @pytest.mark.unit
    @pytest.mark.parametrize("view", VIEWS)
    def test_each_view_is_a_tab_and_has_a_sort(self, view):
        assert view in Plugin._INVENTORY_COUNT_FIELDS
        assert view in Plugin._INVENTORY_LEAD_HEADER
        assert view in Plugin._INVENTORY_ITEM_SORTS

    @pytest.mark.unit
    @pytest.mark.parametrize("view", VIEWS)
    def test_exactly_one_stretch_column(self, view):
        widths = [w for _t, w, _g in Plugin._INVENTORY_ITEM_COLUMNS[view]]
        assert widths.count(0) == 1

    @pytest.mark.unit
    @pytest.mark.parametrize("view", VIEWS)
    def test_getters_tolerate_an_empty_item(self, view):
        # Guards against a getter assuming a key exists.
        for _title, _width, getter in Plugin._INVENTORY_ITEM_COLUMNS[view]:
            assert _cell_text(getter({})) == "—"

    @pytest.mark.unit
    def test_windows_process_row(self):
        item = {"pid": "1304", "ppid": 1100, "name": "lsass.exe", "user": None,
                "command": r"C:\Windows\System32\lsass.exe", "cpu_usage": None}
        rendered = [_cell_text(g(item))
                    for _t, _w, g in Plugin._INVENTORY_ITEM_COLUMNS["Processes"]]
        # USER is null on Windows; COMMAND carries the signal instead.
        assert rendered[0] == "lsass.exe"
        assert rendered[3] == "—"
        assert rendered[4] == r"C:\Windows\System32\lsass.exe"

    @pytest.mark.unit
    def test_macos_process_row(self):
        item = {"pid": "1499", "ppid": 1497, "name": "zsh", "state": " ",
                "user": "keithlangley", "command": "", "threads": 0}
        rendered = [_cell_text(g(item))
                    for _t, _w, g in Plugin._INVENTORY_ITEM_COLUMNS["Processes"]]
        # Mirror image of Windows: USER populated, COMMAND blank.
        assert rendered[3] == "keithlangley"
        assert rendered[4] == "—"

    @pytest.mark.unit
    def test_port_row_renders_ipv6_local_address(self):
        item = {"local_ip": "::", "local_port": 135, "protocol": "tcp6",
                "state": "listening", "process": "svchost.exe", "pid": 1560}
        rendered = [_cell_text(g(item))
                    for _t, _w, g in Plugin._INVENTORY_ITEM_COLUMNS["Ports"]]
        assert rendered[0] == "[::]:135"
        assert rendered[3] == "svchost.exe"

    @pytest.mark.unit
    def test_network_row_shows_addresses_and_traffic(self):
        item = {"name": "Wi-Fi", "state": "up", "mac": "a8:6d:aa:b7:4a:75",
                "ip_addresses": ["10.49.65.18"], "rx_bytes": 1536, "tx_bytes": 0}
        rendered = [_cell_text(g(item))
                    for _t, _w, g in Plugin._INVENTORY_ITEM_COLUMNS["Network"]]
        assert rendered[2] == "10.49.65.18"
        assert rendered[4] == "1.5 KB / 0 B"

    @pytest.mark.unit
    def test_macos_package_blank_architecture(self):
        item = {"name": "Accessibility Reader", "version": "1.0",
                "architecture": " ", "vendor": "Apple", "format": "pkg"}
        rendered = [_cell_text(g(item))
                    for _t, _w, g in Plugin._INVENTORY_ITEM_COLUMNS["Packages"]]
        assert rendered[0] == "Accessibility Reader"
        assert rendered[4] == "—"


class TestSummaryColumns:
    """The device row must summarise the SELECTED view's items, otherwise every
    view renders the same table and only the lead count changes."""

    VIEWS = ("Devices", "Processes", "Ports", "Network", "Packages")

    @pytest.mark.unit
    @pytest.mark.parametrize("view", VIEWS)
    def test_three_summary_columns_per_view(self, view):
        assert len(Plugin._INVENTORY_SUMMARY_COLUMNS[view]) == 3

    @pytest.mark.unit
    def test_each_view_has_a_distinct_header_set(self):
        headers = {
            view: tuple(t for t, _w, _g in cols)
            for view, cols in Plugin._INVENTORY_SUMMARY_COLUMNS.items()
        }
        # This is the regression guard for the reported bug.
        assert len(set(headers.values())) == len(headers)

    @pytest.mark.unit
    @pytest.mark.parametrize("view", VIEWS)
    def test_getters_survive_a_device_with_no_items(self, view):
        row = {"items": [], "status": "disconnected", "last_keep": None}
        for _title, _width, getter in Plugin._INVENTORY_SUMMARY_COLUMNS[view]:
            assert isinstance(_cell_text(getter(row)), str)

    @staticmethod
    def _render(view, row):
        return [_cell_text(g(row))
                for _t, _w, g in Plugin._INVENTORY_SUMMARY_COLUMNS[view]]

    @pytest.mark.unit
    def test_processes_summary(self):
        row = {"items": [
            {"name": "svchost.exe", "user": None},
            {"name": "svchost.exe", "user": None},
            {"name": "lsass.exe", "user": None},
        ]}
        unique, users, top = self._render("Processes", row)
        assert unique == "2"
        assert users == "—"          # Windows reports no owner; 0 would mislead
        assert top == "svchost.exe ×2"

    @pytest.mark.unit
    def test_ports_summary(self):
        row = {"items": [
            {"protocol": "tcp", "state": "listening", "local_port": 445},
            {"protocol": "tcp6", "state": "listening", "local_port": 135},
            {"protocol": "udp", "state": "listening", "local_port": 137},
        ]}
        proto, listening, top = self._render("Ports", row)
        assert proto == "2 / 1"
        assert listening == "3"
        assert top == "135, 137, 445"

    @pytest.mark.unit
    def test_ports_listening_is_absent_when_macos_omits_state(self):
        row = {"items": [{"protocol": "udp", "state": None, "local_port": 137}]}
        assert self._render("Ports", row)[1] == "—"

    @pytest.mark.unit
    def test_network_summary(self):
        row = {"items": [
            {"state": "up", "ip_addresses": ["10.0.0.16", "fe80::1"],
             "rx_bytes": 1024, "tx_bytes": 512},
            {"state": "down", "ip_addresses": [], "rx_bytes": 0, "tx_bytes": 0},
        ]}
        up_down, addresses, traffic = self._render("Network", row)
        assert up_down == "1 / 1"
        assert addresses == "2"
        assert traffic == "1.0 KB / 512 B"

    @pytest.mark.unit
    def test_packages_summary(self):
        row = {"items": [
            {"format": "win", "vendor": "Microsoft Corporation"},
            {"format": "win", "vendor": "Microsoft Corporation"},
            {"format": "pypi", "vendor": "PSF"},
        ]}
        formats, vendors, top = self._render("Packages", row)
        assert formats == "win 2 · pypi 1"
        assert vendors == "2"
        assert top == "Microsoft Corporation ×2"

    @pytest.mark.unit
    def test_devices_summary_keeps_machine_facts(self):
        row = {"os": "macOS 26.5.1", "cpu": "Apple M2 Pro", "cpu_cores": 12,
               "ram_total": 16777216, "status": "active", "last_keep": None}
        os_text, cpu_ram, last_seen = self._render("Devices", row)
        assert os_text == "macOS 26.5.1"
        assert cpu_ram == "Apple M2 Pro (12c) · 16.0 GB"
        assert last_seen == "Active now"

    @pytest.mark.unit
    def test_cpu_ram_drops_the_missing_half(self):
        assert _cpu_ram_text({"cpu": "", "ram_total": 16777216}) == "16.0 GB"
        assert _cpu_ram_text({"cpu": "Xeon", "ram_total": None}) == "Xeon"
        assert _cpu_ram_text({}) == "—"

    @pytest.mark.unit
    def test_top_value_breaks_ties_deterministically(self):
        items = [{"n": "b"}, {"n": "a"}]
        assert _top_value(items, "n") == "a"

    @pytest.mark.unit
    def test_top_value_omits_count_when_unique(self):
        assert _top_value([{"n": "only"}], "n") == "only"


class TestItemSorts:
    @pytest.mark.unit
    def test_processes_sort_by_name_case_insensitively(self):
        items = [{"name": "zsh"}, {"name": "Apple"}, {"name": "bash"}]
        items.sort(key=Plugin._INVENTORY_ITEM_SORTS["Processes"])
        assert [i["name"] for i in items] == ["Apple", "bash", "zsh"]

    @pytest.mark.unit
    def test_ports_sort_numerically_not_lexically(self):
        items = [{"local_port": 443}, {"local_port": 80}, {"local_port": 1024}]
        items.sort(key=Plugin._INVENTORY_ITEM_SORTS["Ports"])
        assert [i["local_port"] for i in items] == [80, 443, 1024]

    @pytest.mark.unit
    def test_network_puts_live_interfaces_first(self):
        items = [{"name": "en1", "state": "down"}, {"name": "en0", "state": "up"},
                 {"name": "anpi0", "state": "down"}]
        items.sort(key=Plugin._INVENTORY_ITEM_SORTS["Network"])
        assert [i["name"] for i in items] == ["en0", "anpi0", "en1"]

    @pytest.mark.unit
    @pytest.mark.parametrize("view", ["Processes", "Ports", "Network", "Packages"])
    def test_sorts_tolerate_missing_keys(self, view):
        items = [{}, {}]
        items.sort(key=Plugin._INVENTORY_ITEM_SORTS[view])  # must not raise
        assert len(items) == 2
