"""
Shared pytest fixtures for the Resistine Desktop test suite.

All fixtures here are available to every test file without importing.
Key design goals:
- Never touch the real ~/.config/resistine or ~/Library/Application Support/Resistine
- Never touch the real system keyring
- Never make real network requests unless the test is explicitly marked @pytest.mark.network
- Never call real subprocess commands unless explicitly mocked
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path so all project imports resolve.
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Stub out GUI-heavy dependencies before any project code is imported.
# Some modules import customtkinter at module load time; this prevents them
# from crashing on a headless CI server.
# ---------------------------------------------------------------------------
def _stub_gui_modules():
    """Insert lightweight stubs for GUI libraries not available in CI."""
    for mod_name in [
        # GUI toolkits
        "customtkinter",
        "tkinter",
        "tkinter.ttk",
        "PIL",
        "PIL.Image",
        "pystray",
        # OpenTelemetry — heavy dependency, not needed for tests
        "opentelemetry",
        "opentelemetry._logs",
        "opentelemetry.exporter",
        "opentelemetry.exporter.otlp",
        "opentelemetry.exporter.otlp.proto",
        "opentelemetry.exporter.otlp.proto.http",
        "opentelemetry.exporter.otlp.proto.http._log_exporter",
        "opentelemetry.sdk",
        "opentelemetry.sdk._logs",
        "opentelemetry.sdk._logs.export",
        "opentelemetry.sdk.resources",
        "opentelemetry.trace",
        # ServiceManagement (macOS only, not available in tests)
        "ServiceManagement",
    ]:
        if mod_name not in sys.modules:
            stub = MagicMock()
            sys.modules[mod_name] = stub

    # customtkinter.CTkImage must behave like a class
    ctk = sys.modules.get("customtkinter")
    if ctk:
        ctk.CTkImage = MagicMock(return_value=MagicMock())
        ctk.set_default_color_theme = MagicMock()
        ctk.set_appearance_mode = MagicMock()

    # opentelemetry stubs need realistic attributes
    otel_logs = sys.modules.get("opentelemetry._logs")
    if otel_logs:
        otel_logs.set_logger_provider = MagicMock()
        otel_logs.LogRecord = MagicMock()

    otel_trace = sys.modules.get("opentelemetry.trace")
    if otel_trace:
        mock_span = MagicMock()
        mock_span.get_span_context.return_value = MagicMock(is_valid=False)
        otel_trace.get_current_span = MagicMock(return_value=mock_span)


_stub_gui_modules()


# ---------------------------------------------------------------------------
# Isolated config directory — each test gets its own temp dir
# ---------------------------------------------------------------------------
@pytest.fixture()
def tmp_config_dir(tmp_path, monkeypatch):
    """Redirect all settings I/O to a private temp directory."""
    config_dir = tmp_path / "resistine_config"
    config_dir.mkdir()
    monkeypatch.setattr("utils.settings.get_config_dir", lambda: str(config_dir))
    return config_dir


# ---------------------------------------------------------------------------
# Mock keyring — never touch the real OS keyring during tests
# ---------------------------------------------------------------------------
@pytest.fixture()
def mock_keyring(monkeypatch):
    """In-memory keyring replacement.

    Provides get_password / set_password / delete_password backed by a dict.
    Monkeypatches the keyring module used by utils.settings and utils.encryption.
    """
    store: dict[tuple, str] = {}

    def _get(service, username):
        return store.get((service, username))

    def _set(service, username, password):
        store[(service, username)] = password

    def _delete(service, username):
        store.pop((service, username), None)

    mock_kr = MagicMock()
    mock_kr.get_password.side_effect = _get
    mock_kr.set_password.side_effect = _set
    mock_kr.delete_password.side_effect = _delete

    # Provide a mock backend class that looks "secure"
    mock_backend = MagicMock()
    mock_backend.__class__.__name__ = "SecureBackend"
    mock_backend.__class__.__module__ = "keyring.backends.macOS"
    mock_kr.get_keyring.return_value = mock_backend

    monkeypatch.setattr("utils.settings.keyring", mock_kr)
    monkeypatch.setattr("utils.encryption.keyring", mock_kr, raising=False)

    return mock_kr, store


# ---------------------------------------------------------------------------
# Convenience: settings with both tmp_config_dir + mock_keyring
# ---------------------------------------------------------------------------
@pytest.fixture()
def isolated_settings(tmp_config_dir, mock_keyring):
    """Return the settings module pre-configured for isolation."""
    import utils.settings as s
    return s


# ---------------------------------------------------------------------------
# Sample VPN config data
# ---------------------------------------------------------------------------
@pytest.fixture()
def sample_vpn_config_json():
    return {
        "Interface": {
            "PrivateKey": "",
            "Address": "10.49.65.6",
            "DNS": ["10.49.11.10"],
        },
        "Peer": {
            "PublicKey": "ABC123serverPubKey=",
            "AllowedIPs": ["10.49.0.0/17"],
            "Endpoint": "18.199.109.145:987",
        },
    }


@pytest.fixture()
def sample_wireguard_conf():
    return (
        "[Interface]\n"
        "PrivateKey = myPrivateKey=\n"
        "Address = 10.49.65.6\n"
        "DNS = 10.49.11.10\n"
        "\n"
        "[Peer]\n"
        "PublicKey = serverPubKey=\n"
        "AllowedIPs = 10.49.0.0/17\n"
        "Endpoint = 18.199.109.145:987\n"
    )


# ---------------------------------------------------------------------------
# Wireguard folder (temp)
# ---------------------------------------------------------------------------
@pytest.fixture()
def wireguard_dir(tmp_path):
    wg = tmp_path / "wireguard"
    wg.mkdir()
    return wg


# ---------------------------------------------------------------------------
# Helpers for writing .conf files
# ---------------------------------------------------------------------------
@pytest.fixture()
def write_conf(wireguard_dir, sample_wireguard_conf):
    def _write(name, content=None):
        path = wireguard_dir / f"{name}.conf"
        path.write_text(content or sample_wireguard_conf)
        return path
    return _write


# ---------------------------------------------------------------------------
# Mock requests factory
# ---------------------------------------------------------------------------
@pytest.fixture()
def mock_requests_post(monkeypatch):
    """Return a factory to configure mock POST responses."""
    import requests as req_mod

    call_log = []

    class _MockPost:
        def configure(self, status_code=200, json_body=None, text=None, raise_exc=None):
            mock_resp = MagicMock()
            mock_resp.status_code = status_code
            mock_resp.ok = (200 <= status_code < 300)
            mock_resp.text = text or (json.dumps(json_body) if json_body else "")
            if json_body is not None:
                mock_resp.json.return_value = json_body
            else:
                mock_resp.json.side_effect = ValueError("no content")

            if raise_exc:
                monkeypatch.setattr(req_mod, "post", MagicMock(side_effect=raise_exc))
            else:
                def _post(*args, **kwargs):
                    call_log.append({"args": args, "kwargs": kwargs})
                    return mock_resp
                monkeypatch.setattr(req_mod, "post", _post)
            return mock_resp

    mp = _MockPost()
    mp.call_log = call_log
    return mp
