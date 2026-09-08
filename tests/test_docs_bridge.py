"""The bridge to ePy Docs, which no longer reaches it directly.

``epy_export`` owns the engine catalog, the availability route and the
render; this module speaks epy_reports' vocabulary to it. The tests
therefore state what the bridge PROMISES rather than which library call
it happens to make, because the previous set asserted the internals --
that it patched ``importlib.util.find_spec`` inside this module, and
that listing the layouts raised when the engine was absent -- and both
of those are exactly what had to change.

Pure Python: no Qt required.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from epy_export import APPEARANCES, DOCUMENT_TYPES, RenderOptions
from epy_export._core import _backends

from epy_reports.epy_suite_connect._adapters import docs_bridge


class _Blocker:
    """Makes ``epy_docs`` genuinely unimportable, as a bundle does.

    Monkeypatching epy_export's helper is not enough to measure this:
    the engine IS installed on the machine these tests run on, so a
    bridge that went back to asking its own import path would answer
    correctly here and wrongly in every shipped executable. Both
    plantings of exactly that passed until this existed.
    """

    def find_spec(self, name, path=None, target=None):  # noqa: ANN001, ANN201
        if name == "epy_docs" or name.startswith("epy_docs."):
            raise ImportError("epy_docs is not importable in this process")
        return None


@pytest.fixture()
def engine_hidden():
    """Hide the engine from every import in this process."""
    saved = sys.modules.pop("epy_docs", None)
    blocker = _Blocker()
    sys.meta_path.insert(0, blocker)
    try:
        yield
    finally:
        sys.meta_path.remove(blocker)
        if saved is not None:
            sys.modules["epy_docs"] = saved


# --- is the engine reachable? --------------------------------------------


def test_it_is_reachable_when_the_engine_imports_here(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_backends, "backend_present", lambda module: True)
    assert docs_bridge.epy_docs_available() is True


def test_it_is_reachable_through_the_interpreter_studio_found(
    monkeypatch: pytest.MonkeyPatch, engine_hidden: None
) -> None:
    # THE case this whole change exists for, and the reason the engine
    # is genuinely hidden rather than merely reported absent: inside the
    # frozen bundle it can never be imported, so asking the import
    # greyed the menu entry out for every user since the first release.
    # ePy Studio names an interpreter that has it.
    monkeypatch.setenv(_backends.ENV_DOCS_PYTHON, sys.executable)
    assert docs_bridge.epy_docs_available() is True


def test_it_is_not_reachable_when_there_is_nothing_to_reach(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_backends, "backend_present", lambda module: False)
    monkeypatch.delenv(_backends.ENV_DOCS_PYTHON, raising=False)
    assert docs_bridge.epy_docs_available() is False


def test_asking_costs_no_import_and_no_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # It answers "should I offer this?" while a menu is being built.
    # Importing the engine to draw a menu item pulls in the whole
    # scientific stack; starting a subprocess is worse.
    import subprocess

    def _refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("asking availability started a subprocess")

    monkeypatch.setattr(subprocess, "run", _refuse)
    monkeypatch.setattr(_backends, "backend_present", lambda module: False)
    monkeypatch.delenv(_backends.ENV_DOCS_PYTHON, raising=False)
    assert docs_bridge.epy_docs_available() is False


# --- the vocabularies a dialog is drawn from -----------------------------


def test_the_layouts_are_listed_even_with_no_engine_at_all(
    monkeypatch: pytest.MonkeyPatch, engine_hidden: None
) -> None:
    # This is the change. The dialog called this IN ITS CONSTRUCTOR, so
    # while the list came from the engine the window could not be built
    # inside the bundle at all -- the export entry was unreachable for a
    # second, independent reason. Hidden for real, because the two lists
    # carry the SAME nine names: nothing in the values can tell where
    # they came from.
    monkeypatch.delenv(_backends.ENV_DOCS_PYTHON, raising=False)
    assert docs_bridge.list_layouts() == list(APPEARANCES)
    assert docs_bridge.list_document_types() == list(DOCUMENT_TYPES)


def test_the_vocabularies_are_the_ones_the_family_publishes() -> None:
    assert "corporate" in docs_bridge.list_layouts()
    assert len(docs_bridge.list_layouts()) == 9
    assert "report" in docs_bridge.list_document_types()


# --- the render ----------------------------------------------------------


class _Recorder:
    """Stands in for epy_export.render and keeps what it was asked."""

    def __init__(self) -> None:
        self.seen: dict[str, object] = {}
        self.options: RenderOptions | None = None

    def __call__(
        self,
        source: Path,
        output_dir: Path,
        *,
        engine_id: str,
        formats: list[str],
        options: RenderOptions | None = None,
    ) -> list[Path]:
        self.options = options
        self.seen = {
            "source": source,
            "output_dir": output_dir,
            "engine_id": engine_id,
            "formats": list(formats),
            "options": options,
        }
        return [output_dir / f"{source.stem}.{name}" for name in formats]


def _rendered(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **kwargs: object
) -> _Recorder:
    recorder = _Recorder()
    monkeypatch.setattr(docs_bridge, "render", recorder)
    # And the guard in front of it. On a machine WITHOUT ePy Docs --
    # every public runner -- the refusal fires before the recorder is
    # ever reached. This machine has the engine, so leaving it out
    # passed here and failed there.
    monkeypatch.setattr(docs_bridge, "available", lambda engine_id: True)
    source = tmp_path / "informe.qmd"
    source.write_text("# T\n", encoding="utf-8")
    docs_bridge.render_document(
        source_path=source,
        layout="academic",
        document_type="paper",
        output_dir=tmp_path / "out",
        **kwargs,  # type: ignore[arg-type]
    )
    return recorder


def test_the_render_goes_to_the_right_engine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen = _rendered(monkeypatch, tmp_path, pdf=True, html=False).seen
    assert seen["engine_id"] == "docs"


def test_only_the_formats_asked_for_are_requested(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Named rather than implied: a format the engine cannot make is
    # refused BY NAME upstream, and silently producing two of three
    # requested files is how a caller comes to believe it has a file it
    # never got.
    assert _rendered(
        monkeypatch, tmp_path, pdf=True, html=False
    ).seen["formats"] == ["pdf"]
    assert _rendered(
        monkeypatch, tmp_path, pdf=False, html=True
    ).seen["formats"] == ["html"]
    assert _rendered(
        monkeypatch, tmp_path, pdf=True, html=True, docx=True
    ).seen["formats"] == ["pdf", "html", "docx"]


def test_the_layout_and_the_document_kind_both_travel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Both are chosen in the dialog. The kind used to stop at the
    # dispatcher, so a reader who asked for a paper received a report.
    options = _rendered(monkeypatch, tmp_path, pdf=True, html=False).options
    assert options is not None
    assert options.appearance == "academic"
    assert options.document_type == "paper"


def test_the_source_is_declared_as_quarto_not_guessed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The entry point this bridge has always used. The two entry points
    # are different methods on the writer, and a Quarto source fed to
    # the Markdown reader leaks its directives into the body as literal
    # text -- so it is declared, never inferred from the suffix.
    options = _rendered(monkeypatch, tmp_path, pdf=True, html=False).options
    assert options is not None
    assert options.source_kind == "quarto"


def test_a_source_named_md_is_still_read_as_quarto(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The control for the test above: guessing from the suffix would
    # change the reader for exactly this file and nothing would say so.
    recorder = _Recorder()
    monkeypatch.setattr(docs_bridge, "render", recorder)
    monkeypatch.setattr(docs_bridge, "available", lambda engine_id: True)
    source = tmp_path / "informe.md"
    source.write_text("# T\n", encoding="utf-8")
    docs_bridge.render_document(
        source_path=source,
        layout="corporate",
        document_type="report",
        output_dir=tmp_path / "out",
        pdf=True,
        html=False,
    )
    assert recorder.options is not None
    assert recorder.options.source_kind == "quarto"


def _refuse(tmp_path: Path) -> None:
    """Ask for a render that cannot happen, so the message can be read."""
    source = tmp_path / "informe.qmd"
    source.write_text("# T\n", encoding="utf-8")
    docs_bridge.render_document(
        source_path=source,
        layout="corporate",
        document_type="report",
        output_dir=tmp_path / "out",
        pdf=True,
        html=False,
    )


def test_an_unreachable_engine_is_refused_by_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, engine_hidden: None
) -> None:
    monkeypatch.delenv(_backends.ENV_DOCS_PYTHON, raising=False)
    with pytest.raises(docs_bridge.BridgeUnavailableError, match="ePy Docs"):
        _refuse(tmp_path)


def test_an_absent_engine_still_says_it_is_an_add_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, engine_hidden: None
) -> None:
    # The distinction that matters to a READER, and the reason the
    # message is not left to the dispatcher: this engine is not
    # something you install, it is something you buy. "Install it, or
    # choose another engine" is right for a caller and useless here.
    monkeypatch.delenv(_backends.ENV_DOCS_PYTHON, raising=False)
    with pytest.raises(docs_bridge.BridgeUnavailableError) as raised:
        _refuse(tmp_path)
    message = str(raised.value)
    assert "commercial add-on" in message
    assert "anmingenieria.com" in message


def test_a_present_but_broken_engine_is_not_reported_as_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # One is fixed by buying something and the other by repairing an
    # install; collapsing them loses that. The engine answers present --
    # deciding whether to OFFER must stay cheap and import nothing --
    # and the real cause surfaces at the moment of use.
    monkeypatch.setattr(_backends, "backend_present", lambda module: True)

    def _explode(module: str, *, why: str) -> object:
        raise docs_bridge.BridgeUnavailableError(
            f"{module} is installed but could not be imported (boom). "
            f"That is a broken installation of it, not a missing one."
        )

    from epy_export.epy_suite_connect._adapters import _docs

    monkeypatch.setattr(_docs, "load_backend", _explode)
    monkeypatch.delenv(_backends.ENV_DOCS_PYTHON, raising=False)
    with pytest.raises(docs_bridge.BridgeUnavailableError) as raised:
        _refuse(tmp_path)
    assert "broken installation" in str(raised.value)


def test_one_condition_carries_one_name() -> None:
    # "epy_docs is not installed" was raised here as its own class and
    # by epy_export as another. A caller cannot know which of two
    # unrelated types to catch: it catches one and the other escapes
    # into a dialog as an unhandled exception.
    from epy_export import BackendUnavailableError, EngineUnavailableError

    assert docs_bridge.BridgeUnavailableError is EngineUnavailableError
    assert docs_bridge.BridgeUnavailableError is BackendUnavailableError


def test_the_bridge_never_names_the_engine_itself() -> None:
    # Its charter: the only module that may reference epy_docs. It now
    # keeps that promise by not referencing it at all -- the engine is
    # named once, in the shared catalog.
    import inspect

    source = inspect.getsource(docs_bridge)
    assert "import epy_docs" not in source
    assert "DocumentWriter" not in source
