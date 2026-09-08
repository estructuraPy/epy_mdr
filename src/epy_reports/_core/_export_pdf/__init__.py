"""Headless Markdown -> PDF rendering for the scriptable API.

Two-pass Paged.js print flow (theme page background, header/footer, grayscale
watermark and document metadata stamped in) so ``Report.to_pdf`` produces the
same PDF the interactive editor does — including index page numbers
(TOC/LOF/LOT/LOE) and cover-aware, section-restarting numbering. The first
pass records the physical page of every anchored heading/figure/table/equation
as a PDF named destination; the index placeholders are filled from that map,
the body is renumbered from 1, and a second pass prints the final PDF. Falls
back to a single pass when the Qt build emits no named destinations. Requires
PySide6; the Qt import is deferred to call time.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

_PAGE_SIZES = {"letter": "Letter", "a4": "A4", "legal": "Legal"}


def render_report_pdf(
    source: str,
    out_path: Path,
    *,
    base_dir: Path | None,
    theme_css: str,
    page_bg: str = "",
    timeout_ms: int = 60000,
) -> None:
    """Render Markdown ``source`` to a paginated PDF via Paged.js.

    Runs the two-pass flow the interactive editor uses: a first export pass
    records the physical page of every anchored heading/figure/table/equation
    (Qt names them as PDF destinations), the index placeholders are filled
    from that map and the body is renumbered from 1, then a second pass prints
    the final PDF. Footer/header numbering restarts per ``[[section-roman]]`` /
    ``[[section-arabic]]`` boundary. When the Qt build emits no named
    destinations the first pass is kept as-is (single-pass fallback).

    A ``cover-pdf`` declared in the front matter is joined at the front
    after the stamping, so it carries no page number; ``annexes`` are
    joined at the back before it, so they are numbered in continuity
    with the body, under a generated section that enters the index.

    Raises:
        FileNotFoundError: When a declared cover or annex is not on
            disk. Raised before rendering starts.
        ValueError: When either key is present and declares nothing.
        RuntimeError: When the Paged.js export does not complete.
    """
    import shutil  # noqa: PLC0415

    # The stamping moved to epy_export, where it lives once instead
    # of twice. Bound to the old local name so the call sites below
    # read as they did: this commit is a MOVE, and a diff that also
    # renames seven call sites hides whether anything else changed.
    import epy_export as _pdf_footer  # noqa: PLC0415
    from PySide6.QtCore import (  # noqa: PLC0415
        QElapsedTimer,
        QEventLoop,
        QMarginsF,
        Qt,
        QUrl,
    )
    from PySide6.QtGui import QPageLayout, QPageSize  # noqa: PLC0415
    from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: PLC0415
    from PySide6.QtWidgets import QApplication  # noqa: PLC0415

    from epy_reports._core.renderer import (  # noqa: PLC0415, E501
        append_annex_section,
        inject_page_numbers,
        normalize_page_size,
        render_markdown,
    )
    from epy_reports._core.snippets import (  # noqa: PLC0415
        parse_front_matter,
        parse_header_cells,
        resolve_pdf_attachments,
    )
    from epy_reports._core.template import is_truthy  # noqa: PLC0415

    meta = parse_front_matter(source)
    page_size = normalize_page_size(meta.get("page-size"))
    lang = meta.get("lang", "en")
    has_cover = is_truthy(meta.get("cover"))

    # Read before rendering: a mistyped path costs a message here, and
    # two Paged.js passes if it is discovered at the joining step.
    cover_pdf, annex_pdfs = resolve_pdf_attachments(meta, base_dir)
    if annex_pdfs:
        source = append_annex_section(source, lang)

    app = QApplication.instance() or QApplication([])
    export_html = render_markdown(
        source, base_dir=base_dir, theme_css=theme_css,
        page_size=page_size, for_export=True,
    )

    view = QWebEngineView()
    view.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    view.resize(820, 1060)
    view.show()

    page_enum = getattr(
        QPageSize.PageSizeId, _PAGE_SIZES.get(page_size, "Letter")
    )
    layout = QPageLayout(
        QPageSize(page_enum), QPageLayout.Orientation.Portrait,
        QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter,
    )

    def pump(ms: int) -> None:
        timer = QElapsedTimer()
        timer.start()
        while timer.elapsed() < ms:
            app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 30)

    def js(expr: str) -> object:
        box: dict[str, object] = {"v": None}
        view.page().runJavaScript(expr, lambda v: box.__setitem__("v", v))
        timer = QElapsedTimer()
        timer.start()
        while box["v"] is None and timer.elapsed() < 4000:
            app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 30)
        return box["v"]

    def print_html(html: str, out_pdf: Path) -> bool:
        """Load ``html``, wait for Paged.js, then print to ``out_pdf``."""
        tmp = out_pdf.with_suffix(".tmp.html")
        tmp.write_text(html, encoding="utf-8")
        loaded = {"ok": False}
        state = {"printed": False, "ok": False}
        load_conn = view.loadFinished.connect(
            lambda ok: loaded.__setitem__("ok", ok)
        )
        view.load(QUrl.fromLocalFile(str(tmp.resolve())))
        timer = QElapsedTimer()
        timer.start()
        while not loaded["ok"] and timer.elapsed() < timeout_ms:
            app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 30)
        while js("window._paged_done === true") is not True and (
            timer.elapsed() < timeout_ms
        ):
            pump(150)
        pump(200)
        print_conn = view.page().pdfPrintingFinished.connect(
            lambda _p, ok: (
                state.__setitem__("ok", ok),
                state.__setitem__("printed", True),
            )
        )
        view.page().printToPdf(str(out_pdf), layout)
        while not state["printed"] and timer.elapsed() < timeout_ms + 10000:
            app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 30)
        view.loadFinished.disconnect(load_conn)
        view.page().pdfPrintingFinished.disconnect(print_conn)
        tmp.unlink(missing_ok=True)
        return bool(state["ok"]) and out_pdf.exists()

    pass1 = out_path.with_suffix(".pass1.pdf")
    segments: list[tuple[int, str]] | None = None
    start_page = 1
    try:
        if not print_html(export_html, pass1):
            raise RuntimeError("PDF export failed (Paged.js pass 1)")
        anchors = _pdf_footer.extract_anchor_pages(pass1)
        content = {
            a: p for a, p in anchors.items()
            if not a.startswith("epy-section-")
        }
        segments = sorted(
            (p, "roman" if a.startswith("epy-section-roman-") else "arabic")
            for a, p in anchors.items()
            if a.startswith(("epy-section-roman-", "epy-section-arabic-"))
        ) or None
        if content:
            # Index blocks emit only links, so every destination is body
            # content; the smallest is the first content page. Cover +
            # TOC/LOF/LOT/LOE before it are unnumbered front matter and the
            # body is renumbered from 1.
            start_page = min(content.values())
            html2 = inject_page_numbers(export_html, anchors, start_page - 1)
            if not print_html(html2, out_path):
                raise RuntimeError("PDF export failed (Paged.js pass 2)")
        else:
            # No named destinations (older Qt): keep pass 1 and stamp from the
            # page after the cover when present.
            shutil.copyfile(pass1, out_path)
            start_page = 2 if has_cover else 1
            segments = None
    finally:
        view.deleteLater()
        pump(20)
        pass1.unlink(missing_ok=True)

    if not out_path.exists():
        raise RuntimeError("PDF export failed (Paged.js did not complete)")

    # Stamp overlays (best-effort) on a temp copy, then move into place.
    work = Path(tempfile.mkdtemp(prefix="epy_reports_pdf_")) / "out.pdf"
    work.write_bytes(out_path.read_bytes())
    try:
        # BEFORE the stamping, which is what numbers these pages: the
        # annexes are part of the document, so the footer that follows
        # counts them in continuity with the body.
        if annex_pdfs:
            _pdf_footer.append_pdf(work, annex_pdfs)
        if page_bg:
            _pdf_footer.add_page_background(work, page_bg)
        watermark = (meta.get("watermark") or "").strip()
        if watermark:
            wm = Path(watermark)
            if not wm.is_absolute() and base_dir is not None:
                wm = base_dir / watermark
            if wm.is_file():
                _pdf_footer.add_watermark(work, wm)
        header_cells = parse_header_cells(meta.get("header"))
        if any(header_cells):
            _pdf_footer.add_header(
                work, header_cells, lang=lang, start_page=start_page
            )
        footer_text = meta.get("footer", "")
        page_numbers = is_truthy(meta.get("page-numbers"))
        if footer_text or page_numbers:
            _pdf_footer.add_footer(
                work, footer_text, page_numbers=page_numbers,
                lang=lang, start_page=start_page, segments=segments,
            )
        _pdf_footer.add_metadata(
            work,
            title=meta.get("title", ""),
            author=meta.get("author", ""),
            subject=meta.get("subtitle", ""),
            keywords=meta.get("keywords", ""),
            rights=meta.get("copyright", ""),
            creator="epy_reports",
            producer="epy_reports — ANM Ingeniería",
        )
        # AFTER the stamping, which is what keeps this page out of the
        # numbering: the reader's cover template is front matter, and
        # the body was already renumbered from 1, so the pages the
        # index declares do not move.
        if cover_pdf is not None:
            _pdf_footer.prepend_pdf(work, cover_pdf)
        out_path.write_bytes(work.read_bytes())
    finally:
        shutil.rmtree(work.parent, ignore_errors=True)
