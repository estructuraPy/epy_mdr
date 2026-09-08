"""Render Quarto / Pandoc Markdown to a styled HTML document.

The actual conversion is delegated to Pandoc (bundled by
``pypandoc-binary``). A small Quarto preprocessor expands titled
fenced callouts so they render with a visible header. A second
preprocessor resolves Quarto-style cross-references
(``@fig-x``, ``@tbl-x``, ``@eq-x``, ``@sec-x``) before Pandoc
sees the source, so they render correctly even without a Quarto
installation.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from importlib import resources
from pathlib import Path

import pypandoc

from epy_reports._core._diagrams import diagram_engines, expand_diagrams
from epy_reports._core._media_export import (
    collect_diagrams,
    render_diagram_pngs,
    simplify_components_for_export,
    substitute_diagram_images,
)
from epy_reports._core._plotly import (
    expand_plotly,
    has_plotly,
    strip_plotly_for_export,
)
from epy_reports._core.snippets import parse_front_matter, strip_front_matter
from epy_reports._core.template import build_html_document

# Citation Style Language: short names users can type in YAML (``csl:
# ieee``) or pick from the View > Citation style menu, mapped to the
# bundled .csl file under ``epy_reports/_config/_assets/csl/``.
CSL_STYLES: dict[str, str] = {
    "ieee":      "ieee.csl",
    "apa":       "apa.csl",
    "chicago":   "chicago-author-date.csl",
    "harvard":   "harvard-cite-them-right.csl",
    "mla":       "modern-language-association.csl",
    "acs":       "american-chemical-society.csl",
    "ama":       "american-medical-association.csl",
    "vancouver": "elsevier-vancouver.csl",
    "nature":    "nature.csl",
    "science":   "science.csl",
    "asce":      "american-society-of-civil-engineers.csl",
    "elsevier":  "elsevier-harvard.csl",
    "springer":  "springer-basic-author-date.csl",
    "apsa":      "american-political-science-association.csl",
}
DEFAULT_CSL_STYLE = "ieee"

# Page sizes — single source of truth shared by the paged preview
# (CSS sheet dimensions) and the PDF export (QPageLayout). Each value
# is ``(width_mm, height_mm)`` in portrait orientation.
PAGE_SIZES: dict[str, tuple[float, float]] = {
    "letter": (215.9, 279.4),
    "a4":     (210.0, 297.0),
    "legal":  (215.9, 355.6),
}
DEFAULT_PAGE_SIZE = "letter"


def normalize_page_size(value: str | None) -> str:
    """Return a valid page-size key, falling back to the default.

    Args:
        value: Raw ``page-size`` front-matter value (any case), or
            ``None`` when the key is absent.

    Returns:
        One of ``"letter"``, ``"a4"`` or ``"legal"``. Missing or
        unknown values normalize to :data:`DEFAULT_PAGE_SIZE`.
    """
    key = (value or "").strip().lower()
    return key if key in PAGE_SIZES else DEFAULT_PAGE_SIZE


# Matches the empty page-number placeholders emitted in index blocks
# (TOC / LOF / LOT / LOE). They are filled in a second export pass once
# the anchor → page mapping is known.
PAGE_NUM_SPAN_RE = re.compile(
    r'<span class="page-num" data-ref="([^"]+)"></span>'
)


def inject_page_numbers(
    html: str, anchor_to_page: dict[str, int], offset: int = 0
) -> str:
    """Fill index page-number placeholders with resolved page numbers.

    Replaces each ``<span class="page-num" data-ref="…"></span>`` with the
    page number of its target anchor. ``offset`` is subtracted from every
    physical page so the printed index numbers match the footer, which
    restarts at 1 on the first content page (cover and index pages are
    unnumbered front matter). Placeholders whose anchor is unknown are
    left untouched.

    Args:
        html: Rendered HTML containing the placeholders.
        anchor_to_page: Map of anchor id → 1-based physical page number.
        offset: Pages of front matter to subtract (``first_content_page
            - 1``). Defaults to 0 (no renumbering).

    Returns:
        The HTML with placeholders filled in.
    """
    def replace(m: re.Match) -> str:
        ref = m.group(1)
        page = anchor_to_page.get(
            ref, anchor_to_page.get(ref.lstrip("/"), 0)
        )
        if page:
            return (
                f'<span class="page-num" data-ref="{ref}">'
                f"{page - offset}</span>"
            )
        return m.group(0)

    return PAGE_NUM_SPAN_RE.sub(replace, html)


def page_size_dimensions(value: str | None) -> tuple[float, float]:
    """Return the ``(width_mm, height_mm)`` for a page-size value.

    The value is normalized first, so unknown or missing values map to
    the default page size's dimensions.
    """
    return PAGE_SIZES[normalize_page_size(value)]


def _resolve_csl(
    csl_value: str | None, base_dir: Path | None
) -> Path | None:
    """Resolve a YAML ``csl:`` value to an existing ``.csl`` file.

    The value may be (1) a short name like ``ieee`` / ``apa`` /
    ``chicago`` that maps to a bundled stylesheet, (2) a relative path
    to a ``.csl`` next to the document, or (3) an absolute path.
    ``None`` or an empty value selects the bundled default (IEEE) so
    every document picks up a styled bibliography without setup.
    """
    key = (csl_value or DEFAULT_CSL_STYLE).strip().lower()
    if key in CSL_STYLES:
        try:
            anchor = resources.files("epy_reports._config._assets.csl")
            target = anchor.joinpath(CSL_STYLES[key])
            with resources.as_file(target) as path:
                if Path(path).is_file():
                    return Path(path)
        except (FileNotFoundError, ModuleNotFoundError):
            return None
        return None
    return _resolve_doc_path(csl_value or "", base_dir)

PANDOC_FORMAT = (
    "markdown"
    "+fenced_divs"
    "+bracketed_spans"
    "+fenced_code_attributes"
    "+link_attributes"
    "+inline_code_attributes"
    "+definition_lists"
    "+tex_math_dollars"
    "+tex_math_single_backslash"
    "+inline_notes"
    "-yaml_metadata_block"
    "+pipe_tables"
    "+grid_tables"
    "+raw_html"
    "+raw_attribute"
    "+implicit_figures"
    "+task_lists"
    "+fancy_lists"
    "+startnum"
    "+example_lists"
    "+citations"
    "+abbreviations"
    "+smart"
    "+autolink_bare_uris"
    "+strikeout"
    "+subscript"
    "+superscript"
)

PANDOC_ARGS = [
    "--mathjax",
    "--syntax-highlighting=tango",
    "--section-divs",
    "--wrap=preserve",
]

CALLOUT_KINDS = ("note", "tip", "warning", "important", "caution")


_CALLOUT_OPEN_RE = re.compile(
    r"^:::+\s*\{\.callout-(?P<kind>"
    + "|".join(CALLOUT_KINDS)
    + r")"
    r"(?:\s+(?P<attrs>[^}]*))?\}\s*$",
    re.MULTILINE,
)

_TITLE_ATTR_RE = re.compile(r'title="([^"]*)"')


def _resolve_doc_path(value: str, base_dir: Path | None) -> Path | None:
    """Resolve a path declared in YAML metadata.

    ``value`` is interpreted relative to ``base_dir`` (the directory of
    the .qmd file) unless it is absolute. Returns ``None`` when the
    resolved path does not exist on disk.
    """
    candidate = Path(value)
    if not candidate.is_absolute() and base_dir is not None:
        candidate = (base_dir / candidate).resolve()
    return candidate if candidate.is_file() else None


def _bibliography_args(
    metadata: dict[str, str], base_dir: Path | None
) -> list[str]:
    """Build the ``--citeproc`` / ``--bibliography`` Pandoc arguments.

    If the YAML front matter declares ``bibliography`` and the file
    resolves on disk, citeproc is enabled. ``csl`` is optional.
    """
    bib_value = metadata.get("bibliography")
    if not bib_value:
        return []
    bib_path = _resolve_doc_path(bib_value, base_dir)
    if bib_path is None:
        return []
    extra: list[str] = [
        "--citeproc",
        f"--bibliography={bib_path}",
    ]
    csl_path = _resolve_csl(metadata.get("csl"), base_dir)
    if csl_path is not None:
        extra.append(f"--csl={csl_path}")
    return extra


def _expand_quarto_callouts(source: str) -> str:
    """Rewrite Quarto-titled callouts into nested Pandoc fenced divs.

    Quarto allows::

        ::: {.callout-note title="Heads up"}
        body
        :::

    Pandoc's ``fenced_divs`` keeps ``title`` only as an HTML attribute,
    so the heading would not be visible. We rewrite the opening fence
    into nested divs (``callout`` + ``callout-titled`` + an inner
    ``callout-title`` div containing the title text) and let CSS take
    care of the styling.
    """

    def replace(match: re.Match[str]) -> str:
        kind = match.group("kind")
        attrs = match.group("attrs") or ""
        title_match = _TITLE_ATTR_RE.search(attrs)
        classes = f".callout .callout-{kind}"
        if not title_match:
            return f"::: {{{classes}}}"
        title_text = title_match.group(1).strip()
        return (
            f"::: {{{classes} .callout-titled}}\n"
            f"::: {{.callout-title}}\n"
            f"{title_text}\n"
            f":::"
        )

    return _CALLOUT_OPEN_RE.sub(replace, source)


# ---------------------------------------------------------------------------
# Cross-reference resolver
# ---------------------------------------------------------------------------

# Matches a Quarto label definition like {#fig-x} or {#tbl-y width=80%}.
_XREF_DEF_RE = re.compile(
    r"\{#(?P<label>(?P<kind>fig|tbl|eq|sec)-[A-Za-z0-9_-]+)[^}]*\}"
)

# Matches a cross-reference like @fig-x, @tbl-y, @eq-z, @sec-w.
# Deliberately restricted to the four Quarto kinds so that bibliography
# citations like @navarro2020 pass through unchanged.
_XREF_REF_RE = re.compile(
    r"@(?P<label>(?:fig|tbl|eq|sec)-[A-Za-z0-9_-]+)"
)

# Figure caption: ![CAP](path){#fig-x ...}
_FIG_CAP_RE = re.compile(
    r"(!\[)((?!(?:[A-Z][a-záéíóúüñA-Z]+ )+\d+:)[^]]*)"
    r"(\]\([^)]*\)\{#(?P<label>fig-[A-Za-z0-9_-]+)[^}]*\})"
)

# Table caption: `: CAP {#tbl-x ...}`  (Pandoc table caption syntax)
_TBL_CAP_RE = re.compile(
    r"^(:\s+)((?!(?:[A-Z][a-záéíóúüñA-Z]+ )+\d+:).+?)"
    r"(\s+\{#(?P<label>tbl-[A-Za-z0-9_-]+)[^}]*\}\s*)$"
)

# Standalone figure caption: `: CAP {#fig-x ...}` on its own line — the
# figure analogue of the Pandoc table-caption line, for figures that are
# NOT markdown images (interactive plotly fences, raw-HTML blocks). The
# resolver rewrites it to a numbered caption paragraph + anchor span, so
# it participates in numbering, @fig- references and the [[lof]] index.
_FIGLINE_CAP_RE = re.compile(
    r"^:\s+((?!(?:[A-Z][a-záéíóúüñA-Z]+ )+\d+:).+?)"
    r"\s+\{#(?P<label>fig-[A-Za-z0-9_-]+)[^}]*\}\s*$"
)

# A figure label attribute in prose that no caption construct consumed —
# not attached to an image (`](path){#fig-x}` puts `)` before `{`). Pandoc
# would print it verbatim (the "{#fig-x} leaked into the caption" defect);
# the resolver rewrites it to an invisible anchor span instead so @fig-
# references keep a live target. fig-only on purpose: tbl/eq/sec attrs are
# consumed by Pandoc (table captions, headings) or handled by _tag_eq.
_ORPHAN_FIG_ATTR_RE = re.compile(
    r"(?<![\)\]])\{#(?P<label>fig-[A-Za-z0-9_-]+)[^}]*\}"
)

# Equation block closing: optional whitespace before `$$` then `{#eq-x}`
# Handles both  `$$ {#eq-x}`  and  `$$  {#eq-x}`  on the same line.
_EQ_CLOSE_RE = re.compile(
    r"(\$\$)\s+(\{#(?P<label>eq-[A-Za-z0-9_-]+)[^}]*\})"
)

# Localised words for the four kinds.
_WORDS: dict[str, dict[str, str]] = {
    "en": {
        "fig": "Figure",
        "tbl": "Table",
        "eq": "Equation",
        "sec": "Section",
    },
    "es": {
        "fig": "Figura",
        "tbl": "Tabla",
        "eq": "Ecuación",
        "sec": "Sección",
    },
}

# Localised section titles for the auto-generated index blocks.
_INDEX_TITLES: dict[str, dict[str, str]] = {
    "en": {
        "toc": "Contents",
        "lof": "List of Figures",
        "lot": "List of Tables",
        "loe": "List of Equations",
    },
    "es": {
        "toc": "Contenido",
        "lof": "Índice de figuras",
        "lot": "Índice de tablas",
        "loe": "Índice de ecuaciones",
    },
}

# Title of the divider section the reader's annex PDFs are joined to.
# Document language, not interface language: a document that declares
# ``lang: es`` says "Anexos" whatever menu language the export ran from.
_ANNEX_TITLES: dict[str, str] = {"en": "Annexes", "es": "Anexos"}

# Fence-start / end detector (``` or ~~~, any leading spaces).
_FENCE_RE = re.compile(r"^\s*(```|~~~)")

# Standalone display-math delimiter: a line with only $$ (and whitespace).
_DMATH_LINE_RE = re.compile(r"^\s*\$\$\s*$")

# One or more backtick runs — used to strip inline code spans.
_INLINE_CODE_RE = re.compile(r"`+[^`]*`+")


def _strip_code_spans(text: str) -> list[tuple[str, bool]]:
    """Split *text* into ``(segment, is_code)`` pairs.

    Non-code segments are the prose the resolver may transform; code
    segments must be returned verbatim.
    """
    result: list[tuple[str, bool]] = []
    last = 0
    for m in _INLINE_CODE_RE.finditer(text):
        if m.start() > last:
            result.append((text[last : m.start()], False))
        result.append((m.group(), True))
        last = m.end()
    if last < len(text):
        result.append((text[last:], False))
    return result


def _number_labels(source: str) -> dict[str, int]:
    """Assign sequential per-kind numbers to every label definition.

    Scans ``source`` line by line, skipping fenced code blocks, and
    numbers each ``{#fig-x}`` / ``{#tbl-x}`` / ``{#eq-x}`` / ``{#sec-x}``
    definition in document order. This is the shared numbering pass used
    by both :func:`_resolve_crossrefs` and :func:`collect_index_entries`
    so the cross-reference links and the auto-generated lists always
    agree on the numbers.

    Args:
        source: Raw Markdown / Quarto source text.

    Returns:
        Mapping from full label (e.g. ``fig-capacity``) to its number.
    """
    numbers: dict[str, int] = {}
    counters: dict[str, int] = {"fig": 0, "tbl": 0, "eq": 0, "sec": 0}
    in_fence = False
    for line in source.splitlines(keepends=True):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for m in _XREF_DEF_RE.finditer(line):
            label = m.group("label")
            kind = m.group("kind")
            if label not in numbers:
                counters[kind] += 1
                numbers[label] = counters[kind]
    return numbers


def _effective_lang(metadata: dict) -> str:
    """Resolve the language used for localized labels and index titles.

    An explicit front-matter ``lang:`` always wins. Without one, fall
    back to the application UI language so the preview and every export
    (HTML/PDF/DOCX) follow the active language — numbered captions
    ("Figura 1" / "Figure 1"), cross-references and the [[toc]]/[[lof]]
    /[[lot]]/[[loe]] titles included — instead of silently defaulting
    to English.

    Args:
        metadata: Parsed front-matter mapping.

    Returns:
        Two-letter-style language tag (e.g. ``"en"``, ``"es"``).
    """
    lang = metadata.get("lang")
    if lang:
        return str(lang)
    from epy_reports._core import (
        _i18n,  # noqa: PLC0415  — avoid cycle at import time
    )

    return _i18n.current_language()


def _resolve_crossrefs(source: str, lang: str = "en") -> str:
    """Resolve Quarto cross-references in *source* before Pandoc sees it.

    Scans for ``{#fig-x}``, ``{#tbl-x}``, ``{#eq-x}``, ``{#sec-x}``
    label definitions and assigns sequential numbers per kind. Then
    prefixes figure/table captions and equation tags at definition sites
    and replaces ``@fig-x`` / ``@tbl-x`` / ``@eq-x`` / ``@sec-x``
    references with ``[Word N](#label)`` links.

    Only the four Quarto cross-ref prefixes are touched — bibliography
    citations (``@author2020``) pass through unchanged. Content inside
    fenced code blocks (``` / ~~~) and inline code spans is never
    transformed.

    Args:
        source: Raw Markdown / Quarto source text.
        lang: Two-letter BCP-47 language tag. ``"es"`` selects Spanish
            caption words; anything else uses English.

    Returns:
        Preprocessed source with numbered captions and resolved refs.
    """
    lang_key = lang[:2].lower() if lang else "en"
    words = _WORDS.get(lang_key, _WORDS["en"])

    # ------------------------------------------------------------------
    # PASS A — number every label definition in document order.
    # Definitions inside fenced code blocks are skipped. Shared with
    # collect_index_entries so numbering stays consistent.
    # ------------------------------------------------------------------
    numbers = _number_labels(source)
    lines = source.splitlines(keepends=True)

    # ------------------------------------------------------------------
    # PASS B + C — transform lines outside fenced blocks.
    # For each non-fence line: protect inline-code spans, apply caption
    # prefixing (B) and reference replacement (C) only to prose parts.
    # ------------------------------------------------------------------

    def _prefix_fig(line: str) -> str:
        """Prefix figure captions at their definition site."""

        def repl(m: re.Match[str]) -> str:
            label = m.group("label")
            n = numbers.get(label)
            if n is None:
                return m.group(0)
            word = words["fig"]
            return f"{m.group(1)}{word} {n}: {m.group(2)}{m.group(3)}"

        return _FIG_CAP_RE.sub(repl, line)

    def _prefix_figline(line: str) -> str:
        """Rewrite a standalone `: CAP {#fig-x}` caption line.

        Becomes an italic numbered caption paragraph plus an anchor span
        (``+bracketed_spans`` renders it as ``<span id="fig-x"></span>``,
        same mechanism as equation anchors).
        """

        def repl(m: re.Match[str]) -> str:
            label = m.group("label")
            n = numbers.get(label)
            if n is None:
                return m.group(0)
            word = words["fig"]
            return f"*{word} {n}: {m.group(1)}* []{{#{label}}}\n"

        return _FIGLINE_CAP_RE.sub(repl, line)

    def _scrub_orphan_fig(line: str) -> str:
        """Convert leftover bare figure attrs to invisible anchor spans."""

        def repl(m: re.Match[str]) -> str:
            label = m.group("label")
            if label not in numbers:
                return m.group(0)
            return f"[]{{#{label}}}"

        return _ORPHAN_FIG_ATTR_RE.sub(repl, line)

    def _prefix_tbl(line: str) -> str:
        """Prefix table captions at their definition site.

        The raw ``{#tbl-x}`` attr is swapped for a bracketed anchor span:
        plain Pandoc (unlike Quarto) does NOT consume attrs on caption
        lines — left in place it prints verbatim inside every rendered
        table caption.
        """

        def repl(m: re.Match[str]) -> str:
            label = m.group("label")
            n = numbers.get(label)
            if n is None:
                return m.group(0)
            word = words["tbl"]
            return (
                f"{m.group(1)}{word} {n}: {m.group(2)} []{{#{label}}}\n"
            )

        return _TBL_CAP_RE.sub(repl, line)

    def _replace_refs(text: str) -> str:
        """Replace @kind-label refs with [Word N](#label) links."""

        def repl(m: re.Match[str]) -> str:
            label = m.group("label")
            n = numbers.get(label)
            if n is None:
                return m.group(0)  # unknown label — leave raw
            kind = label.split("-", 1)[0]
            word = words[kind]
            return f"[{word} {n}](#{label})"

        return _XREF_REF_RE.sub(repl, text)

    def _transform_prose(text: str) -> str:
        """Apply ref replacement to prose, preserving inline code."""
        parts = _strip_code_spans(text)
        out: list[str] = []
        for segment, is_code in parts:
            out.append(segment if is_code else _replace_refs(segment))
        return "".join(out)

    # State for equation block tracking (detect pre-existing \tag).
    # eq_state[0] = True  →  current eq block already has a \tag.
    # Reset on each opening $$ line (outside a fence).
    eq_state = [False]  # mutable so nested _tag_eq can read it

    def _tag_eq(line: str) -> str:
        r"""Inject ``\tag{N}`` and an anchor span on the eq closing line.

        Replaces ``$$ {#eq-x}`` with ``\tag{N} $$ []{#eq-x}``. The
        bracketed span (``+bracketed_spans``) becomes
        ``<span id="eq-x"></span>`` in the rendered output, so prose
        references like ``[Equation N](#eq-x)`` resolve to a real
        anchor. Without it the label would leak as visible text and
        the link target would not exist.
        """

        def repl(m: re.Match[str]) -> str:
            label = m.group("label")
            n = numbers.get(label)
            if n is None:
                return m.group(0)
            anchor = f"[]{{#{label}}}"
            if eq_state[0]:
                # \tag already in the body — only inject the anchor.
                return f"{m.group(1)} {anchor}"
            return f"\\tag{{{n}}} {m.group(1)} {anchor}"

        return _EQ_CLOSE_RE.sub(repl, line)

    out_lines: list[str] = []
    in_fence = False
    in_eq_block = False
    for line in lines:
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out_lines.append(line)
            continue
        if in_fence:
            out_lines.append(line)
            continue
        # Track display-math blocks to detect pre-existing \tag.
        if _DMATH_LINE_RE.match(line):
            if not in_eq_block:
                # Opening $$ — reset block tag state.
                in_eq_block = True
                eq_state[0] = False
            else:
                in_eq_block = False
        elif in_eq_block and "\\tag{" in line:
            eq_state[0] = True
        # Apply caption prefixes (operate on the full line; labels are
        # not inside inline-code spans in practice, and the regexes are
        # specific enough not to mis-fire on code-looking prose).
        line = _prefix_fig(line)
        line = _prefix_figline(line)
        line = _prefix_tbl(line)
        line = _tag_eq(line)
        line = _scrub_orphan_fig(line)
        # Replace prose references, protecting inline code spans.
        line = _transform_prose(line)
        out_lines.append(line)

    return "".join(out_lines)


# ---------------------------------------------------------------------------
# Auto-generated index blocks (TOC + lists of figures / tables / equations)
# and page breaks.
# ---------------------------------------------------------------------------

# Caption extractors (lenient — match any caption text, including one that
# already carries a "Figure N:" prefix). Used only to build the lists.
_FIG_EXTRACT_RE = re.compile(
    r"!\[(?P<caption>[^\]]*)\]\([^)]*\)\{#(?P<label>fig-[A-Za-z0-9_-]+)[^}]*\}"
)
_TBL_EXTRACT_RE = re.compile(
    r"^:\s+(?P<caption>.+?)\s+\{#(?P<label>tbl-[A-Za-z0-9_-]+)[^}]*\}\s*$"
)
_EQ_EXTRACT_RE = re.compile(
    r"\$\$\s+\{#(?P<label>eq-[A-Za-z0-9_-]+)[^}]*\}"
)

# Already-prefixed caption: "Figure 12: ..." / "Figura 12: ..." etc.
_CAPTION_PREFIX_RE = re.compile(
    r"^(?:[A-Za-zÁÉÍÓÚáéíóúüñ]+)\s+\d+:\s+"
)

# ATX heading line: 1-6 leading '#', text, optional {#id ...} attr block.
_HEADING_RE = re.compile(
    r"^(?P<hashes>#{1,6})\s+(?P<text>.*?)\s*$"
)
_HEADING_ID_RE = re.compile(r"\{#(?P<id>[A-Za-z0-9_-]+)[^}]*\}")
# Matches any Pandoc attribute block {…} in a heading (class, id, key=val).
_HEADING_ATTR_BLOCK_RE = re.compile(r"\{[^}]+\}")

# Standalone index markers on their own line (pre-pandoc form).
_TOC_MARKER_RE = re.compile(r"^\s*\[\[\s*toc\s*\]\]\s*$", re.IGNORECASE)
_LOF_MARKER_RE = re.compile(r"^\s*\[\[\s*lof\s*\]\]\s*$", re.IGNORECASE)
_LOT_MARKER_RE = re.compile(r"^\s*\[\[\s*lot\s*\]\]\s*$", re.IGNORECASE)
_LOE_MARKER_RE = re.compile(r"^\s*\[\[\s*loe\s*\]\]\s*$", re.IGNORECASE)
_PAGEBREAK_MARKER_RE = re.compile(
    r"^\s*\[\[\s*pagebreak\s*\]\]\s*$", re.IGNORECASE
)
# Section breaks that also switch the page-number style of what follows.
_SECTION_ROMAN_RE = re.compile(
    r"^\s*\[\[\s*section-roman\s*\]\]\s*$", re.IGNORECASE
)
_SECTION_ARABIC_RE = re.compile(
    r"^\s*\[\[\s*section-arabic\s*\]\]\s*$", re.IGNORECASE
)

# Post-pandoc marker paragraphs (``[[toc]]`` -> ``<p>[[toc]]</p>``).
_TOC_P_RE = re.compile(
    r"<p>\s*\[\[\s*toc\s*\]\]\s*</p>", re.IGNORECASE
)
_LOF_P_RE = re.compile(
    r"<p>\s*\[\[\s*lof\s*\]\]\s*</p>", re.IGNORECASE
)
_LOT_P_RE = re.compile(
    r"<p>\s*\[\[\s*lot\s*\]\]\s*</p>", re.IGNORECASE
)
_LOE_P_RE = re.compile(
    r"<p>\s*\[\[\s*loe\s*\]\]\s*</p>", re.IGNORECASE
)

PAGE_BREAK_HTML = '<div class="page-break"></div>'


def _strip_caption_prefix(caption: str) -> str:
    """Remove a leading ``Figure N:`` / ``Figura N:`` prefix if present.

    The cross-reference resolver prefixes captions at their definition
    site. When collecting list entries we strip any such prefix so the
    list shows the bare caption text (the list builder re-adds the
    localized word and number itself).
    """
    return _CAPTION_PREFIX_RE.sub("", caption.strip()).strip()


def collect_index_entries(
    source: str, lang: str = "en"
) -> dict[str, list]:
    """Collect numbered figure / table / equation entries from *source*.

    Uses the same per-kind numbering as :func:`_resolve_crossrefs` (via
    :func:`_number_labels`) so list numbers match cross-reference links.
    Definitions inside fenced code blocks are ignored. Each entry is a
    tuple:

    * ``fig`` / ``tbl``: ``(number, caption_text, label)``
    * ``eq``: ``(number, label)`` — equations have no caption.

    Args:
        source: Raw Markdown / Quarto source text.
        lang: Two-letter language tag (unused for numbering; kept for a
            symmetrical signature with the builders).

    Returns:
        Mapping with keys ``"fig"``, ``"tbl"`` and ``"eq"``, each a
        list of entry tuples in document order.
    """
    del lang  # numbering is language-independent
    numbers = _number_labels(source)
    figs: list[tuple[int, str, str]] = []
    tbls: list[tuple[int, str, str]] = []
    eqs: list[tuple[int, str]] = []
    seen: set[str] = set()
    in_fence = False
    for line in source.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for m in _FIG_EXTRACT_RE.finditer(line):
            label = m.group("label")
            if label in seen or label not in numbers:
                continue
            seen.add(label)
            caption = _strip_caption_prefix(m.group("caption"))
            figs.append((numbers[label], caption, label))
        figline_m = _FIGLINE_CAP_RE.match(line)
        if figline_m is not None:
            label = figline_m.group("label")
            if label not in seen and label in numbers:
                seen.add(label)
                caption = _strip_caption_prefix(figline_m.group(1))
                figs.append((numbers[label], caption, label))
        tbl_m = _TBL_EXTRACT_RE.match(line)
        if tbl_m is not None:
            label = tbl_m.group("label")
            if label not in seen and label in numbers:
                seen.add(label)
                caption = _strip_caption_prefix(tbl_m.group("caption"))
                tbls.append((numbers[label], caption, label))
        for m in _EQ_EXTRACT_RE.finditer(line):
            label = m.group("label")
            if label in seen or label not in numbers:
                continue
            seen.add(label)
            eqs.append((numbers[label], label))
    figs.sort(key=lambda e: e[0])
    tbls.sort(key=lambda e: e[0])
    eqs.sort(key=lambda e: e[0])
    return {"fig": figs, "tbl": tbls, "eq": eqs}


def collect_headings(source: str) -> list[tuple[int, str, str]]:
    """Collect ATX headings (and their anchor ids) from *source*.

    Headings inside fenced code blocks are ignored. When a heading
    already carries an explicit ``{#id}`` attribute that id is kept;
    otherwise a stable ``toc-h-{n}`` id is generated. The returned ids
    match what :func:`inject_heading_ids` injects, so the rendered
    anchors resolve.

    Args:
        source: Raw Markdown / Quarto source text.

    Returns:
        List of ``(level, text, anchor_id)`` tuples in document order.
    """
    headings, _ = _scan_headings(source)
    return headings


def _scan_headings(
    source: str,
) -> tuple[list[tuple[int, str, str]], list[str]]:
    """Scan headings; return entries plus the (possibly rewritten) lines.

    For headings without an explicit id, a ``toc-h-{n}`` attribute is
    appended to the line so the rendered anchor exists. The same id is
    recorded in the returned heading list.
    """
    out_lines: list[str] = []
    headings: list[tuple[int, str, str]] = []
    in_fence = False
    counter = 0
    for line in source.splitlines(keepends=True):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out_lines.append(line)
            continue
        if in_fence:
            out_lines.append(line)
            continue
        m = _HEADING_RE.match(line.rstrip("\n"))
        if m is None:
            out_lines.append(line)
            continue
        level = len(m.group("hashes"))
        body = m.group("text")
        id_m = _HEADING_ID_RE.search(body)
        if id_m is not None:
            anchor = id_m.group("id")
            # Strip ALL attr blocks so {.class} siblings don't leak into text.
            text = _HEADING_ATTR_BLOCK_RE.sub("", body).strip()
            headings.append((level, text, anchor))
            out_lines.append(line)
            continue
        counter += 1
        anchor = f"toc-h-{counter}"
        # Strip ALL attr blocks (e.g. {.unnumbered}) from displayed text.
        text = _HEADING_ATTR_BLOCK_RE.sub("", body).strip()
        newline = "\n" if line.endswith("\n") else ""
        # If there were existing attr blocks (like {.unnumbered}), merge them
        # with the new id into a single Pandoc attribute block so Pandoc
        # doesn't treat the first block as literal text.
        existing_attrs = [
            blk[1:-1].strip()
            for blk in _HEADING_ATTR_BLOCK_RE.findall(body)
        ]
        if existing_attrs:
            merged = "{" + " ".join(existing_attrs) + f" #{anchor}" + "}"
        else:
            merged = f"{{#{anchor}}}"
        injected = f"{m.group('hashes')} {text} {merged}{newline}"
        headings.append((level, text, anchor))
        out_lines.append(injected)
    return headings, out_lines


def inject_heading_ids(source: str) -> str:
    """Return *source* with stable ids injected into bare headings.

    Headings that already have an explicit ``{#id}`` are left untouched;
    bare headings receive ``{#toc-h-N}`` matching :func:`collect_headings`
    so TOC links resolve to real anchors in the rendered output.
    """
    _, lines = _scan_headings(source)
    return "".join(lines)


def _escape_html(text: str) -> str:
    """Minimal HTML escaping for caption / heading text in list links."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _index_lang_key(lang: str) -> str:
    """Normalize a language tag to a supported index key."""
    key = lang[:2].lower() if lang else "en"
    return key if key in _INDEX_TITLES else "en"


def append_annex_section(source: str, lang: str = "en") -> str:
    """Append the divider section the reader's annex PDFs are joined to.

    The section is written into the Markdown, not drawn onto the PDF
    afterwards, and that is the whole point: written here it inherits
    the theme, takes a heading id, enters the table of contents with
    its real page and is numbered like every other section. A page
    drawn on afterwards would be none of those things.

    It carries a page break, so the divider opens a sheet of its own and
    the joined PDFs follow it instead of sharing a page with the end of
    the body.

    Args:
        source: The document's Markdown source.
        lang: The document's language tag; anything unsupported reads
            as English.

    Returns:
        ``source`` with the section appended.
    """
    key = lang[:2].lower() if lang else "en"
    title = _ANNEX_TITLES.get(key, _ANNEX_TITLES["en"])
    return source.rstrip() + f"\n\n[[pagebreak]]\n\n# {title}\n"


def build_toc_html(
    headings: list[tuple[int, str, str]], lang: str = "en"
) -> str:
    """Build a ``<nav class="toc">`` block from collected headings.

    Args:
        headings: ``(level, text, anchor_id)`` tuples.
        lang: Two-letter language tag for the section title.

    Returns:
        HTML string, or an empty string when there are no headings.
    """
    if not headings:
        return ""
    key = _index_lang_key(lang)
    title = _INDEX_TITLES[key]["toc"]
    items = [
        f'<li class="toc-level-{level}">'
        f'<a href="#{anchor}">'
        f'<span class="toc-text">{_escape_html(text)}</span>'
        f'<span class="toc-dots"></span>'
        f'<span class="page-num" data-ref="{anchor}"></span>'
        f'</a></li>'
        for level, text, anchor in headings
    ]
    return (
        '<nav class="toc">\n'
        f"<h2>{title}</h2>\n"
        "<ul>\n" + "\n".join(items) + "\n</ul>\n</nav>"
    )


def _build_caption_list_html(
    entries: list,
    *,
    css_class: str,
    title: str,
    word: str,
) -> str:
    """Build a list-of-X nav block for fig / tbl entries."""
    if not entries:
        return ""
    items = [
        f'<li><a href="#{label}">'
        f'<span class="toc-text">{word} {n}: {_escape_html(caption)}</span>'
        f'<span class="toc-dots"></span>'
        f'<span class="page-num" data-ref="{label}"></span>'
        f'</a></li>'
        for n, caption, label in entries
    ]
    return (
        f'<nav class="{css_class}">\n'
        f"<h2>{title}</h2>\n"
        "<ul>\n" + "\n".join(items) + "\n</ul>\n</nav>"
    )


def build_figure_list_html(entries: list, lang: str = "en") -> str:
    """Build a ``<nav class="list-of-figures">`` block.

    Args:
        entries: ``(number, caption, label)`` tuples from
            :func:`collect_index_entries`.
        lang: Two-letter language tag.

    Returns:
        HTML string, or empty when there are no entries.
    """
    key = _index_lang_key(lang)
    word = _WORDS.get(key, _WORDS["en"])["fig"]
    return _build_caption_list_html(
        entries,
        css_class="list-of-figures",
        title=_INDEX_TITLES[key]["lof"],
        word=word,
    )


def build_table_list_html(entries: list, lang: str = "en") -> str:
    """Build a ``<nav class="list-of-tables">`` block.

    Args:
        entries: ``(number, caption, label)`` tuples from
            :func:`collect_index_entries`.
        lang: Two-letter language tag.

    Returns:
        HTML string, or empty when there are no entries.
    """
    key = _index_lang_key(lang)
    word = _WORDS.get(key, _WORDS["en"])["tbl"]
    return _build_caption_list_html(
        entries,
        css_class="list-of-tables",
        title=_INDEX_TITLES[key]["lot"],
        word=word,
    )


def build_equation_list_html(entries: list, lang: str = "en") -> str:
    """Build a ``<nav class="list-of-equations">`` block.

    Args:
        entries: ``(number, label)`` tuples from
            :func:`collect_index_entries`. Equations have no caption.
        lang: Two-letter language tag.

    Returns:
        HTML string, or empty when there are no entries.
    """
    if not entries:
        return ""
    key = _index_lang_key(lang)
    word = _WORDS.get(key, _WORDS["en"])["eq"]
    title = _INDEX_TITLES[key]["loe"]
    items = [
        f'<li><a href="#{label}">'
        f'<span class="toc-text">{word} {n}</span>'
        f'<span class="toc-dots"></span>'
        f'<span class="page-num" data-ref="{label}"></span>'
        f'</a></li>'
        for n, label in entries
    ]
    return (
        '<nav class="list-of-equations">\n'
        f"<h2>{title}</h2>\n"
        "<ul>\n" + "\n".join(items) + "\n</ul>\n</nav>"
    )


def _strip_index_markers(source: str) -> str:
    """Remove TOC / list marker lines from *source* (DOCX export).

    The Word writer does not run the HTML post-processing that expands
    these markers, so they would otherwise leak as literal text. Markers
    inside fenced code blocks are preserved.
    """
    out_lines: list[str] = []
    in_fence = False
    for line in source.splitlines(keepends=True):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out_lines.append(line)
            continue
        stripped = line.rstrip("\n")
        if not in_fence and (
            _TOC_MARKER_RE.match(stripped)
            or _LOF_MARKER_RE.match(stripped)
            or _LOT_MARKER_RE.match(stripped)
            or _LOE_MARKER_RE.match(stripped)
        ):
            continue
        out_lines.append(line)
    return "".join(out_lines)


def _expand_page_breaks(source: str) -> str:
    """Replace ``[[pagebreak]]`` marker lines with raw page-break HTML.

    Runs before Pandoc; the raw ``<div>`` passes through thanks to the
    ``+raw_html`` extension. Markers inside fenced code blocks are left
    untouched.
    """
    out_lines: list[str] = []
    in_fence = False
    section_n = 0
    for line in source.splitlines(keepends=True):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out_lines.append(line)
            continue
        stripped = line.rstrip("\n")
        if not in_fence and _PAGEBREAK_MARKER_RE.match(stripped):
            # Emit as a ```{=html} raw block so Pandoc passes the div
            # through verbatim instead of reflowing it.
            out_lines.append(
                f"\n```{{=html}}\n{PAGE_BREAK_HTML}\n```\n\n"
            )
            continue
        section_style = (
            "roman" if _SECTION_ROMAN_RE.match(stripped)
            else "arabic" if _SECTION_ARABIC_RE.match(stripped)
            else None
        )
        if not in_fence and section_style is not None:
            # A section break is a page break carrying an id that the PDF
            # export resolves to a physical page, so footer numbering can
            # restart in the chosen style from here on.
            section_n += 1
            anchor = f"epy-section-{section_style}-{section_n}"
            # Chromium only emits a PDF named destination for an id that is
            # the target of an internal link, so pair the (invisible) anchor
            # span with a self-link; the export then resolves it to a page.
            div = (
                f'<div class="page-break"></div>'
                f'<span id="{anchor}" class="epy-section-anchor"></span>'
                f'<a href="#{anchor}" aria-hidden="true"></a>'
            )
            out_lines.append(f"\n```{{=html}}\n{div}\n```\n\n")
            continue
        out_lines.append(line)
    return "".join(out_lines)


def _with_page_break(html: str) -> str:
    """Append a page-break div after a non-empty index block."""
    if html.strip():
        return html + '\n<div class="page-break"></div>'
    return html


_CONSECUTIVE_BREAKS_RE = re.compile(
    r'(?:<div class="page-break"></div>\s*){2,}'
)


def _collapse_page_breaks(html: str) -> str:
    """Merge runs of adjacent page-break markers into a single one.

    Each index block (TOC/LOF/LOT/LOE) appends its own page break and the
    document may also place an explicit ``[[pagebreak]]`` right after them.
    Two adjacent breaks make Paged.js start a page and then immediately
    break again, leaving a blank page; collapsing them avoids that.
    """
    return _CONSECUTIVE_BREAKS_RE.sub(
        '<div class="page-break"></div>', html
    )


_TABLE_RE = re.compile(r"<table\b[^>]*>.*?</table>", re.DOTALL)
_TABLE_WRAP_OPEN = '<div class="table-wrap">'


def _wrap_wide_tables(body: str) -> str:
    """Wrap every top-level ``<table>`` in a horizontally-scrolling div.

    A table with many columns (numeric results, comparison matrices) would
    otherwise overflow the page or shrink unreadably; ``.table-wrap``
    (see ``style.css``) lets it scroll inside its own box instead.

    Idempotent: a table immediately preceded by an existing
    ``.table-wrap`` opening tag is left untouched, so calling this twice
    on the same body does not nest a second wrapper.
    """

    def repl(match: re.Match[str]) -> str:
        preceding = body[max(0, match.start() - 32) : match.start()]
        if preceding.rstrip().endswith(_TABLE_WRAP_OPEN):
            return match.group(0)
        return f"{_TABLE_WRAP_OPEN}{match.group(0)}</div>"

    return _TABLE_RE.sub(repl, body)


def _expand_index_markers(body: str, source: str, lang: str) -> str:
    """Replace TOC / list marker paragraphs in *body* with HTML blocks.

    Pandoc renders a bare ``[[toc]]`` line as ``<p>[[toc]]</p>``. This
    swaps each such paragraph for the generated navigation block built
    from *source*. Markers with no matching entries become empty.

    Args:
        body: HTML produced by Pandoc.
        source: The original Markdown source (for entry collection).
        lang: Two-letter language tag.

    Returns:
        The body with index markers expanded.
    """
    headings = collect_headings(source)
    entries = collect_index_entries(source, lang=lang)
    body = _TOC_P_RE.sub(
        lambda _m: _with_page_break(build_toc_html(headings, lang)), body
    )
    body = _LOF_P_RE.sub(
        lambda _m: _with_page_break(
            build_figure_list_html(entries["fig"], lang)
        ),
        body,
    )
    body = _LOT_P_RE.sub(
        lambda _m: _with_page_break(
            build_table_list_html(entries["tbl"], lang)
        ),
        body,
    )
    body = _LOE_P_RE.sub(
        lambda _m: _with_page_break(
            build_equation_list_html(entries["eq"], lang)
        ),
        body,
    )
    return body


_SVG_IMG_RE = re.compile(
    r"(!\[[^\]]*\]\()([^)\s]+?\.svg)(\)[^\n]*)"
)


def _rasterize_svgs_for_docx(
    source: str, base_dir: Path | None
) -> tuple[str, Path | None]:
    """Convert ``![alt](*.svg)`` refs into PNG copies in a temp dir.

    Pandoc's DOCX writer needs ``rsvg-convert`` on PATH to embed SVG
    images and silently drops them otherwise. Render each referenced
    SVG into a high-resolution PNG via Qt's bundled SVG renderer
    (already a dependency through PySide6) and rewrite the source to
    point at the PNG. The caller is responsible for removing the temp
    directory after Pandoc finishes.
    """
    if base_dir is None or "!" not in source:
        return source, None
    from PySide6.QtCore import QSize  # noqa: PLC0415
    from PySide6.QtGui import QImage, QPainter  # noqa: PLC0415
    from PySide6.QtSvg import QSvgRenderer  # noqa: PLC0415

    tmp_dir = Path(tempfile.mkdtemp(prefix="epy_reports_svg_"))

    def repl(match: re.Match[str]) -> str:
        prefix, ref, suffix = match.group(1), match.group(2), match.group(3)
        svg_path = (base_dir / ref).resolve()
        if not svg_path.is_file():
            return match.group(0)
        png_path = tmp_dir / (svg_path.stem + ".png")
        try:
            renderer = QSvgRenderer(str(svg_path))
            default = renderer.defaultSize()
            scale = 3  # ~300 DPI raster for crisp print
            size = QSize(default.width() * scale, default.height() * scale)
            image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0xFFFFFFFF)
            painter = QPainter(image)
            renderer.render(painter)
            painter.end()
            image.save(str(png_path), b"PNG")
        except (OSError, RuntimeError, ValueError):
            # Unreadable or malformed SVG — leave the reference unchanged
            # so Pandoc can attempt its own fallback.
            return match.group(0)
        return f"{prefix}{png_path.as_posix()}{suffix}"

    return _SVG_IMG_RE.sub(repl, source), tmp_dir


# Pandoc's native OMML (Word) math writer cannot parse ``\tag{}`` — a
# MathJax-only macro the cross-reference resolver injects to number display
# equations. Left in, each numbered equation fails to convert and degrades to
# a raw LaTeX string in the Word document. It is stripped for DOCX only (HTML
# and PDF render through MathJax, which handles ``\tag``).
_DOCX_EQ_TAG_RE = re.compile(r"\\tag\{[^}]*\}\s*")


def export_docx(
    source: str,
    target: Path,
    base_dir: Path | None = None,
    reference_doc: Path | None = None,
    *,
    theme_css: str = "",
) -> None:
    """Convert Quarto/Pandoc Markdown ``source`` to a ``.docx`` file.

    The pipeline is:

    1. ``_expand_quarto_callouts`` — rewrite titled callout fences.
    2. ``_resolve_crossrefs`` — number and link ``@fig-x`` / ``@tbl-x``
       / ``@eq-x`` / ``@sec-x`` cross-references so they survive Pandoc
       without a Quarto installation.
    3. ``pypandoc.convert_text`` — the actual Markdown → DOCX conversion.

    Args:
        source: Markdown text. Quarto YAML front matter and fenced
            callouts are supported; a linked ``bibliography:`` enables
            citeproc just like the HTML preview.
        target: Destination ``.docx`` path (written by Pandoc).
        base_dir: Directory used to resolve relative image paths.
        reference_doc: Optional Word reference document whose styles
            (fonts, colors, heading levels) Pandoc will copy into the
            output.  When ``None`` or when the file does not exist the
            export proceeds with Pandoc's default styles.
        theme_css: Optional active-theme CSS (``--epy-*`` variables) used
            to colour the rasterized Mermaid/nomnoml diagrams so they match
            the document; empty renders them in the default palette.
    """
    metadata = parse_front_matter(source)
    lang = _effective_lang(metadata)

    # Word has no diagram engine and ignores the component CSS, so render
    # each Mermaid/nomnoml diagram to a themed PNG (best-effort) and rewrite
    # the design components into native Word structures before Pandoc runs.
    source_body = strip_front_matter(source)
    prepared = source_body
    diag_tmp: Path | None = None
    diagrams = collect_diagrams(source_body)
    if diagrams:
        diag_tmp = Path(tempfile.mkdtemp(prefix="epy_reports_docx_diag_"))
        pngs = render_diagram_pngs(diagrams, diag_tmp, theme_css=theme_css)
        prepared = substitute_diagram_images(prepared, pngs)
    prepared = simplify_components_for_export(prepared)
    # Word has no WebGL/Plotly renderer — degrade each figure to its
    # fallback image, or a short note when none was declared.
    prepared = strip_plotly_for_export(prepared)

    prepared = _expand_quarto_callouts(prepared)
    prepared = _resolve_crossrefs(prepared, lang=lang)
    # Strip the MathJax-only \tag{} so numbered equations convert to clean
    # OMML instead of falling back to a raw LaTeX string in Word.
    prepared = _DOCX_EQ_TAG_RE.sub("", prepared)
    # Drop preview-only index markers so they do not leak as literal
    # text into the Word document, then materialize page breaks.
    prepared = _strip_index_markers(prepared)
    prepared = _expand_page_breaks(prepared)
    prepared, svg_tmp = _rasterize_svgs_for_docx(prepared, base_dir)

    # tango matches the HTML preview so code chunks keep colored
    # tokens in Word; the reference-doc supplies the monospace
    # "Source Code" paragraph style.
    extra_args = ["--wrap=preserve", "--syntax-highlighting=tango"]
    # Pass front matter so pandoc sets document title/author in the DOCX.
    # yaml_metadata_block is disabled globally; metadata must be injected.
    for _key in ("title", "subtitle", "author", "date"):
        _val = metadata.get(_key)
        if _val:
            extra_args.append(f"--metadata={_key}:{_val}")
    if base_dir is not None:
        extra_args.append(f"--resource-path={base_dir}")
        if svg_tmp is not None:
            extra_args.append(f"--resource-path={svg_tmp}")
    extra_args += _bibliography_args(metadata, base_dir)
    if reference_doc is not None and reference_doc.is_file():
        extra_args.append(f"--reference-doc={reference_doc}")

    try:
        pypandoc.convert_text(
            prepared,
            to="docx",
            format=PANDOC_FORMAT,
            outputfile=str(target),
            extra_args=extra_args,
        )
        # The reference doc ships one fixed page size; honor the
        # front-matter page-size (letter / a4 / legal) in the DOCX too.
        from epy_reports._core._docx_page import (
            apply_page_size,  # noqa: PLC0415
        )

        apply_page_size(target, normalize_page_size(metadata.get("page-size")))
    finally:
        if svg_tmp is not None:
            shutil.rmtree(svg_tmp, ignore_errors=True)
        if diag_tmp is not None:
            shutil.rmtree(diag_tmp, ignore_errors=True)


def render_markdown(
    source: str,
    base_dir: Path | None = None,
    *,
    title: str = "epy_reports",
    theme_css: str = "",
    paged: bool = False,
    page_size: str = "letter",
    for_export: bool = False,
    continuous: bool = False,
    embed_images: bool = False,
) -> str:
    """Render Quarto/Pandoc Markdown ``source`` to a full HTML page.

    The pipeline is:

    1. ``_expand_quarto_callouts`` — rewrite titled callout fences.
    2. ``_resolve_crossrefs`` — number and link ``@fig-x`` / ``@tbl-x``
       / ``@eq-x`` / ``@sec-x`` cross-references so they survive Pandoc
       without a Quarto installation.
    3. ``pypandoc.convert_text`` — the actual Markdown → HTML5 conversion.

    Args:
        source: Markdown text. Quarto YAML front matter and fenced
            callouts are supported.
        base_dir: Directory used as the HTML ``<base>`` so relative
            paths to images and links resolve correctly.
        title: Fallback document title. Overridden by ``title:`` in
            YAML front matter when present.
        theme_css: Optional ``:root { … }`` block that overrides the
            base stylesheet's custom properties — supplied by the
            active visual theme.
        paged: When ``True``, render the content as a page sheet
            (sheet width + margins on a gray backdrop). Preview-only —
            it does not affect any export.
        page_size: Page-size key (``letter`` / ``a4`` / ``legal``)
            controlling the paged-preview sheet dimensions. Unknown or
            missing values fall back to Letter.
        for_export: When ``True``, paginate the document with Paged.js for
            PDF export (per-page margins, footnotes at the foot of their
            page). Leave off for the live preview.
        continuous: When ``True``, hide the print/page structure (page
            breaks and index page numbers) so the HTML reads as one
            continuous web page. Used by the HTML export.
        embed_images: When ``True``, local ``<img>`` references are
            inlined as base64 ``data:`` URIs and no ``<base>`` tag is
            emitted, so the document stays intact when moved or shared
            on its own. Export-only — the live preview keeps ``<base>``
            resolution instead of re-encoding images on every render.

    Returns:
        A standalone HTML5 document ready for the preview pane or to
        be written to disk.
    """
    metadata = parse_front_matter(source)
    if metadata.get("title"):
        title = metadata["title"]

    lang = _effective_lang(metadata)
    source_body = strip_front_matter(source)
    prepared = _expand_quarto_callouts(source_body)
    prepared = _resolve_crossrefs(prepared, lang=lang)
    prepared = inject_heading_ids(prepared)
    prepared = _expand_page_breaks(prepared)
    prepared = expand_diagrams(prepared)
    # Static (PDF) export: WebGL canvases do not print reliably, so a
    # fence with a fallback= image degrades to that image; without one it
    # stays interactive (best effort). has_plotly() is checked below,
    # after this substitution, so a fully-degraded document never pays
    # for the Plotly.js bundle.
    prepared = expand_plotly(prepared, static=for_export)
    plotly_flag = has_plotly(prepared)

    extra_args = list(PANDOC_ARGS) + _bibliography_args(
        metadata, base_dir
    )

    body = pypandoc.convert_text(
        prepared,
        to="html5",
        format=PANDOC_FORMAT,
        extra_args=extra_args,
    )
    body = _expand_index_markers(body, source, lang)
    body = _collapse_page_breaks(body)
    body = _wrap_wide_tables(body)

    return build_html_document(
        body=body,
        base_dir=base_dir,
        title=title,
        metadata=metadata,
        theme_css=theme_css,
        paged=paged,
        page_size=page_size,
        for_export=for_export,
        continuous=continuous,
        diagrams=frozenset(diagram_engines(source)),
        plotly=plotly_flag,
        embed_images=embed_images,
    )
