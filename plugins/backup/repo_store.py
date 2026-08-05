## @file repo_store.py
## @namespace plugins.backup
"""Persistence for configured backup repositories.

Non-secret metadata (name, backend, location field values) lives in the
``backup`` settings namespace as a JSON list. Every credential — the repository
password and any backend keys (AWS/B2/Azure) — is stored separately via
``settings.set_secret`` so it is Fernet-encrypted at rest (``ENC:`` prefix) and
never appears in the plain config.

At call time ``resolve`` re-hydrates a repo into an engine ``Repository``
(location string + password + credential env), pulling the secrets back out.

Author: the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

from __future__ import annotations

import uuid

from utils import settings

from plugins.backup.backends import get_backend
from plugins.backup.restic_service import Repository

_NS = "backup"
_REPOS_KEY = "repositories"


def _secret_key(repo_id: str, field_key: str) -> str:
    return f"{repo_id}.{field_key}"


def list_repos() -> list[dict]:
    """Return stored repo metadata (no secrets). Each dict has id/name/backend/
    location_values and the derived display location."""
    repos = settings.get(_NS, _REPOS_KEY, []) or []
    return list(repos)


def get_repo(repo_id: str) -> dict | None:
    return next((r for r in list_repos() if r.get("id") == repo_id), None)


def build_location(backend_key: str, location_values: dict) -> str:
    backend = get_backend(backend_key)
    if backend is None:
        raise ValueError(f"unknown backend: {backend_key}")
    return backend.build_location(location_values)


def build_repository(backend_key: str, location_values: dict,
                     secret_values: dict, password: str) -> Repository:
    """Assemble a transient engine Repository from raw form values.

    Used to run ``init`` / ``check`` before the repo is persisted. Maps each
    backend secret field to the environment variable restic expects.
    """
    backend = get_backend(backend_key)
    if backend is None:
        raise ValueError(f"unknown backend: {backend_key}")
    env: dict[str, str] = {}
    for f in backend.secret_fields:
        val = (secret_values.get(f.key) or "").strip()
        if val and f.env:
            env[f.env] = val
    return Repository(
        location=backend.build_location(location_values),
        password=password,
        env=env,
    )


def add_repo(name: str, backend_key: str, location_values: dict,
             secret_values: dict, password: str) -> str:
    """Persist a repository and its secrets. Returns the new repo id."""
    backend = get_backend(backend_key)
    if backend is None:
        raise ValueError(f"unknown backend: {backend_key}")

    repo_id = uuid.uuid4().hex[:12]
    meta = {
        "id": repo_id,
        "name": name.strip() or backend.build_location(location_values),
        "backend": backend_key,
        "location_values": location_values,
        "location": backend.build_location(location_values),
    }
    repos = list_repos()
    repos.append(meta)
    settings.set(_NS, _REPOS_KEY, repos)

    # Secrets: repo password + each backend credential, encrypted at rest.
    settings.set_secret(_NS, _secret_key(repo_id, "password"), password)
    for f in backend.secret_fields:
        val = (secret_values.get(f.key) or "").strip()
        if val:
            settings.set_secret(_NS, _secret_key(repo_id, f.key), val)
    return repo_id


def get_backup_spec(repo_id: str) -> tuple[list[str], list[str]]:
    """Return ``(paths, excludes)`` the user last chose for this repo."""
    meta = get_repo(repo_id) or {}
    return list(meta.get("backup_paths", [])), list(meta.get("excludes", []))


def set_backup_spec(repo_id: str, paths: list[str], excludes: list[str]) -> None:
    """Persist the paths + excludes to back up for this repo."""
    repos = list_repos()
    for r in repos:
        if r.get("id") == repo_id:
            r["backup_paths"] = list(paths)
            r["excludes"] = list(excludes)
    settings.set(_NS, _REPOS_KEY, repos)


def get_retention(repo_id: str) -> dict:
    """Return the ``{keep_daily, keep_weekly, keep_monthly}`` policy (ints)."""
    meta = get_repo(repo_id) or {}
    r = meta.get("retention", {}) or {}
    return {
        "keep_daily": int(r.get("keep_daily", 0) or 0),
        "keep_weekly": int(r.get("keep_weekly", 0) or 0),
        "keep_monthly": int(r.get("keep_monthly", 0) or 0),
    }


def set_retention(repo_id: str, keep_daily: int, keep_weekly: int,
                  keep_monthly: int) -> None:
    repos = list_repos()
    for r in repos:
        if r.get("id") == repo_id:
            r["retention"] = {
                "keep_daily": int(keep_daily),
                "keep_weekly": int(keep_weekly),
                "keep_monthly": int(keep_monthly),
            }
    settings.set(_NS, _REPOS_KEY, repos)


def remove_repo(repo_id: str) -> None:
    """Forget a repository from the app's config. Does NOT delete the actual
    repository data at the storage target — only our stored config + secrets."""
    meta = get_repo(repo_id)
    repos = [r for r in list_repos() if r.get("id") != repo_id]
    settings.set(_NS, _REPOS_KEY, repos)

    settings.delete(_NS, _secret_key(repo_id, "password"))
    if meta:
        backend = get_backend(meta.get("backend", ""))
        if backend:
            for f in backend.secret_fields:
                settings.delete(_NS, _secret_key(repo_id, f.key))


def resolve(repo_id: str) -> Repository:
    """Re-hydrate a persisted repo into an engine Repository (with secrets)."""
    meta = get_repo(repo_id)
    if meta is None:
        raise KeyError(f"no such repository: {repo_id}")
    backend = get_backend(meta["backend"])
    if backend is None:
        raise ValueError(f"unknown backend: {meta['backend']}")

    password = settings.get_secret(_NS, _secret_key(repo_id, "password")) or ""
    env: dict[str, str] = {}
    for f in backend.secret_fields:
        val = settings.get_secret(_NS, _secret_key(repo_id, f.key))
        if val and f.env:
            env[f.env] = val
    return Repository(
        location=meta.get("location") or backend.build_location(
            meta.get("location_values", {})),
        password=password,
        env=env,
    )
