"""Markdown/Quarto snippets, label parsing and YAML front-matter helpers.

Each template embeds plain placeholder tokens (``LABEL``, ``CAPTION``,
``URL``, ``TEXT``...) so the editor can drop the snippet at the
caret and pre-select the most relevant token for the user to type
their replacement right away.

The module also exposes minimal helpers for the YAML front matter
(``parse_front_matter``, ``set_metadata_field``) so other components
can read or update the document's metadata without dragging a YAML
library into the bundle.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

# One parser for the family. The copy that used to live here was
# byte-for-byte the shared one, so a fix to either reached only
# whichever application somebody remembered.
from epy_export import (
    parse_front_matter as parse_front_matter,  # re-export
)
from epy_export import require_pdfs

# Captures Quarto cross-ref labels: {#fig-foo}, {#tbl-bar width=80%}, etc.
_LABEL_RE = re.compile(
    r"\{#(?P<label>(?P<kind>fig|tbl|eq|sec)-[A-Za-z0-9_-]+)[^}]*\}"
)

KIND_DESCRIPTIONS: dict[str, str] = {
    "fig": "Figure",
    "tbl": "Table",
    "eq": "Equation",
    "sec": "Section",
}


@dataclass(frozen=True)
class Label:
    """A Quarto cross-reference label extracted from a buffer."""

    kind: str  # one of fig / tbl / eq / sec
    name: str  # full label, e.g. ``fig-capacity``


def find_labels(text: str) -> list[Label]:
    """Extract every Quarto label in document order, de-duplicated."""
    seen: set[str] = set()
    out: list[Label] = []
    for match in _LABEL_RE.finditer(text):
        name = match.group("label")
        if name in seen:
            continue
        seen.add(name)
        out.append(Label(kind=match.group("kind"), name=name))
    return out


# ----------------------------------------------------------------------
# Insert-block templates. The token in caps (LABEL / TEXT / URL / ...)
# is what the editor pre-selects after insertion.
# ----------------------------------------------------------------------

FIGURE_TEMPLATE = (
    "![CAPTION](path/to/image.png){#fig-LABEL width=80%}"
)

TABLE_TEMPLATE = (
    "| Header 1 | Header 2 | Header 3 |\n"
    "| -------- | -------- | -------- |\n"
    "|          |          |          |\n"
    "|          |          |          |\n"
    "\n"
    ": CAPTION {#tbl-LABEL}"
)

EQUATION_TEMPLATE = (
    "$$\n"
    "y = f(x)\n"
    "$$ {#eq-LABEL}"
)

CODE_BLOCK_TEMPLATE = "```python\nCODE\n```"

LINK_TEMPLATE = "[TEXT](URL)"

IMAGE_MARKDOWN = "![{caption}]({path}){{#fig-{label} width={width}}}"

SECTION_HEADING_TEMPLATE = "## Section title {#sec-LABEL}"

CALLOUT_TEMPLATES: dict[str, str] = {
    "note":      "::: {.callout-note}\nBODY\n:::",
    "tip":       '::: {.callout-tip title="TITLE"}\nBODY\n:::',
    "warning":   '::: {.callout-warning title="TITLE"}\nBODY\n:::',
    "important": '::: {.callout-important title="TITLE"}\nBODY\n:::',
    "caution":   '::: {.callout-caution title="TITLE"}\nBODY\n:::',
}

# Tokens to select after inserting each template (first hit wins).
PRIMARY_PLACEHOLDER: dict[str, str] = {
    "figure":     "LABEL",
    "table":      "LABEL",
    "equation":   "LABEL",
    "code":       "CODE",
    "link":       "TEXT",
    "callout":    "TITLE",  # falls back to BODY for the .note variant
}


# ----------------------------------------------------------------------
# YAML front matter helpers (top-level scalars only).
# ----------------------------------------------------------------------


def strip_front_matter(text: str) -> str:
    """Return the document body with the YAML front-matter block removed."""
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    if end < 0:
        return text
    return text[end + 4:]
def parse_header_cells(value: object) -> list[str]:
    """Normalize a ``header`` front-matter value into a list of cells.

    ``parse_front_matter`` returns scalars as strings, so a YAML flow
    sequence like ``["A", "B"]`` arrives here as that literal string. This
    accepts either a real list or that JSON-ish string and returns the cell
    strings; anything else becomes a single-cell list.
    """
    if isinstance(value, list):
        return [str(x) for x in value]
    text = str(value or "").strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            items = json.loads(text)
        except (ValueError, TypeError):
            items = None
        if isinstance(items, list):
            return [str(x) for x in items]
    return [text]


def parse_path_list(value: object) -> list[str]:
    """Normalize a front-matter value into a list of declared paths.

    Accepts a real list, a YAML flow sequence with or without quotes
    (``[one.pdf, "two.pdf"]``) and a plain comma-separated list. A
    single path with no comma is a one-item list.

    Splitting on commas means a path that contains one is split into
    pieces. Nothing is guessed about that: the pieces do not exist on
    disk, and the caller names them.
    """
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    if text.startswith("[") and text.endswith("]"):
        try:
            items = json.loads(text)
        except (ValueError, TypeError):
            items = None
        if isinstance(items, list):
            return [str(x).strip() for x in items if str(x).strip()]
        # A bare flow sequence -- [one.pdf, two.pdf] -- is not JSON,
        # and it is what somebody writing YAML by hand types.
        text = text[1:-1]
    return [
        part.strip().strip("\"'")
        for part in text.split(",")
        if part.strip().strip("\"'")
    ]


def resolve_pdf_attachments(
    meta: dict[str, str], base_dir: Path | None
) -> tuple[Path | None, list[Path]]:
    """Resolve the reader's own PDF pages declared in the front matter.

    Two keys, resolved relative to the document exactly as ``watermark``
    is: ``cover-pdf`` names one PDF template that becomes the opening
    page, and ``annexes`` names the PDFs appended at the back.

    Where each one is joined is what decides the numbering, and that is
    the export path's business, not this function's. This one only says
    which files were asked for -- and refuses now, before a minute of
    rendering, if any of them is not there.

    Args:
        meta: Parsed front matter.
        base_dir: The document's directory; relative paths resolve
            against it.

    Returns:
        The cover, or ``None``, and the annexes in the declared order.

    Raises:
        ValueError: When ``annexes`` is present and declares nothing,
            which is what a YAML block sequence looks like to a reader
            that only sees a key's own line. Reading that as "no
            annexes" would export a document missing pages its author
            asked for, and it would be discovered by whoever received
            it. An empty list is written ``[]``, which is what the
            document properties dialog writes when the field is
            cleared, and it is not this mistake.

            ``cover-pdf`` is not held to the same rule: it takes one
            path, so an empty value is not a dropped block sequence --
            it is how "no cover" is spelled.
        FileNotFoundError: Naming every declared file that is missing.
    """

    def _resolved(value: str) -> Path:
        candidate = Path(value)
        if not candidate.is_absolute() and base_dir is not None:
            candidate = base_dir / candidate
        return candidate

    if "annexes" in meta and not str(meta.get("annexes") or "").strip():
        raise ValueError(
            "Front matter 'annexes:' declares nothing. Only a key's own "
            "line is read, so a YAML block sequence (one '- path' per "
            "line) never arrives. Write it on the key's line: annexes: "
            "[one.pdf, two.pdf] -- or annexes: [] for none."
        )

    cover_value = str(meta.get("cover-pdf") or "").strip()
    cover = _resolved(cover_value) if cover_value else None
    annexes = [
        _resolved(item) for item in parse_path_list(meta.get("annexes"))
    ]
    require_pdfs([*annexes, *([cover] if cover is not None else [])])
    return cover, annexes


def _format_yaml_value(value: str) -> str:
    """Quote ``value`` if it would be ambiguous as a YAML scalar."""
    needs_quotes = (
        value == ""
        or value[0] in "!&*?|>%@`"
        or value.strip() != value
        or any(ch in value for ch in ":#")
    )
    if needs_quotes:
        escaped = value.replace('"', '\\"')
        return f'"{escaped}"'
    return value


def set_metadata_field(
    text: str, field: str, value: str, *, raw: bool = False
) -> str:
    """Insert or replace a top-level YAML ``field`` in ``text``.

    Creates a front-matter block at the top of the buffer when none
    exists. When the field is already present, its value is replaced
    in place; otherwise the field is appended to the existing block.

    Args:
        text: The full document text.
        field: The YAML key to set.
        value: The value to write.
        raw: When ``True`` the value is written verbatim (no scalar
            quoting). Use it for values that are already valid YAML, such
            as a flow sequence ``["a", "b"]`` for the ``header`` field.
    """
    formatted = value if raw else _format_yaml_value(value)
    line = f"{field}: {formatted}"

    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end >= 0:
            head = text[:3]  # opening '---'
            block = text[3:end]
            tail = text[end:]
            pattern = re.compile(
                rf"^{re.escape(field)}\s*:.*$", re.MULTILINE
            )
            if pattern.search(block):
                block = pattern.sub(line, block, count=1)
            else:
                if not block.endswith("\n"):
                    block += "\n"
                block += line + "\n"
            return head + block + tail

    # No usable front matter — prepend a fresh block.
    return f"---\n{line}\n---\n\n{text}"
