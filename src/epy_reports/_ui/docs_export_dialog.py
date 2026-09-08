"""Dialog for exporting the current document through epy_docs.

Thin: the window itself is the family's, in
``epy_export._ui.docs_export_dialog``. It is the same two combos, the
same directory picker, the same format checkboxes and the same three
remembered keys in all three editors, and only the registry scope and
the translators differ -- so those are what this module supplies.

Both names below keep the shapes this application already imports:
``DocsExportDialog(source_path)`` and ``_RenderWorker(...)``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from epy_export._ui.docs_export_dialog import DocsExportDialog as _Shared
from epy_export._ui.docs_export_dialog import RenderWorker as _Worker
from PySide6.QtCore import QSettings  # noqa: F401 - patched by name in tests
from PySide6.QtWidgets import QWidget

from epy_reports._core import _i18n as i18n

__all__ = ["DocsExportDialog"]


def _render(**kwargs: Any) -> Any:
    """Call this application's bridge, resolved at call time.

    Looked up when the render runs rather than bound when this module is
    imported: bound early, replacing the bridge function -- which is how
    the worker is tested, and how a caller could redirect it -- would
    have no effect and no signal.
    """
    from epy_reports.epy_suite_connect._adapters import (  # noqa: PLC0415
        docs_bridge,
    )

    return docs_bridge.render_document(**kwargs)


class _RenderWorker(_Worker):
    """The family's render thread, pointed at this application's bridge."""

    def __init__(
        self,
        source_path: Path,
        layout: str,
        document_type: str,
        output_dir: Path,
        pdf: bool,
        html: bool,
        docx: bool = False,
    ) -> None:
        """Store the render parameters.

        Args:
            source_path: Absolute path to the source Markdown file.
            layout: Layout name.
            document_type: Document kind.
            output_dir: Destination directory.
            pdf: Request PDF output.
            html: Request HTML output.
            docx: Request Word output.
        """
        super().__init__(
            _render,
            source_path,
            layout,
            document_type,
            output_dir,
            pdf,
            html,
            docx,
        )


class DocsExportDialog(_Shared):
    """The family's export dialog, in this application's scope."""

    def __init__(
        self, source_path: Path, parent: QWidget | None = None
    ) -> None:
        """Build the dialog and restore what was chosen last time.

        Args:
            source_path: Absolute path to the file being exported.
            parent: Optional Qt parent widget.
        """
        super().__init__(
            source_path,
            app_name="epy_reports",
            translate=i18n.tr,
            translate_widget=i18n.translate_widget,
            parent=parent,
        )
