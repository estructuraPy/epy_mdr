"""epy_reports GUI: multi-tab Quarto/Markdown editor with PDF export."""

from __future__ import annotations

import argparse
import importlib.resources
import shutil
import sys
from collections import defaultdict
from pathlib import Path

from epy_export import ORGANIZATION
from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCursor,
    QIcon,
    QKeySequence,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QStatusBar,
    QTabWidget,
    QToolBar,
    QToolButton,
)

from epy_reports._core import _i18n as i18n
from epy_reports._core import bib, snippets, themes
from epy_reports._core._design import document_css
from epy_reports._core.renderer import export_docx, render_markdown
from epy_reports._ui.about_dialog import _load_branding_pixmap
from epy_reports._ui.tab import MarkdownTab
from epy_reports.epy_suite_connect._adapters.docs_bridge import (
    epy_docs_available,
)

APP_NAME = "epy_reports"

SUPPORTED_EXTENSIONS = {".md", ".markdown", ".qmd"}

FILE_FILTER = "Markdown / Quarto (*.md *.markdown *.qmd);;All files (*)"

AUTOSAVE_INTERVAL_MS = 30_000

def _load_manual_text(filename: str = "welcome.md") -> str:
    """Load a bundled user-manual document and resolve its image placeholders.

    The user manual is a full document that demonstrates every content type
    with its syntax and documents the Python API; it ships as Markdown under
    ``_config/_assets/`` so it can be edited freely. It exists in English
    (``welcome.md``, the preloaded welcome tab) and Spanish
    (``welcome_es.md``); both are openable from the Help menu.

    The ``__EPY_LOGO__``, ``__SHOT_EDITOR__`` and ``__SHOT_PROPERTIES__``
    placeholders are replaced with ``file://`` URIs to the bundled images so
    the cover page and figures render even though the tab has no file path
    (a relative reference would not resolve in the preview or the export).
    """
    text = (
        importlib.resources.files("epy_reports._config._assets")
        .joinpath(filename)
        .read_text(encoding="utf-8")
    )
    # Resolve bundled images (logo + screenshots) to absolute file:// URIs.
    # The welcome tab has no file path, so relative image references would
    # not resolve in the preview or the export.
    assets = {
        "__EPY_LOGO__": ("branding", "epy_reports.png"),
        "__SHOT_EDITOR__": ("screenshots", "editor.png"),
        "__SHOT_PROPERTIES__": ("screenshots", "document_properties.png"),
        "__SHOT_FIGURE__": ("screenshots", "dlg_figure.png"),
        "__SHOT_TABLE__": ("screenshots", "dlg_table.png"),
        "__SHOT_EQUATION__": ("screenshots", "dlg_equation.png"),
        "__SHOT_CHECKLIST__": ("screenshots", "dlg_checklist.png"),
        "__SHOT_FOOTNOTE__": ("screenshots", "dlg_footnote.png"),
        "__SHOT_XREF__": ("screenshots", "dlg_xref.png"),
        "__SHOT_BIB__": ("screenshots", "dlg_bib.png"),
        "__SHOT_THEME_EDITOR__": ("screenshots", "dlg_theme.png"),
    }
    # The Spanish manual (``welcome_es.md``) uses the same placeholders but
    # resolves them to the localized screenshot variants (``*_es.png``) when
    # those exist, so it shows the UI in Spanish. The logo is shared.
    is_es = Path(filename).stem.endswith("_es")
    root = importlib.resources.files("epy_reports._config._assets")
    for placeholder, (subdir, name) in assets.items():
        if is_es and subdir == "screenshots":
            stem, _, ext = name.rpartition(".")
            es_name = f"{stem}_es.{ext}"
            try:
                if root.joinpath(subdir).joinpath(es_name).is_file():
                    name = es_name
            except OSError:
                pass
        try:
            res = root.joinpath(subdir).joinpath(name)
            uri = Path(str(res)).resolve().as_uri()
        except (FileNotFoundError, ValueError, OSError):
            uri = ""
        text = text.replace(placeholder, uri)
    return text


WELCOME_TEXT = _load_manual_text("welcome.md")


