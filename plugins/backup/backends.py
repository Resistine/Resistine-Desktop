## @file backends.py
## @namespace plugins.backup
"""Restic backend descriptors.

Restic addresses every storage target with a single *repository location*
string and, for cloud targets, a handful of credential environment variables.
This module describes each supported backend declaratively so the UI can render
its form generically and the repo store can turn the collected values into a
location string + credential env for the engine.

Field kinds:
  * ``location`` fields build the ``RESTIC_REPOSITORY`` string (not secret).
  * ``secret`` fields are credentials — stored encrypted and injected as env
    vars at call time, never written to the location or the command line.

Adding a backend is just adding an entry here; no UI changes required.

Author: the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class Field:
    key: str                 # identifier used in the values dict
    label: str               # UI label
    placeholder: str = ""    # UI hint / example
    secret: bool = False     # stored encrypted + rendered masked
    required: bool = True
    env: str = ""            # for secret fields: the env var restic reads


@dataclass(frozen=True)
class Backend:
    key: str
    label: str
    # Fields that feed the location string.
    location_fields: list[Field]
    # Credential fields injected into the environment (all secret).
    secret_fields: list[Field]
    # values(dict) -> RESTIC_REPOSITORY string.
    build_location: Callable[[dict], str]
    help: str = ""

    def all_fields(self) -> list[Field]:
        return [*self.location_fields, *self.secret_fields]


def _local_loc(v: dict) -> str:
    return (v.get("path") or "").strip()


def _sftp_loc(v: dict) -> str:
    user = (v.get("user") or "").strip()
    host = (v.get("host") or "").strip()
    path = (v.get("path") or "").strip()
    prefix = f"{user}@{host}" if user else host
    return f"sftp:{prefix}:{path}"


def _s3_loc(v: dict) -> str:
    endpoint = (v.get("endpoint") or "s3.amazonaws.com").strip()
    endpoint = endpoint.replace("https://", "").replace("http://", "")
    bucket = (v.get("bucket") or "").strip()
    path = (v.get("path") or "").strip().strip("/")
    base = f"s3:{endpoint}/{bucket}"
    return f"{base}/{path}" if path else base


def _b2_loc(v: dict) -> str:
    bucket = (v.get("bucket") or "").strip()
    path = (v.get("path") or "").strip().strip("/")
    return f"b2:{bucket}:{path}" if path else f"b2:{bucket}:"


def _azure_loc(v: dict) -> str:
    container = (v.get("container") or "").strip()
    path = (v.get("path") or "").strip().strip("/")
    return f"azure:{container}:{path}" if path else f"azure:{container}:"


BACKENDS: list[Backend] = [
    Backend(
        key="local",
        label="Local folder",
        location_fields=[
            Field("path", "Folder", placeholder="e.g. D:\\Backups\\resistine"),
        ],
        secret_fields=[],
        build_location=_local_loc,
        help="A folder on this computer or an attached/USB drive.",
    ),
    Backend(
        key="sftp",
        label="SFTP / SSH",
        location_fields=[
            Field("user", "User", placeholder="username", required=False),
            Field("host", "Host", placeholder="backup.example.com"),
            Field("path", "Remote path", placeholder="/srv/restic/repo"),
        ],
        secret_fields=[],
        build_location=_sftp_loc,
        help="A server reachable over SSH. Uses your SSH keys/agent for auth.",
    ),
    Backend(
        key="s3",
        label="Amazon S3 (or compatible)",
        location_fields=[
            Field("endpoint", "Endpoint", placeholder="s3.amazonaws.com",
                  required=False),
            Field("bucket", "Bucket", placeholder="my-backup-bucket"),
            Field("path", "Path (optional)", placeholder="hostname/repo",
                  required=False),
        ],
        secret_fields=[
            Field("access_key", "Access key ID", secret=True,
                  env="AWS_ACCESS_KEY_ID"),
            Field("secret_key", "Secret access key", secret=True,
                  env="AWS_SECRET_ACCESS_KEY"),
        ],
        build_location=_s3_loc,
        help="Amazon S3 or any S3-compatible service (MinIO, Wasabi, …).",
    ),
    Backend(
        key="b2",
        label="Backblaze B2",
        location_fields=[
            Field("bucket", "Bucket", placeholder="my-backup-bucket"),
            Field("path", "Path (optional)", placeholder="hostname/repo",
                  required=False),
        ],
        secret_fields=[
            Field("account_id", "Account ID / keyID", secret=True,
                  env="B2_ACCOUNT_ID"),
            Field("account_key", "Application key", secret=True,
                  env="B2_ACCOUNT_KEY"),
        ],
        build_location=_b2_loc,
        help="Backblaze B2 cloud storage.",
    ),
    Backend(
        key="azure",
        label="Azure Blob Storage",
        location_fields=[
            Field("container", "Container", placeholder="backups"),
            Field("path", "Path (optional)", placeholder="hostname/repo",
                  required=False),
        ],
        secret_fields=[
            Field("account_name", "Account name", secret=True,
                  env="AZURE_ACCOUNT_NAME"),
            Field("account_key", "Account key", secret=True,
                  env="AZURE_ACCOUNT_KEY"),
        ],
        build_location=_azure_loc,
        help="Microsoft Azure Blob Storage.",
    ),
]

_BY_KEY = {b.key: b for b in BACKENDS}


def get_backend(key: str) -> Backend | None:
    return _BY_KEY.get(key)
