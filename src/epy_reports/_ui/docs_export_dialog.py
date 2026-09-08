"""Dialog for exporting the current document through epy_docs."""

from __future__ import annotations

from pathlib import Path

from epy_export import ORGANIZATION
from PySide6.QtCore import QSettings, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from epy_reports._core import _i18n as i18n


class _RenderWorker(QThread):
    """Background thread that calls docs_bridge.render_document.

    Signals:
        finished_ok: Emitted with the output directory path on success.
        finished_err: Emitted with the error message string on failure.
    """

    finished_ok = Signal(str)
    finished_err = Signal(str)

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
        """Store render parameters.

        Args:
            source_path: Absolute path to the source Markdown file.
            layout: epy_docs layout name.
            document_type: epy_docs document type.
            output_dir: Destination directory for the rendered output.
            pdf: Request PDF output.
            html: Request HTML output.
            docx: Request Word (.docx) output.
        """
        super().__init__()
        self._source_path = source_path
        self._layout = layout
        self._document_type = document_type
        self._output_dir = output_dir
        self._pdf = pdf
        self._html = html
        self._docx = docx

    def run(self) -> None:
        """Execute the render; emit the appropriate signal when done."""
        from epy_reports.epy_suite_connect._adapters.docs_bridge import (  # noqa: PLC0415
            render_document,
        )

        try:
            render_document(
                source_path=self._source_path,
                layout=self._layout,
                document_type=self._document_type,
                output_dir=self._output_dir,
                pdf=self._pdf,
                html=self._html,
                docx=self._docx,
            )
            self.finished_ok.emit(str(self._output_dir))
        except Exception as exc:  # noqa: BLE001
            self.finished_err.emit(str(exc))


class DocsExportDialog(QDialog):
    """Modal dialog for configuring and launching an epy_docs export.

    Presents layout / document-type combos, an output directory picker,
    and PDF / HTML checkboxes.  Persists last-used values in
    ``QSettings`` under the keys ``docs_layout``, ``docs_doctype``, and
    ``docs_outdir``.

    Args:
        source_path: Path to the Markdown / Quarto file being exported.
        parent: Optional Qt parent widget.
    """

    def __init__(
        self,
        source_path: Path,
        parent=None,
    ) -> None:
        """Build the dialog widgets and restore persisted settings.

        Args:
            source_path: Absolute path to the file being exported.
            parent: Optional Qt parent widget.
        """
        super().__init__(parent)
        self.setWindowTitle("Export via epy_docs")
        self.setMinimumWidth(460)

        self._source_path = source_path
        # The constant, not the literal. app.py already uses it, and
        # two spellings of one organisation is how a dialog comes to
        # read a different registry tree than the window that opened
        # it -- silently, because both spellings work today.
        self._settings = QSettings(ORGANIZATION, "epy_reports")

        from epy_reports.epy_suite_connect._adapters.docs_bridge import (  # noqa: PLC0415
            list_document_types,
            list_layouts,
        )

        layouts = list_layouts()
        doc_types = list_document_types()

        # --- Layout combo ------------------------------------------
        self._combo_layout = QComboBox()
        self._combo_layout.addItems(layouts)
        saved_layout = str(
            self._settings.value("docs_layout", "corporate")
        )
        if saved_layout in layouts:
            self._combo_layout.setCurrentText(saved_layout)

        # --- Document type combo -----------------------------------
        self._combo_doctype = QComboBox()
        self._combo_doctype.addItems(doc_types)
        saved_doctype = str(
            self._settings.value("docs_doctype", "report")
        )
        if saved_doctype in doc_types:
            self._combo_doctype.setCurrentText(saved_doctype)

        # --- Output directory row ----------------------------------
        default_outdir = str(source_path.parent / "results")
        saved_outdir = str(
            self._settings.value("docs_outdir", default_outdir)
        )
        self._edit_outdir = QLineEdit(saved_outdir)
        self._btn_browse = QPushButton("Browse…")
        self._btn_browse.clicked.connect(self._browse_outdir)
        outdir_row = QHBoxLayout()
        outdir_row.addWidget(self._edit_outdir)
        outdir_row.addWidget(self._btn_browse)

        # --- Checkboxes --------------------------------------------
        self._chk_pdf = QCheckBox("PDF")
        self._chk_pdf.setChecked(True)
        self._chk_html = QCheckBox("HTML")
        self._chk_html.setChecked(True)
        self._chk_docx = QCheckBox("DOCX")
        self._chk_docx.setChecked(False)
        checks_row = QHBoxLayout()
        checks_row.addWidget(self._chk_pdf)
        checks_row.addWidget(self._chk_html)
        checks_row.addWidget(self._chk_docx)
        checks_row.addStretch()

        # --- Form layout ------------------------------------------
        form = QFormLayout()
        form.addRow("Layout:", self._combo_layout)
        form.addRow("Document type:", self._combo_doctype)
        form.addRow("Output directory:", outdir_row)
        form.addRow("Output formats:", checks_row)

        # --- Button box -------------------------------------------
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        # --- Status label (hidden until needed) -------------------
        self._lbl_status = QLabel("")
        self._lbl_status.setVisible(False)

        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addWidget(self._lbl_status)
        root.addWidget(buttons)
        i18n.translate_widget(self)

    def _browse_outdir(self) -> None:
        """Open a directory picker and update the output path field."""
        start = self._edit_outdir.text() or str(
            self._source_path.parent
        )
        chosen = QFileDialog.getExistingDirectory(
            self, i18n.tr("Select output directory"), start
        )
        if chosen:
            self._edit_outdir.setText(chosen)

    # ----------------------------------------------------------------

    @property
    def layout_name(self) -> str:
        """Selected layout name."""
        return self._combo_layout.currentText()

    @property
    def document_type(self) -> str:
        """Selected document type."""
        return self._combo_doctype.currentText()

    @property
    def output_dir(self) -> Path:
        """Selected output directory as a ``Path``."""
        return Path(self._edit_outdir.text())

    @property
    def export_pdf(self) -> bool:
        """``True`` when the PDF checkbox is checked."""
        return self._chk_pdf.isChecked()

    @property
    def export_html(self) -> bool:
        """``True`` when the HTML checkbox is checked."""
        return self._chk_html.isChecked()

    @property
    def export_docx(self) -> bool:
        """``True`` when the DOCX checkbox is checked."""
        return self._chk_docx.isChecked()

    def persist_settings(self) -> None:
        """Save the current combo / directory values to QSettings."""
        self._settings.setValue("docs_layout", self.layout_name)
        self._settings.setValue("docs_doctype", self.document_type)
        self._settings.setValue("docs_outdir", str(self.output_dir))
