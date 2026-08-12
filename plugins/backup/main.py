## @file main.py
## @namespace plugins.backup
"""Backup plugin (PyQt6) — a cross-platform Restic frontend.

Restic is the backup engine: one self-contained binary that behaves identically
on Linux, macOS and Windows, with AES-256 encryption and block-level dedup. This
plugin is a desktop GUI over it (in the spirit of BackRest): detect/manage the
binary, configure encrypted repositories (local or cloud), run backups, browse
snapshots, and restore — all without the user touching a terminal.

Layering:
  * ``restic_service.py``  — no-Qt engine wrapper (subprocess + JSON).
  * ``restic_installer.py``— auto-download + verify the restic binary.
  * ``backends.py``        — declarative storage-backend descriptors.
  * ``repo_store.py``      — persistence (config + encrypted secrets).
  * this file              — the UI; threads every long restic call.

Phase 1: binary detection + status.  Phase 2a: auto-install.  Phase 2b (here):
repository configuration (local + cloud) with ``init`` / open.

Author: the Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""

from __future__ import annotations

import os
import platform
import re
import threading

from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui import theme
from gui.qt_widgets import StatusBadge, centered, heading, muted, scroll_page
from plugins.backup import backends, repo_store, restic_installer, win_timestamps
from plugins.backup.restic_service import ResticError, ResticService
from plugins.base_plugin import BasePlugin
from utils.logger import logger

_DIR = os.path.dirname(os.path.realpath(__file__))
_IS_WINDOWS = platform.system() == "Windows"


def _parse_failed_timestamp_paths(stderr: str) -> list[str]:
    """Extract the directory paths restic couldn't set a timestamp on.

    Lines look like: ``… failed to restore timestamp of "C:\\a\\b": Access is
    denied.`` — the quoted path has doubled backslashes, which we unescape.
    """
    paths = []
    for m in re.finditer(r'failed to restore timestamp of "([^"]+)"', stderr):
        paths.append(m.group(1).replace("\\\\", "\\"))
    return paths


def _iso_to_epoch(iso: str) -> float | None:
    """Parse a restic RFC3339 mtime to epoch seconds, or None."""
    if not iso:
        return None
    try:
        s = iso.replace("Z", "+00:00")
        # fromisoformat accepts at most microseconds; trim extra digits.
        s = re.sub(r"(\.\d{6})\d+", r"\1", s)
        return datetime.fromisoformat(s).timestamp()
    except (ValueError, TypeError):
        return None


def _fmt_time(iso: str) -> str:
    """Format a restic snapshot timestamp (RFC3339) as a short local string."""
    if not iso:
        return "—"
    try:
        # restic emits e.g. 2026-01-12T17:20:03.123456-05:00
        cleaned = iso.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return iso[:16]


def _restore_errors_benign(stderr: str) -> bool:
    """True when a non-zero restore only hit ignorable metadata errors.

    On Windows, restic often can't set timestamps/permissions on directories it
    synthesises under the restore target (``Access is denied``) and exits 1 with
    "ignoring error … failed to restore timestamp" lines — the file *data* is
    still fully restored. Treat those as a warning, not a failure.
    """
    lines = [ln.strip() for ln in stderr.splitlines() if ln.strip()]
    if not lines:
        return False

    def benign(ln: str) -> bool:
        low = ln.lower()
        return ("failed to restore timestamp" in low
                or "ignoring error" in low
                or low.startswith("fatal: there were"))

    return all(benign(ln) for ln in lines)


def _fmt_bytes(n) -> str:
    try:
        n = float(n)
    except (ValueError, TypeError):
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


class _NoScrollComboBox(QComboBox):
    """A combo box that ignores wheel events (mirrors the settings plugin) so
    scrolling the page doesn't accidentally change the selected backend."""

    def wheelEvent(self, event):  # noqa: N802 (Qt override)
        event.ignore()


