"""A single editor/preview tab used by the epy_reports window."""

from __future__ import annotations

import contextlib
import re
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

import epy_export
from PySide6.QtCore import QMarginsF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QDesktopServices,
    QFont,
    QFontDatabase,
    QKeySequence,
    QPageLayout,
    QPageSize,
    QShortcut,
    QTextCursor,
)
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QInputDialog,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from epy_reports._core import _i18n as i18n
from epy_reports._core import snippets
from epy_reports._core.renderer import (
    append_annex_section,
    inject_page_numbers,
    normalize_page_size,
    render_markdown,
)
from epy_reports._core.template import is_truthy
from epy_reports._ui.checklist_dialog import ChecklistDialog
from epy_reports._ui.columns_dialog import ThreeColumnDialog, TwoColumnDialog
from epy_reports._ui.equation_dialog import EquationDialog
from epy_reports._ui.figure_dialog import FigureDialog
from epy_reports._ui.footnote_dialog import FootnoteDialog
from epy_reports._ui.table_dialog import TableDialog
from epy_reports._ui.xref_dialog import CrossRefDialog

RENDER_DEBOUNCE_MS = 250
POS_POLL_MS = 400
UNTITLED = "untitled.md"

# Reads the preview's scroll position as a 0..1 ratio so the next render can
# return to it (see ``_PREVIEW_RESTORE`` in template.py). "" before any
# content has scrolled.
_CAPTURE_POS_JS = (
    "(function () {"
    "  try {"
    "    var el = document.scrollingElement || document.documentElement;"
    "    if (!el) return '';"
    "    var d = el.scrollHeight - el.clientHeight;"
    "    return d > 0 ? 'epypos=s:' + (el.scrollTop / d) : '';"
    "  } catch (e) { return ''; }"
    "})()"
)

# Matches the integer suffix of a ``[^fn-N]`` footnote marker.
_FOOTNOTE_RE = re.compile(r"\[\^fn-(\d+)\]")

# Export readiness poll (MathJax typeset + Paged.js pagination): how long
# to wait before giving up and printing anyway.
_PAGED_TIMEOUT_MS = 60_000
_MATHJAX_POLL_MS = 100


def next_label_suffix(text: str, kind: str) -> str:
    """Return the next sequential integer suffix for ``kind`` labels.

    Scans all Quarto labels of the given kind in ``text`` (e.g.
    ``fig``, ``tbl``, ``eq``, ``sec``).  Among suffixes that are pure
    integers, returns ``str(max + 1)``.  When no integer suffix exists
    the function returns ``"1"``.

    Args:
        text: Full Markdown buffer contents.
        kind: Label kind — one of ``fig``, ``tbl``, ``eq``, ``sec``.

    Returns:
        Short sequential string, e.g. ``"3"`` when ``{#fig-1}`` and
        ``{#fig-2}`` are already present.
    """
    labels = snippets.find_labels(text)
    ints: list[int] = []
    prefix = f"{kind}-"
    for label in labels:
        if label.kind != kind:
            continue
        suffix = label.name[len(prefix):]
        if suffix.isdigit():
            ints.append(int(suffix))
    return str(max(ints) + 1) if ints else "1"


def next_footnote_suffix(text: str) -> str:
    """Return the next sequential integer suffix for ``[^fn-N]`` markers.

    Scans every ``[^fn-N]`` footnote marker in ``text`` whose suffix is
    a pure integer and returns ``str(max + 1)``. When none exist the
    function returns ``"1"``. Kept module-level so it is unit-testable
    without a widget instance, mirroring :func:`next_label_suffix`.

    Args:
        text: Full Markdown buffer contents.

    Returns:
        Short sequential string, e.g. ``"3"`` when ``[^fn-1]`` and
        ``[^fn-2]`` are already present.
    """
    ints = [int(m) for m in _FOOTNOTE_RE.findall(text)]
    return str(max(ints) + 1) if ints else "1"


class _ExternalOpenPage(QWebEnginePage):
    """Throwaway page that redirects any load to the system browser.

    ``QWebEngineView`` swallows ``target="_blank"`` links unless
    ``createWindow`` returns a page; this stand-in receives the popup
    navigation and hands the URL to the OS instead, so "open in new
    window" links actually work from the preview.
    """

    def acceptNavigationRequest(  # noqa: N802 (Qt override)
        self,
        url: QUrl | str,
        _type: QWebEnginePage.NavigationType,
        _is_main_frame: bool,
    ) -> bool:
        # Qt declares this virtual with a url that may arrive as
        # a string; narrowing to QUrl would have refused exactly
        # the calls the base class promises to make.
        QDesktopServices.openUrl(
            QUrl(url) if isinstance(url, str) else url
        )
        self.deleteLater()
        return False


class _PreviewView(QWebEngineView):
    """Preview view: popup links go to the system browser."""

    # OPEN, and deliberately not silenced away: Qt declares this
    # virtual on the VIEW as returning a QWebEngineView, and this
    # returns a page. The documented hook for target="_blank" is
    # the PAGE's createWindow; moving it there is a behaviour
    # change in the preview, which is why it is recorded rather
    # than done in a typing pass. Popup handling has no live test.
    def createWindow(  # noqa: N802 (Qt override)  # pyright: ignore[reportIncompatibleMethodOverride] - see the note above
        self,
        _window_type: QWebEnginePage.WebWindowType,
    ) -> QWebEnginePage:
        return _ExternalOpenPage(self)


