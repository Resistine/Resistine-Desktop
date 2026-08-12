## @file restic_service.py
## @namespace plugins.backup
"""Cross-platform Restic engine.

Restic is a single self-contained binary that behaves identically on Linux,
macOS and Windows, which is exactly why it was chosen for this plugin. This
module is the thin, UI-agnostic wrapper the Backup plugin drives:

  * locate / validate the ``restic`` binary,
  * build the environment a call needs (repository + password), and
  * run each operation as a subprocess, preferring restic's ``--json`` output
    so results parse deterministically.

Nothing here touches Qt — the plugin's ``main.py`` owns threading and the UI.
On Windows every subprocess is already forced to ``CREATE_NO_WINDOW`` by
``utils.win_console``, so no console flashes here.

Author: the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from utils.logger import logger
from utils.settings import get_config_dir

_IS_WINDOWS = platform.system() == "Windows"
_BINARY_NAME = "restic.exe" if _IS_WINDOWS else "restic"

# Namespace/key under which a user-chosen restic path override may be stored.
_SETTINGS_NS = "backup"
_SETTINGS_BINARY_KEY = "restic_path"


class ResticError(RuntimeError):
    """A restic invocation failed. Carries the process' stderr for the UI."""

    def __init__(self, message: str, *, returncode: int | None = None,
                 stderr: str = ""):
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr


@dataclass
class ResticResult:
    """Outcome of a restic call. ``json`` is populated for ``--json`` calls."""

    returncode: int
    stdout: str = ""
    stderr: str = ""
    json: Any = None

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@dataclass
class Repository:
    """A restic repository target the plugin can operate on.

    ``location`` is a restic repository string: a local path, ``sftp:user@host:/path``,
    ``s3:...``, ``b2:...``, ``azure:...``, etc. The password is passed via the
    environment at call time and is NEVER placed on the command line.
    """

    location: str
    password: str = ""
    # Extra backend credentials (e.g. AWS_ACCESS_KEY_ID) merged into env.
    env: dict[str, str] = field(default_factory=dict)


def _bundled_dir() -> str:
    """Directory where a bundled restic binary would ship (next to this file's
    plugin), and the per-user fallback where an auto-download would land."""
    return os.path.dirname(os.path.realpath(__file__))


def _user_bin_dir() -> str:
    return os.path.join(get_config_dir(), "bin")


