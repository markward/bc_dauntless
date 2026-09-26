import ast

import pytest

from engine.appc import mod_hardpoint_writer as mw

AUTHOR = 'import App\nX = App.EngineProperty_Create("Port Warp")\nApp.g_kModelPropertyManager.RegisterLocalTemplate(X)\n'


def _model():
    return {
        "Port Warp": [("SetGlowRegionShape", (0, "Box")),
                      ("SetLightEmitterKind", (0, "point"))],
        "__parts__": {"wing": [("SetTransitionSeconds", (2.0,))]},
    }


def test_emit_then_split_then_read_round_trips():
    block = mw.emit_block(_model())
    text = mw.append_block(AUTHOR, block, "\n")
    author, got = mw.split_block(text)
    assert author == AUTHOR
    assert got == block
    assert mw.read_block(got) == _model()


def test_block_is_guarded_and_python_parses():
    block = mw.emit_block(_model())
    assert block.startswith(mw.START_MARKER)
    assert block.rstrip("\n").endswith(mw.END_MARKER)
    assert 'if hasattr(App, "DAUNTLESS_ENV") and App.DAUNTLESS_ENV >= 1:' in block
    assert "def _dauntless_spv(find):" in block
    ast.parse(block)
    for bad in ("f\"", "True", "False", " as "):
        assert bad not in block


def test_empty_model_emits_nothing():
    assert mw.emit_block({}) == ""
    assert mw.emit_block({"Port Warp": [], "__parts__": {}}) == ""


def test_reading_a_block_has_no_side_effect_on_the_live_manager():
    import App
    mgr = App.g_kModelPropertyManager
    scope = App.TGModelPropertyManager.LOCAL_TEMPLATES
    assert mgr.FindByName("wing", scope) is None
    mw.read_block(mw.emit_block(_model()))
    assert mgr.FindByName("wing", scope) is None


def test_no_block_reads_as_empty():
    author, block = mw.split_block(AUTHOR)
    assert author == AUTHOR and block is None
    assert mw.read_block(None) == {}


@pytest.mark.parametrize("text", [
    AUTHOR + mw.START_MARKER + "\n",                                  # no end
    AUTHOR + mw.END_MARKER + "\n",                                    # no start
    AUTHOR + mw.emit_block(_model()) + mw.emit_block(_model()),       # two blocks
])
def test_malformed_markers_are_refused(text):
    with pytest.raises(mw.ManagedBlockError):
        mw.split_block(text)


def test_author_without_trailing_newline_gets_one_before_the_block():
    text = mw.append_block(AUTHOR.rstrip("\n"), mw.emit_block(_model()), "\n")
    assert "RegisterLocalTemplate(X)\n" + mw.START_MARKER in text


def test_crlf_block():
    block = mw.emit_block(_model(), newline="\r\n")
    assert "\r\n" in block and "\n" not in block.replace("\r\n", "")
    assert mw.read_block(block) == _model()


def test_the_block_runs_against_a_live_find():
    """Executed as a hardpoint file would be: the guarded call site applies
    the setters to whatever find() returns."""
    calls = []

    class Prop:
        def __getattr__(self, n):
            return lambda *a: calls.append((n, a))

    class Mgr:
        def FindByName(self, name, scope):
            return Prop() if name == "Port Warp" else None
        def RegisterLocalTemplate(self, p):
            pass

    class FakeApp:
        DAUNTLESS_ENV = 1
        g_kModelPropertyManager = Mgr()
        class TGModelPropertyManager:
            LOCAL_TEMPLATES = 1
        @staticmethod
        def ArticulatedPartProperty_Create(name):
            return Prop()

    import sys
    prev = sys.modules.get("App")
    sys.modules["App"] = FakeApp
    try:
        exec(mw.emit_block(_model()), {"App": FakeApp})
    finally:
        sys.modules["App"] = prev
    assert ("SetGlowRegionShape", (0, "Box")) in calls