class MarkdownTab(QWidget):
    """Editor + live preview for one Markdown buffer.

    Signals:
        pathChanged: Emitted when the on-disk path is set or changed.
        dirtyChanged: Emitted with the new dirty flag when it flips.
    """

    pathChanged = Signal()  # noqa: N815 (Qt signal naming convention)
    dirtyChanged = Signal(bool)  # noqa: N815 (Qt signal naming)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Build the editor, the web preview and the debounce timer."""
        super().__init__(parent)

        self._path: Path | None = None
        self._dirty = False
        self._suppress_change = False
        self._theme_css: str = ""
        self._page_bg: str = ""
        self._paged = False
        self._preview_tmp_dir: Path | None = None

        self.editor = QPlainTextEdit(self)
        self._setup_editor()

        self.view = _PreviewView(self)
        # A fresh render must not leave stale history entries behind:
        # otherwise Back steps through every previous debounce render of
        # the same page instead of returning from a link jump. The flag
        # marks loads issued by _render_into_view; loads that arrive via
        # history navigation (Back from a web page) keep their history.
        self._expect_render_load = False
        self.view.loadFinished.connect(self._on_preview_load_finished)
        # Browser-style history navigation on the preview pane.
        back = QShortcut(QKeySequence("Alt+Left"), self.view)
        back.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        back.activated.connect(self.view.back)
        forward = QShortcut(QKeySequence("Alt+Right"), self.view)
        forward.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        forward.activated.connect(self.view.forward)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(self.editor)
        splitter.addWidget(self.view)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([520, 600])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(RENDER_DEBOUNCE_MS)
        self._render_timer.timeout.connect(self._render)

        # The scroll position is polled into ``_last_pos`` on a timer so a
        # re-render can return to it WITHOUT making the reload depend on an
        # async callback (a dropped callback would leave the preview, and
        # theme switches, never updating).
        self._last_pos = ""
        # A monotonic query param makes every preview URL unique. Loading the
        # same file path with only a changed ``#fragment`` is an in-page
        # navigation that does NOT reload — which silently swallowed theme
        # switches; the changing ``?r=`` forces a full reload every time.
        self._render_seq = 0
        self._pos_timer = QTimer(self)
        self._pos_timer.setInterval(POS_POLL_MS)
        self._pos_timer.timeout.connect(self._poll_position)
        self._pos_timer.start()

        self.editor.textChanged.connect(self._on_text_changed)

    def _setup_editor(self) -> None:
        """Configure the editor with monospace font and 4-space tabs."""
        font = QFontDatabase.systemFont(
            QFontDatabase.SystemFont.FixedFont
        )
        if font.pointSize() < 1:
            font = QFont("Consolas")
        font.setPointSize(11)
        self.editor.setFont(font)
        metrics = self.editor.fontMetrics()
        self.editor.setTabStopDistance(4 * metrics.horizontalAdvance(" "))
        self.editor.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth
        )
        self.editor.setPlaceholderText(
            i18n.tr("Type Markdown here. Preview updates on the right.")
        )

    # ------------------------------------------------------------- API

    @property
    def path(self) -> Path | None:
        """Return the on-disk path, or ``None`` for unsaved buffers."""
        return self._path

    @property
    def dirty(self) -> bool:
        """Return ``True`` if the buffer has unsaved changes."""
        return self._dirty

    def title(self) -> str:
        """Return the tab title, suffixed with ``*`` when dirty."""
        base = self._path.name if self._path is not None else UNTITLED
        return f"{base} *" if self._dirty else base

    def text(self) -> str:
        """Return the current editor text."""
        return self.editor.toPlainText()

    def set_initial_text(
        self, text: str, path: Path | None = None
    ) -> None:
        """Populate the buffer from disk or a template, then render.

        Args:
            text: Initial buffer contents.
            path: Optional path that ``text`` was loaded from.
        """
        self._suppress_change = True
        self.editor.setPlainText(text)
        self._suppress_change = False
        self._path = path
        self._set_dirty(False)
        self._render_now()
        self.pathChanged.emit()

    def load_file(self, path: Path) -> None:
        """Load a Markdown file from disk into this tab."""
        text = path.read_text(encoding="utf-8")
        self.set_initial_text(text, path)

    def save(self) -> bool:
        """Save the buffer to its current path.

        Returns:
            ``True`` if the buffer was written, ``False`` when no path
            is associated with the tab (caller should fall back to
            *Save As*).
        """
        if self._path is None:
            return False
        epy_export.write_text_atomic(self._path, self.editor.toPlainText())
        self._set_dirty(False)
        return True

    def save_as(self, path: Path) -> None:
        """Save the buffer to ``path`` and adopt it as current path."""
        path.write_text(self.editor.toPlainText(), encoding="utf-8")
        self._path = path
        self._set_dirty(False)
        self.pathChanged.emit()
        # Re-render so the preview's <base> uses the new directory.
        self._render_now()

    def reload(self) -> None:
        """Reload the buffer from disk, discarding in-memory changes."""
        if self._path is None:
            return
        self.load_file(self._path)

    def set_theme_css(self, css: str, page_bg: str = "") -> None:
        """Update the preview's theme CSS and re-render immediately.

        Args:
            css: The theme's ``:root { … }`` override block.
            page_bg: The theme's page background hex color (``--bg``), used
                to paint the PDF page background edge to edge on export.
        """
        self._theme_css = css
        self._page_bg = page_bg
        # Same document, only the theme changed — keep the scroll position.
        self._render_now(preserve=True)

    def refresh_preview(self) -> None:
        """Re-render the preview in place, keeping the scroll position.

        Used on a live UI-language switch: numbered captions
        ("Figura 1" / "Figure 1"), cross-references and index titles
        follow the application language when the document declares no
        ``lang:`` of its own, so the preview must re-render to show it.
        """
        self._render_now(preserve=True)

    def set_paged(self, value: bool) -> None:
        """Toggle the A4 page-view preview and re-render immediately.

        Preview-only: PDF/HTML/DOCX exports are unaffected. The PDF
        export path forces a non-paged render before printing so the
        gray backdrop never leaks into the exported file.

        Args:
            value: ``True`` to show the content as an A4 sheet.
        """
        self._paged = value
        self._render_now()

    def export_pdf(
        self,
        target: Path,
        on_done: Callable[[Path, bool], None] | None = None,
    ) -> None:
        """Export the current preview to ``target`` as a PDF file.

        The export is a strict improvement over a bare
        ``printToPdf``: it (a) renders a fresh, non-paged export page
        into the view and gates printing on the view's ``loadFinished``
        so the print never fires against a stale page, (b) waits for
        MathJax to finish typesetting so equations are rendered, (c)
        prints with an explicit portrait page layout (page size taken
        from the document's ``page-size`` front matter, default Letter)
        with ~15 mm margins, and (d) when the document front matter
        declares a ``footer`` text or a truthy ``page-numbers`` value,
        stamps every page via
        :func:`epy_export.add_footer`
        before delivering the final file.

        Args:
            target: Destination ``.pdf`` path.
            on_done: Optional callback ``(target, ok)`` invoked when the
                export finishes (success or failure). ``target`` is the
                final destination path so the caller can report it.

        Raises:
            FileNotFoundError: When ``cover-pdf`` or ``annexes`` names a
                file that is not on disk. Raised before anything is
                rendered, and before ``on_done`` exists to hear it, so
                the caller reports the reason rather than the bare
                failure the callback carries.
            ValueError: When either key is present and declares nothing.
        """
        text = self.editor.toPlainText()
        # Stop the live-preview debounce so a pending re-render cannot fire
        # mid-export and load the preview page into the same view the export
        # is printing from (which would make printToPdf fail and the file
        # never be written). It re-arms on the next edit (single-shot).
        self._render_timer.stop()
        meta = snippets.parse_front_matter(text)
        footer_text = meta.get("footer", "")
        page_numbers = is_truthy(meta.get("page-numbers"))
        lang = meta.get("lang", "en")
        page_size = normalize_page_size(meta.get("page-size"))
        header_cells = snippets.parse_header_cells(meta.get("header"))
        has_cover = is_truthy(meta.get("cover"))

        # PDF document metadata (embedded into the exported file). A
        # copyright/rights notice is always recorded — taken from the
        # ``copyright`` front-matter key, or derived as "© <year> <author>"
        # — so the file carries authorship and ownership information.
        doc_title = meta.get("title", "").strip()
        author = meta.get("author", "").strip()
        subtitle = meta.get("subtitle", "").strip()
        keywords = meta.get("keywords", "").strip()
        rights = meta.get("copyright", "").strip()
        if not rights and author:
            year = meta.get("date", "")[:4].strip()
            rights = f"© {year} {author}" if year.isdigit() else f"© {author}"

        base_dir = self._path.parent if self._path is not None else None
        title = self._path.name if self._path is not None else UNTITLED

        # Optional grayscale watermark image (front-matter ``watermark:``),
        # resolved relative to the document when given a relative path.
        watermark_path: Path | None = None
        watermark = meta.get("watermark", "").strip()
        if watermark:
            candidate = Path(watermark)
            if not candidate.is_absolute() and base_dir is not None:
                candidate = base_dir / watermark
            if candidate.is_file():
                watermark_path = candidate

        # The reader's own PDF pages: a cover template that opens the
        # document and annexes that close it. Read before rendering, so
        # a mistyped path is reported instead of costing two Paged.js
        # passes and then failing at the joining step.
        cover_pdf, annex_pdfs = snippets.resolve_pdf_attachments(
            meta, base_dir
        )
        if annex_pdfs:
            text = append_annex_section(text, lang)

        export_html = render_markdown(
            text,
            base_dir=base_dir,
            title=title,
            theme_css=self._theme_css,
            paged=False,
            page_size=page_size,
            for_export=True,
        )

        tmp_dir = Path(tempfile.mkdtemp(prefix="epy_reports_pdf_"))
        pass1_pdf = tmp_dir / "pass1.pdf"
        tmp_pdf = tmp_dir / "export.pdf"

        def finalize(
            ok: bool, start_page: int,
            segments: list[tuple[int, str]] | None = None,
        ) -> None:
            """Stamp header/footer overlays, move into place, then notify.

            ``start_page`` is the first content page: cover and index
            front matter before it stay clean, and the footer renumbers
            content from 1 (see
            :func:`epy_export.add_footer`).
            ``segments`` carries any ``[[section-roman]]`` /
            ``[[section-arabic]]`` boundaries so numbering restarts per
            section in the chosen style.
            """
            result_ok = ok
            try:
                if ok:
                    # The stamping is epy_export's; the local
                    # `_core._pdf_footer` this used to name has not
                    # existed since the extraction, and every PDF export
                    # from the window raised ModuleNotFoundError here.
                    _pdf_footer = epy_export

                    # BEFORE the stamping, which is what numbers these
                    # pages: the annexes are part of the document, so
                    # the footer counts them in continuity with the
                    # body.
                    if annex_pdfs:
                        _pdf_footer.append_pdf(tmp_pdf, annex_pdfs)
                    if self._page_bg:
                        _pdf_footer.add_page_background(
                            tmp_pdf, self._page_bg,
                        )
                    if watermark_path is not None:
                        # Best-effort: a missing Pillow must not fail export.
                        with contextlib.suppress(OSError, RuntimeError):
                            _pdf_footer.add_watermark(tmp_pdf, watermark_path)
                    if any(header_cells):
                        _pdf_footer.add_header(
                            tmp_pdf, header_cells,
                            lang=lang, start_page=start_page,
                        )
                    if footer_text or page_numbers:
                        _pdf_footer.add_footer(
                            tmp_pdf,
                            footer_text,
                            page_numbers=page_numbers,
                            lang=lang,
                            start_page=start_page,
                            segments=segments,
                        )
                    # Embed document metadata + copyright last, so it
                    # survives the page-stamping rewrites above.
                    _pdf_footer.add_metadata(
                        tmp_pdf,
                        title=doc_title or title,
                        author=author,
                        subject=subtitle,
                        keywords=keywords,
                        rights=rights,
                        # Required, with no default: the shared engine
                        # refuses to guess which application produced a
                        # document. This call site was missed when the
                        # stamping moved to epy_export, and it is the
                        # PDF export of the WINDOW -- every export from
                        # the interface raised TypeError, which the
                        # `except (OSError, RuntimeError)` below does
                        # not even catch.
                        creator="epy_reports",
                        producer="epy_reports — ANM Ingeniería",
                    )
                    # AFTER the stamping, which is what keeps this page
                    # out of the numbering: the reader's cover template
                    # is front matter, and the body was already
                    # renumbered from 1, so the pages the index
                    # declares do not move.
                    if cover_pdf is not None:
                        _pdf_footer.prepend_pdf(tmp_pdf, cover_pdf)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(tmp_pdf), str(target))
            except (OSError, RuntimeError):
                result_ok = False
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                # Always restore the user's live preview (re-applying
                # the current paged + page-size state) on both paths.
                self._render_now()
            if on_done is not None:
                on_done(target, result_ok)

        def load_and_print(html: str, out_pdf: Path, after) -> None:
            """Load ``html`` into the view, wait for MathJax, print to PDF."""
            html_file = tmp_dir / f"{out_pdf.stem}.html"
            html_file.write_text(html, encoding="utf-8")

            def do_print() -> None:
                self.view.page().pdfPrintingFinished.connect(
                    lambda _p, ok: after(ok),
                    Qt.ConnectionType.SingleShotConnection,
                )
                self.view.page().printToPdf(
                    str(out_pdf), self._page_layout(page_size)
                )

            def on_loaded(ok: bool) -> None:
                if not ok:
                    after(False)
                    return
                self._wait_for_export_ready(do_print)

            # Connect the one-shot loadFinished BEFORE loading so the
            # signal can never be missed; SingleShotConnection keeps it
            # from leaking into later preview reloads.
            self.view.loadFinished.connect(
                on_loaded, Qt.ConnectionType.SingleShotConnection
            )
            self.view.load(QUrl.fromLocalFile(str(html_file.resolve())))

        def after_pass2(
            first_content_page: int, ok: bool,
            segments: list[tuple[int, str]] | None = None,
        ) -> None:
            finalize(ok, first_content_page, segments)

        def _section_segments(
            anchors: dict[str, int],
        ) -> list[tuple[int, str]] | None:
            """Extract ``(page, style)`` section boundaries from anchors."""
            found: list[tuple[int, str]] = []
            for anchor_id, page in anchors.items():
                if anchor_id.startswith("epy-section-roman-"):
                    found.append((page, "roman"))
                elif anchor_id.startswith("epy-section-arabic-"):
                    found.append((page, "arabic"))
            return sorted(found) or None

        def after_pass1(ok: bool) -> None:
            if not ok:
                finalize(False, 1)
                return
            anchor_to_page = epy_export.extract_anchor_pages(pass1_pdf)
            segments = _section_segments(anchor_to_page)
            # Section markers are page breaks, not body content; exclude them
            # when locating the first content page.
            content_anchors = {
                a: p for a, p in anchor_to_page.items()
                if not a.startswith("epy-section-")
            }
            if content_anchors:
                # Index blocks emit only links, so every destination is in
                # the body; the smallest is the first content page. Cover +
                # TOC/LOF/LOT/LOE before it are unnumbered front matter and
                # the body is renumbered from 1.
                first = min(content_anchors.values())
                html2 = inject_page_numbers(
                    export_html, anchor_to_page, first - 1
                )
                load_and_print(
                    html2, tmp_pdf,
                    lambda ok2: after_pass2(first, ok2, segments),
                )
            else:
                # No named destinations (older Qt / no anchors): skip the
                # second pass and just stamp from the first content page,
                # which is the page after the cover when present.
                shutil.copy(pass1_pdf, tmp_pdf)
                finalize(True, 2 if has_cover else 1, segments)

        load_and_print(export_html, pass1_pdf, after_pass1)

    @staticmethod
    def _page_layout(page_size: str) -> QPageLayout:
        """Return a portrait page layout with zero printer margin.

        Paged.js already lays out every page with the 30 mm ``@page``
        margin, so the printer margin MUST be zero — otherwise the two
        stack (30 mm + 30 mm) and the PDF prints with a 60 mm margin. The
        theme background is painted edge to edge after export by
        :func:`epy_export.add_page_background`.

        Args:
            page_size: Page-size key (``letter`` / ``a4`` / ``legal``).
                Unknown or missing values fall back to Letter.

        Returns:
            A :class:`QPageLayout` using the matching
            :class:`QPageSize.PageSizeId`.
        """
        ids = {
            "letter": QPageSize.PageSizeId.Letter,
            "a4":     QPageSize.PageSizeId.A4,
            "legal":  QPageSize.PageSizeId.Legal,
        }
        size_id = ids.get(normalize_page_size(page_size), ids["letter"])
        margins = QMarginsF(0.0, 0.0, 0.0, 0.0)
        return QPageLayout(
            QPageSize(size_id),
            QPageLayout.Orientation.Portrait,
            margins,
            QPageLayout.Unit.Millimeter,
        )

    def _wait_for_export_ready(self, then: Callable[[], None]) -> None:
        r"""Poll ``window._paged_done`` then run ``then``.

        The export page runs MathJax and then Paged.js; the Paged.js
        runner sets ``window._paged_done`` only once typesetting has
        finished *and* pagination (page margins, footnotes at the foot of
        their page) is complete. Printing before that prints raw
        ``\[ … \]`` math or an unpaginated page. This polls the flag and
        calls ``then`` as soon as it is truthy, or after a timeout so the
        export still completes if pagination stalls.
        """
        elapsed = [0]

        def check() -> None:
            def handle(done: object) -> None:
                if done is True:
                    then()
                    return
                elapsed[0] += _MATHJAX_POLL_MS
                if elapsed[0] >= _PAGED_TIMEOUT_MS:
                    then()
                    return
                QTimer.singleShot(_MATHJAX_POLL_MS, check)

            self.view.page().runJavaScript(
                "window._paged_done === true", handle
            )

        check()

    # ------------------------------------------------- editor actions

    def toggle_bold(self) -> None:
        """Wrap the current selection (or caret) in ``**...**``."""
        self._wrap_selection("**", "**", placeholder="bold")

    def toggle_italic(self) -> None:
        """Wrap the current selection (or caret) in ``*...*``."""
        self._wrap_selection("*", "*", placeholder="italic")

    def toggle_inline_code(self) -> None:
        """Wrap the current selection (or caret) in ``` `...` ```."""
        self._wrap_selection("`", "`", placeholder="code")

    def set_heading_level(self, level: int) -> None:
        """Replace the current line's heading prefix to ``level``.

        Args:
            level: ``1``-``6`` to apply that ``#``-level prefix; ``0``
                to strip any existing prefix (turn the line back into
                a paragraph).
        """
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(
            QTextCursor.MoveOperation.EndOfBlock,
            QTextCursor.MoveMode.KeepAnchor,
        )
        line = cursor.selectedText()
        stripped = line.lstrip("#").lstrip(" ")
        if level <= 0:
            new_line = stripped
        else:
            level = max(1, min(level, 6))
            prefix = "#" * level
            new_line = f"{prefix} {stripped}" if stripped else f"{prefix} "
        cursor.insertText(new_line)
        # Place the caret at the end of the new line.
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    def insert_section_heading(self) -> None:
        """Prompt for heading text, insert with auto sec-N label."""
        text, ok = QInputDialog.getText(
            self, "Section heading", "Heading text:",
            text="Section title",
        )
        if not ok or not text:
            text = "Section title"
        suffix = self._next_label_suffix("sec")
        md = f"## {text} {{#sec-{suffix}}}"
        cursor = self.editor.textCursor()
        if cursor.positionInBlock() != 0:
            cursor.insertText("\n")
        cursor.insertText(md + "\n")
        self.editor.setFocus()

    def insert_link(self) -> None:
        """Insert ``[text](url)``; uses the current selection as text."""
        cursor = self.editor.textCursor()
        if cursor.hasSelection():
            text = cursor.selectedText()
            inserted = f"[{text}](URL)"
            cursor.insertText(inserted)
            end = cursor.position()
            cursor.setPosition(end - 4)
            cursor.setPosition(
                end - 1, QTextCursor.MoveMode.KeepAnchor
            )
            self.editor.setTextCursor(cursor)
        else:
            self._insert_template(snippets.LINK_TEMPLATE, "TEXT")
        self.editor.setFocus()

    def _next_label_suffix(self, kind: str) -> str:
        """Return the next sequential integer suffix for ``kind``.

        Delegates to the module-level :func:`next_label_suffix` so
        the logic is unit-testable without a widget instance.
        """
        return next_label_suffix(self.editor.toPlainText(), kind)

    def insert_figure(self) -> None:
        """Open FigureDialog; insert figure Markdown on accept."""
        dialog = FigureDialog(
            self, default_id=self._next_label_suffix("fig")
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        md = dialog.build_markdown()
        cursor = self.editor.textCursor()
        if cursor.positionInBlock() != 0:
            cursor.insertText("\n")
        cursor.insertText(md + "\n")
        self.editor.setFocus()

    def insert_image_from_dialog(self) -> None:
        """Pick an image file, copy to figures/, insert at cursor."""
        start_dir = (
            str(self._path.parent)
            if self._path is not None
            else ""
        )
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Insert image",
            start_dir,
            "Images (*.png *.jpg *.jpeg *.gif *.svg *.webp *.bmp)"
            ";;All files (*)",
        )
        if not filename:
            return

        src = Path(filename)

        # Determine figures/ directory
        if self._path is not None:
            figures_dir = self._path.parent / "figures"
        else:
            figures_dir = Path.cwd() / "figures"
        figures_dir.mkdir(parents=True, exist_ok=True)

        # Resolve name collision
        dst = figures_dir / src.name
        if dst.exists():
            stem = src.stem
            suffix = src.suffix
            counter = 1
            while dst.exists():
                dst = figures_dir / f"{stem}-{counter}{suffix}"
                counter += 1

        shutil.copy2(str(src), str(dst))

        # Build relative path for markdown
        if self._path is not None:
            rel = dst.relative_to(self._path.parent)
        else:
            rel = dst
        md_path = str(rel).replace("\\", "/")

        # Sequential label independent of filename
        label = self._next_label_suffix("fig")

        # Caption: prompt user with filename as default
        caption, ok = QInputDialog.getText(
            self,
            "Image caption",
            "Caption:",
            text=src.stem,
        )
        if not ok:
            caption = src.stem
        caption = caption or src.stem

        # Width: prompt the user; blank or cancel falls back to 80%.
        width, ok = QInputDialog.getText(
            self,
            "Image width",
            "Width (e.g. 80%, 300px):",
            text="80%",
        )
        if not ok or not width.strip():
            width = "80%"

        md = snippets.IMAGE_MARKDOWN.format(
            caption=caption, path=md_path, label=label, width=width
        )

        cursor = self.editor.textCursor()
        if cursor.positionInBlock() != 0:
            cursor.insertText("\n")
        cursor.insertText(md + "\n")
        self.editor.setFocus()

    def insert_table(self) -> None:
        """Open table dialog, then insert pipe table with caption."""
        dialog = TableDialog(
            self, default_id=self._next_label_suffix("tbl")
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        md = dialog.build_markdown()
        cursor = self.editor.textCursor()
        if cursor.positionInBlock() != 0:
            cursor.insertText("\n")
        cursor.insertText(md)
        self.editor.setFocus()

    def insert_checklist(self) -> None:
        """Open checklist dialog, then insert task-list items at cursor."""
        dialog = ChecklistDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        md = dialog.build_markdown()
        cursor = self.editor.textCursor()
        # build_markdown already starts with a blank line, so we only
        # need to move to a new line when we are not at the start of
        # the document and the leading blank line is not enough.
        cursor.insertText(md)
        self.editor.setFocus()

    def insert_two_columns(self) -> None:
        """Open TwoColumnDialog; insert a two-column fenced-div block."""
        dialog = TwoColumnDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        md = dialog.build_markdown()
        cursor = self.editor.textCursor()
        # build_markdown starts with a blank line for separation.
        cursor.insertText(md)
        self.editor.setFocus()

    def insert_three_columns(self) -> None:
        """Open ThreeColumnDialog; insert a three-column fenced-div block."""
        dialog = ThreeColumnDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        md = dialog.build_markdown()
        cursor = self.editor.textCursor()
        # build_markdown starts with a blank line for separation.
        cursor.insertText(md)
        self.editor.setFocus()

    def insert_equation(self) -> None:
        """Open EquationDialog; insert display equation on accept."""
        dialog = EquationDialog(
            self, default_id=self._next_label_suffix("eq")
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        md = dialog.build_markdown()
        cursor = self.editor.textCursor()
        if cursor.positionInBlock() != 0:
            cursor.insertText("\n")
        cursor.insertText(md + "\n")
        self.editor.setFocus()

    def insert_footnote(self) -> None:
        """Open FootnoteDialog; insert marker + append definition.

        The inline marker ``[^fn-N]`` is inserted at the caret and the
        matching definition ``[^fn-N]: ...`` is appended to the end of
        the buffer (footnote definitions may live anywhere; end-of-doc
        keeps the prose clean). The default id is the next sequential
        footnote suffix.
        """
        default_id = next_footnote_suffix(self.editor.toPlainText())
        dialog = FootnoteDialog(self, default_id=default_id)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        marker, definition = dialog.build_parts()
        cursor = self.editor.textCursor()
        cursor.insertText(marker)
        # Append the definition at the very end of the buffer.
        end = self.editor.textCursor()
        end.movePosition(QTextCursor.MoveOperation.End)
        current = self.editor.toPlainText()
        prefix = "" if current.endswith("\n\n") else (
            "\n" if current.endswith("\n") else "\n\n"
        )
        end.insertText(f"{prefix}{definition}\n")
        self.editor.setFocus()

    def insert_page_break(self) -> None:
        """Insert a ``[[pagebreak]]`` marker on its own line."""
        cursor = self.editor.textCursor()
        if cursor.positionInBlock() != 0:
            cursor.insertText("\n")
        cursor.insertText("[[pagebreak]]\n")
        self.editor.setFocus()

    def insert_index_marker(self, kind: str) -> None:
        """Insert a ``[[kind]]`` auto-index marker on its own line."""
        cursor = self.editor.textCursor()
        if cursor.positionInBlock() != 0:
            cursor.insertText("\n")
        cursor.insertText(f"[[{kind}]]\n")
        self.editor.setFocus()

    def insert_code_block(self) -> None:
        """Insert a fenced Python code block skeleton."""
        self._insert_template(snippets.CODE_BLOCK_TEMPLATE, "CODE")

    def insert_design_block(self, kind: str = "stat") -> None:
        """Insert a shared design block (card, big stat, timeline, ...)."""
        from epy_reports._core._design import design_block  # noqa: PLC0415

        skeleton, token = design_block(kind)
        self._insert_template(skeleton, token)

    def insert_disclosure(self, kind: str = "ai") -> None:
        """Insert a disclosure note (AI use, document integrity, ...)."""
        from epy_reports._core._design import disclosure_block  # noqa: PLC0415

        skeleton, token = disclosure_block(kind)
        self._insert_template(skeleton, token)

    def insert_callout(self, kind: str = "note") -> None:
        """Insert a Quarto fenced callout, with title prompt if needed."""
        template = snippets.CALLOUT_TEMPLATES.get(
            kind, snippets.CALLOUT_TEMPLATES["note"]
        )
        if "TITLE" in template:
            title, ok = QInputDialog.getText(
                self, "Callout title", "Title:", text=kind.title(),
            )
            if ok and title:
                template = template.replace("TITLE", title)
        token = "TITLE" if "TITLE" in template else "BODY"
        self._insert_template(template, token)

    def insert_cross_reference(self) -> None:
        """Open the cross-ref picker and insert ``@label`` on confirm.

        The picker is fed with both buffer labels (figure / table /
        equation / section) and BibTeX entries from the linked
        ``bibliography:`` file, so a single shortcut can cite
        anything.
        """
        text = self.editor.toPlainText()
        labels = snippets.find_labels(text)
        bib_entries = self._bib_entries_for_buffer(text)
        cite_labels = [
            snippets.Label(kind="cite", name=entry.key)
            for entry in bib_entries
        ]
        combined = labels + cite_labels
        if not combined:
            QMessageBox.information(
                self,
                i18n.tr("Cross-reference"),
                i18n.tr(
                    "Nothing to cite yet. Add a figure / table / "
                    "equation / section heading, or link a "
                    "bibliography (.bib)."
                ),
            )
            return
        # Pre-fetch bib metadata for nicer labels in the picker.
        bib_lookup = {e.key: e for e in bib_entries}
        dialog = CrossRefDialog(
            combined, parent=self, bib_lookup=bib_lookup
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        chosen = dialog.selected_label()
        if chosen is None:
            return
        cursor = self.editor.textCursor()
        cursor.insertText(f"@{chosen.name}")
        self.editor.setFocus()

    # ------------------------------------------- bibliography link

    def link_bibliography(self, bib_path: Path) -> None:
        """Write ``bibliography: <path>`` into the YAML front matter.

        The path is stored relative to the file's directory when the
        document already lives on disk, so the link travels with the
        project. A new YAML block is created at the top of the buffer
        if none exists.
        """
        text = self.editor.toPlainText()
        value = self._relative_to_doc(bib_path)
        updated = snippets.set_metadata_field(text, "bibliography", value)
        if updated == text:
            return
        self._apply_buffer_replacement(updated)

    def bib_entries(self) -> list:
        """Return the parsed BibTeX entries for the linked bib file."""
        return self._bib_entries_for_buffer(self.editor.toPlainText())

    def bib_path(self) -> Path | None:
        """Return the resolved path of the linked .bib, or ``None``.

        Mirrors the resolution logic used to load the entries — the
        path comes from the ``bibliography:`` YAML field, resolved
        against the document's directory when relative. Existence is
        not enforced; the caller can use the result as the *target*
        of a write operation even when the file does not exist yet.
        """
        meta = snippets.parse_front_matter(self.editor.toPlainText())
        value = meta.get("bibliography")
        if not value:
            return None
        bib_path = Path(value)
        if not bib_path.is_absolute() and self._path is not None:
            bib_path = (self._path.parent / bib_path).resolve()
        return bib_path

    # ------------------------------------------------- internals

    def _bib_entries_for_buffer(self, text: str) -> list:
        """Resolve the ``bibliography:`` field and parse the .bib."""
        from epy_reports._core import bib

        meta = snippets.parse_front_matter(text)
        value = meta.get("bibliography")
        if not value:
            return []
        bib_path = Path(value)
        if not bib_path.is_absolute() and self._path is not None:
            bib_path = (self._path.parent / bib_path).resolve()
        if not bib_path.is_file():
            return []
        return bib.parse_bib_file(bib_path)

    def _relative_to_doc(self, target: Path) -> str:
        """Return ``target`` relative to the file directory if possible."""
        target = target.resolve()
        if self._path is None:
            return str(target).replace("\\", "/")
        base = self._path.parent.resolve()
        try:
            rel = target.relative_to(base)
            return str(rel).replace("\\", "/")
        except ValueError:
            return str(target).replace("\\", "/")

    def _apply_buffer_replacement(self, new_text: str) -> None:
        """Replace the entire buffer atomically and update state."""
        cursor = self.editor.textCursor()
        cursor.beginEditBlock()
        try:
            cursor.select(QTextCursor.SelectionType.Document)
            cursor.insertText(new_text)
        finally:
            cursor.endEditBlock()
        self._set_dirty(True)
        self._render_now()

    # -------------------------------------------- editor primitives

    def _wrap_selection(
        self, left: str, right: str, placeholder: str = ""
    ) -> None:
        """Wrap the selection in ``left``/``right`` or insert markers.

        Without a selection, ``placeholder`` is inserted between the
        markers and pre-selected so the user can type over it.
        """
        cursor = self.editor.textCursor()
        if cursor.hasSelection():
            text = cursor.selectedText()
            cursor.insertText(f"{left}{text}{right}")
        else:
            cursor.insertText(f"{left}{placeholder}{right}")
            end = cursor.position()
            cursor.setPosition(end - len(right) - len(placeholder))
            cursor.setPosition(
                end - len(right),
                QTextCursor.MoveMode.KeepAnchor,
            )
            self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    def _insert_template(self, template: str, select_token: str) -> None:
        """Insert ``template`` at the caret and select ``select_token``.

        Block-level templates get a leading newline when the caret is
        not already at the start of a line, so the inserted Markdown
        does not glue to the previous paragraph.
        """
        cursor = self.editor.textCursor()
        block_template = "\n" in template
        if block_template and cursor.positionInBlock() != 0:
            cursor.insertText("\n")
        start = cursor.position()
        cursor.insertText(template)
        index = template.find(select_token)
        if index >= 0:
            cursor.setPosition(start + index)
            cursor.setPosition(
                start + index + len(select_token),
                QTextCursor.MoveMode.KeepAnchor,
            )
            self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    # ----------------------------------------------------- internals

    def _set_dirty(self, value: bool) -> None:
        """Update the dirty flag and notify listeners on change."""
        if self._dirty != value:
            self._dirty = value
            self.dirtyChanged.emit(value)

    def _on_text_changed(self) -> None:
        """React to user edits: flag dirty and schedule a re-render."""
        if self._suppress_change:
            return
        if not self._dirty:
            self._set_dirty(True)
        self._render_timer.start()

    def _render(self) -> None:
        """Debounced re-render after an edit; keeps the scroll position."""
        self._render_now(preserve=True)

    def _render_now(self, *, preserve: bool = False) -> None:
        r"""Render synchronously via file:// to bypass setHtml's 2 MB cap.

        The HTML embeds the entire MathJax bundle inline (~2 MB) so
        equations render offline. ``setHtml`` truncates anything past
        2 MB, which left MathJax untyped and equations stuck as raw
        ``\[ … \]`` text. Writing to a per-tab temp file and using
        ``view.load()`` removes the cap. The ``<base href>`` tag in
        the rendered HTML still points at the document's directory,
        so relative figures, bib files and links resolve correctly.

        When ``preserve`` is set (an edit or theme change to the same
        document), the preview's scroll position is captured and
        re-applied after the reload, so it does not jump back to the top
        on every keystroke.
        """
        self._render_into_view(paged=self._paged, preserve=preserve)

    def _render_into_view(
        self,
        *,
        paged: bool,
        page_size: str | None = None,
        preserve: bool = False,
    ) -> None:
        """Render the buffer into the preview, forcing ``paged`` state.

        Shared by the live preview (``_render_now``) and the PDF export
        path, which needs to force a non-paged render before printing.
        The page size comes from the document's ``page-size`` front
        matter (default Letter) unless ``page_size`` overrides it, so
        the preview sheet matches what the export will produce.

        Args:
            paged: Whether to render the paged-preview sheet.
            page_size: Explicit page-size key. ``None`` reads it from
                the buffer's front matter.
            preserve: When ``True``, capture the preview's scroll position
                before the reload and restore it afterwards.
        """
        text = self.editor.toPlainText()
        if page_size is None:
            meta = snippets.parse_front_matter(text)
            page_size = normalize_page_size(meta.get("page-size"))
        base_dir = self._path.parent if self._path is not None else None
        title = (
            self._path.name if self._path is not None else UNTITLED
        )
        try:
            html = render_markdown(
                text,
                base_dir=base_dir,
                title=title,
                theme_css=self._theme_css,
                paged=paged,
                page_size=page_size,
            )
        except Exception as exc:
            msg = str(exc).replace("&", "&amp;").replace("<", "&lt;")
            html = (
                "<!doctype html><html><head><meta charset='utf-8'></head>"
                "<body style='font-family:monospace;padding:1em;color:#c00'>"
                f"<b>Render error</b><pre>{msg}</pre>"
                "</body></html>"
            )
        if self._preview_tmp_dir is None:
            self._preview_tmp_dir = Path(
                tempfile.mkdtemp(prefix="epy_reports_preview_")
            )
        preview_path = self._preview_tmp_dir / "preview.html"
        preview_path.write_text(html, encoding="utf-8")
        url = QUrl.fromLocalFile(str(preview_path.resolve()))
        # Load immediately and unconditionally; ``?r=`` forces a real reload
        # and, when preserving, the ``#fragment`` carries the scroll ratio to
        # return to. Never wait on a callback.
        self._render_seq += 1
        url.setQuery(f"r={self._render_seq}")
        if preserve and self._last_pos:
            url.setFragment(self._last_pos)
        self._expect_render_load = True
        self.view.load(url)

    def _on_preview_load_finished(self, _ok: bool) -> None:
        """Drop stale history after render loads (keep it for navigation).

        Every debounced re-render loads a new ``?r=`` URL; without this,
        the session history fills with one entry per keystroke and Back
        walks through them. History that the USER built by navigating
        (an anchor jump, a web link) is preserved: those loads do not
        carry the render flag.
        """
        if self._expect_render_load:
            self._expect_render_load = False
            self.view.history().clear()

    def _poll_position(self) -> None:
        """Cache the preview scroll position for the next render."""
        page = self.view.page()
        if page is not None:
            page.runJavaScript(_CAPTURE_POS_JS, self._store_position)

    def _store_position(self, pos: object) -> None:
        """Record a captured ``epypos=…`` token (ignore empty/None)."""
        if isinstance(pos, str) and pos:
            self._last_pos = pos

    def cleanup_preview_tmp(self) -> None:
        """Delete the temp dir backing the live preview (call on close)."""
        tmp = self._preview_tmp_dir
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)
            self._preview_tmp_dir = None