class Plugin(BasePlugin):
    """Backup — encrypted, deduplicated backups via Restic."""

    def __init__(self, app):
        super().__init__(
            id="013",
            version="2025.01.01",
            order=7,  # after Antivirus (6) in the sidebar
            name="Backup",
            status=None,
            description="Encrypted, deduplicated backups powered by Restic.",
            supported_systems=["Windows", "Darwin", "Linux"],
            translations={"US": "Backup", "ES": "Copia", "FR": "Sauvegarde"},
            icon_light_path=os.path.join(_DIR, "backup_light.png"),
            icon_dark_path=os.path.join(_DIR, "backup_dark.png"),
        )
        self.app = app
        self.restic = ResticService()
        # Cheap cached facts refreshed by the async probe; check_status reads
        # these so the sidebar badge never triggers a subprocess on the UI thread.
        self._restic_version: str | None = None
        self._probed = False
        self._installing = False
        # Widgets bound in create_main_screen.
        self._status_badge: StatusBadge | None = None
        self._status_line: QLabel | None = None
        self._install_btn: QPushButton | None = None
        self._install_bar: QProgressBar | None = None
        self._repos_box: QVBoxLayout | None = None
        self._add_card: QFrame | None = None
        self._name_edit: QLineEdit | None = None
        self._backend_combo: _NoScrollComboBox | None = None
        self._fields_form: QFormLayout | None = None
        self._password_edit: QLineEdit | None = None
        self._add_error: QLabel | None = None
        self._add_btn: QPushButton | None = None
        self._create_btn: QPushButton | None = None
        # Dynamic per-backend field editors, keyed by field.key.
        self._field_widgets: dict[str, QLineEdit] = {}
        self._creating = False
        # Per-row summary sublabels (repo_id -> QLabel) for async snapshot info.
        self._row_summaries: dict[str, QLabel] = {}
        # Selected-repo detail / backup panel state.
        self._selected_repo_id: str | None = None
        self._detail_card: QFrame | None = None
        self._detail_title: QLabel | None = None
        self._detail_stats: QLabel | None = None
        self._paths_list: QListWidget | None = None
        self._excludes_edit: QLineEdit | None = None
        self._backup_btn: QPushButton | None = None
        self._backup_bar: QProgressBar | None = None
        self._backup_status: QLabel | None = None
        self._snaps_box: QVBoxLayout | None = None
        self._backing_up = False
        # Maintenance (retention / verify) widgets + state.
        self._keep_daily: QLineEdit | None = None
        self._keep_weekly: QLineEdit | None = None
        self._keep_monthly: QLineEdit | None = None
        self._maint_status: QLabel | None = None
        self._maint_busy = False
        self.status = self.get_status()
        self._probe_restic_async()

    # ===================================================================
    #  Status / detection
    # ===================================================================
    def check_status(self) -> str:
        if not self._probed:
            return "Info"
        return "OK" if self._restic_version else "Warning"

    def _marshal(self, fn) -> None:
        """Run ``fn`` on the UI thread if the shell supports it, else inline."""
        if getattr(self, "app", None) and hasattr(self.app, "after"):
            self.app.after(0, fn)
        else:
            fn()

    def _probe_restic_async(self) -> None:
        def work():
            version = None
            try:
                version = self.restic.version()
            except Exception as e:
                logger.warning(f"Backup: restic probe failed: {e}")

            def apply():
                self._restic_version = version
                self._probed = True
                self.status = self.get_status()
                self._render_status()
            self._marshal(apply)

        threading.Thread(target=work, daemon=True, name="restic-probe").start()

    # ===================================================================
    #  Screen
    # ===================================================================
    def create_main_screen(self) -> QWidget:
        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(12)

        col.addWidget(heading("Backup"))
        col.addWidget(
            muted(
                "Encrypted, deduplicated backups to local drives or the cloud, "
                "powered by Restic."
            )
        )
        col.addWidget(self._divider())

        col.addWidget(self._build_engine_card())
        col.addWidget(self._build_repos_card())
        col.addWidget(self._build_add_card())
        col.addWidget(self._build_detail_card())
        col.addStretch(1)

        self._render_status()
        self._refresh_repos_list()
        return scroll_page(centered(inner))

    def _divider(self) -> QFrame:
        d = QFrame()
        d.setObjectName("Divider")
        d.setFixedHeight(1)
        return d

    # ---- Engine status card ----------------------------------------------
    def _build_engine_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 16, 16, 16)
        cl.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(10)
        title = QLabel("Restic engine")
        title.setStyleSheet("font-size: 15px; font-weight: 700;")
        header.addWidget(title)
        self._status_badge = StatusBadge(None)
        header.addWidget(self._status_badge)
        header.addStretch(1)
        cl.addLayout(header)

        self._status_line = QLabel("Checking for Restic…")
        self._status_line.setWordWrap(True)
        self._status_line.setStyleSheet(
            f"color: {theme.color('text_secondary')};")
        cl.addWidget(self._status_line)

        self._install_bar = QProgressBar()
        self._install_bar.setRange(0, 100)
        self._install_bar.hide()
        cl.addWidget(self._install_bar)

        btn_row = QHBoxLayout()
        self._install_btn = QPushButton("Install Restic")
        self._install_btn.clicked.connect(self._start_install)
        self._install_btn.hide()
        btn_row.addWidget(self._install_btn)
        btn_row.addStretch(1)
        cl.addLayout(btn_row)
        return card

    # ---- Repositories list card ------------------------------------------
    def _build_repos_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 16, 16, 16)
        cl.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("Repositories")
        title.setStyleSheet("font-size: 15px; font-weight: 700;")
        header.addWidget(title)
        header.addStretch(1)
        self._add_btn = QPushButton("Add repository")
        self._add_btn.clicked.connect(self._show_add_form)
        header.addWidget(self._add_btn)
        cl.addLayout(header)

        self._repos_box = QVBoxLayout()
        self._repos_box.setSpacing(8)
        cl.addLayout(self._repos_box)
        return card

    def _refresh_repos_list(self) -> None:
        if self._repos_box is None:
            return
        # Clear existing rows.
        while self._repos_box.count():
            item = self._repos_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            elif item.layout() is not None:
                self._clear_layout(item.layout())
        self._row_summaries = {}

        repos = repo_store.list_repos()
        if not repos:
            empty = muted("No repositories yet. Add one to start backing up.")
            self._repos_box.addWidget(empty)
            return

        for meta in repos:
            self._repos_box.addWidget(self._repo_row(meta))
        self._load_summaries_async([r.get("id", "") for r in repos])

    def _load_summaries_async(self, repo_ids: list[str]) -> None:
        """Fetch snapshot count + last-backup time per repo off the UI thread,
        then update each row's summary label (if it still exists)."""

        def work():
            for rid in repo_ids:
                text = self._summary_for(rid)

                def apply(rid=rid, text=text):
                    label = self._row_summaries.get(rid)
                    if label is not None:
                        label.setText(text)
                self._marshal(apply)

        threading.Thread(target=work, daemon=True, name="restic-summaries").start()

    def _summary_for(self, repo_id: str) -> str:
        try:
            snaps = self.restic.snapshot_list(repo_store.resolve(repo_id))
        except Exception as e:
            logger.debug(f"Backup: summary fetch failed for {repo_id}: {e}")
            return "Couldn't read snapshots"
        if not snaps:
            return "No snapshots yet"
        n = len(snaps)
        last = _fmt_time(snaps[0].get("time", ""))
        return f"{n} snapshot{'s' if n != 1 else ''} · last {last}"

    def _repo_row(self, meta: dict) -> QFrame:
        repo_id = meta.get("id", "")
        backend = backends.get_backend(meta.get("backend", ""))
        row = QFrame()
        row.setObjectName("Surface")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(12, 10, 12, 10)
        rl.setSpacing(10)

        text = QVBoxLayout()
        text.setSpacing(2)
        name = QLabel(meta.get("name", "(unnamed)"))
        name.setStyleSheet("font-weight: 600;")
        text.addWidget(name)
        sub = QLabel(
            f"{backend.label if backend else meta.get('backend', '?')}  ·  "
            f"{meta.get('location', '')}")
        sub.setStyleSheet(f"color: {theme.color('text_secondary')}; font-size: 12px;")
        text.addWidget(sub)
        summary = QLabel("Loading snapshots…")
        summary.setStyleSheet(f"color: {theme.color('text_secondary')}; font-size: 12px;")
        text.addWidget(summary)
        self._row_summaries[repo_id] = summary
        rl.addLayout(text, 1)

        # Right side: Open + Remove, with an inline remove-confirmation swap.
        open_btn = QPushButton("Open")
        open_btn.setObjectName("SurfaceBtn")
        open_btn.clicked.connect(lambda _=False, rid=repo_id: self._select_repo(rid))
        rl.addWidget(open_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        remove = QPushButton("Remove")
        remove.setObjectName("Danger")
        rl.addWidget(remove, 0, Qt.AlignmentFlag.AlignVCenter)

        confirm = QWidget()
        cl = QHBoxLayout(confirm)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(6)
        q = QLabel("Remove?")
        q.setStyleSheet(f"color: {theme.color('text_secondary')}; font-size: 12px;")
        cl.addWidget(q)
        yes = QPushButton("Confirm")
        yes.setObjectName("Danger")
        cancel = QPushButton("Cancel")
        cancel.setObjectName("Secondary")
        cl.addWidget(yes)
        cl.addWidget(cancel)
        confirm.hide()
        rl.addWidget(confirm, 0, Qt.AlignmentFlag.AlignVCenter)

        def start_confirm():
            remove.hide()
            open_btn.setEnabled(False)
            confirm.show()

        def end_confirm():
            confirm.hide()
            remove.show()
            open_btn.setEnabled(True)

        remove.clicked.connect(lambda _=False: start_confirm())
        cancel.clicked.connect(lambda _=False: end_confirm())
        yes.clicked.connect(lambda _=False, rid=repo_id: self._do_remove(rid))
        return row

    def _do_remove(self, repo_id: str) -> None:
        # Config-only removal; the actual repository data at the target is left
        # untouched (restic never deletes it, and neither do we here).
        repo_store.remove_repo(repo_id)
        if self._selected_repo_id == repo_id:
            self._selected_repo_id = None
            if self._detail_card:
                self._detail_card.hide()
        self._refresh_repos_list()

    # ---- Add-repository form card -----------------------------------------
    def _build_add_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        self._add_card = card
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 16, 16, 16)
        cl.setSpacing(10)

        title = QLabel("Add a repository")
        title.setStyleSheet("font-size: 15px; font-weight: 700;")
        cl.addWidget(title)

        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("e.g. Laptop → USB drive")
        form.addRow("Name", self._name_edit)

        self._backend_combo = _NoScrollComboBox()
        for b in backends.BACKENDS:
            self._backend_combo.addItem(b.label, b.key)
        self._backend_combo.currentIndexChanged.connect(
            lambda _=0: self._rebuild_backend_fields())
        form.addRow("Storage", self._backend_combo)
        cl.addLayout(form)

        # Dynamic backend-specific fields live in their own form, rebuilt on
        # backend change.
        self._fields_form = QFormLayout()
        self._fields_form.setSpacing(8)
        self._fields_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        cl.addLayout(self._fields_form)

        pw_form = QFormLayout()
        pw_form.setSpacing(8)
        pw_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._password_edit = QLineEdit()
        self._password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._password_edit.setPlaceholderText("Encrypts the repository — keep it safe")
        pw_form.addRow("Repository password", self._password_edit)
        cl.addLayout(pw_form)

        self._add_error = QLabel("")
        self._add_error.setWordWrap(True)
        self._add_error.setStyleSheet("color: #DC2626; font-size: 12px;")
        self._add_error.hide()
        cl.addWidget(self._add_error)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("Secondary")
        cancel.clicked.connect(self._hide_add_form)
        btns.addWidget(cancel)
        self._create_btn = QPushButton("Create / open")
        self._create_btn.clicked.connect(self._on_create_repo)
        btns.addWidget(self._create_btn)
        cl.addLayout(btns)

        self._rebuild_backend_fields()
        card.hide()  # collapsed until "Add repository" is clicked
        return card

    def _show_add_form(self) -> None:
        if self._restic_version is None:
            # Guard: no engine yet.
            if self._status_line:
                self._status_line.setText(
                    "Install Restic first, then add a repository.")
            return
        if self._add_card:
            self._reset_add_form()
            self._add_card.show()
        if self._add_btn:
            self._add_btn.setEnabled(False)

    def _hide_add_form(self) -> None:
        if self._add_card:
            self._add_card.hide()
        if self._add_btn:
            self._add_btn.setEnabled(True)

    def _reset_add_form(self) -> None:
        if self._name_edit:
            self._name_edit.clear()
        if self._password_edit:
            self._password_edit.clear()
        if self._backend_combo:
            self._backend_combo.setCurrentIndex(0)
        if self._add_error:
            self._add_error.hide()
        self._rebuild_backend_fields()

    def _current_backend_key(self) -> str:
        if self._backend_combo is None:
            return "local"
        return self._backend_combo.currentData() or "local"

    def _rebuild_backend_fields(self) -> None:
        if self._fields_form is None:
            return
        self._clear_form(self._fields_form)
        self._field_widgets = {}
        backend = backends.get_backend(self._current_backend_key())
        if backend is None:
            return
        for f in backend.all_fields():
            edit = QLineEdit()
            edit.setPlaceholderText(f.placeholder)
            if f.secret:
                edit.setEchoMode(QLineEdit.EchoMode.Password)
            self._field_widgets[f.key] = edit
            if backend.key == "local" and f.key == "path":
                # Local folder gets a Browse… button alongside the field.
                roww = QWidget()
                rl = QHBoxLayout(roww)
                rl.setContentsMargins(0, 0, 0, 0)
                rl.setSpacing(6)
                rl.addWidget(edit, 1)
                browse = QPushButton("Browse…")
                browse.setObjectName("Secondary")
                browse.clicked.connect(self._browse_local_folder)
                rl.addWidget(browse)
                self._fields_form.addRow(f.label, roww)
            else:
                self._fields_form.addRow(f.label, edit)

    def _browse_local_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(
            None, "Choose a backup folder")
        if path and "path" in self._field_widgets:
            self._field_widgets["path"].setText(path)

    def _collect_form(self) -> tuple[str, str, dict, dict, str]:
        backend = backends.get_backend(self._current_backend_key())
        name = self._name_edit.text() if self._name_edit else ""
        password = self._password_edit.text() if self._password_edit else ""
        location_values: dict[str, str] = {}
        secret_values: dict[str, str] = {}
        for f in (backend.location_fields if backend else []):
            location_values[f.key] = self._field_widgets[f.key].text()
        for f in (backend.secret_fields if backend else []):
            secret_values[f.key] = self._field_widgets[f.key].text()
        return name, self._current_backend_key(), location_values, secret_values, password

    def _form_error(self, msg: str) -> None:
        if self._add_error:
            self._add_error.setText(msg)
            self._add_error.show()

    def _on_create_repo(self) -> None:
        if self._creating:
            return
        name, backend_key, loc_values, sec_values, password = self._collect_form()
        backend = backends.get_backend(backend_key)

        # Client-side validation of required fields.
        if not password:
            self._form_error("A repository password is required.")
            return
        for f in (backend.all_fields() if backend else []):
            if f.required and not (loc_values.get(f.key) or sec_values.get(f.key)):
                self._form_error(f"“{f.label}” is required.")
                return

        transient = repo_store.build_repository(
            backend_key, loc_values, sec_values, password)
        self._creating = True
        if self._create_btn:
            self._create_btn.setEnabled(False)
            self._create_btn.setText("Working…")
        if self._add_error:
            self._add_error.hide()

        def work():
            ok, opened, err = self._init_or_open(transient)

            def done():
                self._creating = False
                if self._create_btn:
                    self._create_btn.setEnabled(True)
                    self._create_btn.setText("Create / open")
                if not ok:
                    self._form_error(err or "Could not create or open the repository.")
                    return
                repo_store.add_repo(name, backend_key, loc_values, sec_values, password)
                self._hide_add_form()
                self._refresh_repos_list()
            self._marshal(done)

        threading.Thread(target=work, daemon=True, name="restic-init").start()

    def _init_or_open(self, transient) -> tuple[bool, bool, str]:
        """Create the repo, or open it if it already exists.

        Returns ``(ok, opened_existing, error)``. When ``init`` reports the
        repo already exists, we validate the password by listing snapshots — a
        success there means the user supplied the right password for an existing
        repo, so we adopt it rather than failing.
        """
        try:
            res = self.restic.init(transient)
        except ResticError as e:
            return False, False, str(e)
        if res.ok:
            return True, False, ""
        stderr = (res.stderr or "").lower()
        if "already" in stderr and ("exist" in stderr or "initialized" in stderr
                                    or "config" in stderr):
            try:
                probe = self.restic.snapshots(transient)
            except ResticError as e:
                return False, False, str(e)
            if probe.ok:
                return True, True, ""
            return False, False, ("A repository already exists here but the "
                                  "password didn't match it.")
        return False, False, (res.stderr or "").strip() or "restic init failed."

    # ---- Repository detail / backup panel ---------------------------------
    def _build_detail_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        self._detail_card = card
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 16, 16, 16)
        cl.setSpacing(10)

        self._detail_title = QLabel("Repository")
        self._detail_title.setStyleSheet("font-size: 15px; font-weight: 700;")
        cl.addWidget(self._detail_title)
        self._detail_stats = QLabel("")
        self._detail_stats.setStyleSheet(
            f"color: {theme.color('text_secondary')}; font-size: 12px;")
        cl.addWidget(self._detail_stats)

        # Paths to back up.
        cl.addWidget(self._section_label("Paths to back up"))
        self._paths_list = QListWidget()
        self._paths_list.setMaximumHeight(120)
        cl.addWidget(self._paths_list)

        prow = QHBoxLayout()
        add_files = QPushButton("Add files…")
        add_files.setObjectName("Secondary")
        add_files.clicked.connect(self._add_backup_files)
        add_folder = QPushButton("Add folder…")
        add_folder.setObjectName("Secondary")
        add_folder.clicked.connect(self._add_backup_folder)
        remove_path = QPushButton("Remove selected")
        remove_path.setObjectName("Secondary")
        remove_path.clicked.connect(self._remove_backup_path)
        prow.addWidget(add_files)
        prow.addWidget(add_folder)
        prow.addWidget(remove_path)
        prow.addStretch(1)
        cl.addLayout(prow)

        # Excludes.
        ex_form = QFormLayout()
        ex_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._excludes_edit = QLineEdit()
        self._excludes_edit.setPlaceholderText("*.tmp, node_modules  (comma-separated)")
        ex_form.addRow("Exclude", self._excludes_edit)
        cl.addLayout(ex_form)

        # Back up now + progress.
        brow = QHBoxLayout()
        self._backup_btn = QPushButton("Back up now")
        self._backup_btn.clicked.connect(self._on_backup)
        brow.addWidget(self._backup_btn)
        brow.addStretch(1)
        cl.addLayout(brow)

        self._backup_bar = QProgressBar()
        self._backup_bar.setRange(0, 100)
        self._backup_bar.hide()
        cl.addWidget(self._backup_bar)
        self._backup_status = QLabel("")
        self._backup_status.setWordWrap(True)
        self._backup_status.setStyleSheet(
            f"color: {theme.color('text_secondary')}; font-size: 12px;")
        cl.addWidget(self._backup_status)

        cl.addWidget(self._divider())
        cl.addWidget(self._section_label("Snapshots"))
        self._snaps_box = QVBoxLayout()
        self._snaps_box.setSpacing(4)
        cl.addLayout(self._snaps_box)

        # --- Maintenance: retention + integrity check ---------------------
        cl.addWidget(self._divider())
        cl.addWidget(self._section_label("Maintenance"))

        ret_row = QHBoxLayout()
        ret_row.setSpacing(6)
        ret_row.addWidget(QLabel("Keep"))
        self._keep_daily = self._int_edit()
        self._keep_weekly = self._int_edit()
        self._keep_monthly = self._int_edit()
        ret_row.addWidget(self._keep_daily)
        ret_row.addWidget(QLabel("daily"))
        ret_row.addWidget(self._keep_weekly)
        ret_row.addWidget(QLabel("weekly"))
        ret_row.addWidget(self._keep_monthly)
        ret_row.addWidget(QLabel("monthly"))
        ret_row.addStretch(1)
        cl.addLayout(ret_row)

        maint_btns = QHBoxLayout()
        apply_ret = QPushButton("Apply retention && prune")
        apply_ret.setObjectName("Danger")
        apply_ret.clicked.connect(self._on_apply_retention)
        verify = QPushButton("Verify integrity")
        verify.setObjectName("Secondary")
        verify.clicked.connect(self._on_check)
        maint_btns.addWidget(apply_ret)
        maint_btns.addWidget(verify)
        maint_btns.addStretch(1)
        cl.addLayout(maint_btns)

        self._maint_status = QLabel("")
        self._maint_status.setWordWrap(True)
        self._maint_status.setStyleSheet(
            f"color: {theme.color('text_secondary')}; font-size: 12px;")
        cl.addWidget(self._maint_status)

        card.hide()
        return card

    def _int_edit(self) -> QLineEdit:
        e = QLineEdit()
        e.setFixedWidth(52)
        e.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return e

    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-weight: 600; font-size: 13px;")
        return lbl

    def _select_repo(self, repo_id: str) -> None:
        self._selected_repo_id = repo_id
        meta = repo_store.get_repo(repo_id) or {}
        if self._detail_title:
            self._detail_title.setText(f"Repository — {meta.get('name', '')}")
        paths, excludes = repo_store.get_backup_spec(repo_id)
        if self._paths_list is not None:
            self._paths_list.clear()
            self._paths_list.addItems(paths)
        if self._excludes_edit is not None:
            self._excludes_edit.setText(", ".join(excludes))
        # Load retention policy (blank when 0 / unset).
        ret = repo_store.get_retention(repo_id)
        for edit, key in ((self._keep_daily, "keep_daily"),
                          (self._keep_weekly, "keep_weekly"),
                          (self._keep_monthly, "keep_monthly")):
            if edit is not None:
                edit.setText(str(ret[key]) if ret[key] else "")
        if self._backup_bar:
            self._backup_bar.hide()
        if self._backup_status:
            self._backup_status.setText("")
        if self._maint_status:
            self._maint_status.setText("")
        if self._detail_stats:
            self._detail_stats.setText("")
        if self._detail_card:
            self._detail_card.show()
        self._refresh_snapshots()
        self._refresh_stats()

    def _refresh_stats(self) -> None:
        """Fetch the repo's on-disk size + snapshot count for the header."""
        if self._detail_stats is None or not self._selected_repo_id:
            return
        self._detail_stats.setText("Reading repository size…")
        repo_id = self._selected_repo_id

        def work():
            try:
                res = self.restic.stats(repo_store.resolve(repo_id), mode="raw-data")
                data = res.json if isinstance(res.json, dict) else None
            except Exception as e:
                logger.debug(f"Backup: stats failed for {repo_id}: {e}")
                data = None

            def apply():
                if self._selected_repo_id != repo_id or self._detail_stats is None:
                    return
                if not data:
                    self._detail_stats.setText("")
                    return
                n = data.get("snapshots_count", 0)
                size = _fmt_bytes(data.get("total_size", 0))
                self._detail_stats.setText(
                    f"{n} snapshot{'s' if n != 1 else ''} · {size} on disk")
            self._marshal(apply)

        threading.Thread(target=work, daemon=True, name="restic-stats").start()

    def _add_backup_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(None, "Choose files to back up")
        for f in files:
            self._paths_list.addItem(f)
        self._persist_spec()

    def _add_backup_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(None, "Choose a folder to back up")
        if folder:
            self._paths_list.addItem(folder)
            self._persist_spec()

    def _remove_backup_path(self) -> None:
        for item in self._paths_list.selectedItems():
            self._paths_list.takeItem(self._paths_list.row(item))
        self._persist_spec()

    def _current_paths(self) -> list[str]:
        return [self._paths_list.item(i).text()
                for i in range(self._paths_list.count())]

    def _current_excludes(self) -> list[str]:
        raw = self._excludes_edit.text() if self._excludes_edit else ""
        return [s.strip() for s in raw.split(",") if s.strip()]

    def _persist_spec(self) -> None:
        if self._selected_repo_id:
            repo_store.set_backup_spec(
                self._selected_repo_id, self._current_paths(), self._current_excludes())

    def _on_backup(self) -> None:
        if self._backing_up or not self._selected_repo_id:
            return
        paths = self._current_paths()
        if not paths:
            if self._backup_status:
                self._backup_status.setText("Add at least one path to back up.")
            return
        self._persist_spec()
        excludes = self._current_excludes()
        repo = repo_store.resolve(self._selected_repo_id)

        self._backing_up = True
        if self._backup_btn:
            self._backup_btn.setEnabled(False)
            self._backup_btn.setText("Backing up…")
        if self._backup_bar:
            self._backup_bar.setValue(0)
            self._backup_bar.show()

        def on_json(msg: dict) -> None:
            mt = msg.get("message_type")
            if mt not in ("status", "summary"):
                return

            def apply():
                if mt == "status":
                    pct = int((msg.get("percent_done", 0) or 0) * 100)
                    if self._backup_bar:
                        self._backup_bar.setValue(pct)
                    if self._backup_status:
                        self._backup_status.setText(
                            f"Backing up… {pct}%  "
                            f"({msg.get('files_done', 0)}/{msg.get('total_files', 0)} files)")
                elif mt == "summary" and self._backup_status:
                    if self._backup_bar:
                        self._backup_bar.setValue(100)
                    self._backup_status.setText(
                        f"Done. {msg.get('files_new', 0)} new, "
                        f"{msg.get('files_changed', 0)} changed · "
                        f"{_fmt_bytes(msg.get('data_added', 0))} added.")
            self._marshal(apply)

        def work():
            try:
                res = self.restic.backup(repo, paths, excludes=excludes,
                                         on_progress=on_json)
                err = "" if res.ok else (res.stderr or "").strip()
            except Exception as e:
                err = str(e)

            def done():
                self._backing_up = False
                if self._backup_btn:
                    self._backup_btn.setEnabled(True)
                    self._backup_btn.setText("Back up now")
                if err and self._backup_status:
                    self._backup_status.setText(f"Backup failed: {err}")
                self._refresh_snapshots()
                self._refresh_stats()
                # Refresh the row summary for this repo too.
                if self._selected_repo_id:
                    self._load_summaries_async([self._selected_repo_id])
            self._marshal(done)

        threading.Thread(target=work, daemon=True, name="restic-backup").start()

    def _refresh_snapshots(self) -> None:
        if self._snaps_box is None or not self._selected_repo_id:
            return
        self._clear_layout(self._snaps_box)
        loading = muted("Loading…")
        self._snaps_box.addWidget(loading)
        repo_id = self._selected_repo_id

        def work():
            try:
                snaps = self.restic.snapshot_list(repo_store.resolve(repo_id))
                err = ""
            except Exception as e:
                snaps, err = [], str(e)

            def apply():
                # Guard against a selection change while we were fetching.
                if self._selected_repo_id != repo_id or self._snaps_box is None:
                    return
                self._clear_layout(self._snaps_box)
                if err:
                    self._snaps_box.addWidget(muted(f"Couldn't read snapshots: {err}"))
                    return
                if not snaps:
                    self._snaps_box.addWidget(muted("No snapshots yet."))
                    return
                for s in snaps:
                    self._snaps_box.addWidget(self._snapshot_row(s))
            self._marshal(apply)

        threading.Thread(target=work, daemon=True, name="restic-snaps").start()

    def _snapshot_row(self, snap: dict) -> QFrame:
        short = snap.get("short_id", snap.get("id", "")[:8])
        snap_id = snap.get("id", short)
        when = _fmt_time(snap.get("time", ""))
        paths = ", ".join(snap.get("paths", []) or [])
        row = QFrame()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)
        label = QLabel(f"{short}  ·  {when}  ·  {paths}")
        label.setStyleSheet(
            f"color: {theme.color('text_secondary')}; font-size: 12px;")
        label.setWordWrap(True)
        rl.addWidget(label, 1)
        restore = QPushButton("Restore…")
        restore.setObjectName("SurfaceBtn")
        restore.clicked.connect(
            lambda _=False, sid=snap_id, sshort=short: self._on_restore(sid, sshort))
        rl.addWidget(restore, 0, Qt.AlignmentFlag.AlignTop)
        return row

    # ---- Maintenance: check / retention / restore -------------------------
    def _parse_keep(self, edit: QLineEdit | None) -> int:
        try:
            return max(0, int((edit.text() if edit else "").strip() or 0))
        except ValueError:
            return 0

    def _on_check(self) -> None:
        if self._maint_busy or not self._selected_repo_id:
            return
        repo = repo_store.resolve(self._selected_repo_id)
        self._maint_busy = True
        if self._maint_status:
            self._maint_status.setText("Verifying repository integrity…")

        def work():
            try:
                res = self.restic.check(repo)
                ok = res.ok
                msg = (res.stderr or res.stdout or "").strip()
            except Exception as e:
                ok, msg = False, str(e)

            def done():
                self._maint_busy = False
                if self._maint_status:
                    self._maint_status.setText(
                        "Integrity check passed — repository is healthy."
                        if ok else f"Integrity check failed: {msg}")
            self._marshal(done)

        threading.Thread(target=work, daemon=True, name="restic-check").start()

    def _on_apply_retention(self) -> None:
        if self._maint_busy or not self._selected_repo_id:
            return
        kd = self._parse_keep(self._keep_daily)
        kw = self._parse_keep(self._keep_weekly)
        km = self._parse_keep(self._keep_monthly)
        if not (kd or kw or km):
            if self._maint_status:
                self._maint_status.setText(
                    "Set at least one keep value before applying retention.")
            return
        repo_store.set_retention(self._selected_repo_id, kd, kw, km)
        meta = repo_store.get_repo(self._selected_repo_id) or {}

        # Destructive: forget removes snapshots outside the policy and prune
        # deletes their now-unreferenced data. Require explicit confirmation.
        confirmed = QMessageBox.question(
            self.app, "Apply retention & prune",
            f"This will permanently delete snapshots in “{meta.get('name', '')}” "
            f"outside the policy (keep {kd} daily, {kw} weekly, {km} monthly) "
            "and prune the freed data.\n\nThis cannot be undone. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes
        if not confirmed:
            return

        repo = repo_store.resolve(self._selected_repo_id)
        self._maint_busy = True
        if self._maint_status:
            self._maint_status.setText("Applying retention and pruning…")

        def work():
            try:
                res = self.restic.forget(repo, keep_daily=kd, keep_weekly=kw,
                                         keep_monthly=km, prune=True)
                ok = res.ok
                msg = (res.stderr or "").strip()
            except Exception as e:
                ok, msg = False, str(e)

            def done():
                self._maint_busy = False
                if self._maint_status:
                    self._maint_status.setText(
                        "Retention applied and repository pruned."
                        if ok else f"Retention failed: {msg}")
                self._refresh_snapshots()
                self._refresh_stats()
                if self._selected_repo_id:
                    self._load_summaries_async([self._selected_repo_id])
            self._marshal(done)

        threading.Thread(target=work, daemon=True, name="restic-forget").start()

    def _on_restore(self, snapshot_id: str, short: str) -> None:
        if self._maint_busy or not self._selected_repo_id:
            return
        target = QFileDialog.getExistingDirectory(
            None, f"Restore snapshot {short} into…")
        if not target:
            return
        # Full restore: recreate the snapshot's paths under the target (files
        # keep their names and directory structure, nothing is separated). The
        # real backed-up files and folders receive their correct timestamps;
        # only protected system path-scaffolding (e.g. C\Users) may fail to have
        # its timestamp set on Windows — a cosmetic issue the benign-warning
        # handling below reports softly rather than as a failure.
        # Restore writes into the target and can overwrite existing files there.
        try:
            not_empty = bool(os.listdir(target))
        except OSError:
            not_empty = False
        if not_empty:
            proceed = QMessageBox.question(
                self.app, "Directory not empty",
                f"“{target}” isn't empty. Restoring may overwrite files that "
                "share a path with the snapshot.\n\nContinue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            ) == QMessageBox.StandardButton.Yes
            if not proceed:
                return

        repo = repo_store.resolve(self._selected_repo_id)
        self._maint_busy = True
        if self._maint_status:
            self._maint_status.setText(f"Restoring snapshot {short}…")

        def work():
            warned = False
            try:
                res = self.restic.restore(repo, snapshot_id, target)
                ok = res.ok
                msg = (res.stderr or "").strip()
                if not ok and _restore_errors_benign(msg):
                    # Data restored; the only errors are ignorable timestamp
                    # failures on locked system scaffolding dirs. On Windows we
                    # own those dirs and can repair their mtimes ourselves.
                    ok = True
                    if _IS_WINDOWS:
                        remaining = self._repair_timestamps(
                            repo, snapshot_id, target, msg)
                        warned = remaining > 0
                    else:
                        warned = True
            except Exception as e:
                ok, msg = False, str(e)

            def done():
                self._maint_busy = False
                if ok:
                    note = (" (some system folder timestamps couldn't be set)"
                            if warned else "")
                    if self._maint_status:
                        self._maint_status.setText(
                            f"Restored snapshot {short} into {target}.{note}")
                    QMessageBox.information(
                        self.app, "Restore complete",
                        f"Snapshot {short} was restored into:\n{target}{note}")
                else:
                    if self._maint_status:
                        self._maint_status.setText(f"Restore failed: {msg}")
                    QMessageBox.critical(self.app, "Restore failed",
                                         msg or "restic restore failed.")
            self._marshal(done)

        threading.Thread(target=work, daemon=True, name="restic-restore").start()

    def _repair_timestamps(self, repo, snapshot_id: str, target: str,
                           stderr: str) -> int:
        """Set the correct mtime on the system scaffolding dirs restic couldn't.

        Returns the count still unfixed (0 = all repaired). Windows only; called
        off the UI thread. Reads the intended times from the snapshot metadata
        and applies them via ``win_timestamps`` (owner DACL rewrite + os.utime).
        """
        failed_paths = _parse_failed_timestamp_paths(stderr)
        if not failed_paths:
            return 0

        # Map each failed target path back to its snapshot tree path (e.g.
        # <target>\C\Users -> /C/Users) so we can look up the intended mtime.
        tree_of: dict[str, str] = {}
        for p in failed_paths:
            try:
                rel = os.path.relpath(p, target)
            except ValueError:
                continue  # different drive than target; skip
            tree_of[p] = "/" + rel.replace(os.sep, "/").replace("\\", "/")

        try:
            mtimes = self.restic.tree_mtimes(
                repo, snapshot_id, set(tree_of.values()))
        except Exception as e:
            logger.debug(f"Backup: tree_mtimes failed: {e}")
            mtimes = {}

        fixes: list[tuple[str, float]] = []
        for path, tree in tree_of.items():
            epoch = _iso_to_epoch(mtimes.get(tree, ""))
            if epoch is not None:
                fixes.append((path, epoch))

        fixed, _failed = win_timestamps.apply_directory_mtimes(fixes)
        return len(failed_paths) - fixed

    # ===================================================================
    #  Install flow
    # ===================================================================
    def _start_install(self) -> None:
        if self._installing or not restic_installer.is_supported_platform():
            if not restic_installer.is_supported_platform() and self._status_line:
                self._status_line.setText(
                    "This platform isn't supported by the Restic installer.")
            return
        self._installing = True
        if self._install_btn:
            self._install_btn.setEnabled(False)
            self._install_btn.setText("Installing…")
        if self._install_bar:
            self._install_bar.setValue(0)
            self._install_bar.show()

        def on_progress(frac: float, msg: str) -> None:
            def apply():
                if self._install_bar:
                    self._install_bar.setValue(int(frac * 100))
                if self._status_line:
                    self._status_line.setText(msg)
            self._marshal(apply)

        def work():
            ok, msg = restic_installer.install(on_progress=on_progress)

            def done():
                self._installing = False
                self.restic.forget_binary()
                if self._install_bar:
                    self._install_bar.hide()
                if self._install_btn:
                    self._install_btn.setEnabled(True)
                    self._install_btn.setText("Install Restic")
                if not ok and self._status_line:
                    self._status_line.setText(f"Install failed: {msg}")
                self._probe_restic_async()
            self._marshal(done)

        threading.Thread(target=work, daemon=True, name="restic-install").start()

    # ===================================================================
    #  Rendering helpers
    # ===================================================================
    def _render_status(self) -> None:
        if self._status_badge is None or self._status_line is None:
            return
        show_install = self._probed and not self._restic_version \
            and not self._installing
        if self._install_btn is not None:
            self._install_btn.setVisible(show_install)
        # Adding a repo requires the engine; gate the button on detection.
        if self._add_btn is not None:
            self._add_btn.setEnabled(bool(self._restic_version))

        if self._installing:
            return
        if not self._probed:
            self._status_badge.set_status("Info")
            self._status_line.setText("Checking for Restic…")
        elif self._restic_version:
            self._status_badge.set_status("OK")
            self._status_line.setText(
                f"Restic {self._restic_version} detected. "
                "Add a repository below to start backing up.")
        else:
            self._status_badge.set_status("Warning")
            self._status_line.setText(
                "Restic isn't installed on this system. Click Install to "
                "download it automatically, or place the binary on your PATH.")

    def _clear_form(self, form: QFormLayout) -> None:
        while form.rowCount():
            form.removeRow(0)

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            elif item.layout() is not None:
                self._clear_layout(item.layout())

    def on_theme_changed(self):
        if getattr(self, "app", None) and hasattr(self.app, "update_plugin"):
            self.app.update_plugin(self.id)
