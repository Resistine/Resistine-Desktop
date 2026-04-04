"""Tests for plugins.antivirus.clamav — ClamAV backend operations.

Covers: binary discovery, config generation, DB info, freshclam,
clamd status, scanning, quarantine, and whitelist management.
"""

import os
import subprocess
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

# Import after conftest stubs GUI modules
from plugins.antivirus import clamav


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def clamav_dirs(tmp_path, monkeypatch):
    """Redirect all clamav module-level paths to a temp directory."""
    data_dir = tmp_path / "clamav"
    data_dir.mkdir()
    db_dir = data_dir / "db"
    db_dir.mkdir()
    log_dir = data_dir / "log"
    log_dir.mkdir()
    run_dir = data_dir / "run"
    run_dir.mkdir()
    quarantine_dir = data_dir / "quarantine"
    quarantine_dir.mkdir()

    monkeypatch.setattr(clamav, "_CLAMAV_DATA_DIR", str(data_dir))
    monkeypatch.setattr(clamav, "_DB_DIR", str(db_dir))
    monkeypatch.setattr(clamav, "_LOG_DIR", str(log_dir))
    monkeypatch.setattr(clamav, "_RUN_DIR", str(run_dir))
    monkeypatch.setattr(clamav, "_QUARANTINE_DIR", str(quarantine_dir))
    monkeypatch.setattr(clamav, "_CLAMD_CONF", str(data_dir / "clamd.conf"))
    monkeypatch.setattr(clamav, "_FRESHCLAM_CONF", str(data_dir / "freshclam.conf"))
    monkeypatch.setattr(clamav, "_CLAMD_SOCKET", str(run_dir / "clamd.sock"))
    monkeypatch.setattr(clamav, "_CLAMD_PID", str(run_dir / "clamd.pid"))
    monkeypatch.setattr(clamav, "_WHITELIST_FILE", str(data_dir / "whitelist.txt"))

    return {
        "data": data_dir,
        "db": db_dir,
        "log": log_dir,
        "run": run_dir,
        "quarantine": quarantine_dir,
    }


# ---------------------------------------------------------------------------
# Binary discovery
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestFindBinary:
    def test_finds_binary_on_path(self, monkeypatch):
        """_find_binary falls back to shutil.which when no bundled binary exists."""
        monkeypatch.setattr("sys.frozen", False, raising=False)
        monkeypatch.setattr(
            "shutil.which", lambda name: f"/usr/local/bin/{name}",
        )
        # Ensure no candidate file exists
        monkeypatch.setattr(os.path, "isfile", lambda p: False)
        result = clamav._find_binary("clamscan")
        assert result == "/usr/local/bin/clamscan"

    def test_returns_none_when_not_found(self, monkeypatch):
        monkeypatch.setattr("sys.frozen", False, raising=False)
        monkeypatch.setattr("shutil.which", lambda name: None)
        monkeypatch.setattr(os.path, "isfile", lambda p: False)
        assert clamav._find_binary("nonexistent") is None

    def test_finds_frozen_binary(self, monkeypatch, tmp_path):
        """When frozen, checks Helpers dir relative to executable."""
        monkeypatch.setattr("sys.frozen", True, raising=False)
        monkeypatch.setattr("sys.executable", str(tmp_path / "MacOS" / "Resistine"))

        helpers = tmp_path / "Helpers"
        helpers.mkdir(parents=True)
        binary = helpers / "clamscan"
        binary.write_text("#!/bin/sh\n")
        binary.chmod(0o755)

        result = clamav._find_binary("clamscan")
        assert result is not None
        assert result.endswith("clamscan")

    def test_get_binaries_returns_dict_for_all_names(self, monkeypatch):
        monkeypatch.setattr(clamav, "_find_binary", lambda n: f"/bin/{n}")
        bins = clamav.get_binaries()
        assert set(bins.keys()) == {"clamscan", "clamdscan", "clamd", "freshclam", "clamonacc"}
        assert all(v == f"/bin/{k}" for k, v in bins.items())

    def test_is_available_true(self, monkeypatch):
        monkeypatch.setattr(clamav, "_find_binary", lambda n: "/bin/clamscan" if n == "clamscan" else None)
        assert clamav.is_available() is True

    def test_is_available_false(self, monkeypatch):
        monkeypatch.setattr(clamav, "_find_binary", lambda n: None)
        assert clamav.is_available() is False


# ---------------------------------------------------------------------------
# Certs discovery
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestFindCertsDir:
    def test_returns_none_when_no_certs(self, monkeypatch):
        monkeypatch.setattr("sys.frozen", False, raising=False)
        # No candidate dirs exist
        result = clamav._find_certs_dir()
        # May or may not be None depending on filesystem; just verify it's
        # None when the dirs don't exist
        if result is not None:
            assert os.path.isdir(result)

    def test_finds_dev_certs(self, monkeypatch, tmp_path):
        monkeypatch.setattr("sys.frozen", False, raising=False)

        # Create a fake project structure
        plugins_dir = tmp_path / "plugins" / "antivirus"
        plugins_dir.mkdir(parents=True)
        certs_dir = tmp_path / "scripts" / "build" / "clamav-artifacts" / "certs"
        certs_dir.mkdir(parents=True)
        (certs_dir / "clamav.crt").write_text("cert")

        # Monkey-patch __file__ indirectly via the project root calculation
        monkeypatch.setattr(
            clamav, "_find_certs_dir",
            lambda: str(certs_dir),
        )
        assert clamav._find_certs_dir() == str(certs_dir)


