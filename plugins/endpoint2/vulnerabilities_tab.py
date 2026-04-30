"""Vulnerabilities tab for the Wazuh plugin (placeholder).

The pane is currently empty — it stays as a stub so the tab strip and the
file layout match the Events / Overview structure. Actual content will be
filled in once a sample data source for vulnerabilities is wired up
(`agent.013.json` has `vulnerabilities: {}` empty).

Author: Resistine Team
Copyright (c) Resistine 2025
Licensed under the GNU General Public License v2 or later
"""


class VulnerabilitiesTabMixin:
    """Mixin providing the Vulnerabilities-tab UI for the Wazuh plugin."""

    def _build_vulnerabilities_pane(self, parent):
        """Render the Vulnerabilities pane into `parent`. Currently a no-op."""
        # Intentionally empty — pane is created by _build_content_area; content
        # is deferred until a data source exists.
        return
