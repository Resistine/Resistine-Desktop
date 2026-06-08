"""Tests for scripts/clamav/freshclam-update.sh — the macOS freshclam
auto-update wrapper run by the LaunchDaemon.

Drives the real bash script with PATH-shimmed `freshclam`/`sleep` so the
jitter cadence and the missing-binary guard are exercised without waiting
4 hours or needing a real ClamAV install. macOS/Linux only (needs bash).
"""

import os
import platform
import re
import stat
import subprocess

import pytest

pytestmark = pytest.mark.skipif(
    platform.system() == "Windows",
    reason="freshclam-update.sh is a bash script (macOS/Linux only)",
)

_WRAPPER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts", "clamav", "freshclam-update.sh",
)


def _write_exec(path, body):
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


# These tests intentionally run the real bash wrapper, so every test method
# below requests the `allow_subprocess` fixture (conftest blocks real
# subprocess by default — see tests/conftest.py:_block_real_subprocess).


def _run_wrapper(tmp_path, env_extra, *, freshclam_body, conf_exists=True):
    """Run the wrapper with FRESHCLAM/CONF pointed at tmp shims.

    The wrapper hardcodes absolute /Applications paths, so we run a patched
    copy with FRESHCLAM/CONF redefined to our shims. `sleep` is shimmed to
    record its argument and exit non-zero, which breaks the wrapper's
    infinite loop after exactly one cycle.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()

    fake_freshclam = tmp_path / "freshclam-bin"
    _write_exec(fake_freshclam, freshclam_body)

    conf = tmp_path / "freshclam.conf"
    if conf_exists:
        conf.write_text("# test conf\n")

    sleep_log = tmp_path / "sleep.log"
    # sleep shim: log the requested seconds (instantly, never actually
    # sleeping). The wrapper's `while true` loop only ends when the process
    # dies, so after logging the SECOND sleep (initial jitter = 1st, cadence
    # = 2nd) we kill the wrapper ($PPID) to stop after exactly one cycle.
    # The missing-conf guard records only one sleep (3600) and exits on its
    # own, so killing on the 2nd never triggers there.
    _write_exec(
        bindir / "sleep",
        f'#!/bin/bash\n'
        f'echo "$1" >> {sleep_log!s}\n'
        f'n=$(wc -l < {sleep_log!s})\n'
        f'if [ "$n" -ge 2 ]; then kill "$PPID" 2>/dev/null; fi\n'
        f'exit 0\n',
    )

    # Patch the two hardcoded constants to point at our shims.
    src = open(_WRAPPER).read()
    src = src.replace(
        'FRESHCLAM="/Applications/Resistine.app/Contents/Helpers/freshclam"',
        f'FRESHCLAM="{fake_freshclam!s}"',
    )
    src = src.replace(
        'CONF="/Library/Application Support/Resistine/clamav/freshclam.conf"',
        f'CONF="{conf!s}"',
    )
    patched = tmp_path / "wrapper.sh"
    patched.write_text(src)

    env = os.environ.copy()
    env["PATH"] = f"{bindir!s}:{env['PATH']}"
    env.update(env_extra)

    proc = subprocess.run(
        ["bash", str(patched)],
        env=env, capture_output=True, text=True, timeout=30,
    )
    intervals = (
        [int(x) for x in sleep_log.read_text().split()]
        if sleep_log.exists() else []
    )
    return proc, intervals


@pytest.mark.unit
class TestFreshclamWrapperCadence:
    def test_jitter_within_base_to_base_plus_3600(self, tmp_path, allow_subprocess):
        # With a small base interval the first (and only) loop sleep must be
        # in [base, base+3600). Initial 0-15min jitter sleep also goes to the
        # log, so we take the LAST recorded value (the cadence sleep).
        proc, intervals = _run_wrapper(
            tmp_path,
            {"RESISTINE_FRESHCLAM_INTERVAL": "1"},
            freshclam_body='#!/bin/bash\nexit 0\n',
        )
        assert intervals, f"wrapper never slept; stdout={proc.stdout}"
        cadence = intervals[-1]
        assert 1 <= cadence < 1 + 3600

    def test_default_base_interval_is_14400(self, tmp_path, allow_subprocess):
        # No override → cadence sleep is 14400 + [0,3600).
        proc, intervals = _run_wrapper(
            tmp_path, {},
            freshclam_body='#!/bin/bash\nexit 0\n',
        )
        assert intervals, f"wrapper never slept; stdout={proc.stdout}"
        cadence = intervals[-1]
        assert 14400 <= cadence < 14400 + 3600

    def test_runs_freshclam_with_config_file(self, tmp_path, allow_subprocess):
        # The wrapper must call freshclam by absolute path WITH the conf,
        # never a bare `freshclam`.
        marker = tmp_path / "ran"
        proc, _ = _run_wrapper(
            tmp_path,
            {"RESISTINE_FRESHCLAM_INTERVAL": "1"},
            freshclam_body=(
                f'#!/bin/bash\necho "$@" > {marker!s}\nexit 0\n'
            ),
        )
        assert marker.exists(), f"freshclam never invoked; stdout={proc.stdout}"
        assert "--config-file=" in marker.read_text()

    def test_continues_on_freshclam_failure(self, tmp_path, allow_subprocess):
        # A non-zero freshclam exit must NOT stop the loop — the wrapper
        # logs FAILED and still computes the next sleep.
        proc, intervals = _run_wrapper(
            tmp_path,
            {"RESISTINE_FRESHCLAM_INTERVAL": "1"},
            freshclam_body='#!/bin/bash\nexit 47\n',
        )
        assert "FAILED" in proc.stdout
        assert intervals, "wrapper should still sleep after a failed update"


@pytest.mark.unit
class TestFreshclamWrapperGuard:
    def test_missing_conf_long_sleeps_and_exits_clean(self, tmp_path, allow_subprocess):
        # No conf → guard branch: log + sleep 3600 + exit 0 (no hot-loop,
        # never enters the update loop).
        proc, intervals = _run_wrapper(
            tmp_path,
            {"RESISTINE_FRESHCLAM_INTERVAL": "1"},
            freshclam_body='#!/bin/bash\nexit 0\n',
            conf_exists=False,
        )
        assert proc.returncode == 0
        # The only sleep recorded is the 3600s retry from the guard.
        assert intervals == [3600], f"intervals={intervals}"
        assert re.search(r"missing|retry", proc.stdout, re.I)