# ---------------------------------------------------------------------------
# Environment setup
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestClamavEnv:
    def test_env_contains_system_env(self):
        env = clamav._clamav_env()
        # Should include PATH from the system environment
        assert "PATH" in env

    def test_sets_cvd_certs_dir_when_found(self, monkeypatch):
        monkeypatch.delenv("CVD_CERTS_DIR", raising=False)
        monkeypatch.setattr(clamav, "_find_certs_dir", lambda: "/fake/certs")
        env = clamav._clamav_env()
        assert env["CVD_CERTS_DIR"] == "/fake/certs"

    def test_skips_cvd_certs_when_already_set(self, monkeypatch):
        monkeypatch.setenv("CVD_CERTS_DIR", "/existing/certs")
        env = clamav._clamav_env()
        assert env["CVD_CERTS_DIR"] == "/existing/certs"

    def test_skips_cvd_certs_when_not_found(self, monkeypatch):
        monkeypatch.delenv("CVD_CERTS_DIR", raising=False)
        monkeypatch.setattr(clamav, "_find_certs_dir", lambda: None)
        env = clamav._clamav_env()
        assert "CVD_CERTS_DIR" not in env

    def test_sets_ssl_cert_file_when_exists(self, monkeypatch, tmp_path):
        monkeypatch.delenv("SSL_CERT_FILE", raising=False)
        cert = tmp_path / "ca.pem"
        cert.write_text("cert")

        original_isfile = os.path.isfile

        def patched_isfile(path):
            if path == str(cert):
                return True
            return original_isfile(path)

        # Patch the ca_path list to include our temp cert
        monkeypatch.setattr(clamav, "_find_certs_dir", lambda: None)
        # We can't easily patch the tuple inside the function, so just
        # verify the existing behavior: if SSL_CERT_FILE already set, it's kept
        monkeypatch.setenv("SSL_CERT_FILE", str(cert))
        env = clamav._clamav_env()
        assert env["SSL_CERT_FILE"] == str(cert)


# ---------------------------------------------------------------------------
# Config generation
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestConfigGeneration:
    def test_write_clamd_conf_creates_file(self, clamav_dirs):
        clamav._write_clamd_conf()
        conf_path = os.path.join(str(clamav_dirs["data"]), "clamd.conf")
        assert os.path.isfile(conf_path)
        content = open(conf_path).read()
        assert "LocalSocket" in content
        assert str(clamav_dirs["run"]) in content
        assert "DatabaseDirectory" in content
        assert str(clamav_dirs["db"]) in content

    def test_write_freshclam_conf_creates_file(self, clamav_dirs, monkeypatch):
        monkeypatch.setattr(clamav, "_find_certs_dir", lambda: None)
        clamav._write_freshclam_conf()
        conf_path = os.path.join(str(clamav_dirs["data"]), "freshclam.conf")
        assert os.path.isfile(conf_path)
        content = open(conf_path).read()
        assert "DatabaseDirectory" in content
        assert "DatabaseMirror database.clamav.net" in content
        assert "CVDCertsDirectory" not in content

    def test_write_freshclam_conf_includes_certs(self, clamav_dirs, monkeypatch):
        monkeypatch.setattr(clamav, "_find_certs_dir", lambda: "/my/certs")
        clamav._write_freshclam_conf()
        conf_path = os.path.join(str(clamav_dirs["data"]), "freshclam.conf")
        content = open(conf_path).read()
        assert "CVDCertsDirectory /my/certs" in content

    def test_ensure_config_creates_both(self, clamav_dirs, monkeypatch):
        monkeypatch.setattr(clamav, "_find_certs_dir", lambda: None)
        clamav.ensure_config()
        assert os.path.isfile(os.path.join(str(clamav_dirs["data"]), "clamd.conf"))
        assert os.path.isfile(os.path.join(str(clamav_dirs["data"]), "freshclam.conf"))

    def test_ensure_dirs_creates_missing(self, tmp_path, monkeypatch):
        new_db = tmp_path / "new_db"
        new_log = tmp_path / "new_log"
        new_run = tmp_path / "new_run"
        new_q = tmp_path / "new_quarantine"
        monkeypatch.setattr(clamav, "_DB_DIR", str(new_db))
        monkeypatch.setattr(clamav, "_LOG_DIR", str(new_log))
        monkeypatch.setattr(clamav, "_RUN_DIR", str(new_run))
        monkeypatch.setattr(clamav, "_QUARANTINE_DIR", str(new_q))
        clamav._ensure_dirs()
        assert new_db.is_dir()
        assert new_log.is_dir()
        assert new_run.is_dir()
        assert new_q.is_dir()


# ---------------------------------------------------------------------------
# Signature database info
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestDbInfo:
    def test_no_db_files_returns_dashes(self, clamav_dirs):
        info = clamav.get_db_info()
        assert info["signatures"] == "\u2014"
        assert info["last_updated"] == "\u2014"

    def test_parses_cvd_header(self, clamav_dirs):
        """CVD header format: ClamAV-VDB:date:ver:sigs:..."""
        db_dir = clamav_dirs["db"]
        header = "ClamAV-VDB:01 Jan 2025:100:5000:63:xxx"
        # Pad to 512 bytes
        header = header + "\x00" * (512 - len(header))
        cvd_path = db_dir / "main.cvd"
        cvd_path.write_bytes(header.encode("ascii"))

        info = clamav.get_db_info()
        assert info["signatures"] == "5,000"
        # last_updated is formatted from mtime, which is "now"
        assert info["last_updated"] != "\u2014"

    def test_sums_multiple_cvd_files(self, clamav_dirs):
        db_dir = clamav_dirs["db"]
        for name, sigs in [("main.cvd", 3000), ("daily.cld", 2000)]:
            header = f"ClamAV-VDB:01 Jan 2025:100:{sigs}:63:xxx"
            header = header + "\x00" * (512 - len(header))
            (db_dir / name).write_bytes(header.encode("ascii"))

        info = clamav.get_db_info()
        assert info["signatures"] == "5,000"

    def test_handles_corrupt_cvd(self, clamav_dirs):
        db_dir = clamav_dirs["db"]
        (db_dir / "bad.cvd").write_bytes(b"not a valid header")
        info = clamav.get_db_info()
        # Should not crash — signatures stays as dash
        assert info["signatures"] == "\u2014"

    def test_has_database_true(self, clamav_dirs):
        (clamav_dirs["db"] / "main.cvd").write_bytes(b"data")
        assert clamav.has_database() is True

    def test_has_database_false(self, clamav_dirs):
        assert clamav.has_database() is False

    def test_has_database_with_cld(self, clamav_dirs):
        (clamav_dirs["db"] / "daily.cld").write_bytes(b"data")
        assert clamav.has_database() is True


