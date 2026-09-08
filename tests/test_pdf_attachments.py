"""The reader's own PDF pages: a cover template and annexes.

Two front-matter keys, and the ORDER of the export pipeline is what
gives each one its behaviour. The annexes are joined before the
stamping, so the footer numbers them in continuity with the body; the
cover is joined after it, so it carries no number and the pages the
index declares do not move. Nothing here changes how numbering works --
that is the point of doing it this way.

The mechanism itself is measured in epy_export (a cover joined after
the footer comes back with an empty page, an annex joined before it
comes back as "Page 3 of 3"). What is measured HERE is that this
application's two export paths -- the scriptable API and the editor
window -- actually join at those two points.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from epy_reports._core.renderer import append_annex_section, collect_headings
from epy_reports._core.snippets import (
    parse_front_matter,
    parse_path_list,
    resolve_pdf_attachments,
)

SRC = Path(__file__).resolve().parents[1] / "src"


def _pdf(path: Path, pages: int = 1) -> Path:
    """Write a small real PDF, since the resolver checks the disk."""
    from pypdf import PdfWriter

    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612.0, height=792.0)
    with path.open("wb") as handle:
        writer.write(handle)
    return path


# ----------------------------------------------------------------------
# Reading the declaration.
# ----------------------------------------------------------------------


def test_the_forms_that_fit_on_the_key_s_own_line_are_read() -> None:
    # The front-matter reader sees top-level scalars, so these are the
    # forms that can arrive at all.
    assert parse_path_list('["one.pdf", "two.pdf"]') == ["one.pdf", "two.pdf"]
    assert parse_path_list("[one.pdf, two.pdf]") == ["one.pdf", "two.pdf"]
    assert parse_path_list("one.pdf, two.pdf") == ["one.pdf", "two.pdf"]
    assert parse_path_list("one.pdf") == ["one.pdf"]
    assert parse_path_list(["one.pdf", "two.pdf"]) == ["one.pdf", "two.pdf"]
    assert parse_path_list("") == []
    assert parse_path_list(None) == []


def test_a_block_sequence_is_refused_instead_of_read_as_nothing(
    tmp_path: Path,
) -> None:
    """The trap this key sets, and the only way out of it.

    A block sequence is how anyone who knows YAML writes a list, and it
    is exactly what the reader cannot see: the key's own line is empty
    and the indented lines are skipped. Reading that as "no annexes"
    would export a document missing pages the author asked for, and
    nobody would find out until it was received.
    """
    meta = parse_front_matter(
        "---\ntitle: T\nannexes:\n  - uno.pdf\n  - dos.pdf\n---\n\nBody.\n"
    )
    assert meta["annexes"] == "", "the reader saw the block sequence"
    with pytest.raises(ValueError) as raised:
        resolve_pdf_attachments(meta, tmp_path)
    message = str(raised.value)
    assert "annexes" in message
    # Actionable: it says which form to write instead.
    assert "[one.pdf, two.pdf]" in message


def test_nothing_declared_means_nothing_joined(tmp_path: Path) -> None:
    cover, annexes = resolve_pdf_attachments({"title": "T"}, tmp_path)
    assert cover is None
    assert annexes == []


def test_a_cleared_field_is_not_read_as_the_block_sequence_mistake(
    tmp_path: Path,
) -> None:
    """What the properties dialog writes when the reader empties a field.

    The refusal above exists because an empty ``annexes:`` is almost
    always a block sequence the reader cannot see being dropped. It
    must not fire on the one case where empty genuinely means empty, or
    clearing a field in the dialog would make every later export refuse.
    """
    cover, annexes = resolve_pdf_attachments(
        {"cover-pdf": "", "annexes": "[]"}, tmp_path
    )
    assert cover is None
    assert annexes == []


def test_paths_resolve_against_the_document(tmp_path: Path) -> None:
    _pdf(tmp_path / "plantilla" / "portada.pdf")
    _pdf(tmp_path / "anexos" / "ensayos.pdf")
    absolute = _pdf(tmp_path / "elsewhere" / "planos.pdf")
    cover, annexes = resolve_pdf_attachments(
        {
            "cover-pdf": "plantilla/portada.pdf",
            "annexes": f"anexos/ensayos.pdf, {absolute}",
        },
        tmp_path,
    )
    assert cover == tmp_path / "plantilla" / "portada.pdf"
    assert annexes[0] == tmp_path / "anexos" / "ensayos.pdf"
    assert annexes[1] == absolute


def test_the_declared_order_is_the_order_they_are_joined(
    tmp_path: Path,
) -> None:
    for name in ("c.pdf", "a.pdf", "b.pdf"):
        _pdf(tmp_path / name)
    _, annexes = resolve_pdf_attachments(
        {"annexes": "c.pdf, a.pdf, b.pdf"}, tmp_path
    )
    assert [p.name for p in annexes] == ["c.pdf", "a.pdf", "b.pdf"]


def test_every_missing_file_is_named_before_anything_is_rendered(
    tmp_path: Path,
) -> None:
    """Named, and named early.

    An export that discovers a mistyped path at the joining step has
    already spent two Paged.js passes on a document it is about to
    throw away, and it reaches the reader as a bare failure.
    """
    _pdf(tmp_path / "here.pdf")
    with pytest.raises(FileNotFoundError) as raised:
        resolve_pdf_attachments(
            {"cover-pdf": "falta.pdf", "annexes": "here.pdf, tampoco.pdf"},
            tmp_path,
        )
    message = str(raised.value)
    assert "falta.pdf" in message
    assert "tampoco.pdf" in message
    assert "here.pdf" not in message


# ----------------------------------------------------------------------
# The generated section.
# ----------------------------------------------------------------------


def test_the_section_follows_the_document_s_language() -> None:
    # Not the interface language: a document that declares lang: es says
    # "Anexos" whatever menu language the export was run from.
    assert "# Anexos" in append_annex_section("Body.", "es")
    assert "# Annexes" in append_annex_section("Body.", "en")
    assert "# Annexes" in append_annex_section("Body.", "de")


def test_the_section_opens_a_page_of_its_own() -> None:
    out = append_annex_section("Body.", "es")
    assert "[[pagebreak]]" in out
    assert out.index("[[pagebreak]]") < out.index("# Anexos")


def test_the_section_is_a_real_heading_that_enters_the_index() -> None:
    """Written into the Markdown, not drawn onto the PDF afterwards.

    That is the whole reason it is generated here: a page drawn on the
    finished PDF would have no heading id, no entry in the table of
    contents and no section number. This one is picked up by the same
    scan every other heading goes through.
    """
    source = "# Introduccion\n\nBody.\n"
    headings = collect_headings(append_annex_section(source, "es"))
    assert [text for _level, text, _anchor in headings] == [
        "Introduccion",
        "Anexos",
    ]
    level, _text, anchor = headings[-1]
    assert level == 1
    assert anchor, "the generated section has no anchor to link to"


def test_the_body_is_kept_intact() -> None:
    source = "---\ntitle: T\n---\n\nBody paragraph.\n"
    out = append_annex_section(source, "en")
    assert out.startswith(source.rstrip())


# ----------------------------------------------------------------------
# Both export paths join at the two points the design requires.
# ----------------------------------------------------------------------

PATHS = {
    "scriptable API": (
        SRC / "epy_reports" / "_core" / "_export_pdf" / "__init__.py",
        "render_report_pdf",
    ),
    "editor window": (
        SRC / "epy_reports" / "_ui" / "tab.py",
        "export_pdf",
    ),
}


WATCHED = {
    "append_pdf", "prepend_pdf", "add_page_background", "add_watermark",
    "add_header", "add_footer", "add_metadata", "append_annex_section",
    "resolve_pdf_attachments",
}


def _function(path: Path, function: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    return next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == function
    )


def _name_of(node: ast.Call) -> str:
    """The called name, whether it is reached through a module or not."""
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    if isinstance(node.func, ast.Name):
        return node.func.id
    return ""


def _call_order(path: Path, function: str) -> list[str]:
    """Return the stamping/joining calls inside ``function``, in order."""
    calls = [
        (node.lineno, _name_of(node))
        for node in ast.walk(_function(path, function))
        if isinstance(node, ast.Call) and _name_of(node) in WATCHED
    ]
    return [name for _line, name in sorted(calls)]


@pytest.mark.parametrize("route", sorted(PATHS))
def test_the_annexes_are_joined_before_the_stamping(route: str) -> None:
    # Before it, so the footer counts them: that is the only thing that
    # numbers them, and there is no second numbering path to check.
    order = _call_order(*PATHS[route])
    assert "append_pdf" in order, f"{route} never joins the annexes"
    assert order.index("append_pdf") < order.index("add_footer")


@pytest.mark.parametrize("route", sorted(PATHS))
def test_the_cover_is_joined_after_the_stamping(route: str) -> None:
    # After everything, metadata included: a cover joined one step
    # earlier would be stamped, and one joined before the footer would
    # push every page of the body one number along.
    order = _call_order(*PATHS[route])
    assert "prepend_pdf" in order, f"{route} never joins the cover"
    assert order.index("prepend_pdf") > order.index("add_metadata")
    assert order[-1] == "prepend_pdf"


@pytest.mark.parametrize("route", sorted(PATHS))
def test_the_section_is_generated_only_when_there_are_annexes(
    route: str,
) -> None:
    """Generated on the condition, not unconditionally.

    An empty "Annexes" heading at the end of every report, with nothing
    under it, is a defect the reader would have to delete by hand from
    every document they write.
    """
    target = _function(*PATHS[route])
    guarded = [
        node for node in ast.walk(target)
        if isinstance(node, ast.If)
        and any(
            _name_of(call) == "append_annex_section"
            for stmt in node.body
            for call in ast.walk(stmt)
            if isinstance(call, ast.Call)
        )
    ]
    assert guarded, f"{route} never generates the section"
    assert len(guarded) == 1
    assert isinstance(guarded[0].test, ast.Name)
    assert guarded[0].test.id == "annex_pdfs"


@pytest.mark.parametrize("route", sorted(PATHS))
def test_the_section_is_written_before_the_document_is_rendered(
    route: str,
) -> None:
    # It has to be part of the source Pandoc sees, or it has no heading
    # id, no entry in the table of contents and no section number.
    order = _call_order(*PATHS[route])
    assert "append_annex_section" in order, f"{route} skips the section"
    assert order.index("append_annex_section") < order.index("append_pdf")


@pytest.mark.parametrize("route", sorted(PATHS))
def test_the_declaration_is_read_before_anything_is_rendered(
    route: str,
) -> None:
    # First of all of it: a mistyped path costs a message, not two
    # Paged.js passes and then a failure with no reason in it.
    order = _call_order(*PATHS[route])
    assert order[0] == "resolve_pdf_attachments", f"{route}: {order}"


@pytest.mark.parametrize("route", sorted(PATHS))
def test_the_annexes_are_stamped_like_the_rest_of_the_document(
    route: str,
) -> None:
    # Not only numbered: the theme background, the watermark and the
    # header reach them too, because they are joined before all of it.
    order = _call_order(*PATHS[route])
    first = order.index("append_pdf")
    for name in ("add_page_background", "add_watermark", "add_header"):
        assert name in order, f"{route} does not call {name}"
        assert first < order.index(name), f"{route} joins after {name}"