class ResticService:
    """Stateless-ish wrapper around the restic binary.

    A single instance is fine to reuse; it caches the resolved binary path but
    re-resolves on demand if the cache is cleared (``forget_binary``).
    """

    def __init__(self) -> None:
        self._binary: Optional[str] = None

    # ---- Binary resolution ------------------------------------------------
    def resolve_binary(self) -> Optional[str]:
        """Return an absolute path to a usable restic binary, or None.

        Search order: explicit settings override → PATH → bundled with the
        plugin → per-user bin dir (auto-download target). The result is cached.
        """
        if self._binary and os.path.isfile(self._binary):
            return self._binary

        candidates: list[str] = []

        # 1. Explicit user override from settings.
        try:
            from utils import settings
            override = settings.get(_SETTINGS_NS, _SETTINGS_BINARY_KEY, None)
            if override:
                candidates.append(override)
        except Exception as e:  # settings must never block detection
            logger.debug(f"restic: settings override lookup failed: {e}")

        # 2. On PATH.
        on_path = shutil.which("restic")
        if on_path:
            candidates.append(on_path)

        # 3. Bundled next to the plugin, and 4. per-user bin dir.
        candidates.append(os.path.join(_bundled_dir(), _BINARY_NAME))
        candidates.append(os.path.join(_user_bin_dir(), _BINARY_NAME))

        for path in candidates:
            if path and os.path.isfile(path):
                self._binary = path
                logger.info(f"restic: using binary at {path}")
                return path

        logger.info("restic: no binary found on this system")
        return None

    def forget_binary(self) -> None:
        """Drop the cached binary path (call after an install/override change)."""
        self._binary = None

    def is_available(self) -> bool:
        return self.resolve_binary() is not None

    def version(self) -> Optional[str]:
        """Return the restic version string (e.g. ``0.17.3``) or None if the
        binary is missing or unresponsive."""
        binary = self.resolve_binary()
        if not binary:
            return None
        try:
            res = self._run(["version"], timeout=15)
        except ResticError as e:
            logger.warning(f"restic version probe failed: {e}")
            return None
        # Output looks like: "restic 0.17.3 compiled with go1.23 on windows/amd64"
        parts = res.stdout.split()
        if len(parts) >= 2 and parts[0] == "restic":
            return parts[1]
        return res.stdout.strip() or None

    # ---- Repository operations -------------------------------------------
    def init(self, repo: Repository) -> ResticResult:
        """Create a new repository at ``repo.location``."""
        return self._run(["init"], repo=repo)

    def check(self, repo: Repository) -> ResticResult:
        """Verify repository integrity."""
        return self._run(["check"], repo=repo)

    def snapshots(self, repo: Repository) -> ResticResult:
        """List snapshots (parsed JSON in ``.json``)."""
        return self._run(["snapshots"], repo=repo, want_json=True)

    def snapshot_list(self, repo: Repository) -> list[dict]:
        """Convenience: return the snapshots array (newest first), or []."""
        res = self.snapshots(repo)
        snaps = res.json if isinstance(res.json, list) else []
        # restic already returns oldest→newest; present newest first.
        return list(reversed(snaps))

    def tree_mtimes(self, repo: Repository, snapshot_id: str,
                    wanted: set[str]) -> dict[str, str]:
        """Return ``{tree_path: mtime_iso}`` for the nodes in *wanted*.

        ``restic ls --long --json`` streams one JSON object per line (ndjson),
        each carrying the node's tree ``path`` and ``mtime`` — the source time
        the restore tried (and, for locked system dirs, failed) to apply.
        """
        res = self._run(["ls", "--long", "--json", snapshot_id], repo=repo)
        out: dict[str, str] = {}
        for line in res.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                node = json.loads(line)
            except json.JSONDecodeError:
                continue
            path = node.get("path")
            if path in wanted and path not in out:
                out[path] = node.get("mtime", "")
                if len(out) == len(wanted):
                    break
        return out

    def stats(self, repo: Repository, mode: str = "raw-data") -> ResticResult:
        """Repository stats (JSON in ``.json``).

        ``raw-data`` reports the deduplicated/compressed size actually stored
        (the repo's on-disk footprint); ``restore-size`` reports the logical
        size needed to restore.
        """
        return self._run(["stats", "--mode", mode], repo=repo, want_json=True)

    def backup(self, repo: Repository, paths: list[str],
               *, excludes: Optional[list[str]] = None,
               tags: Optional[list[str]] = None,
               on_progress: Optional[Callable[[dict], None]] = None) -> ResticResult:
        """Back up ``paths`` into the repository.

        With ``on_progress`` set, restic is run with ``--json`` and each status
        line is decoded and forwarded (status / summary messages) so the UI can
        show live progress.
        """
        args = ["backup", *paths]
        for ex in (excludes or []):
            args += ["--exclude", ex]
        for tag in (tags or []):
            args += ["--tag", tag]
        if on_progress is not None:
            return self._run_streaming(args, repo=repo, on_json=on_progress)
        return self._run(args, repo=repo, want_json=True)

    def restore(self, repo: Repository, snapshot_id: str, target: str,
                *, include: Optional[list[str]] = None) -> ResticResult:
        """Restore ``snapshot_id`` into ``target`` directory."""
        args = ["restore", snapshot_id, "--target", target]
        for inc in (include or []):
            args += ["--include", inc]
        return self._run(args, repo=repo)

    def forget(self, repo: Repository, *, keep_daily: int = 0,
               keep_weekly: int = 0, keep_monthly: int = 0,
               prune: bool = True) -> ResticResult:
        """Apply a retention policy, optionally pruning freed data."""
        args = ["forget"]
        if keep_daily:
            args += ["--keep-daily", str(keep_daily)]
        if keep_weekly:
            args += ["--keep-weekly", str(keep_weekly)]
        if keep_monthly:
            args += ["--keep-monthly", str(keep_monthly)]
        if prune:
            args.append("--prune")
        return self._run(args, repo=repo)

    # ---- Subprocess plumbing ---------------------------------------------
    def _env(self, repo: Optional[Repository]) -> dict[str, str]:
        env = dict(os.environ)
        if repo is not None:
            env["RESTIC_REPOSITORY"] = repo.location
            env["RESTIC_PASSWORD"] = repo.password
            env.update(repo.env)
        return env

    def _run(self, args: list[str], *, repo: Optional[Repository] = None,
             want_json: bool = False, timeout: Optional[int] = None) -> ResticResult:
        """Run restic to completion and return a ResticResult.

        Raises ResticError when the binary is missing or the process cannot be
        launched; a non-zero exit is returned as a ResticResult (with stderr)
        rather than raised, so callers can surface restic's own message.
        """
        binary = self.resolve_binary()
        if not binary:
            raise ResticError("restic binary not found")

        cmd = [binary]
        if want_json:
            cmd.append("--json")
        cmd += args

        try:
            proc = subprocess.run(
                cmd, env=self._env(repo), capture_output=True, text=True,
                timeout=timeout,
            )
        except FileNotFoundError as e:
            raise ResticError(f"could not launch restic: {e}") from e
        except subprocess.TimeoutExpired as e:
            raise ResticError(f"restic timed out after {timeout}s",
                              stderr=str(e)) from e

        parsed: Any = None
        if want_json and proc.stdout.strip():
            try:
                parsed = json.loads(proc.stdout)
            except json.JSONDecodeError:
                # Some commands emit newline-delimited JSON; keep raw on failure.
                logger.debug("restic: --json output was not a single object")

        return ResticResult(proc.returncode, proc.stdout, proc.stderr, parsed)

    def _run_streaming(self, args: list[str], *, repo: Repository,
                       on_json: Callable[[dict], None]) -> ResticResult:
        """Run restic with ``--json`` and forward each decoded line to
        ``on_json`` as it arrives. Returns the final aggregate result."""
        binary = self.resolve_binary()
        if not binary:
            raise ResticError("restic binary not found")

        cmd = [binary, "--json", *args]
        proc = subprocess.Popen(
            cmd, env=self._env(repo), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1,
        )
        last: dict = {}
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            last = msg
            try:
                on_json(msg)
            except Exception as e:  # a UI callback must not kill the backup
                logger.error(f"restic progress callback error: {e}")
        stderr = proc.stderr.read() if proc.stderr else ""
        rc = proc.wait()
        return ResticResult(rc, "", stderr, last)