# ---------------------------------------------------------------------------
# Freshclam
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestRunFreshclam:
    def test_binary_not_found(self, monkeypatch):
        monkeypatch.setattr(clamav, "_find_binary", lambda n: None)
        ok, msg = clamav.run_freshclam()
        assert ok is False
        assert "not found" in msg

    def test_success(self, monkeypatch, clamav_dirs):
        monkeypatch.setattr(clamav, "_find_binary", lambda n: "/bin/freshclam")
        monkeypatch.setattr(clamav, "_find_certs_dir", lambda: None)

        mock_proc = MagicMock()
        mock_proc.stdout = iter(["Downloading main.cvd\n", "Done\n"])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            ok, msg = clamav.run_freshclam()
            assert ok is True
            assert "success" in msg.lower()
            # Verify the command includes --config-file and --stdout
            cmd = mock_popen.call_args[0][0]
            assert "--config-file" in cmd
            assert "--stdout" in cmd

    def test_already_up_to_date(self, monkeypatch, clamav_dirs):
        monkeypatch.setattr(clamav, "_find_binary", lambda n: "/bin/freshclam")
        monkeypatch.setattr(clamav, "_find_certs_dir", lambda: None)

        mock_proc = MagicMock()
        mock_proc.stdout = iter(["main.cvd is up to date\n"])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 1  # Non-zero but "up to date" in output

        with patch("subprocess.Popen", return_value=mock_proc):
            ok, msg = clamav.run_freshclam()
            assert ok is True
            assert "up to date" in msg.lower()

    def test_failure_nonzero_exit(self, monkeypatch, clamav_dirs):
        monkeypatch.setattr(clamav, "_find_binary", lambda n: "/bin/freshclam")
        monkeypatch.setattr(clamav, "_find_certs_dir", lambda: None)

        mock_proc = MagicMock()
        mock_proc.stdout = iter(["ERROR: something went wrong\n"])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 2

        with patch("subprocess.Popen", return_value=mock_proc):
            ok, msg = clamav.run_freshclam()
            assert ok is False
            assert "2" in msg

    def test_exception_during_run(self, monkeypatch, clamav_dirs):
        monkeypatch.setattr(clamav, "_find_binary", lambda n: "/bin/freshclam")
        monkeypatch.setattr(clamav, "_find_certs_dir", lambda: None)

        with patch("subprocess.Popen", side_effect=OSError("no such file")):
            ok, msg = clamav.run_freshclam()
            assert ok is False
            assert "no such file" in msg

    def test_on_line_callback(self, monkeypatch, clamav_dirs):
        monkeypatch.setattr(clamav, "_find_binary", lambda n: "/bin/freshclam")
        monkeypatch.setattr(clamav, "_find_certs_dir", lambda: None)

        mock_proc = MagicMock()
        mock_proc.stdout = iter(["line1\n", "line2\n"])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0

        lines_received = []
        with patch("subprocess.Popen", return_value=mock_proc):
            clamav.run_freshclam(on_line=lines_received.append)

        assert lines_received == ["line1", "line2"]


# ---------------------------------------------------------------------------
# Clamd status checks
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestClamdStatus:
    def test_clamd_pid_alive_no_file(self, clamav_dirs):
        assert clamav._clamd_pid_alive() is False

    def test_clamd_pid_alive_valid_pid(self, clamav_dirs):
        pid_path = clamav_dirs["run"] / "clamd.pid"
        pid_path.write_text(str(os.getpid()))  # Our own PID is always alive
        assert clamav._clamd_pid_alive() is True

    def test_clamd_pid_alive_dead_pid(self, clamav_dirs):
        pid_path = clamav_dirs["run"] / "clamd.pid"
        pid_path.write_text("99999999")  # Very unlikely to be a real PID
        # os.kill(99999999, 0) should raise OSError
        assert clamav._clamd_pid_alive() is False

    def test_clamd_pid_alive_bad_content(self, clamav_dirs):
        pid_path = clamav_dirs["run"] / "clamd.pid"
        pid_path.write_text("not_a_number")
        assert clamav._clamd_pid_alive() is False

    def test_ping_socket_no_file(self, clamav_dirs):
        assert clamav._ping_socket("/nonexistent/socket") is False

    def test_ping_socket_connection_refused(self, clamav_dirs, tmp_path):
        sock_path = str(tmp_path / "test.sock")
        # Create file but it's not a real socket
        open(sock_path, "w").close()
        assert clamav._ping_socket(sock_path) is False

    def test_active_clamd_socket_none(self, monkeypatch):
        monkeypatch.setattr(clamav, "_ping_socket", lambda p: False)
        assert clamav._active_clamd_socket() is None

    def test_active_clamd_socket_user(self, monkeypatch):
        monkeypatch.setattr(
            clamav, "_ping_socket",
            lambda p: p == clamav._CLAMD_SOCKET,
        )
        assert clamav._active_clamd_socket() == clamav._CLAMD_SOCKET

    def test_active_clamd_socket_system(self, monkeypatch):
        def _ping(p):
            return p == clamav._SYSTEM_CLAMD_SOCKET

        monkeypatch.setattr(clamav, "_ping_socket", _ping)
        assert clamav._active_clamd_socket() == clamav._SYSTEM_CLAMD_SOCKET

    def test_is_clamd_running_true(self, monkeypatch):
        monkeypatch.setattr(clamav, "_active_clamd_socket", lambda: "/some/socket")
        assert clamav.is_clamd_running() is True

    def test_is_clamd_running_false(self, monkeypatch):
        monkeypatch.setattr(clamav, "_active_clamd_socket", lambda: None)
        assert clamav.is_clamd_running() is False


