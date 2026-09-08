"""Tests for the DocsExportDialog widget and its render worker."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication

from epy_reports._ui import docs_export_dialog as ded
from epy_reports._ui.docs_export_dialog import DocsExportDialog, _RenderWorker

_app: QApplication | None = None


@pytest.fixture(scope="module")
def qapp():
    """Provide a module-scoped QApplication instance."""
    global _app
    if _app is None:
        _instance = QApplication.instance()
        _app = (
            _instance
            if isinstance(_instance, QApplication)
            else QApplication([])
        )
    return _app


@pytest.fixture
def stub_bridge():
    """Kept as a no-op so the tests below read as they always did.

    The dialog used to ask the BRIDGE for its layouts and document
    kinds, and this fixture answered for it. It asks the family's
    shared vocabulary now, which is what lets the window be built at
    all inside a frozen bundle -- so there is nothing left to stub, and
    a fixture that pretended otherwise would be measuring itself.
    """
    return None


# ---------------------------------------------------------------------------
# Dialog construction + properties
# ---------------------------------------------------------------------------


def test_dialog_populates_combos(qapp, stub_bridge):
    """Both combos list the vocabulary the family publishes."""
    from epy_export import APPEARANCES, DOCUMENT_TYPES

    dlg = DocsExportDialog(Path("doc.md"))
    layouts = [
        dlg._combo_layout.itemText(i)
        for i in range(dlg._combo_layout.count())
    ]
    kinds = [
        dlg._combo_doctype.itemText(i)
        for i in range(dlg._combo_doctype.count())
    ]
    assert layouts == list(APPEARANCES)
    assert kinds == list(DOCUMENT_TYPES)


def test_default_output_dir_is_source_results(qapp, stub_bridge, tmp_path):
    """The default output directory hangs off the source's results/."""
    src = tmp_path / "doc.md"
    with patch.object(ded.QSettings, "value", side_effect=lambda k, d: d):
        dlg = DocsExportDialog(src)
    assert dlg.output_dir == tmp_path / "results"


def test_format_checkbox_defaults(qapp, stub_bridge):
    """PDF and HTML default on, DOCX off."""
    dlg = DocsExportDialog(Path("doc.md"))
    assert dlg.export_pdf is True
    assert dlg.export_html is True
    assert dlg.export_docx is False


def test_properties_reflect_widget_state(qapp, stub_bridge):
    """The public properties echo the widget values."""
    dlg = DocsExportDialog(Path("doc.md"))
    dlg._combo_layout.setCurrentText("academic")
    dlg._combo_doctype.setCurrentText("paper")
    dlg._edit_outdir.setText(str(Path("out").resolve()))
    assert dlg.layout_name == "academic"
    assert dlg.document_type == "paper"
    assert dlg.output_dir == Path("out").resolve()


# ---------------------------------------------------------------------------
# Worker thread (run() called directly, no event loop)
# ---------------------------------------------------------------------------


def test_worker_emits_ok_on_success(qapp, monkeypatch):
    """A successful render emits finished_ok with the output dir."""
    import epy_reports.epy_suite_connect._adapters.docs_bridge as bridge

    monkeypatch.setattr(
        bridge, "render_document", lambda **kw: None
    )
    worker = _RenderWorker(
        Path("src.md"), "corporate", "report", Path("out"),
        pdf=True, html=False,
    )
    received: list[str] = []
    worker.finished_ok.connect(received.append)
    worker.run()
    assert received == [str(Path("out"))]


def test_worker_emits_err_on_failure(qapp, monkeypatch):
    """A failing render emits finished_err with the message."""
    import epy_reports.epy_suite_connect._adapters.docs_bridge as bridge

    def _boom(**kw):
        raise RuntimeError("render exploded")

    monkeypatch.setattr(bridge, "render_document", _boom)
    worker = _RenderWorker(
        Path("src.md"), "corporate", "report", Path("out"),
        pdf=True, html=True,
    )
    errors: list[str] = []
    worker.finished_err.connect(errors.append)
    worker.run()
    assert errors == ["render exploded"]


# ---------------------------------------------------------------------------
# Reachable without the engine
#
# The dialog could not be BUILT without ePy Docs: its constructor asked
# the engine for its layouts and document kinds, and inside the frozen
# bundle the engine can never be imported. So even once the availability
# question was answered correctly, opening this window would still have
# raised -- a second, independent reason the export entry was dead in
# every shipped executable.


class _Blocker:
    """Makes ``epy_docs`` genuinely unimportable, as a bundle does."""

    def find_spec(self, name, path=None, target=None):  # noqa: ANN001, ANN201
        if name == "epy_docs" or name.startswith("epy_docs."):
            raise ImportError("epy_docs is not importable in this process")
        return None


@pytest.fixture
def engine_hidden():
    """Hide the engine from every import in this process.

    Reporting it absent is not enough to measure this: it IS installed
    on the machine these tests run on, so a constructor that went back
    to asking it would build fine here and fail only where nobody is
    watching. Measured -- that planting passed until this existed.
    """
    import sys

    saved = sys.modules.pop("epy_docs", None)
    blocker = _Blocker()
    sys.meta_path.insert(0, blocker)
    try:
        yield
    finally:
        sys.meta_path.remove(blocker)
        if saved is not None:
            sys.modules["epy_docs"] = saved


def test_the_dialog_is_built_with_no_engine_on_the_machine(
    qapp, tmp_path, engine_hidden, monkeypatch
):
    """The window exists even where the engine cannot be imported."""
    from epy_export._core import _backends

    monkeypatch.delenv(_backends.ENV_DOCS_PYTHON, raising=False)
    source = tmp_path / "informe.md"
    source.write_text("# T\n", encoding="utf-8")
    dialog = DocsExportDialog(source)
    assert dialog.windowTitle()


def test_the_dialog_offers_the_family_vocabulary(
    qapp, tmp_path, engine_hidden, monkeypatch
):
    """Both combos are filled from the shared vocabulary."""
    from epy_export import APPEARANCES, DOCUMENT_TYPES
    from PySide6.QtWidgets import QComboBox

    monkeypatch.delenv("EPY_DOCS_PYTHON", raising=False)
    source = tmp_path / "informe.md"
    source.write_text("# T\n", encoding="utf-8")
    dialog = DocsExportDialog(source)
    offered = {
        tuple(box.itemText(index) for index in range(box.count()))
        for box in dialog.findChildren(QComboBox)
    }
    assert tuple(APPEARANCES) in offered
    assert tuple(DOCUMENT_TYPES) in offered


def test_the_organisation_is_not_spelt_inline():
    """One constant, in one place, for the whole family.

    Two spellings of one organisation is how a dialog comes to read a
    different registry tree than the window that opened it -- silently,
    because both spellings work today. The scope now lives in the
    shared window, so neither module may carry the literal.
    """
    import inspect

    from epy_export._ui import docs_export_dialog as shared

    for module in (ded, shared):
        source = inspect.getsource(module)
        assert "ANM Ingenier" not in source, module.__name__
    assert "ORGANIZATION" in inspect.getsource(shared)
