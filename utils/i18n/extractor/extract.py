#!/usr/bin/env python3
"""
Collect native localization resources from Android, Apple, Windows and Linux
projects into one directory that can later be committed manually and connected
to Weblate.

The script deliberately performs no Git or GitHub operations.

Supported resource formats:
  Android:  .xml (strings.xml, plurals, string-array)
  Apple:    .xcstrings, .strings, .stringsdict
  Windows:  .resx
  Linux:    .po, .pot, Qt .ts
  Generic:  .json

Python: 3.11+
Dependencies: standard library only
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import logging
import os
import plistlib
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    print("Python 3.11 or newer is required (missing tomllib).", file=sys.stderr)
    raise SystemExit(1)


LOGGER = logging.getLogger("i18n-extract")

DEFAULT_PATTERNS: dict[str, tuple[str, ...]] = {
    "android": (
        "**/values*/strings*.xml",
    ),
    "apple": (
        "**/*.xcstrings",
        "**/*.lproj/*.strings",
        "**/*.lproj/*.stringsdict",
    ),
    "windows": (
        "**/*.resx",
    ),
    "linux": (
        "**/*.po",
        "**/*.pot",
        "**/*.ts",
    ),
    "generic": (
        "**/*.json",
    ),
}

SUPPORTED_PLATFORMS = frozenset(DEFAULT_PATTERNS)
SUPPORTED_SUFFIXES = frozenset(
    {".xml", ".xcstrings", ".strings", ".stringsdict", ".resx", ".po", ".pot", ".ts", ".json"}
)


class ExtractionError(RuntimeError):
    """Raised for invalid configuration or unsafe extraction operations."""


@dataclass(frozen=True)
class SourceConfig:
    name: str
    platform: str
    path: Path
    destination: Path
    include: tuple[str, ...]
    exclude: tuple[str, ...] = ()
    enabled: bool = True


@dataclass(frozen=True)
class AppConfig:
    config_path: Path
    output_dir: Path
    report_path: Path
    state_path: Path
    sources: tuple[SourceConfig, ...]


@dataclass
class ValidationResult:
    valid: bool = True
    string_count: int | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class PlannedFile:
    source_name: str
    platform: str
    source_path: Path
    destination_path: Path
    relative_source_path: Path
    sha256: str
    size_bytes: int
    status: str
    validation: ValidationResult

    def as_report_dict(self, root: Path) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "platform": self.platform,
            "source": display_path(self.source_path, root),
            "destination": display_path(self.destination_path, root),
            "relative_source_path": self.relative_source_path.as_posix(),
            "status": self.status,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "string_count": self.validation.string_count,
            "valid": self.validation.valid,
            "warnings": self.validation.warnings,
            "errors": self.validation.errors,
        }


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Collect localization files into a Weblate-ready directory. "
            "No Git commands are executed."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("i18n-extract.toml"),
        help="TOML configuration file (default: i18n-extract.toml)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Override project.output_dir from the configuration",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="Override project.report_path from the configuration",
    )
    parser.add_argument(
        "--source",
        action="append",
        dest="source_names",
        default=[],
        metavar="NAME",
        help="Process only the named source; may be repeated",
    )
    parser.add_argument(
        "--platform",
        action="append",
        choices=sorted(SUPPORTED_PLATFORMS),
        default=[],
        help="Process only this platform; may be repeated",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned changes without writing files or a report",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write files; exit with code 2 when changes are required",
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help=(
            "Remove files previously created by this tool that are no longer "
            "present in selected sources"
        ),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail when any localization file cannot be validated",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args(argv)


def load_config(config_path: Path, output_override: Path | None, report_override: Path | None) -> AppConfig:
    config_path = config_path.expanduser().resolve()
    if not config_path.is_file():
        raise ExtractionError(f"Configuration file not found: {config_path}")

    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)

    project = raw.get("project", {})
    if not isinstance(project, dict):
        raise ExtractionError("[project] must be a TOML table")

    config_dir = config_path.parent
    output_value = output_override or Path(str(project.get("output_dir", "locales")))
    report_value = report_override or Path(str(project.get("report_path", "build/i18n-extract-report.json")))
    state_value = Path(str(project.get("state_path", "build/i18n-extract-state.json")))

    output_dir = resolve_from(config_dir, output_value)
    report_path = resolve_from(config_dir, report_value)
    state_path = resolve_from(config_dir, state_value)

    raw_sources = raw.get("sources", [])
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ExtractionError("Configuration must contain at least one [[sources]] entry")

    seen_names: set[str] = set()
    sources: list[SourceConfig] = []

    for index, item in enumerate(raw_sources, start=1):
        if not isinstance(item, dict):
            raise ExtractionError(f"[[sources]] entry #{index} must be a table")

        name = require_string(item, "name", index)
        platform = require_string(item, "platform", index).lower()
        source_value = require_string(item, "path", index)
        destination_value = require_string(item, "destination", index)

        if name in seen_names:
            raise ExtractionError(f"Duplicate source name: {name}")
        seen_names.add(name)

        if platform not in SUPPORTED_PLATFORMS:
            allowed = ", ".join(sorted(SUPPORTED_PLATFORMS))
            raise ExtractionError(f"Unsupported platform '{platform}' in source '{name}'. Allowed: {allowed}")

        include = tuple(read_string_list(item, "include") or DEFAULT_PATTERNS[platform])
        exclude = tuple(read_string_list(item, "exclude"))
        enabled = item.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ExtractionError(f"'enabled' must be true or false in source '{name}'")

        source_path = resolve_from(config_dir, Path(source_value))
        destination = safe_relative_path(Path(destination_value), f"destination for source '{name}'")

        sources.append(
            SourceConfig(
                name=name,
                platform=platform,
                path=source_path,
                destination=destination,
                include=include,
                exclude=exclude,
                enabled=enabled,
            )
        )

    return AppConfig(
        config_path=config_path,
        output_dir=output_dir,
        report_path=report_path,
        state_path=state_path,
        sources=tuple(sources),
    )


def require_string(item: dict[str, Any], key: str, index: int) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ExtractionError(f"Missing or invalid '{key}' in [[sources]] entry #{index}")
    return value.strip()


def read_string_list(item: dict[str, Any], key: str) -> list[str]:
    value = item.get(key, [])
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(entry, str) and entry for entry in value):
        raise ExtractionError(f"'{key}' must be an array of non-empty strings")
    return value


def resolve_from(base: Path, value: Path) -> Path:
    value = value.expanduser()
    return value.resolve() if value.is_absolute() else (base / value).resolve()


def safe_relative_path(path: Path, label: str) -> Path:
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ExtractionError(f"Unsafe {label}: {path}")
    return path


def select_sources(config: AppConfig, names: Sequence[str], platforms: Sequence[str]) -> list[SourceConfig]:
    requested_names = set(names)
    requested_platforms = set(platforms)

    available_names = {source.name for source in config.sources}
    unknown_names = requested_names - available_names
    if unknown_names:
        raise ExtractionError(f"Unknown source name(s): {', '.join(sorted(unknown_names))}")

    selected = [
        source
        for source in config.sources
        if source.enabled
        and (not requested_names or source.name in requested_names)
        and (not requested_platforms or source.platform in requested_platforms)
    ]

    if not selected:
        raise ExtractionError("No enabled sources matched the selected filters")
    return selected


def discover_source_files(source: SourceConfig) -> list[tuple[Path, Path]]:
    if not source.path.exists():
        raise ExtractionError(f"Source path does not exist for '{source.name}': {source.path}")

    if source.path.is_file():
        relative = Path(source.path.name)
        if is_excluded(relative, source.exclude):
            return []
        return [(source.path, relative)]

    discovered: dict[Path, Path] = {}
    for pattern in source.include:
        for candidate in source.path.glob(pattern):
            if not candidate.is_file():
                continue
            relative = candidate.relative_to(source.path)
            if is_excluded(relative, source.exclude):
                continue
            discovered[candidate.resolve()] = relative

    return sorted(discovered.items(), key=lambda pair: pair[1].as_posix())


def is_excluded(relative: Path, patterns: Iterable[str]) -> bool:
    path = relative.as_posix()
    return any(fnmatch.fnmatch(path, pattern) or relative.match(pattern) for pattern in patterns)


def build_plan(config: AppConfig, sources: Sequence[SourceConfig]) -> list[PlannedFile]:
    plan: list[PlannedFile] = []
    destinations: dict[Path, Path] = {}

    for source in sources:
        files = discover_source_files(source)
        LOGGER.info("%s: found %d localization file(s)", source.name, len(files))

        for source_path, relative in files:
            destination_path = (config.output_dir / source.destination / relative).resolve()
            ensure_inside(config.output_dir, destination_path)

            previous_source = destinations.get(destination_path)
            if previous_source is not None:
                raise ExtractionError(
                    "Destination collision: "
                    f"{source_path} and {previous_source} both map to {destination_path}"
                )
            destinations[destination_path] = source_path

            content_hash = sha256_file(source_path)
            status = compare_status(source_path, destination_path, content_hash)
            validation = validate_resource(source.platform, source_path)

            plan.append(
                PlannedFile(
                    source_name=source.name,
                    platform=source.platform,
                    source_path=source_path,
                    destination_path=destination_path,
                    relative_source_path=relative,
                    sha256=content_hash,
                    size_bytes=source_path.stat().st_size,
                    status=status,
                    validation=validation,
                )
            )

    return sorted(plan, key=lambda item: item.destination_path.as_posix())


def compare_status(source: Path, destination: Path, source_hash: str) -> str:
    if not destination.exists():
        return "create"
    if not destination.is_file():
        raise ExtractionError(f"Destination exists but is not a file: {destination}")
    return "unchanged" if sha256_file(destination) == source_hash else "update"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_resource(platform: str, path: Path) -> ValidationResult:
    suffix = path.suffix.lower()
    try:
        if suffix == ".xcstrings":
            return validate_xcstrings(path)
        if suffix == ".strings":
            return validate_apple_strings(path)
        if suffix == ".stringsdict":
            return validate_stringsdict(path)
        if suffix == ".resx":
            return validate_resx(path)
        if suffix in {".po", ".pot"}:
            return validate_po(path)
        if suffix == ".ts":
            return validate_qt_ts(path)
        if suffix == ".json":
            return validate_json(path)
        if suffix == ".xml" and platform == "android":
            return validate_android_xml(path)

        result = ValidationResult()
        result.warnings.append(f"No validator registered for '{suffix or path.name}'")
        return result
    except (OSError, UnicodeError, ValueError, ET.ParseError, plistlib.InvalidFileException) as exc:
        return ValidationResult(valid=False, errors=[str(exc)])


def validate_android_xml(path: Path) -> ValidationResult:
    root = ET.parse(path).getroot()
    if root.tag != "resources":
        raise ValueError("Android resource root element must be <resources>")

    names: set[str] = set()
    duplicates: set[str] = set()
    count = 0
    for child in root:
        if child.tag not in {"string", "plurals", "string-array"}:
            continue
        name = child.attrib.get("name")
        if not name:
            continue
        count += 1
        if name in names:
            duplicates.add(name)
        names.add(name)

    result = ValidationResult(string_count=count)
    if duplicates:
        result.valid = False
        result.errors.append("Duplicate resource names: " + ", ".join(sorted(duplicates)))
    return result


def validate_xcstrings(path: Path) -> ValidationResult:
    data = read_json(path)
    strings = data.get("strings")
    if not isinstance(strings, dict):
        raise ValueError("XCStrings file must contain an object named 'strings'")
    return ValidationResult(string_count=len(strings))


def validate_apple_strings(path: Path) -> ValidationResult:
    text = read_text_with_bom(path)
    # Remove block and line comments before counting key/value assignments.
    without_comments = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    without_comments = re.sub(r"//[^\r\n]*", "", without_comments)
    entries = re.findall(
        r'(?m)^\s*(?:"(?:\\.|[^"\\])*"|[A-Za-z0-9_.-]+)\s*=\s*"(?:\\.|[^"\\])*"\s*;',
        without_comments,
    )
    result = ValidationResult(string_count=len(entries))
    if not entries and without_comments.strip():
        result.warnings.append("No standard key/value entries were detected")
    return result


def validate_stringsdict(path: Path) -> ValidationResult:
    with path.open("rb") as handle:
        data = plistlib.load(handle)
    if not isinstance(data, dict):
        raise ValueError("Stringsdict root must be a dictionary")
    return ValidationResult(string_count=len(data))


def validate_resx(path: Path) -> ValidationResult:
    root = ET.parse(path).getroot()
    data_nodes = root.findall("data")
    names: set[str] = set()
    duplicates: set[str] = set()
    count = 0
    for node in data_nodes:
        name = node.attrib.get("name")
        if not name:
            continue
        count += 1
        if name in names:
            duplicates.add(name)
        names.add(name)

    result = ValidationResult(string_count=count)
    if duplicates:
        result.valid = False
        result.errors.append("Duplicate resource names: " + ", ".join(sorted(duplicates)))
    return result


def validate_po(path: Path) -> ValidationResult:
    text = read_text_with_bom(path)
    count = 0
    fuzzy = 0
    current_fuzzy = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#,") and any(part.strip() == "fuzzy" for part in stripped.split(",")):
            current_fuzzy = True
        elif stripped.startswith("msgid "):
            value = stripped[6:].strip()
            if value != '""':
                count += 1
                if current_fuzzy:
                    fuzzy += 1
            current_fuzzy = False

    result = ValidationResult(string_count=count)
    if fuzzy:
        result.warnings.append(f"Contains {fuzzy} fuzzy translation(s)")
    return result


def validate_qt_ts(path: Path) -> ValidationResult:
    root = ET.parse(path).getroot()
    if root.tag != "TS":
        raise ValueError("Qt translation file root element must be <TS>")
    return ValidationResult(string_count=len(root.findall(".//message")))


def validate_json(path: Path) -> ValidationResult:
    data = read_json(path)
    return ValidationResult(string_count=count_json_strings(data))


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def count_json_strings(value: Any) -> int:
    if isinstance(value, str):
        return 1
    if isinstance(value, dict):
        return sum(count_json_strings(item) for item in value.values())
    if isinstance(value, list):
        return sum(count_json_strings(item) for item in value)
    return 0


def read_text_with_bom(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    return raw.decode("utf-8")


def execute_plan(plan: Sequence[PlannedFile], dry_run: bool) -> None:
    for item in plan:
        if item.status == "unchanged":
            LOGGER.debug("unchanged: %s", item.destination_path)
            continue

        action = "would create" if dry_run and item.status == "create" else None
        if dry_run and item.status == "update":
            action = "would update"
        if action:
            LOGGER.info("%s: %s", action, item.destination_path)
            continue

        atomic_copy(item.source_path, item.destination_path)
        LOGGER.info("%s: %s", item.status, item.destination_path)


def atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_name = handle.name
            with source.open("rb") as source_handle:
                shutil.copyfileobj(source_handle, handle)
            handle.flush()
            os.fsync(handle.fileno())

        source_mode = source.stat().st_mode & 0o777
        os.chmod(temp_name, source_mode)
        os.replace(temp_name, destination)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def load_state(state_path: Path, output_dir: Path) -> dict[str, set[Path]]:
    if not state_path.is_file():
        return {}

    try:
        with state_path.open("r", encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ExtractionError(f"Cannot read extraction state: {exc}") from exc

    raw_sources = state.get("sources", {})
    if not isinstance(raw_sources, dict):
        raise ExtractionError("Invalid extraction state: 'sources' must be an object")

    loaded: dict[str, set[Path]] = {}
    for source_name, entries in raw_sources.items():
        if not isinstance(source_name, str) or not isinstance(entries, list):
            continue
        paths: set[Path] = set()
        for entry in entries:
            if not isinstance(entry, str):
                continue
            relative = safe_relative_path(Path(entry), f"state path for source '{source_name}'")
            candidate = (output_dir / relative).resolve()
            ensure_inside(output_dir, candidate)
            paths.add(candidate)
        loaded[source_name] = paths
    return loaded


def write_state(
    state_path: Path,
    output_dir: Path,
    state: dict[str, set[Path]],
) -> None:
    payload = {
        "schema_version": 1,
        "output_dir": str(output_dir),
        "sources": {
            source_name: sorted(
                path.resolve().relative_to(output_dir.resolve()).as_posix()
                for path in paths
            )
            for source_name, paths in sorted(state.items())
        },
    }

    state_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = state_path.with_name(f".{state_path.name}.tmp")
    try:
        with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, state_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def prune_outputs(
    previous_state: dict[str, set[Path]],
    current_by_source: dict[str, set[Path]],
    selected_source_names: Sequence[str],
    output_dir: Path,
    dry_run: bool,
) -> list[Path]:
    stale: list[Path] = []
    for source_name in selected_source_names:
        previous = previous_state.get(source_name, set())
        current = current_by_source.get(source_name, set())
        stale.extend(previous - current)

    stale = sorted(set(stale))
    for path in stale:
        ensure_inside(output_dir, path)
        if dry_run:
            LOGGER.info("would remove: %s", path)
            continue
        if path.is_file() or path.is_symlink():
            path.unlink()
            remove_empty_parents(path.parent, output_dir)
            LOGGER.info("remove: %s", path)
    return stale


def remove_empty_parents(directory: Path, stop: Path) -> None:
    stop = stop.resolve()
    current = directory.resolve()
    while current != stop and is_within(stop, current):
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def ensure_inside(root: Path, candidate: Path) -> None:
    if not is_within(root.resolve(), candidate.resolve()):
        raise ExtractionError(f"Path escapes output directory: {candidate}")


def is_within(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def display_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def summarize(plan: Sequence[PlannedFile], removed: Sequence[Path]) -> dict[str, int]:
    summary = {
        "files": len(plan),
        "create": 0,
        "update": 0,
        "unchanged": 0,
        "removed": len(removed),
        "invalid": 0,
        "strings": 0,
    }
    for item in plan:
        summary[item.status] += 1
        if not item.validation.valid:
            summary["invalid"] += 1
        if item.validation.string_count is not None:
            summary["strings"] += item.validation.string_count
    return summary


def write_report(
    config: AppConfig,
    selected_sources: Sequence[SourceConfig],
    plan: Sequence[PlannedFile],
    removed: Sequence[Path],
) -> None:
    project_root = config.config_path.parent
    summary = summarize(plan, removed)
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config": display_path(config.config_path, project_root),
        "output_dir": display_path(config.output_dir, project_root),
        "git_operations": False,
        "sources": [
            {
                "name": source.name,
                "platform": source.platform,
                "path": display_path(source.path, project_root),
                "destination": source.destination.as_posix(),
            }
            for source in selected_sources
        ],
        "summary": summary,
        "files": [item.as_report_dict(project_root) for item in plan],
        "removed": [display_path(path, project_root) for path in removed],
    }

    config.report_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = config.report_path.with_name(f".{config.report_path.name}.tmp")
    try:
        with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, config.report_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def log_validation(plan: Sequence[PlannedFile]) -> None:
    for item in plan:
        for warning in item.validation.warnings:
            LOGGER.warning("%s: %s", item.source_path, warning)
        for error in item.validation.errors:
            LOGGER.error("%s: %s", item.source_path, error)


def log_summary(summary: dict[str, int], dry_run: bool) -> None:
    prefix = "Planned" if dry_run else "Completed"
    LOGGER.info(
        "%s: %d file(s), %d create, %d update, %d unchanged, %d removed, %d string(s), %d invalid",
        prefix,
        summary["files"],
        summary["create"],
        summary["update"],
        summary["unchanged"],
        summary["removed"],
        summary["strings"],
        summary["invalid"],
    )
    LOGGER.info("Git operations: disabled")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging(args.verbose)

    if args.dry_run and args.check:
        LOGGER.error("Use either --dry-run or --check, not both")
        return 1

    readonly = args.dry_run or args.check

    try:
        config = load_config(args.config, args.output, args.report)
        selected_sources = select_sources(config, args.source_names, args.platform)
        plan = build_plan(config, selected_sources)
        log_validation(plan)

        invalid_count = sum(not item.validation.valid for item in plan)
        if args.strict and invalid_count:
            LOGGER.error("Strict validation failed for %d file(s); nothing was written", invalid_count)
            return 1

        previous_state = load_state(config.state_path, config.output_dir)
        current_by_source: dict[str, set[Path]] = {source.name: set() for source in selected_sources}
        for item in plan:
            current_by_source.setdefault(item.source_name, set()).add(item.destination_path)

        selected_source_names = [source.name for source in selected_sources]
        removed = prune_outputs(
            previous_state=previous_state,
            current_by_source=current_by_source,
            selected_source_names=selected_source_names,
            output_dir=config.output_dir,
            dry_run=readonly,
        ) if args.prune else []

        execute_plan(plan, dry_run=readonly)
        summary = summarize(plan, removed)
        log_summary(summary, dry_run=readonly)

        changes_required = summary["create"] + summary["update"] + summary["removed"] > 0
        if args.check:
            return 2 if changes_required else 0
        if args.dry_run:
            return 0

        write_report(config, selected_sources, plan, removed)

        next_state = {name: set(paths) for name, paths in previous_state.items()}
        for source_name in selected_source_names:
            current = current_by_source.get(source_name, set())
            if args.prune:
                next_state[source_name] = set(current)
            else:
                next_state[source_name] = next_state.get(source_name, set()) | set(current)
        write_state(config.state_path, config.output_dir, next_state)

        LOGGER.info("Report: %s", config.report_path)
        LOGGER.info("State: %s", config.state_path)
        return 0

    except ExtractionError as exc:
        LOGGER.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        LOGGER.error("Interrupted")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