class MarkdownWindow(QMainWindow):
    """Main window: holds a tab bar with one MarkdownTab per file."""

    def __init__(self) -> None:
        """Build the tab widget, toolbar, menu, and welcome tab."""
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1280, 820)

        self.tabs = QTabWidget(self)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self._close_tab_at)
        self.tabs.currentChanged.connect(self._on_current_changed)
        self.setCentralWidget(self.tabs)
        self.setStatusBar(QStatusBar(self))

        self._build_actions()
        self._build_format_actions()
        self._build_insert_actions()
        self._build_menu()
        self._build_toolbar()
        # Every command lives in the toolbar dropdowns; hide the
        # legacy menu bar so we don't show two stacked top rows.
        self.menuBar().hide()

        self.setAcceptDrops(True)

        # Autosave and the export guards both depend on this counter.
        self._exports_in_flight = 0

        # Load persisted theme (defaults to EPY when nothing is saved).
        self._settings = QSettings(ORGANIZATION, "epy_reports")
        saved_theme = str(
            self._settings.value("theme", themes.DEFAULT_THEME_ID)
        )
        self._current_theme: themes.Theme = themes.get(saved_theme)
        self._apply_theme(self._current_theme.id, persist=False)

        # Restore the persisted A4 page-view preference and apply it.
        self._paged_enabled = (
            str(self._settings.value("paged", "false")).lower() == "true"
        )
        self.act_page_view.setChecked(self._paged_enabled)
        self._apply_paged(self._paged_enabled)

        # Restore the persisted autosave preference. The timer must exist
        # BEFORE setChecked: the action's toggled signal is already wired.
        self._autosave_enabled = (
            str(self._settings.value("autosave", "false")).lower() == "true"
        )
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(AUTOSAVE_INTERVAL_MS)
        self._autosave_timer.timeout.connect(self._autosave_current)
        # Setting the check state also starts/stops the repeating timer via
        # the toggled handler, so restoring the preference restores both.
        self.act_autosave.setChecked(self._autosave_enabled)

        # Internationalization: snapshot the English chrome, then apply the
        # persisted language. Switching later relabels the UI live.
        self._capture_i18n()
        i18n.on_language_changed(self._retranslate_ui)
        saved_lang = str(self._settings.value("language", "en"))
        if saved_lang in i18n.LANGUAGES and saved_lang != "en":
            i18n.set_language(saved_lang)
        self._sync_language_menu()

        # Window icon (title bar + taskbar).
        logo_pix = _load_branding_pixmap("epy_reports.png")
        if not logo_pix.isNull():
            self.setWindowIcon(QIcon(logo_pix))

        self._open_welcome_tab()

    # ------------------------------------------------- actions/menus

    def _build_actions(self) -> None:
        """Create all QActions used by the menu and the toolbar."""
        self.act_new = QAction("New", self)
        self.act_new.setShortcut(QKeySequence.StandardKey.New)
        self.act_new.triggered.connect(self._new_tab)

        self.act_open = QAction("Open...", self)
        self.act_open.setShortcut(QKeySequence.StandardKey.Open)
        self.act_open.triggered.connect(self._open_dialog)

        self.act_save = QAction("Save", self)
        self.act_save.setShortcut(QKeySequence.StandardKey.Save)
        self.act_save.triggered.connect(self._save_current)

        self.act_save_as = QAction("Save As...", self)
        self.act_save_as.setShortcut(QKeySequence.StandardKey.SaveAs)
        self.act_save_as.triggered.connect(self._save_current_as)

        self.act_reload = QAction("Reload", self)
        self.act_reload.setShortcut("F5")
        self.act_reload.triggered.connect(self._reload_current)

        self.act_close = QAction("Close Tab", self)
        self.act_close.setShortcut(QKeySequence.StandardKey.Close)
        self.act_close.triggered.connect(self._close_current_tab)

        self.act_pdf = QAction("Export as PDF...", self)
        self.act_pdf.setShortcut(QKeySequence("Ctrl+P"))
        self.act_pdf.triggered.connect(self._export_pdf)

        self.act_export_html = QAction("Export as HTML...", self)
        self.act_export_html.setShortcut(QKeySequence("Ctrl+Shift+P"))
        self.act_export_html.triggered.connect(self._export_html)

        self.act_export_docx = QAction("Export as DOCX...", self)
        self.act_export_docx.setShortcut(QKeySequence("Ctrl+Shift+D"))
        self.act_export_docx.triggered.connect(self._export_docx)

        self.act_print = QAction("Print...", self)
        self.act_print.setShortcut(QKeySequence("Ctrl+Alt+P"))
        self.act_print.triggered.connect(self._print_document)

        self.act_doc_properties = QAction("Document properties…", self)
        self.act_doc_properties.setShortcut(QKeySequence("Ctrl+Shift+Y"))
        self.act_doc_properties.triggered.connect(
            self._edit_document_properties
        )

        self.act_quit = QAction("Quit", self)
        self.act_quit.setShortcut(QKeySequence.StandardKey.Quit)
        self.act_quit.triggered.connect(self.close)

        self.act_manual_en = QAction("User manual (English)", self)
        self.act_manual_en.triggered.connect(
            lambda: self._open_manual("welcome.md")
        )
        self.act_manual_es = QAction("User manual (Spanish)", self)
        self.act_manual_es.triggered.connect(
            lambda: self._open_manual("welcome_es.md")
        )

        self.act_about = QAction("About epy_reports…", self)
        self.act_about.triggered.connect(self._show_about)

        self.act_page_view = QAction("Page view", self, checkable=True)
        self.act_page_view.setShortcut(QKeySequence("Ctrl+Shift+A"))
        self.act_page_view.toggled.connect(self._toggle_page_view)

        self.act_autosave = QAction("Autosave", self, checkable=True)
        self.act_autosave.toggled.connect(self._toggle_autosave)

        self.act_docs_export = QAction("Export via epy_docs...", self)
        if epy_docs_available():
            self.act_docs_export.triggered.connect(
                self._export_via_docs
            )
        else:
            self.act_docs_export.setEnabled(False)
            self.act_docs_export.setToolTip(
                i18n.tr("Requires the epy-docs package")
            )

        # Theme radio actions (one per registered theme, exclusive group).
        self._build_theme_actions()

        # Custom-theme editor actions (live in the Theme submenu).
        self.act_theme_gallery = QAction("Browse themes…", self)
        self.act_theme_gallery.triggered.connect(self._open_theme_gallery)
        self.act_new_theme = QAction("New theme…", self)
        self.act_new_theme.triggered.connect(
            lambda: self._open_theme_editor(edit_id=None)
        )
        self.act_edit_theme = QAction("Edit current theme…", self)
        self.act_edit_theme.triggered.connect(self._edit_current_theme)
        self.act_delete_theme = QAction("Delete custom theme…", self)
        self.act_delete_theme.triggered.connect(self._delete_custom_theme)

        # Page-size actions (Letter default, exclusive group). The key
        # is stored as action data and written into the document's
        # ``page-size`` front matter when chosen.
        from epy_reports._core.renderer import PAGE_SIZES  # noqa: PLC0415

        self.page_size_group = QActionGroup(self)
        self.page_size_group.setExclusive(True)
        self.page_size_actions: dict[str, QAction] = {}
        for key in PAGE_SIZES:
            act = QAction(key.title(), self, checkable=True)
            act.setData(key)
            self.page_size_group.addAction(act)
            self.page_size_actions[key] = act
        self.page_size_group.triggered.connect(
            lambda action: self._set_page_size(action.data())
        )

        # Language actions (English / Spanish, exclusive group). The
        # endonyms ("English" / "Español") are intentionally NOT
        # translated; the rest of the UI is, via _retranslate_ui.
        self.lang_group = QActionGroup(self)
        self.lang_group.setExclusive(True)
        self.lang_actions: dict[str, QAction] = {}
        for code, name in i18n.LANGUAGES.items():
            act = QAction(name, self, checkable=True)
            act.setData(code)
            self.lang_group.addAction(act)
            self.lang_actions[code] = act
        self.lang_group.triggered.connect(
            lambda action: self._set_language(action.data())
        )

    def _on_active_tab(self, fn_name: str, *args) -> None:
        """Forward an action to the active tab if there is one."""
        tab = self._current_tab()
        if tab is None:
            return
        method = getattr(tab, fn_name)
        method(*args)

    def _build_format_actions(self) -> None:
        """Create text-formatting actions (headings, bold/italic, ...)."""
        self.heading_actions: list[QAction] = []
        for level in range(1, 7):
            act = QAction(
                i18n.tr("Heading {level}").format(level=level),
                self,
            )
            act.setShortcut(QKeySequence(f"Ctrl+{level}"))
            act.triggered.connect(
                lambda checked=False, lv=level: self._on_active_tab(
                    "set_heading_level", lv
                )
            )
            self.heading_actions.append(act)

        self.act_no_heading = QAction("Remove heading", self)
        self.act_no_heading.setShortcut(QKeySequence("Ctrl+0"))
        self.act_no_heading.triggered.connect(
            lambda: self._on_active_tab("set_heading_level", 0)
        )

        self.act_bold = QAction("Bold", self)
        self.act_bold.setShortcut(QKeySequence("Ctrl+B"))
        self.act_bold.triggered.connect(
            lambda: self._on_active_tab("toggle_bold")
        )

        self.act_italic = QAction("Italic", self)
        self.act_italic.setShortcut(QKeySequence("Ctrl+I"))
        self.act_italic.triggered.connect(
            lambda: self._on_active_tab("toggle_italic")
        )

        self.act_inline_code = QAction("Inline code", self)
        self.act_inline_code.setShortcut(QKeySequence("Ctrl+E"))
        self.act_inline_code.triggered.connect(
            lambda: self._on_active_tab("toggle_inline_code")
        )

        self.act_link = QAction("Link...", self)
        self.act_link.setShortcut(QKeySequence("Ctrl+K"))
        self.act_link.triggered.connect(
            lambda: self._on_active_tab("insert_link")
        )

    def _build_insert_actions(self) -> None:
        """Create block-insertion actions (figure/table/eq/callout)."""
        self.act_ins_section = QAction(
            "Section heading with label", self
        )
        self.act_ins_section.setShortcut(QKeySequence("Ctrl+Shift+H"))
        self.act_ins_section.triggered.connect(
            lambda: self._on_active_tab("insert_section_heading")
        )

        self.act_ins_figure = QAction("Figure (skeleton)", self)
        self.act_ins_figure.setShortcut(QKeySequence("Ctrl+Shift+F"))
        self.act_ins_figure.triggered.connect(
            lambda: self._on_active_tab("insert_figure")
        )

        self.act_ins_image = QAction("Image from file...", self)
        self.act_ins_image.setShortcut(QKeySequence("Ctrl+Shift+I"))
        self.act_ins_image.triggered.connect(
            lambda: self._on_active_tab("insert_image_from_dialog")
        )

        self.act_ins_table = QAction("Table", self)
        self.act_ins_table.setShortcut(QKeySequence("Ctrl+Shift+T"))
        self.act_ins_table.triggered.connect(
            lambda: self._on_active_tab("insert_table")
        )

        self.act_ins_checklist = QAction("Checklist", self)
        self.act_ins_checklist.setShortcut(QKeySequence("Ctrl+Shift+L"))
        self.act_ins_checklist.triggered.connect(
            lambda: self._on_active_tab("insert_checklist")
        )

        self.act_ins_two_columns = QAction("Two-column block", self)
        self.act_ins_two_columns.setShortcut(QKeySequence("Ctrl+Shift+2"))
        self.act_ins_two_columns.triggered.connect(
            lambda: self._on_active_tab("insert_two_columns")
        )

        self.act_ins_three_columns = QAction("Three-column block", self)
        self.act_ins_three_columns.setShortcut(QKeySequence("Ctrl+Shift+3"))
        self.act_ins_three_columns.triggered.connect(
            lambda: self._on_active_tab("insert_three_columns")
        )

        self.act_ins_equation = QAction("Equation", self)
        self.act_ins_equation.setShortcut(QKeySequence("Ctrl+Shift+Q"))
        self.act_ins_equation.triggered.connect(
            lambda: self._on_active_tab("insert_equation")
        )

        self.act_ins_code_block = QAction("Code block", self)
        self.act_ins_code_block.setShortcut(QKeySequence("Ctrl+Shift+K"))
        self.act_ins_code_block.triggered.connect(
            lambda: self._on_active_tab("insert_code_block")
        )

        # Shared design blocks (cards, big stats, timelines, agendas) opened
        # through a visual picker, like the slide-layout picker in epy_slides.
        self.act_design_block = QAction("Design block…", self)
        self.act_design_block.triggered.connect(
            self._open_design_block_picker
        )

        self.act_ins_footnote = QAction("Footnote", self)
        self.act_ins_footnote.setShortcut(QKeySequence("Ctrl+Shift+O"))
        self.act_ins_footnote.triggered.connect(
            lambda: self._on_active_tab("insert_footnote")
        )

        self.act_ins_page_break = QAction("Page break", self)
        self.act_ins_page_break.setShortcut(QKeySequence("Ctrl+Shift+G"))
        self.act_ins_page_break.triggered.connect(
            lambda: self._on_active_tab("insert_page_break")
        )

        self.act_ins_section_roman = QAction(
            "Section break (Roman i, ii, iii)", self
        )
        self.act_ins_section_roman.triggered.connect(
            lambda: self._on_active_tab(
                "insert_index_marker", "section-roman"
            )
        )
        self.act_ins_section_arabic = QAction(
            "Section break (Arabic 1, 2, 3)", self
        )
        self.act_ins_section_arabic.triggered.connect(
            lambda: self._on_active_tab(
                "insert_index_marker", "section-arabic"
            )
        )

        self.act_ins_toc = QAction("Table of contents  [[toc]]", self)
        self.act_ins_toc.setShortcut(QKeySequence("Ctrl+Shift+U"))
        self.act_ins_toc.triggered.connect(
            lambda: self._on_active_tab("insert_index_marker", "toc")
        )

        self.act_ins_lof = QAction("List of figures  [[lof]]", self)
        self.act_ins_lof.triggered.connect(
            lambda: self._on_active_tab("insert_index_marker", "lof")
        )

        self.act_ins_lot = QAction("List of tables  [[lot]]", self)
        self.act_ins_lot.triggered.connect(
            lambda: self._on_active_tab("insert_index_marker", "lot")
        )

        self.act_ins_loe = QAction("List of equations  [[loe]]", self)
        self.act_ins_loe.triggered.connect(
            lambda: self._on_active_tab("insert_index_marker", "loe")
        )

        self.callout_actions: list[QAction] = []
        for kind in ("note", "tip", "warning", "important", "caution"):
            act = QAction(
                i18n.tr("Callout: {kind}").format(
                    kind=kind.title()
                ),
                self,
            )
            act.triggered.connect(
                lambda checked=False, k=kind: self._on_active_tab(
                    "insert_callout", k
                )
            )
            self.callout_actions.append(act)
        # Convenience: Ctrl+Shift+C inserts a basic note callout.
        self.callout_actions[0].setShortcut(QKeySequence("Ctrl+Shift+C"))

        from epy_reports._core._design import (  # noqa: PLC0415
            DISCLOSURE_PRESETS,
        )
        self.disclosure_actions: list[QAction] = []
        for d_kind, (d_label, _d_text) in DISCLOSURE_PRESETS.items():
            d_act = QAction(
                i18n.tr("Disclosure: {label}").format(
                    label=d_label
                ),
                self,
            )
            d_act.triggered.connect(
                lambda checked=False, k=d_kind: self._on_active_tab(
                    "insert_disclosure", k
                )
            )
            self.disclosure_actions.append(d_act)

        self.act_cross_ref = QAction("Insert reference...", self)
        self.act_cross_ref.setShortcut(QKeySequence("Ctrl+R"))
        self.act_cross_ref.triggered.connect(
            lambda: self._on_active_tab("insert_cross_reference")
        )

        self.act_link_bib = QAction(
            "Link bibliography (.bib)...", self
        )
        self.act_link_bib.setShortcut(QKeySequence("Ctrl+Shift+B"))
        self.act_link_bib.triggered.connect(self._link_bibliography)

        self.act_new_bib_entry = QAction(
            "New bibliography entry...", self
        )
        self.act_new_bib_entry.setShortcut(QKeySequence("Ctrl+Shift+N"))
        self.act_new_bib_entry.triggered.connect(self._new_bib_entry)

        # Citation style — IEEE by default, APA / Chicago selectable.
        from epy_reports._core.renderer import CSL_STYLES  # noqa: PLC0415

        self.csl_group = QActionGroup(self)
        self.csl_group.setExclusive(True)
        self.csl_actions: dict[str, QAction] = {}
        for key in CSL_STYLES:
            act = QAction(key.upper(), self, checkable=True)
            act.triggered.connect(
                lambda _checked=False, k=key: self._set_csl_style(k)
            )
            self.csl_group.addAction(act)
            self.csl_actions[key] = act

    def _build_menu(self) -> None:
        """Build content menus as plain ``QMenu`` objects.

        The toolbar reuses these objects via popup ``QToolButton``s,
        so we deliberately do NOT add them to the native menu bar —
        that would double the top chrome. The native menu bar is
        hidden once everything is built.
        """
        self.file_menu = QMenu("&File", self)
        self.file_menu.addAction(self.act_new)
        self.file_menu.addAction(self.act_open)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.act_save)
        self.file_menu.addAction(self.act_save_as)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.act_reload)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.act_close)
        self.file_menu.addAction(self.act_quit)

        self.text_menu = QMenu("&Text", self)
        self.heading_sub = self.text_menu.addMenu("Heading")
        for act in self.heading_actions:
            self.heading_sub.addAction(act)
        self.heading_sub.addSeparator()
        self.heading_sub.addAction(self.act_no_heading)
        self.text_menu.addSeparator()
        self.text_menu.addAction(self.act_bold)
        self.text_menu.addAction(self.act_italic)
        self.text_menu.addAction(self.act_inline_code)
        self.text_menu.addSeparator()
        self.text_menu.addAction(self.act_link)

        self.elements_menu = QMenu("&Elements", self)
        self.elements_menu.addAction(self.act_ins_section)
        self.elements_menu.addSeparator()
        self.elements_menu.addAction(self.act_ins_figure)
        self.elements_menu.addAction(self.act_ins_image)
        self.elements_menu.addSeparator()
        self.elements_menu.addAction(self.act_ins_table)
        self.elements_menu.addAction(self.act_ins_checklist)
        self.elements_menu.addAction(self.act_ins_two_columns)
        self.elements_menu.addAction(self.act_ins_three_columns)
        self.elements_menu.addAction(self.act_ins_equation)
        self.elements_menu.addAction(self.act_ins_footnote)
        self.elements_menu.addSeparator()
        self.elements_menu.addAction(self.act_ins_code_block)
        self.callout_sub = self.elements_menu.addMenu("Callout")
        for act in self.callout_actions:
            self.callout_sub.addAction(act)
        self.disclosure_sub = self.elements_menu.addMenu(
            i18n.tr("Disclosure")
        )
        for act in self.disclosure_actions:
            self.disclosure_sub.addAction(act)
        self.elements_menu.addAction(self.act_design_block)
        self.elements_menu.addSeparator()
        self.elements_menu.addAction(self.act_ins_page_break)
        self.elements_menu.addAction(self.act_ins_section_roman)
        self.elements_menu.addAction(self.act_ins_section_arabic)
        self.indexes_sub = self.elements_menu.addMenu("Indexes")
        self.indexes_sub.addAction(self.act_ins_toc)
        self.indexes_sub.addAction(self.act_ins_lof)
        self.indexes_sub.addAction(self.act_ins_lot)
        self.indexes_sub.addAction(self.act_ins_loe)

        self.references_menu = QMenu("&References", self)
        self.references_menu.aboutToShow.connect(
            self._populate_references_menu
        )
        self._populate_references_menu()

        self.export_menu = QMenu("E&xport", self)
        self.export_menu.addAction(self.act_pdf)
        self.export_menu.addAction(self.act_export_html)
        self.export_menu.addAction(self.act_export_docx)
        self.export_menu.addSeparator()
        self.export_menu.addAction(self.act_print)
        self.export_menu.addSeparator()
        self.export_menu.addAction(self.act_docs_export)

        self.view_menu = QMenu("&View", self)
        self.theme_sub = self.view_menu.addMenu("Theme")
        self._populate_theme_menu()
        self.view_menu.addSeparator()
        self.view_menu.addAction(self.act_page_view)
        self.view_menu.addAction(self.act_autosave)
        self.page_size_menu = self.view_menu.addMenu("Page size")
        for act in self.page_size_group.actions():
            self.page_size_menu.addAction(act)
        # Tick the radio matching the current document each time the
        # submenu opens, mirroring the Citation-style pattern.
        self.page_size_menu.aboutToShow.connect(
            self._sync_page_size_menu
        )
        self.language_menu = self.view_menu.addMenu("Language")
        for act in self.lang_group.actions():
            self.language_menu.addAction(act)

        self.document_menu = QMenu("&Document", self)
        self.document_menu.addAction(self.act_doc_properties)

        self._build_templates_menu()

        self.help_menu = QMenu("&Help", self)
        self.help_menu.addAction(self.act_manual_en)
        self.help_menu.addAction(self.act_manual_es)
        self.help_menu.addSeparator()
        self.help_menu.addAction(self.act_about)

    def _build_toolbar(self) -> None:
        """Toolbar: five dropdowns + reload."""
        bar = QToolBar("Main", self)
        bar.setMovable(False)
        self.addToolBar(bar)

        # (button, english_text) pairs so the labels can be retranslated.
        self._toolbar_buttons: list[tuple[QToolButton, str]] = []

        self._add_dropdown(bar, "File", self.file_menu)
        self._add_dropdown(bar, "Text", self.text_menu)
        self._add_dropdown(bar, "Elements", self.elements_menu)
        self._add_dropdown(bar, "Document", self.document_menu)
        self._add_dropdown(bar, "References", self.references_menu)
        self._add_dropdown(bar, "Export", self.export_menu)
        self._add_dropdown(bar, "View", self.view_menu)
        self._add_dropdown(bar, "Templates", self.templates_menu)
        self._add_dropdown(bar, "Help", self.help_menu)

        bar.addSeparator()
        bar.addAction(self.act_reload)

    def _add_dropdown(
        self, bar: QToolBar, text: str, menu: QMenu
    ) -> None:
        """Add a popup-style QToolButton to ``bar`` that opens ``menu``."""
        btn = QToolButton(self)
        btn.setText(i18n.tr(text))
        btn.setMenu(menu)
        btn.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        bar.addWidget(btn)
        self._toolbar_buttons.append((btn, text))

    # --------------------------------------------- internationalization

    def _capture_i18n(self) -> None:
        """Snapshot the English text of every stable action/menu.

        The map drives :meth:`_retranslate_ui`, so the source text stays the
        translation key even after the label has been switched to Spanish.
        """
        self._tr_actions: dict[QAction, str] = {}
        self._tr_menus: dict[QMenu, str] = {}
        for obj in vars(self).values():
            if isinstance(obj, QAction):
                if obj.text():
                    self._tr_actions[obj] = obj.text()
            elif isinstance(obj, QMenu):
                if obj.title():
                    self._tr_menus[obj] = obj.title()
            elif isinstance(obj, QActionGroup):
                for act in obj.actions():
                    if act.text():
                        self._tr_actions[act] = act.text()
            elif isinstance(obj, list):
                for act in obj:
                    if isinstance(act, QAction) and act.text():
                        self._tr_actions[act] = act.text()
            elif isinstance(obj, dict):
                for act in obj.values():
                    if isinstance(act, QAction) and act.text():
                        self._tr_actions[act] = act.text()

    def _retranslate_ui(self) -> None:
        """Re-apply translations to every captured widget (live switch)."""
        for action, english in self._tr_actions.items():
            action.setText(i18n.tr(english))
        for menu, english in self._tr_menus.items():
            menu.setTitle(i18n.tr(english))
        for btn, english in getattr(self, "_toolbar_buttons", []):
            btn.setText(i18n.tr(english))
        self._sync_language_menu()
        # Re-render every open preview: numbered captions and index
        # titles follow the app language when the document has no lang:.
        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            if isinstance(widget, MarkdownTab):
                widget.refresh_preview()

    def _set_language(self, code: str) -> None:
        """Persist the chosen UI language and relabel the UI live."""
        self._settings.setValue("language", code)
        i18n.set_language(code)

    def _sync_language_menu(self) -> None:
        """Tick the radio item matching the active language."""
        act = self.lang_actions.get(i18n.current_language())
        if act is not None:
            act.setChecked(True)

    # --------------------------------------------- references menu

    def _populate_references_menu(self) -> None:
        """Rebuild the References dropdown from the current buffer.

        The menu has three groups:

        * Buffer labels (figures / tables / equations / sections),
          grouped by kind.
        * Citations from the linked ``bibliography:`` file, when one
          is set in YAML front matter.
        * Actions to link a new ``.bib`` or open the cross-ref
          picker dialog.
        """
        menu = self.references_menu
        menu.clear()
        tab = self._current_tab()
        if tab is None:
            placeholder = menu.addAction(i18n.tr("(no document open)"))
            placeholder.setEnabled(False)
            menu.addSeparator()
            menu.addAction(self.act_link_bib)
            menu.addAction(self.act_cross_ref)
            return

        text = tab.text()
        labels = snippets.find_labels(text)
        bib_entries = tab.bib_entries()

        if not labels:
            placeholder = menu.addAction(i18n.tr("(no labels in this file)"))
            placeholder.setEnabled(False)
        else:
            groups: defaultdict[str, list[snippets.Label]] = (
                defaultdict(list)
            )
            for label in labels:
                groups[label.kind].append(label)
            for kind in ("fig", "tbl", "eq", "sec"):
                if kind not in groups:
                    continue
                title = i18n.tr(
                    snippets.KIND_DESCRIPTIONS.get(kind, kind) + "s"
                )
                sub = menu.addMenu(title)
                for label in groups[kind]:
                    act = sub.addAction(f"@{label.name}")
                    act.triggered.connect(
                        lambda checked=False, n=label.name:
                        self._insert_cross_ref_name(n)
                    )

        if bib_entries:
            menu.addSeparator()
            cite_sub = menu.addMenu(
                f"{i18n.tr('Citations')} ({len(bib_entries)})"
            )
            for entry in bib_entries:
                act = cite_sub.addAction(entry.short_label())
                act.setToolTip(
                    f"{entry.type} — {entry.title}"
                    if entry.title
                    else entry.type
                )
                act.triggered.connect(
                    lambda checked=False, k=entry.key:
                    self._insert_cross_ref_name(k)
                )

        menu.addSeparator()
        menu.addAction(self.act_link_bib)
        menu.addAction(self.act_new_bib_entry)
        style_sub = menu.addMenu("Citation style")
        current_style = self._current_csl_key_from_tab(tab)
        for key, act in self.csl_actions.items():
            act.setChecked(key == current_style)
            style_sub.addAction(act)
        menu.addAction(self.act_cross_ref)

    def _insert_cross_ref_name(self, name: str) -> None:
        """Insert ``@name`` at the active tab's caret."""
        tab = self._current_tab()
        if tab is None:
            return
        tab.editor.insertPlainText(f"@{name}")
        tab.editor.setFocus()

    # -------------------------------------------------------- themes

    def _apply_theme(self, theme_id: str, *, persist: bool = True) -> None:
        """Switch the application + every tab to ``theme_id``.

        Args:
            theme_id: Identifier from :data:`themes.THEMES`.
            persist: When ``True`` save the choice to QSettings so it
                survives between sessions. ``False`` is used during
                startup so we do not overwrite the same value.
        """
        theme = themes.get(theme_id)
        self._current_theme = theme
        app = QApplication.instance()
        if isinstance(app, QApplication):
            themes.apply_palette(app, theme)
            app.setStyleSheet(themes.qss_for(theme))

        css = document_css(theme)
        page_bg = theme.css_vars.get("bg", "")
        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            if isinstance(widget, MarkdownTab):
                widget.set_theme_css(css, page_bg)

        if theme.id in self.theme_actions:
            self.theme_actions[theme.id].setChecked(True)

        if persist:
            self._settings.setValue("theme", theme.id)
            self.statusBar().showMessage(
                i18n.tr("Theme: {name}").format(
                    name=theme.display_name
                ),
                2000,
            )

    def _build_theme_actions(self) -> None:
        """(Re)create the exclusive group of theme radio actions."""
        self.theme_group = QActionGroup(self)
        self.theme_group.setExclusive(True)
        self.theme_actions: dict[str, QAction] = {}
        for theme in themes.THEMES.values():
            act = QAction(theme.display_name, self, checkable=True)
            act.setData(theme.id)
            self.theme_group.addAction(act)
            self.theme_actions[theme.id] = act
        self.theme_group.triggered.connect(
            lambda action: self._apply_theme(action.data())
        )

    def _populate_theme_menu(self) -> None:
        """Fill the Theme submenu: theme radios + custom-theme actions."""
        self.theme_sub.clear()
        for act in self.theme_group.actions():
            self.theme_sub.addAction(act)
        self.theme_sub.addSeparator()
        self.theme_sub.addAction(self.act_theme_gallery)
        self.theme_sub.addAction(self.act_new_theme)
        self.theme_sub.addAction(self.act_edit_theme)
        self.theme_sub.addAction(self.act_delete_theme)

    def _refresh_themes(self, select_id: str | None = None) -> None:
        """Reload bundled + user themes and rebuild the Theme submenu."""
        # Drop the soon-to-be-replaced theme actions from the i18n map so
        # _retranslate_ui never touches deleted QAction objects.
        for act in self.theme_group.actions():
            self._tr_actions.pop(act, None)
        themes.reload()
        self._build_theme_actions()
        self._populate_theme_menu()
        # Register the new theme actions for live retranslation.
        for act in self.theme_group.actions():
            self._tr_actions[act] = act.text()
        if i18n.current_language() != "en":
            self._retranslate_ui()
        if select_id:
            self._apply_theme(select_id)

    def _open_theme_gallery(self) -> None:
        """Open the theme gallery; apply the chosen theme on accept."""
        from epy_reports._ui.theme_gallery_dialog import (  # noqa: PLC0415
            ThemeGalleryDialog,
        )

        dialog = ThemeGalleryDialog(self, current_id=self._current_theme.id)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        theme_id = dialog.selected_theme_id()
        if theme_id:
            self._apply_theme(theme_id)

    def _open_design_block_picker(self) -> None:
        """Open the design-block picker; insert the chosen block on accept."""
        from epy_reports._ui.design_block_dialog import (  # noqa: PLC0415
            DesignBlockDialog,
        )

        dialog = DesignBlockDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        kind = dialog.selected_kind()
        if kind:
            self._on_active_tab("insert_design_block", kind)

    def _open_theme_editor(self, edit_id: str | None = None) -> None:
        """Open the theme editor; on save, persist and select the theme."""
        from epy_reports._ui.theme_editor_dialog import (  # noqa: PLC0415
            ThemeEditorDialog,
        )

        dialog = ThemeEditorDialog(
            self, base_theme_id=self._current_theme.id, edit_id=edit_id
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            theme_id = themes.save_user_theme(dialog.epyson_payload())
        except OSError as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        self._refresh_themes(select_id=theme_id)
        self.statusBar().showMessage(
            i18n.tr("Theme saved: {name}").format(name=dialog.theme_name()),
            3000,
        )

    def _edit_current_theme(self) -> None:
        """Edit the active theme in place if custom, otherwise clone it."""
        current = self._current_theme.id
        edit_id = current if current in themes.user_theme_ids() else None
        self._open_theme_editor(edit_id=edit_id)

    def _delete_custom_theme(self) -> None:
        """Delete a custom theme chosen from the user-generated set."""
        from PySide6.QtWidgets import QInputDialog  # noqa: PLC0415

        user_ids = sorted(themes.user_theme_ids())
        if not user_ids:
            QMessageBox.information(
                self, APP_NAME, i18n.tr("No custom themes to delete.")
            )
            return
        names = [themes.THEMES[i].display_name for i in user_ids]
        choice, ok = QInputDialog.getItem(
            self, i18n.tr("Delete custom theme…"),
            i18n.tr("Theme:"), names, 0, False,
        )
        if not ok:
            return
        theme_id = user_ids[names.index(choice)]
        confirm = QMessageBox.question(
            self, APP_NAME,
            i18n.tr("Delete the custom theme {name}?").format(name=choice),
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        themes.delete_user_theme(theme_id)
        fallback = (
            themes.DEFAULT_THEME_ID
            if self._current_theme.id == theme_id
            else self._current_theme.id
        )
        self._refresh_themes(select_id=fallback)

    def _toggle_page_view(self, enabled: bool) -> None:
        """Toggle A4 page view on every tab and persist the choice."""
        self._paged_enabled = enabled
        self._apply_paged(enabled)
        self._settings.setValue("paged", "true" if enabled else "false")
        message = (
            i18n.tr("Page view: on")
            if enabled
            else i18n.tr("Page view: off")
        )
        self.statusBar().showMessage(message, 2000)

    def _toggle_autosave(self, enabled: bool) -> None:
        """Toggle periodic autosave and persist the choice."""
        self._settings.setValue("autosave", "true" if enabled else "false")
        if enabled:
            self._autosave_timer.start()
        else:
            self._autosave_timer.stop()

    def _autosave_current(self) -> None:
        """Autosave the current tab when it is safe to do so.

        The slot deliberately avoids ``_save_current``: an autosave must
        never open the Save As dialog for an untitled buffer, and it must
        yield while an export is using the current document.
        """
        if not self.act_autosave.isChecked():
            return
        if self._exports_in_flight > 0:
            return
        tab = self._current_tab()
        if tab is None or not tab.dirty:
            return
        if tab.save():
            self._refresh_tab_title(tab)
            self.statusBar().showMessage(
                i18n.tr("Autosaved: {path}").format(path=str(tab.path)),
                3000,
            )

    def _apply_paged(self, enabled: bool) -> None:
        """Forward the page-view flag to every open tab."""
        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            if isinstance(widget, MarkdownTab):
                widget.set_paged(enabled)

    def _current_page_size_from_tab(self) -> str:
        """Return the active document's page-size key (default Letter)."""
        from epy_reports._core.renderer import (  # noqa: PLC0415
            DEFAULT_PAGE_SIZE,
            normalize_page_size,
        )

        tab = self._current_tab()
        if tab is None:
            return DEFAULT_PAGE_SIZE
        meta = snippets.parse_front_matter(tab.editor.toPlainText())
        return normalize_page_size(meta.get("page-size"))

    def _sync_page_size_menu(self) -> None:
        """Check the radio matching the current document's page size."""
        current = self._current_page_size_from_tab()
        for key, act in self.page_size_actions.items():
            act.setChecked(key == current)

    def _set_page_size(self, key: str) -> None:
        """Write ``page-size: <key>`` into the active tab and re-render."""
        tab = self._current_tab()
        if tab is None:
            return
        text = tab.editor.toPlainText()
        updated = snippets.set_metadata_field(text, "page-size", key)
        if updated == text:
            self.statusBar().showMessage(
                i18n.tr("Page size: {name} (no change)").format(
                    name=key.title()
                ),
                3000,
            )
            return
        cursor = tab.editor.textCursor()
        cursor.beginEditBlock()
        cursor.select(cursor.SelectionType.Document)
        cursor.insertText(updated)
        cursor.endEditBlock()
        self.statusBar().showMessage(
            i18n.tr("Page size: {name}").format(name=key.title()), 3000
        )

    def _show_about(self) -> None:
        """Open the About epy_reports dialog modally."""
        from epy_reports._ui.about_dialog import AboutDialog  # noqa: PLC0415

        dlg = AboutDialog(self)
        dlg.exec()

    # ----------------------------------------------- config templates

    def _build_templates_menu(self) -> None:
        """Build the Templates dropdown (save / apply / delete)."""
        self.templates_menu = QMenu("&Templates", self)

        self.act_save_template = QAction(
            "Save current settings as template…", self
        )
        self.act_save_template.triggered.connect(self._save_template)

        self.apply_template_menu = QMenu("Apply template", self)
        self.delete_template_menu = QMenu("Delete template", self)

        self.templates_menu.addAction(self.act_save_template)
        self.templates_menu.addSeparator()
        self.templates_menu.addMenu(self.apply_template_menu)
        self.templates_menu.addMenu(self.delete_template_menu)

        # Rebuild the dynamic submenus right before they are shown so
        # newly saved templates appear without restarting the app.
        self.apply_template_menu.aboutToShow.connect(
            self._populate_apply_template_menu
        )
        self.delete_template_menu.aboutToShow.connect(
            self._populate_delete_template_menu
        )

    def _populate_apply_template_menu(self) -> None:
        """Rebuild the Apply-template submenu from disk."""
        from epy_reports._core import templates  # noqa: PLC0415

        menu = self.apply_template_menu
        menu.clear()
        names = templates.list_templates()
        if not names:
            placeholder = menu.addAction("(no templates saved)")
            placeholder.setEnabled(False)
            return
        for name in names:
            act = menu.addAction(name)
            act.triggered.connect(
                lambda _checked=False, n=name: self._apply_template(n)
            )

    def _populate_delete_template_menu(self) -> None:
        """Rebuild the Delete-template submenu from disk."""
        from epy_reports._core import templates  # noqa: PLC0415

        menu = self.delete_template_menu
        menu.clear()
        names = templates.list_templates()
        if not names:
            placeholder = menu.addAction("(no templates saved)")
            placeholder.setEnabled(False)
            return
        for name in names:
            act = menu.addAction(name)
            act.triggered.connect(
                lambda _checked=False, n=name: self._delete_template(n)
            )

    def _save_template(self) -> None:
        """Capture current config and save it under a chosen name."""
        from PySide6.QtWidgets import QInputDialog  # noqa: PLC0415

        from epy_reports._core import templates  # noqa: PLC0415

        name, ok = QInputDialog.getText(
            self, "Save template", "Template name:"
        )
        if not ok or not name.strip():
            return
        tab = self._current_tab()
        meta = (
            snippets.parse_front_matter(tab.editor.toPlainText())
            if tab is not None
            else {}
        )
        data = {
            "theme": self._current_theme.id,
            "csl": meta.get("csl", ""),
            "header": meta.get("header", ""),
            "footer": meta.get("footer", ""),
            "page_numbers": meta.get("page-numbers", ""),
            "page_size": meta.get("page-size", ""),
            "cover": meta.get("cover", ""),
            "logo": meta.get("logo", ""),
        }
        try:
            templates.save_template(name, data)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return
        self.statusBar().showMessage(
            i18n.tr("Saved template: {name}").format(
                name=name.strip()
            ),
            3000,
        )

    def _apply_template(self, name: str) -> None:
        """Apply a saved template: theme + front-matter keys."""
        from epy_reports._core import templates  # noqa: PLC0415

        try:
            tpl = templates.load_template(name)
        except (OSError, FileNotFoundError, ValueError) as exc:
            QMessageBox.warning(self, APP_NAME, str(exc))
            return

        theme_id = tpl.get("theme")
        if theme_id:
            self._apply_theme(theme_id)

        tab = self._current_tab()
        if tab is None:
            return
        # Map template keys to the front-matter field names (scalars).
        field_map = {
            "csl": "csl",
            "footer": "footer",
            "page_numbers": "page-numbers",
            "page_size": "page-size",
            "cover": "cover",
            "logo": "logo",
        }
        text = tab.editor.toPlainText()
        updated = text
        for key, field in field_map.items():
            value = tpl.get(key)
            if value in (None, ""):
                continue
            updated = snippets.set_metadata_field(
                updated, field, str(value)
            )
        # The running header is a YAML flow sequence (e.g. ["A", "B"]);
        # write it raw so the list literal is not quoted as a scalar.
        header = tpl.get("header")
        if header:
            updated = snippets.set_metadata_field(
                updated, "header", str(header), raw=True
            )
        if updated != text:
            cursor = tab.editor.textCursor()
            cursor.beginEditBlock()
            cursor.select(cursor.SelectionType.Document)
            cursor.insertText(updated)
            cursor.endEditBlock()
        self.statusBar().showMessage(
            i18n.tr("Applied template: {name}").format(name=name), 3000
        )

    def _delete_template(self, name: str) -> None:
        """Delete a saved template after confirmation."""
        from epy_reports._core import templates  # noqa: PLC0415

        choice = QMessageBox.question(
            self,
            i18n.tr("Delete template"),
            i18n.tr("Delete template '{name}'?").format(name=name),
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if choice != QMessageBox.StandardButton.Yes:
            return
        templates.delete_template(name)
        self.statusBar().showMessage(
            i18n.tr("Deleted template: {name}").format(name=name), 3000
        )

    @staticmethod
    def _localize_asset(tab: MarkdownTab, value: str) -> str:
        """Copy a picked image into the document's ``figures/`` directory.

        Returns a project-relative path (``figures/<name>``) so the logo or
        watermark travels with the document and resolves in the preview and
        every export. Values that are already relative, missing on disk, or
        belong to an unsaved document are returned unchanged.
        """
        src = Path(value)
        if tab.path is None or not src.is_absolute() or not src.is_file():
            return value
        figures = tab.path.parent / "figures"
        figures.mkdir(parents=True, exist_ok=True)
        dst = figures / src.name
        if src.resolve() != dst.resolve() and not dst.exists():
            shutil.copy2(str(src), str(dst))
        return f"figures/{dst.name}"

    def _edit_document_properties(self) -> None:
        """Open the Document properties form and write the front matter."""
        from epy_reports._ui.document_properties_dialog import (  # noqa: PLC0415
            DocumentPropertiesDialog,
        )

        tab = self._current_tab()
        if tab is None:
            return
        text = tab.editor.toPlainText()
        meta = snippets.parse_front_matter(text)
        dialog = DocumentPropertiesDialog(self, meta)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        updated = text
        for field, value, raw in dialog.updates():
            # Copy a picked logo / watermark into the project so it travels
            # with the document and resolves in the preview and exports.
            if field in ("logo", "watermark") and value:
                value = self._localize_asset(tab, value)
            updated = snippets.set_metadata_field(
                updated, field, value, raw=raw
            )
        if updated != text:
            cursor = tab.editor.textCursor()
            cursor.beginEditBlock()
            cursor.select(cursor.SelectionType.Document)
            cursor.insertText(updated)
            cursor.endEditBlock()
            # Repaint the preview immediately so the cover, logo and
            # watermark reflect the new properties without waiting.
            tab.set_theme_css(
                document_css(self._current_theme),
                self._current_theme.css_vars.get("bg", ""),
            )
        # Keep the page-size radio + preview in sync with any change.
        self._sync_page_size_menu()
        self.statusBar().showMessage(
            i18n.tr("Document properties updated"), 3000
        )

    def _link_bibliography(self) -> None:
        """Pick a .bib file and write it into the YAML front matter."""
        tab = self._current_tab()
        if tab is None:
            return
        start = (
            str(tab.path.parent)
            if tab.path is not None
            else ""
        )
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Link bibliography",
            start,
            "BibTeX (*.bib);;All files (*)",
        )
        if not filename:
            return
        bib_path = Path(filename)
        tab.link_bibliography(bib_path)
        entries = bib.parse_bib_file(bib_path)
        self.statusBar().showMessage(
            i18n.tr("Linked {filename} — {count} entries").format(
                filename=bib_path.name, count=len(entries)
            ),
            5000,
        )

    def _current_csl_key_from_tab(self, tab) -> str:
        """Return the bundled-style key the active document currently uses.

        The YAML ``csl:`` field is checked first. A short name that
        matches a bundled style wins; anything else (custom path or
        absent) maps to the IEEE default so the menu always reflects
        an effective state.
        """
        from epy_reports._core.renderer import (  # noqa: PLC0415
            CSL_STYLES,
            DEFAULT_CSL_STYLE,
        )

        if tab is None:
            return DEFAULT_CSL_STYLE
        meta = snippets.parse_front_matter(tab.editor.toPlainText())
        value = (meta.get("csl") or "").strip().lower()
        return value if value in CSL_STYLES else DEFAULT_CSL_STYLE

    def _set_csl_style(self, key: str) -> None:
        """Write ``csl: <key>`` into the active tab's YAML front matter."""
        tab = self._current_tab()
        if tab is None:
            return
        text = tab.editor.toPlainText()
        updated = snippets.set_metadata_field(text, "csl", key)
        if updated == text:
            self.statusBar().showMessage(
                i18n.tr("Citation style: {style} (no change)").format(
                    style=key.upper()
                ),
                3000,
            )
            return
        cursor = tab.editor.textCursor()
        cursor.beginEditBlock()
        cursor.select(cursor.SelectionType.Document)
        cursor.insertText(updated)
        cursor.endEditBlock()
        self.statusBar().showMessage(
            i18n.tr("Citation style: {style}").format(style=key.upper()),
            3000,
        )

    def _new_bib_entry(self) -> None:
        """Open the BibEntryDialog and append the result to the linked .bib.

        Walks four cases:

        1. No active tab → silently ignored (the action is also hidden
           in that branch of :meth:`_populate_references_menu`).
        2. No linked bibliography → prompt the user to pick or create
           one; the chosen file becomes the new ``bibliography:``
           target written into the YAML front matter.
        3. Linked .bib exists → open the dialog with its current keys
           so the user is warned before re-using one.
        4. Linked .bib path is set but the file does not exist yet →
           the dialog accepts and the file is created on save.
        """
        from epy_reports._ui.bib_dialog import BibEntryDialog  # noqa: PLC0415

        tab = self._current_tab()
        if tab is None:
            return

        bib_path = tab.bib_path()
        if bib_path is None:
            start = str(tab.path.parent) if tab.path is not None else ""
            filename, _ = QFileDialog.getSaveFileName(
                self,
                "Bibliography target",
                start,
                "BibTeX (*.bib);;All files (*)",
                options=QFileDialog.Option.DontConfirmOverwrite,
            )
            if not filename:
                return
            bib_path = Path(filename)
            tab.link_bibliography(bib_path)

        existing_keys = (
            bib.keys_in_file(bib_path) if bib_path.exists() else set()
        )
        dlg = BibEntryDialog(self, existing_keys=existing_keys)
        if dlg.exec() != BibEntryDialog.DialogCode.Accepted:
            return
        draft = dlg.build_draft()
        bib.append_entry_to_file(bib_path, draft)
        self.statusBar().showMessage(
            i18n.tr("Added @{key} to {filename}").format(
                key=draft.key, filename=bib_path.name
            ),
            5000,
        )
        # Refresh the References dropdown so the new key shows up.
        self._populate_references_menu()

    # ----------------------------------------------- export helpers

    def _resolve_reference_doc(self, theme_id: str) -> Path | None:
        """Return the bundled DOCX reference template for ``theme_id``.

        Resolves via ``importlib.resources`` so it works both from a
        source install and from a frozen PyInstaller build.  Returns
        ``None`` when the asset is missing so the caller can fall back
        to a default Pandoc export.

        Args:
            theme_id: Theme identifier, e.g. ``"corporate"``.

        Returns:
            Resolved :class:`~pathlib.Path` to the ``.docx`` template,
            or ``None`` if the file cannot be found.
        """
        try:
            pkg = importlib.resources.files(
                "epy_reports._config._assets.reference_docx"
            )
            ref = pkg / f"{theme_id}.docx"
            # Materialise the resource as a real path (works for both
            # installed and frozen builds; raises FileNotFoundError when
            # the file is absent inside the zip/bundle).
            with importlib.resources.as_file(ref) as p:
                if p.is_file():
                    return p
        except (FileNotFoundError, TypeError, ModuleNotFoundError):
            pass
        return None

    def _export_docx(self) -> None:
        """Save the current document as a Word (.docx) file."""
        self._exports_in_flight += 1
        try:
            tab = self._current_tab()
            if tab is None:
                return
            default = (
                str(tab.path.with_suffix(".docx"))
                if tab.path is not None
                else "untitled.docx"
            )
            filename, _ = QFileDialog.getSaveFileName(
                self, "Export DOCX", default, "Word document (*.docx)"
            )
            if not filename:
                return
            target = Path(filename)
            if target.suffix == "":
                target = target.with_suffix(".docx")
            text = tab.editor.toPlainText()
            base_dir = tab.path.parent if tab.path is not None else None
            reference_doc = self._resolve_reference_doc(
                self._current_theme.id
            )
            try:
                export_docx(
                    text, target, base_dir=base_dir,
                    reference_doc=reference_doc,
                    theme_css=document_css(self._current_theme),
                )
            except (OSError, RuntimeError) as exc:
                QMessageBox.critical(
                    self, i18n.tr("Export DOCX failed"), str(exc)
                )
                self.statusBar().showMessage(
                    i18n.tr("Export failed: {name}").format(
                        name=target.name
                    ),
                    5000,
                )
                return
            self.statusBar().showMessage(
                i18n.tr("Exported {name}").format(name=target.name), 5000
            )
        finally:
            self._exports_in_flight -= 1

    def _export_html(self) -> None:
        """Save the current preview as a standalone HTML file."""
        self._exports_in_flight += 1
        try:
            tab = self._current_tab()
            if tab is None:
                return
            default = (
                str(tab.path.with_suffix(".html"))
                if tab.path is not None
                else "untitled.html"
            )
            filename, _ = QFileDialog.getSaveFileName(
                self, "Export HTML", default, "HTML (*.html *.htm)"
            )
            if not filename:
                return
            target = Path(filename)
            if target.suffix == "":
                target = target.with_suffix(".html")
            text = tab.editor.toPlainText()
            base_dir = tab.path.parent if tab.path is not None else None
            title = tab.path.name if tab.path is not None else "untitled"
            try:
                html = render_markdown(
                    text,
                    base_dir=base_dir,
                    title=title,
                    theme_css=document_css(self._current_theme),
                    continuous=True,
                )
                target.write_text(html, encoding="utf-8")
                self.statusBar().showMessage(
                    i18n.tr("Saved HTML: {path}").format(path=target), 3000
                )
            except Exception as exc:  # noqa: BLE001 - failure must reach user
                QMessageBox.critical(
                    self, i18n.tr("Export HTML failed"), str(exc)
                )
                self.statusBar().showMessage(
                    i18n.tr("Export failed: {name}").format(
                        name=target.name
                    ),
                    5000,
                )
        finally:
            self._exports_in_flight -= 1

    def _print_document(self) -> None:
        """Open the system print dialog for the current preview."""
        tab = self._current_tab()
        if tab is None:
            return
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dialog = QPrintDialog(printer, self)
        if dialog.exec() != QPrintDialog.DialogCode.Accepted:
            return
        # Keep ``printer`` alive while the async print finishes.
        self._active_printer = printer
        tab.view.page().print(  # pyright: ignore[reportAttributeAccessIssue] - PySide6 stubs omit QWebEnginePage.print, which Qt exposes for printing
            printer,
            lambda _ok: setattr(self, "_active_printer", None),
        )

    # ----------------------------------------------- tab management

    def _open_welcome_tab(self) -> None:
        """Create the initial untitled tab shown at startup."""
        tab = self._create_tab()
        tab.set_initial_text(WELCOME_TEXT, path=None)

    def _open_manual(self, filename: str) -> None:
        """Open a bundled user-manual document (Help menu) in a new tab.

        The manual is loaded as an untitled buffer so the user can edit and
        save it anywhere without overwriting the bundled copy. Image
        placeholders are resolved to ``file://`` URIs so the cover and
        figures render even with no file path.
        """
        try:
            text = _load_manual_text(filename)
        except (FileNotFoundError, OSError):
            QMessageBox.warning(
                self,
                i18n.tr("Manual unavailable"),
                i18n.tr(
                    "Could not load the bundled manual '{filename}'."
                ).format(filename=filename),
            )
            return
        tab = self._create_tab()
        tab.set_initial_text(text, path=None)

    def _create_tab(self) -> MarkdownTab:
        """Instantiate a new MarkdownTab and wire its signals."""
        tab = MarkdownTab(self)
        tab.set_theme_css(
            document_css(self._current_theme),
            self._current_theme.css_vars.get("bg", ""),
        )
        tab.set_paged(self._paged_enabled)
        tab.dirtyChanged.connect(
            lambda _flag, t=tab: self._refresh_tab_title(t)
        )
        tab.pathChanged.connect(lambda t=tab: self._refresh_tab_title(t))
        index = self.tabs.addTab(tab, tab.title())
        self.tabs.setCurrentIndex(index)
        return tab

    def _refresh_tab_title(self, tab: MarkdownTab) -> None:
        """Update the tab label and window title for ``tab``."""
        index = self.tabs.indexOf(tab)
        if index < 0:
            return
        self.tabs.setTabText(index, tab.title())
        if tab.path is not None:
            self.tabs.setTabToolTip(index, str(tab.path))
        if tab is self._current_tab():
            self._update_window_title()

    def _update_window_title(self) -> None:
        """Reflect the current tab's title in the main window."""
        tab = self._current_tab()
        if tab is None:
            self.setWindowTitle(APP_NAME)
            return
        self.setWindowTitle(f"{APP_NAME} — {tab.title()}")
        if tab.path is not None:
            self.statusBar().showMessage(str(tab.path))
        else:
            self.statusBar().clearMessage()

    def _current_tab(self) -> MarkdownTab | None:
        """Return the currently visible MarkdownTab, if any."""
        widget = self.tabs.currentWidget()
        if isinstance(widget, MarkdownTab):
            return widget
        return None

    def _on_current_changed(self, _index: int) -> None:
        """Refresh window title when the user switches tabs."""
        self._update_window_title()
        # The References dropdown depends on the active buffer; refresh
        # it so its initial state matches the visible tab.
        if hasattr(self, "references_menu"):
            self._populate_references_menu()

    # ------------------------------------------------- file actions

    def _new_tab(self) -> MarkdownTab:
        """Create an empty untitled tab and focus it."""
        tab = self._create_tab()
        tab.set_initial_text("", path=None)
        return tab

    def _open_dialog(self) -> None:
        """Show an open-file dialog and load selected files in tabs."""
        current = self._current_tab()
        start = (
            str(current.path.parent)
            if current is not None and current.path is not None
            else ""
        )
        filenames, _ = QFileDialog.getOpenFileNames(
            self, "Open document", start, FILE_FILTER
        )
        for filename in filenames:
            self.open_path(Path(filename))

    def open_path(self, path: Path) -> None:
        """Open ``path`` in a new tab, or focus the existing tab.

        If ``path`` is already open in some tab, the existing tab is
        focused instead of opening a duplicate. If the current tab is
        the welcome / untitled empty tab, it is reused.
        """
        if not path.is_file():
            QMessageBox.warning(
                self,
                APP_NAME,
                i18n.tr("Not a file:\n{path}").format(path=path),
            )
            return

        path = path.resolve()
        for i in range(self.tabs.count()):
            existing = self.tabs.widget(i)
            if (
                isinstance(existing, MarkdownTab)
                and existing.path is not None
                and existing.path.resolve() == path
            ):
                self.tabs.setCurrentIndex(i)
                return

        target = self._current_tab()
        if (
            target is None
            or target.path is not None
            or target.dirty
            or target.text().strip()
        ):
            target = self._create_tab()
        target.load_file(path)
        self._refresh_tab_title(target)

    def _save_current(self) -> bool:
        """Save the current tab, falling back to *Save As* if needed."""
        tab = self._current_tab()
        if tab is None:
            return False
        if tab.path is None:
            return self._save_current_as()
        tab.save()
        self._refresh_tab_title(tab)
        self.statusBar().showMessage(
            i18n.tr("Saved: {path}").format(path=tab.path), 3000
        )
        return True

    def _save_current_as(self) -> bool:
        """Prompt for a target path and write the current tab there."""
        tab = self._current_tab()
        if tab is None:
            return False
        default = (
            str(tab.path)
            if tab.path is not None
            else "untitled.md"
        )
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save As", default, FILE_FILTER
        )
        if not filename:
            return False
        target = Path(filename)
        if target.suffix == "":
            target = target.with_suffix(".md")
        tab.save_as(target)
        self._refresh_tab_title(tab)
        self.statusBar().showMessage(
            i18n.tr("Saved: {path}").format(path=target), 3000
        )
        return True

    def _reload_current(self) -> None:
        """Discard buffer changes and reload the current tab from disk."""
        tab = self._current_tab()
        if tab is None or tab.path is None:
            return
        if tab.dirty:
            choice = QMessageBox.question(
                self,
                i18n.tr("Reload"),
                i18n.tr("Discard unsaved changes and reload from disk?"),
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if choice != QMessageBox.StandardButton.Yes:
                return
        tab.reload()
        self.statusBar().showMessage(
            i18n.tr("Reloaded: {path}").format(path=tab.path), 2000
        )

    def _export_pdf(self) -> None:
        """Export the current tab's preview to a PDF file."""
        self._exports_in_flight += 1
        started = False
        try:
            tab = self._current_tab()
            if tab is None:
                return
            default = (
                str(tab.path.with_suffix(".pdf"))
                if tab.path is not None
                else "untitled.pdf"
            )
            filename, _ = QFileDialog.getSaveFileName(
                self, "Export PDF", default, "PDF (*.pdf)"
            )
            if not filename:
                return
            target = Path(filename)
            if target.suffix == "":
                target = target.with_suffix(".pdf")
            self.statusBar().showMessage(i18n.tr("Exporting PDF..."), 0)
            try:
                tab.export_pdf(target, self._on_pdf_done)
            except (FileNotFoundError, ValueError) as exc:
                # A cover or annex the document declares and the disk
                # does not have. The generic "failed to write" below
                # would leave the reader guessing which of their own
                # paths is wrong, so the reason is shown verbatim.
                self.statusBar().clearMessage()
                QMessageBox.warning(
                    self,
                    APP_NAME,
                    i18n.tr("PDF pages could not be joined:\n{reason}")
                    .format(reason=exc),
                )
                return
            started = True
        finally:
            if not started:
                self._exports_in_flight -= 1

    def _on_pdf_done(self, path: Path, ok: bool) -> None:
        """Report the result of an asynchronous PDF export."""
        try:
            if ok:
                self.statusBar().showMessage(
                    i18n.tr("Saved PDF: {path}").format(path=path), 5000
                )
            else:
                self.statusBar().clearMessage()
                QMessageBox.warning(
                    self,
                    APP_NAME,
                    i18n.tr("Failed to write PDF:\n{path}").format(
                        path=path
                    ),
                )
        finally:
            self._exports_in_flight -= 1

    def _export_via_docs(self) -> None:
        """Launch the epy_docs export dialog and render in a worker."""
        self._exports_in_flight += 1
        started = False
        try:
            from epy_reports._ui.docs_export_dialog import (  # noqa: PLC0415
                DocsExportDialog,
                _RenderWorker,
            )

            tab = self._current_tab()
            if tab is None:
                return

            # Require the buffer to be saved on disk.
            if tab.path is None or tab.dirty:
                choice = QMessageBox.question(
                    self,
                    APP_NAME,
                    i18n.tr(
                        "The document must be saved before exporting via "
                        "epy_docs. Save now?"
                    ),
                    QMessageBox.StandardButton.Save
                    | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Save,
                )
                if choice != QMessageBox.StandardButton.Save:
                    return
                if not self._save_current():
                    return

            if tab.path is None:
                return

            dialog = DocsExportDialog(tab.path, parent=self)
            if dialog.exec() != DocsExportDialog.DialogCode.Accepted:
                return

            dialog.persist_settings()

            source = tab.path
            layout = dialog.layout_name
            doc_type = dialog.document_type
            out_dir = dialog.output_dir
            want_pdf = dialog.export_pdf
            want_html = dialog.export_html
            want_docx = dialog.export_docx

            QApplication.setOverrideCursor(
                QCursor(Qt.CursorShape.WaitCursor)
            )
            self.statusBar().showMessage(
                i18n.tr("Exporting via epy_docs…"), 0
            )

            self._docs_worker = _RenderWorker(
                source_path=source,
                layout=layout,
                document_type=doc_type,
                output_dir=out_dir,
                pdf=want_pdf,
                html=want_html,
                docx=want_docx,
            )
            self._docs_worker.finished_ok.connect(self._on_docs_done_ok)
            self._docs_worker.finished_err.connect(self._on_docs_done_err)
            self._docs_worker.start()
            started = True
        finally:
            if not started:
                self._exports_in_flight -= 1

    def _on_docs_done_ok(self, out_dir: str) -> None:
        """Handle a successful epy_docs render."""
        try:
            QApplication.restoreOverrideCursor()
            self.statusBar().showMessage(
                i18n.tr("Exported to {path}").format(path=out_dir), 5000
            )
        finally:
            self._exports_in_flight -= 1

    def _on_docs_done_err(self, message: str) -> None:
        """Handle a failed epy_docs render."""
        try:
            QApplication.restoreOverrideCursor()
            self.statusBar().clearMessage()
            QMessageBox.critical(
                self,
                APP_NAME,
                i18n.tr("epy_docs export failed:\n\n{message}").format(
                    message=message
                ),
            )
        finally:
            self._exports_in_flight -= 1

    # ------------------------------------------------ closing logic

    def _confirm_close(self, tab: MarkdownTab) -> bool:
        """Prompt how to handle a dirty tab. Returns False to abort."""
        if not tab.dirty:
            return True
        name = tab.path.name if tab.path is not None else "untitled.md"
        choice = QMessageBox.question(
            self,
            i18n.tr("Unsaved changes"),
            i18n.tr(
                "'{name}' has unsaved changes. Save before closing?"
            ).format(name=name),
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if choice == QMessageBox.StandardButton.Save:
            self.tabs.setCurrentWidget(tab)
            return self._save_current()
        return choice == QMessageBox.StandardButton.Discard

    def _close_tab_at(self, index: int) -> None:
        """Handle the close button on a specific tab."""
        widget = self.tabs.widget(index)
        if not isinstance(widget, MarkdownTab):
            return
        if not self._confirm_close(widget):
            return
        self.tabs.removeTab(index)
        widget.cleanup_preview_tmp()
        widget.deleteLater()
        if self.tabs.count() == 0:
            self._open_welcome_tab()

    def _close_current_tab(self) -> None:
        """Close the active tab via the ``Ctrl+W`` shortcut."""
        index = self.tabs.currentIndex()
        if index >= 0:
            self._close_tab_at(index)

    def closeEvent(self, event) -> None:  # noqa: N802
        """Prompt to save every dirty tab before exiting."""
        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            if isinstance(widget, MarkdownTab) and not self._confirm_close(
                widget
            ):
                event.ignore()
                return
        event.accept()

    # -------------------------------------------------- drag & drop

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        """Accept drags that carry file URLs."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        """Open every dropped Markdown/Quarto file in its own tab."""
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.suffix.lower() in SUPPORTED_EXTENSIONS:
                self.open_path(path)


def _run_gui(files: list[str]) -> int:
    """Boot the Qt application and open ``files`` in tabs."""
    app = QApplication(sys.argv)

    # Set the application-level icon (taskbar / OS task switcher).
    logo_pix = _load_branding_pixmap("epy_reports.png")
    if not logo_pix.isNull():
        app.setWindowIcon(QIcon(logo_pix))

    window = MarkdownWindow()
    window.show()
    for raw in files:
        candidate = Path(raw)
        if candidate.exists():
            window.open_path(candidate)
    return app.exec()


def _run_register(make_default: bool) -> int:
    """Register the app for ``.md`` / ``.qmd`` on Windows."""
    from epy_reports._core import winreg_assoc

    try:
        changes = winreg_assoc.register(make_default=make_default)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for line in changes:
        print(line)
    print(
        f"\nDone. You can right-click a .md / .markdown / .qmd file "
        f"> Open with > {APP_NAME}."
    )
    if make_default:
        print(
            "\nWindows 10/11 will NOT honour a default app set from\n"
            "the registry alone — it requires you to confirm the\n"
            "choice in Settings (the UserChoice key is hash-signed\n"
            "and only Windows itself can produce a valid hash).\n"
            f"\nOpening Settings → Default apps for {APP_NAME}.\n"
            "Pick each extension (.md, .markdown, .qmd) and select\n"
            f"{APP_NAME} from the list."
        )
        winreg_assoc.open_default_apps_settings()
    return 0


def _run_set_default() -> int:
    """Open Settings → Default apps so the user can pick this app."""
    from epy_reports._core import winreg_assoc

    if not winreg_assoc.open_default_apps_settings():
        print(
            "Could not open the Settings page. Open it manually: "
            "Settings → Apps → Default apps → search "
            f"{APP_NAME}.",
            file=sys.stderr,
        )
        return 2
    print(
        f"Opened Settings → Default apps. Pick .md / .markdown / "
        f".qmd and select {APP_NAME} from the list."
    )
    return 0


def _run_unregister() -> int:
    """Remove the file-association keys created by ``--register``."""
    from epy_reports._core import winreg_assoc

    try:
        changes = winreg_assoc.unregister()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not changes:
        print("Nothing to remove.")
        return 0
    for line in changes:
        print(line)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    """Build the top-level ``argparse`` parser for the CLI."""
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description=(
            "Quarto/Markdown editor and viewer with one-click "
            "PDF export."
        ),
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Quarto/Markdown files to open in tabs at startup.",
    )
    parser.add_argument(
        "--register",
        action="store_true",
        help=(
            f"Add an 'Open with {APP_NAME}' entry for .md, .markdown "
            "and .qmd on Windows (HKCU, no admin)."
        ),
    )
    parser.add_argument(
        "--as-default",
        action="store_true",
        help=(
            f"With --register, also set {APP_NAME} as the default "
            "program for the supported extensions."
        ),
    )
    parser.add_argument(
        "--unregister",
        action="store_true",
        help="Remove the keys created by --register.",
    )
    parser.add_argument(
        "--set-default",
        action="store_true",
        help=(
            "Open Settings → Default apps so you can pick "
            f"{APP_NAME} as the handler. Use this after --register "
            "since Windows requires user confirmation."
        ),
    )
    return parser


def _ensure_utf8_streams() -> None:
    """Force stdout/stderr to UTF-8 so non-ASCII help text works.

    PowerShell pipes default to cp1252 on Windows, which makes argparse
    crash when ``--help`` contains characters like ``->`` arrows or
    em-dashes. Reconfiguring the streams is harmless when they are
    already UTF-8 or when stdout is unavailable (frozen GUI).
    """
    import contextlib

    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        with contextlib.suppress(ValueError, OSError):
            reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``epy_reports`` console script."""
    _ensure_utf8_streams()
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.unregister:
        return _run_unregister()
    if args.register:
        return _run_register(make_default=args.as_default)
    if args.set_default:
        return _run_set_default()
    return _run_gui(args.files)


if __name__ == "__main__":
    raise SystemExit(main())
