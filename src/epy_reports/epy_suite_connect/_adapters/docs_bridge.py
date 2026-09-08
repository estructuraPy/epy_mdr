"""Bridge module between epy_reports and the optional epy_docs package.

Independence contract
---------------------
This is the **only** module in epy_reports that may reference
``epy_docs``, and it no longer reaches it directly: ``epy_export`` owns
the engine catalog, the availability route and the render, and this
module is the thin layer that speaks epy_reports' vocabulary to it.

That indirection is not ceremony. Deciding whether the engine is here
by importing it HERE has a permanently wrong answer inside a frozen
bundle -- PyInstaller closes ``sys.path`` to the bundle, so a package
installed in the user's own Python is invisible however the spec is
written -- and this menu entry was greyed out in every shipped
executable from the first release until that moved. ``epy_export``
answers about the MACHINE and renders in the interpreter ePy Studio
found when it has to.

Usage example::

    from epy_reports.epy_suite_connect._adapters.docs_bridge import (
        epy_docs_available,
        render_document,
    )

    if epy_docs_available():
        produced = render_document(
            source_path=Path("report.qmd"),
            layout="corporate",
            document_type="report",
            output_dir=Path("results"),
            pdf=True,
            html=True,
        )
"""

from __future__ import annotations

from pathlib import Path

from epy_export import (
    APPEARANCES,
    DOCUMENT_TYPES,
    EngineUnavailableError,
    RenderOptions,
    available,
    render,
)

ENGINE_ID = "docs"
"""The engine this bridge speaks for, as the shared catalog names it."""

# One condition, one name. "epy_docs is not installed" was raised here
# as its own class and by epy_export as another, and a caller cannot
# know which of two unrelated types to catch: it catches one and the
# other escapes into a dialog as an unhandled exception. The name is
# kept because it is the word this package's callers already use.
BridgeUnavailableError = EngineUnavailableError


def epy_docs_available() -> bool:
    """Return whether this machine can render through epy_docs.

    Asks the shared route, which answers about the MACHINE rather than
    about this process's import path: inside the frozen bundle the
    engine can never be imported, and ePy Studio publishes the
    interpreter that carries it.

    Returns:
        Whether the engine can be reached at all. Nothing is imported
        and no subprocess is started, so this stays cheap enough to
        build a menu with.
    """
    return available(ENGINE_ID)


def list_layouts() -> list[str]:
    """Return the layout names this family publishes.

    Read from the shared vocabulary rather than from the engine. A
    dialog that asked the ENGINE could not be built at all inside the
    bundle, where the engine cannot be imported -- which is the second
    reason this export entry was unreachable.

    Returns:
        The nine layout names, in the order the family publishes them.
    """
    return list(APPEARANCES)


def list_document_types() -> list[str]:
    """Return the document kinds the generic writer can build.

    Returns:
        The kinds, in the order the family publishes them.
    """
    return list(DOCUMENT_TYPES)


def render_document(
    source_path: Path,
    layout: str,
    document_type: str,
    output_dir: Path,
    pdf: bool,
    html: bool,
    docx: bool = False,
) -> list[Path]:
    """Render ``source_path`` through epy_docs and return what it made.

    Args:
        source_path: Absolute path to the ``.md`` or ``.qmd`` source.
        layout: Layout name as returned by :func:`list_layouts`.
        document_type: Document kind as returned by
            :func:`list_document_types`.
        output_dir: Directory for the rendered output; created when
            absent.
        pdf: When ``True``, request PDF output.
        html: When ``True``, request HTML output.
        docx: When ``True``, request Word (.docx) output.

    Returns:
        One path per format produced. The paths are checked to exist
        before this returns: the engine reports success and writes
        nothing when Quarto is missing, so its own answer is not
        evidence.

    Raises:
        BridgeUnavailableError: When the engine cannot be reached.
        RenderFailedError: When it ran and produced nothing sound.
        ValueError: When no format was asked for, or the layout or the
            document kind is not one the family publishes.

    Note:
        ``source_kind`` is fixed to ``"quarto"`` because that is the
        entry point this bridge has always used. It is declared rather
        than guessed from the suffix: the two entry points are different
        methods on the writer, and a Quarto source fed to the Markdown
        reader leaks its directives into the body as literal text.
    """
    if not epy_docs_available():
        # Said here rather than left to the dispatcher. Its message is
        # right for a caller ("install it, or choose another engine")
        # and wrong for a reader: this engine is not something you
        # install, it is something you buy, and the distinction between
        # "not bought" and "broken install" is the difference between
        # two completely different actions.
        raise BridgeUnavailableError(
            "ePy Docs is not available on this machine. It is a "
            "commercial add-on by ANM Ingenieria: "
            "ahnavarro@anmingenieria.com"
        )
    formats = [
        name
        for name, wanted in (("pdf", pdf), ("html", html), ("docx", docx))
        if wanted
    ]
    return render(
        source_path,
        output_dir,
        engine_id=ENGINE_ID,
        formats=formats,
        options=RenderOptions(
            appearance=layout,
            document_type=document_type,
            source_kind="quarto",
        ),
    )