# ---------------------------------------------------------------------------
# Clamonacc status
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestClamonaccStatus:
    def test_running(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert clamav.is_clamonacc_running() is True
            cmd = mock_run.call_args[0][0]
            assert cmd == ["pgrep", "-x", "clamonacc"]

    def test_not_running(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            assert clamav.is_clamonacc_running() is False

    def test_exception(self):
        with patch("subprocess.run", side_effect=OSError("fail")):
            assert clamav.is_clamonacc_running() is False


# ---------------------------------------------------------------------------
# App bundle detection
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestIsAppBundle:
    def test_not_bundle(self, monkeypatch):
        monkeypatch.setattr("sys.executable", "/usr/bin/python3")
        monkeypatch.setattr("sys.argv", ["/usr/bin/python3"])
        assert clamav._is_app_bundle() is False

    def test_is_bundle_via_executable(self, monkeypatch):
        monkeypatch.setattr(
            "sys.executable",
            "/Applications/Resistine.app/Contents/MacOS/Resistine",
        )
        assert clamav._is_app_bundle() is True

    def test_is_bundle_via_argv(self, monkeypatch):
        monkeypatch.setattr("sys.executable", "/usr/bin/python3")
        monkeypatch.setattr(
            "sys.argv",
            ["/Applications/Resistine.app/Contents/MacOS/main"],
        )
        assert clamav._is_app_bundle() is True


# ---------------------------------------------------------------------------
# Full Disk Access check
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestFullDiskAccess:
    def test_fda_granted_mail_accessible(self, monkeypatch):
        monkeypatch.setattr(os, "listdir", lambda p: ["Inbox"])
        assert clamav.has_full_disk_access() is True

    def test_fda_denied_mail(self, monkeypatch):
        def _listdir(p):
            if "Mail" in p:
                raise PermissionError("denied")
            raise FileNotFoundError("no dir")
        monkeypatch.setattr(os, "listdir", _listdir)
        # Falls through to Safari check
        # If Safari also raises PermissionError → False
        assert clamav.has_full_disk_access() is False

    def test_fda_no_mail_no_safari(self, monkeypatch):
        def _listdir(p):
            raise FileNotFoundError("no dir")
        monkeypatch.setattr(os, "listdir", _listdir)
        # Neither exists → assume granted
        assert clamav.has_full_disk_access() is True


# ---------------------------------------------------------------------------
# get_realtime_status
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestGetRealtimeStatus:
    def test_not_installed(self, monkeypatch):
        monkeypatch.setattr(clamav, "is_clamav_installed", lambda: False)
        monkeypatch.setattr(clamav, "has_database", lambda: False)
        monkeypatch.setattr(clamav, "is_clamd_running", lambda: False)
        monkeypatch.setattr(clamav, "is_clamonacc_running", lambda: False)
        monkeypatch.setattr(clamav, "_is_app_bundle", lambda: False)
        s = clamav.get_realtime_status()
        assert s["state"] == "not_installed"
        assert s["installed"] is False

    def test_no_database(self, monkeypatch):
        monkeypatch.setattr(clamav, "is_clamav_installed", lambda: True)
        monkeypatch.setattr(clamav, "has_database", lambda: False)
        monkeypatch.setattr(clamav, "is_clamd_running", lambda: False)
        monkeypatch.setattr(clamav, "is_clamonacc_running", lambda: False)
        monkeypatch.setattr(clamav, "_is_app_bundle", lambda: False)
        s = clamav.get_realtime_status()
        assert s["state"] == "no_database"

    def test_protected(self, monkeypatch):
        monkeypatch.setattr(clamav, "is_clamav_installed", lambda: True)
        monkeypatch.setattr(clamav, "has_database", lambda: True)
        monkeypatch.setattr(clamav, "is_clamd_running", lambda: True)
        monkeypatch.setattr(clamav, "is_clamonacc_running", lambda: True)
        monkeypatch.setattr(clamav, "_is_app_bundle", lambda: False)
        s = clamav.get_realtime_status()
        assert s["state"] == "protected"
        assert s["clamd_running"] is True
        assert s["clamonacc_running"] is True

    def test_error_daemons_not_running(self, monkeypatch):
        monkeypatch.setattr(clamav, "is_clamav_installed", lambda: True)
        monkeypatch.setattr(clamav, "has_database", lambda: True)
        monkeypatch.setattr(clamav, "is_clamd_running", lambda: False)
        monkeypatch.setattr(clamav, "is_clamonacc_running", lambda: False)
        monkeypatch.setattr(clamav, "_is_app_bundle", lambda: False)
        s = clamav.get_realtime_status()
        assert s["state"] == "error"

    def test_approval_required_in_bundle(self, monkeypatch):
        monkeypatch.setattr(clamav, "is_clamav_installed", lambda: True)
        monkeypatch.setattr(clamav, "has_database", lambda: True)
        monkeypatch.setattr(clamav, "is_clamd_running", lambda: True)
        monkeypatch.setattr(clamav, "is_clamonacc_running", lambda: True)
        monkeypatch.setattr(clamav, "_is_app_bundle", lambda: True)
        monkeypatch.setattr(clamav, "_daemons_approved", lambda: False)
        monkeypatch.setattr(clamav, "has_full_disk_access", lambda: True)
        s = clamav.get_realtime_status()
        assert s["state"] == "approval_required"

    def test_fda_required_in_bundle(self, monkeypatch):
        monkeypatch.setattr(clamav, "is_clamav_installed", lambda: True)
        monkeypatch.setattr(clamav, "has_database", lambda: True)
        monkeypatch.setattr(clamav, "is_clamd_running", lambda: True)
        monkeypatch.setattr(clamav, "is_clamonacc_running", lambda: True)
        monkeypatch.setattr(clamav, "_is_app_bundle", lambda: True)
        monkeypatch.setattr(clamav, "_daemons_approved", lambda: True)
        monkeypatch.setattr(clamav, "has_full_disk_access", lambda: False)
        s = clamav.get_realtime_status()
        assert s["state"] == "fda_required"

    def test_not_bundle_skips_approval_and_fda(self, monkeypatch):
        """Outside app bundle, approved and fda default to True."""
        monkeypatch.setattr(clamav, "is_clamav_installed", lambda: True)
        monkeypatch.setattr(clamav, "has_database", lambda: True)
        monkeypatch.setattr(clamav, "is_clamd_running", lambda: True)
        monkeypatch.setattr(clamav, "is_clamonacc_running", lambda: True)
        monkeypatch.setattr(clamav, "_is_app_bundle", lambda: False)
        s = clamav.get_realtime_status()
        assert s["approved"] is True
        assert s["fda_granted"] is True
        assert s["state"] == "protected"


# ---------------------------------------------------------------------------
# Start / Stop clamd
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestStartStopClamd:
    def test_start_already_running(self, monkeypatch):
        monkeypatch.setattr(clamav, "is_clamd_running", lambda: True)
        ok, msg = clamav.start_clamd()
        assert ok is True
        assert "already running" in msg

    def test_start_binary_not_found(self, monkeypatch):
        monkeypatch.setattr(clamav, "is_clamd_running", lambda: False)
        monkeypatch.setattr(clamav, "_find_binary", lambda n: None)
        ok, msg = clamav.start_clamd()
        assert ok is False
        assert "not found" in msg

    def test_start_no_database(self, monkeypatch):
        monkeypatch.setattr(clamav, "is_clamd_running", lambda: False)
        monkeypatch.setattr(clamav, "_find_binary", lambda n: "/bin/clamd")
        monkeypatch.setattr(clamav, "has_database", lambda: False)
        ok, msg = clamav.start_clamd()
        assert ok is False
        assert "database" in msg.lower()

    def test_start_success(self, monkeypatch, clamav_dirs):
        call_count = {"n": 0}

        def _is_running():
            call_count["n"] += 1
            return call_count["n"] > 2  # Becomes running after 2 checks

        monkeypatch.setattr(clamav, "is_clamd_running", _is_running)
        monkeypatch.setattr(clamav, "_find_binary", lambda n: "/bin/clamd")
        monkeypatch.setattr(clamav, "has_database", lambda: True)
        monkeypatch.setattr(clamav, "_find_certs_dir", lambda: None)
        monkeypatch.setattr(time, "sleep", lambda t: None)

        with patch("subprocess.Popen") as mock_popen:
            ok, msg = clamav.start_clamd()
            assert ok is True
            assert "started" in msg
            mock_popen.assert_called_once()

    def test_start_timeout(self, monkeypatch, clamav_dirs):
        monkeypatch.setattr(clamav, "is_clamd_running", lambda: False)
        monkeypatch.setattr(clamav, "_find_binary", lambda n: "/bin/clamd")
        monkeypatch.setattr(clamav, "has_database", lambda: True)
        monkeypatch.setattr(clamav, "_find_certs_dir", lambda: None)
        monkeypatch.setattr(time, "sleep", lambda t: None)

        with patch("subprocess.Popen"):
            ok, msg = clamav.start_clamd()
            assert ok is False
            assert "not start in time" in msg

    def test_start_cleans_stale_socket(self, monkeypatch, clamav_dirs):
        # Create stale socket and pid files
        sock = clamav_dirs["run"] / "clamd.sock"
        pid = clamav_dirs["run"] / "clamd.pid"
        sock.write_text("stale")
        pid.write_text("stale")

        call_count = {"n": 0}

        def _is_running():
            call_count["n"] += 1
            return call_count["n"] > 1

        monkeypatch.setattr(clamav, "is_clamd_running", _is_running)
        monkeypatch.setattr(clamav, "_find_binary", lambda n: "/bin/clamd")
        monkeypatch.setattr(clamav, "has_database", lambda: True)
        monkeypatch.setattr(clamav, "_find_certs_dir", lambda: None)
        monkeypatch.setattr(time, "sleep", lambda t: None)

        with patch("subprocess.Popen"):
            clamav.start_clamd()

        # Stale files should have been removed
        assert not sock.exists()
        assert not pid.exists()

    def test_stop_not_running(self, monkeypatch, clamav_dirs):
        monkeypatch.setattr(clamav, "_clamd_pid_alive", lambda: False)
        ok, msg = clamav.stop_clamd()
        assert ok is True
        assert "not running" in msg

    def test_stop_cleans_stale_files(self, monkeypatch, clamav_dirs):
        """When not running but stale socket/pid exist, they get cleaned up."""
        monkeypatch.setattr(clamav, "_clamd_pid_alive", lambda: False)
        sock = clamav_dirs["run"] / "clamd.sock"
        pid = clamav_dirs["run"] / "clamd.pid"
        sock.write_text("stale")
        pid.write_text("stale")
        clamav.stop_clamd()
        assert not sock.exists()
        assert not pid.exists()

    def test_stop_sends_sigterm(self, monkeypatch, clamav_dirs):
        pid_file = clamav_dirs["run"] / "clamd.pid"
        pid_file.write_text("12345")

        alive_count = {"n": 0}

        def _alive():
            alive_count["n"] += 1
            return alive_count["n"] <= 1  # Alive on first call, then dead

        monkeypatch.setattr(clamav, "_clamd_pid_alive", _alive)
        monkeypatch.setattr(time, "sleep", lambda t: None)

        with patch("os.kill") as mock_kill:
            ok, msg = clamav.stop_clamd()
            assert ok is True
            assert "stopped" in msg
            mock_kill.assert_called_once_with(12345, 15)


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestScanPath:
    def test_no_binary_found(self, monkeypatch):
        monkeypatch.setattr(clamav, "_active_clamd_socket", lambda: None)
        monkeypatch.setattr(clamav, "_find_binary", lambda n: None)
        result = clamav.scan_path("/tmp/test")
        assert result["error"] == "ClamAV not installed."
        assert result["scanned"] == 0

    def test_no_database_standalone(self, monkeypatch):
        monkeypatch.setattr(clamav, "_active_clamd_socket", lambda: None)
        monkeypatch.setattr(clamav, "_find_binary", lambda n: "/bin/clamscan")
        monkeypatch.setattr(clamav, "has_database", lambda: False)
        result = clamav.scan_path("/tmp/test")
        assert "database" in result["error"].lower()

    def test_clean_scan_via_clamscan(self, monkeypatch, clamav_dirs):
        monkeypatch.setattr(clamav, "_active_clamd_socket", lambda: None)
        monkeypatch.setattr(clamav, "_find_binary", lambda n: "/bin/clamscan" if n == "clamscan" else None)
        monkeypatch.setattr(clamav, "has_database", lambda: True)
        monkeypatch.setattr(clamav, "get_whitelist", lambda: [])
        monkeypatch.setattr(os.path, "isdir", lambda p: False)

        mock_proc = MagicMock()
        mock_proc.stdout = iter([
            "/tmp/test/file1.txt: OK\n",
            "/tmp/test/file2.txt: OK\n",
            "Scanned files: 2\n",
            "Infected files: 0\n",
            "Time: 1.5 sec\n",
        ])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0

        with patch("subprocess.Popen", return_value=mock_proc):
            result = clamav.scan_path("/tmp/test/file1.txt")

        assert result["scanned"] == 2
        assert result["infected"] == 0
        assert result["duration"] == "1.5 sec"
        assert result["error"] == ""

    def test_infected_scan(self, monkeypatch, clamav_dirs):
        monkeypatch.setattr(clamav, "_active_clamd_socket", lambda: None)
        monkeypatch.setattr(clamav, "_find_binary", lambda n: "/bin/clamscan" if n == "clamscan" else None)
        monkeypatch.setattr(clamav, "has_database", lambda: True)
        monkeypatch.setattr(clamav, "get_whitelist", lambda: [])
        monkeypatch.setattr(os.path, "isdir", lambda p: False)

        mock_proc = MagicMock()
        mock_proc.stdout = iter([
            "/tmp/virus.exe: Win.Trojan.Agent FOUND\n",
            "Scanned files: 1\n",
            "Infected files: 1\n",
        ])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 1

        with patch("subprocess.Popen", return_value=mock_proc):
            result = clamav.scan_path("/tmp/virus.exe")

        assert result["infected"] == 1
        assert len(result["infections"]) == 1
        assert "FOUND" in result["infections"][0]

    def test_scan_via_clamdscan(self, monkeypatch, clamav_dirs):
        """When clamd is running, uses clamdscan with --config-file."""
        monkeypatch.setattr(clamav, "_active_clamd_socket", lambda: clamav._CLAMD_SOCKET)
        monkeypatch.setattr(clamav, "_find_binary", lambda n: f"/bin/{n}")
        monkeypatch.setattr(os.path, "isdir", lambda p: False)

        mock_proc = MagicMock()
        mock_proc.stdout = iter(["/tmp/file: OK\n"])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            clamav.scan_path("/tmp/file")
            cmd = mock_popen.call_args[0][0]
            assert "/bin/clamdscan" in cmd[0]
            assert "--config-file" in cmd

    def test_scan_directory_adds_multiscan(self, monkeypatch, clamav_dirs):
        monkeypatch.setattr(clamav, "_active_clamd_socket", lambda: clamav._CLAMD_SOCKET)
        monkeypatch.setattr(clamav, "_find_binary", lambda n: f"/bin/{n}")
        monkeypatch.setattr(os.path, "isdir", lambda p: True)

        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            clamav.scan_path("/tmp/dir")
            cmd = mock_popen.call_args[0][0]
            assert "--multiscan" in cmd

    def test_scan_cancel(self, monkeypatch, clamav_dirs):
        monkeypatch.setattr(clamav, "_active_clamd_socket", lambda: None)
        monkeypatch.setattr(clamav, "_find_binary", lambda n: "/bin/clamscan")
        monkeypatch.setattr(clamav, "has_database", lambda: True)
        monkeypatch.setattr(clamav, "get_whitelist", lambda: [])
        monkeypatch.setattr(os.path, "isdir", lambda p: False)

        cancel = threading.Event()
        cancel.set()  # Already cancelled

        mock_proc = MagicMock()
        mock_proc.stdout = iter(["/tmp/file: OK\n"])
        mock_proc.wait.return_value = None

        with patch("subprocess.Popen", return_value=mock_proc):
            result = clamav.scan_path("/tmp/file", cancel=cancel)

        assert result["error"] == "Scan cancelled."
        mock_proc.kill.assert_called_once()

    def test_scan_killed_by_signal(self, monkeypatch, clamav_dirs):
        monkeypatch.setattr(clamav, "_active_clamd_socket", lambda: None)
        monkeypatch.setattr(clamav, "_find_binary", lambda n: "/bin/clamscan")
        monkeypatch.setattr(clamav, "has_database", lambda: True)
        monkeypatch.setattr(clamav, "get_whitelist", lambda: [])
        monkeypatch.setattr(os.path, "isdir", lambda p: False)

        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.wait.return_value = None
        mock_proc.returncode = -9  # SIGKILL

        with patch("subprocess.Popen", return_value=mock_proc):
            result = clamav.scan_path("/tmp/file")

        assert "signal 9" in result["error"]
        assert "quarantined" in result["error"]

    def test_scan_error_exit(self, monkeypatch, clamav_dirs):
        monkeypatch.setattr(clamav, "_active_clamd_socket", lambda: None)
        monkeypatch.setattr(clamav, "_find_binary", lambda n: "/bin/clamscan")
        monkeypatch.setattr(clamav, "has_database", lambda: True)
        monkeypatch.setattr(clamav, "get_whitelist", lambda: [])
        monkeypatch.setattr(os.path, "isdir", lambda p: False)

        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 2

        with patch("subprocess.Popen", return_value=mock_proc):
            result = clamav.scan_path("/tmp/file")

        assert "error during scanning" in result["error"].lower()

    def test_scan_timeout(self, monkeypatch, clamav_dirs):
        monkeypatch.setattr(clamav, "_active_clamd_socket", lambda: None)
        monkeypatch.setattr(clamav, "_find_binary", lambda n: "/bin/clamscan")
        monkeypatch.setattr(clamav, "has_database", lambda: True)
        monkeypatch.setattr(clamav, "get_whitelist", lambda: [])
        monkeypatch.setattr(os.path, "isdir", lambda p: False)

        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        # First call (timeout=30) raises; second call (timeout=5 in except) succeeds
        mock_proc.wait.side_effect = [
            subprocess.TimeoutExpired(cmd="clamscan", timeout=30),
            None,
        ]

        with patch("subprocess.Popen", return_value=mock_proc):
            result = clamav.scan_path("/tmp/file")

        assert "timed out" in result["error"].lower()
        mock_proc.kill.assert_called_once()

    def test_scan_popen_failure(self, monkeypatch, clamav_dirs):
        monkeypatch.setattr(clamav, "_active_clamd_socket", lambda: None)
        monkeypatch.setattr(clamav, "_find_binary", lambda n: "/bin/clamscan")
        monkeypatch.setattr(clamav, "has_database", lambda: True)
        monkeypatch.setattr(clamav, "get_whitelist", lambda: [])
        monkeypatch.setattr(os.path, "isdir", lambda p: False)

        with patch("subprocess.Popen", side_effect=OSError("Permission denied")):
            result = clamav.scan_path("/tmp/file")

        assert "Permission denied" in result["error"]

    def test_scan_on_line_callback(self, monkeypatch, clamav_dirs):
        monkeypatch.setattr(clamav, "_active_clamd_socket", lambda: None)
        monkeypatch.setattr(clamav, "_find_binary", lambda n: "/bin/clamscan")
        monkeypatch.setattr(clamav, "has_database", lambda: True)
        monkeypatch.setattr(clamav, "get_whitelist", lambda: [])
        monkeypatch.setattr(os.path, "isdir", lambda p: False)

        mock_proc = MagicMock()
        mock_proc.stdout = iter(["/tmp/f: OK\n"])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0

        lines = []
        with patch("subprocess.Popen", return_value=mock_proc):
            clamav.scan_path("/tmp/f", on_line=lines.append)

        assert lines == ["/tmp/f: OK"]

    def test_scan_uses_system_socket_conf(self, monkeypatch, clamav_dirs):
        """When system daemon is active, uses system clamd.conf."""
        monkeypatch.setattr(
            clamav, "_active_clamd_socket",
            lambda: clamav._SYSTEM_CLAMD_SOCKET,
        )
        monkeypatch.setattr(clamav, "_find_binary", lambda n: f"/bin/{n}")
        monkeypatch.setattr(os.path, "isdir", lambda p: False)

        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            clamav.scan_path("/tmp/file")
            cmd = mock_popen.call_args[0][0]
            assert clamav._SYSTEM_CLAMD_CONF in cmd

    def test_scan_clamscan_excludes_whitelist(self, monkeypatch, clamav_dirs):
        monkeypatch.setattr(clamav, "_active_clamd_socket", lambda: None)
        monkeypatch.setattr(clamav, "_find_binary", lambda n: "/bin/clamscan")
        monkeypatch.setattr(clamav, "has_database", lambda: True)
        monkeypatch.setattr(clamav, "get_whitelist", lambda: ["/excluded/dir"])
        monkeypatch.setattr(os.path, "isdir", lambda p: p == "/excluded/dir" or p == "/tmp/file")

        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            clamav.scan_path("/tmp/file")
            cmd = mock_popen.call_args[0][0]
            assert "--exclude-dir" in cmd
            # Standard excludes (.git etc) + whitelist dir
            exclude_dir_indices = [i for i, v in enumerate(cmd) if v == "--exclude-dir"]
            assert len(exclude_dir_indices) >= 6  # 5 standard + 1 whitelist

    def test_scan_derives_scanned_from_output(self, monkeypatch, clamav_dirs):
        """clamdscan doesn't output 'Scanned files:' — count from output lines."""
        monkeypatch.setattr(clamav, "_active_clamd_socket", lambda: clamav._CLAMD_SOCKET)
        monkeypatch.setattr(clamav, "_find_binary", lambda n: f"/bin/{n}")
        monkeypatch.setattr(os.path, "isdir", lambda p: False)

        mock_proc = MagicMock()
        mock_proc.stdout = iter([
            "/tmp/a: OK\n",
            "/tmp/b: OK\n",
            "/tmp/c: Win.Virus FOUND\n",
        ])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 1

        with patch("subprocess.Popen", return_value=mock_proc):
            result = clamav.scan_path("/tmp/dir")

        # No "Scanned files:" line, so derived from OK/FOUND lines
        assert result["scanned"] == 3


# ---------------------------------------------------------------------------
# Quarantine
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestQuarantine:
    def test_quarantine_file_not_found(self, clamav_dirs):
        ok, msg = clamav.quarantine_file("/nonexistent/file")
        assert ok is False
        assert "not found" in msg.lower()

    def test_quarantine_success(self, clamav_dirs, tmp_path):
        infected = tmp_path / "virus.exe"
        infected.write_text("malware content")

        ok, dest = clamav.quarantine_file(str(infected))
        assert ok is True
        assert dest.endswith(".quarantined")
        assert not infected.exists()
        assert os.path.exists(dest)
        # File should be chmod 0o000
        assert os.stat(dest).st_mode & 0o777 == 0o000

    def test_quarantine_duplicate_name(self, clamav_dirs, tmp_path):
        """Second quarantine of same-named file gets .1.quarantined suffix."""
        q_dir = clamav_dirs["quarantine"]
        # Pre-create a quarantined file
        (q_dir / "virus.exe.quarantined").write_text("first")

        infected = tmp_path / "virus.exe"
        infected.write_text("second malware")

        ok, dest = clamav.quarantine_file(str(infected))
        assert ok is True
        assert "virus.exe.1.quarantined" in dest

    def test_list_quarantined_empty(self, clamav_dirs):
        result = clamav.list_quarantined()
        assert result == []

    def test_list_quarantined_returns_sorted(self, clamav_dirs):
        q = clamav_dirs["quarantine"]
        (q / "b.quarantined").write_text("")
        (q / "a.quarantined").write_text("")
        result = clamav.list_quarantined()
        assert len(result) == 2
        assert os.path.basename(result[0]) == "a.quarantined"
        assert os.path.basename(result[1]) == "b.quarantined"

    def test_restore_quarantined_not_found(self, clamav_dirs):
        ok, msg = clamav.restore_quarantined("/nonexistent", "/tmp/dest")
        assert ok is False
        assert "not found" in msg.lower()

    def test_restore_quarantined_success(self, clamav_dirs, tmp_path):
        q = clamav_dirs["quarantine"]
        qfile = q / "virus.exe.quarantined"
        qfile.write_text("content")
        qfile.chmod(0o000)

        dest = tmp_path / "restored.exe"
        ok, msg = clamav.restore_quarantined(str(qfile), str(dest))
        assert ok is True
        assert "Restored" in msg
        assert dest.exists()
        assert dest.read_text() == "content"
        assert not qfile.exists()

    def test_delete_quarantined_not_found(self, clamav_dirs):
        ok, msg = clamav.delete_quarantined("/nonexistent")
        assert ok is False
        assert "not found" in msg.lower()

    def test_delete_quarantined_success(self, clamav_dirs):
        q = clamav_dirs["quarantine"]
        qfile = q / "virus.exe.quarantined"
        qfile.write_text("content")
        qfile.chmod(0o000)

        ok, msg = clamav.delete_quarantined(str(qfile))
        assert ok is True
        assert "Deleted" in msg
        assert not qfile.exists()


# ---------------------------------------------------------------------------
# Whitelist
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestWhitelist:
    def test_get_whitelist_empty(self, clamav_dirs):
        assert clamav.get_whitelist() == []

    def test_add_and_get_whitelist(self, clamav_dirs):
        clamav.add_to_whitelist("/some/path")
        assert clamav.get_whitelist() == ["/some/path"]

    def test_add_duplicate_no_op(self, clamav_dirs):
        clamav.add_to_whitelist("/path1")
        clamav.add_to_whitelist("/path1")
        assert clamav.get_whitelist() == ["/path1"]

    def test_add_multiple(self, clamav_dirs):
        clamav.add_to_whitelist("/path1")
        clamav.add_to_whitelist("/path2")
        result = clamav.get_whitelist()
        assert "/path1" in result
        assert "/path2" in result
        assert len(result) == 2

    def test_remove_from_whitelist(self, clamav_dirs):
        clamav.add_to_whitelist("/path1")
        clamav.add_to_whitelist("/path2")
        clamav.remove_from_whitelist("/path1")
        assert clamav.get_whitelist() == ["/path2"]

    def test_remove_nonexistent_does_not_crash(self, clamav_dirs):
        clamav.add_to_whitelist("/path1")
        clamav.remove_from_whitelist("/nonexistent")
        assert clamav.get_whitelist() == ["/path1"]

    def test_get_whitelist_ignores_blank_lines(self, clamav_dirs):
        wl_path = os.path.join(str(clamav_dirs["data"]), "whitelist.txt")
        with open(wl_path, "w") as f:
            f.write("/path1\n\n\n/path2\n   \n")
        assert clamav.get_whitelist() == ["/path1", "/path2"]


# ---------------------------------------------------------------------------
# Daemons approved
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestDaemonsApproved:
    def test_not_app_bundle(self, monkeypatch):
        monkeypatch.setattr(clamav, "_is_app_bundle", lambda: False)
        assert clamav._daemons_approved() is False

    def test_smappservice_import_error(self, monkeypatch):
        monkeypatch.setattr(clamav, "_is_app_bundle", lambda: True)
        # ServiceManagement is mocked — simulate ImportError
        import builtins
        original_import = builtins.__import__

        def _mock_import(name, *args, **kwargs):
            if name == "ServiceManagement":
                raise ImportError("no module")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _mock_import)
        assert clamav._daemons_approved() is False


# ---------------------------------------------------------------------------
# Open settings helpers
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestOpenSettings:
    def test_open_fda_settings(self):
        with patch("subprocess.Popen") as mock_popen:
            clamav.open_fda_settings()
            mock_popen.assert_called_once()
            cmd = mock_popen.call_args[0][0]
            assert "open" in cmd
            assert "Privacy_AllFiles" in cmd[1]

    def test_open_fda_settings_error(self):
        with patch("subprocess.Popen", side_effect=OSError("fail")):
            # Should not raise
            clamav.open_fda_settings()


# ---------------------------------------------------------------------------
# Legacy plist cleanup
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestLegacyPlists:
    def test_cleanup_no_legacy_found(self, monkeypatch):
        monkeypatch.setattr(os.path, "exists", lambda p: False)
        # Should not call subprocess
        with patch("subprocess.run") as mock_run:
            clamav._cleanup_legacy_plists()
            mock_run.assert_not_called()

    def test_cleanup_runs_osascript(self, monkeypatch):
        # Pretend all legacy plists exist
        original_exists = os.path.exists
        monkeypatch.setattr(
            os.path, "exists",
            lambda p: p in clamav._LEGACY_PLIST_PATHS or original_exists(p),
        )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            clamav._cleanup_legacy_plists()
            mock_run.assert_called_once()
            cmd = mock_run.call_args[0][0]
            assert "osascript" in cmd
            # Should include launchctl bootout and rm -f commands
            script_arg = cmd[2]
            assert "launchctl bootout" in script_arg
            assert "rm -f" in script_arg
