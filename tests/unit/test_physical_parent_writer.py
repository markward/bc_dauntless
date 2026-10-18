import ast

from engine.appc import hardpoint_override_writer as w
from engine.appc import mod_hardpoint_writer as mw

AUTHOR = ('import App\n'
          'PortCannon = App.PhaserProperty_Create("Port Cannon")\n'
          'PortCannon.SetPhysicalParent("left wing")\n'
          'App.g_kModelPropertyManager.RegisterLocalTemplate(PortCannon)\n'
          'Other = App.PhaserProperty_Create("Other")\n'
          'App.g_kModelPropertyManager.RegisterLocalTemplate(Other)\n')
PLAIN = AUTHOR.replace('PortCannon.SetPhysicalParent("left wing")\n', '')


def _stock(edits, base=None):
    models = base if base is not None else {}
    for e in edits:
        w.apply_edit(models, "bop", e)
    return models


def test_stock_set_emits_call():
    text = w.emit(_stock([("Port Cannon", "SetPhysicalParent", ("birdofprey",))]))
    assert '        p.SetPhysicalParent("birdofprey")' in text
    assert "DAUNTLESS_ENV" not in text


def test_stock_unset_removes_call():
    models = _stock([("Port Cannon", "SetPhysicalParent", ("a",)),
                     ("Port Cannon", "SetRadius", (0.5,)),
                     ("Port Cannon", "__unset__", "SetPhysicalParent")])
    assert models["bop"]["Port Cannon"] == [("SetRadius", (0.5,))]
    assert "SetPhysicalParent" not in w.emit(models)


def test_stock_unset_drops_empty_block():
    models = _stock([("Port Cannon", "SetPhysicalParent", ("a",)),
                     ("Port Cannon", "__unset__", "SetPhysicalParent")])
    text = w.emit(models)
    assert "find(" not in text.split("def _bop", 1)[1]


def test_mod_set_lands_inside_guarded_block():
    out = mw.rewrite(PLAIN, "bop", [("Port Cannon", "SetPhysicalParent", ("wing",))])
    assert out.startswith(PLAIN)
    block = out[len(PLAIN):]
    assert 'p.SetPhysicalParent("wing")' in block
    assert "DAUNTLESS_ENV" in block


def test_mod_unset_without_author_call_removes():
    first = mw.rewrite(PLAIN, "bop", [("Port Cannon", "SetPhysicalParent", ("wing",))])
    out = mw.rewrite(first, "bop", [("Port Cannon", "__unset__", "SetPhysicalParent")])
    assert out == PLAIN


def test_mod_unset_with_author_call_writes_none():
    out = mw.rewrite(AUTHOR, "bop", [("Port Cannon", "__unset__", "SetPhysicalParent")])
    assert out.startswith(AUTHOR)
    assert "p.SetPhysicalParent(None)" in out[len(AUTHOR):]
    ast.parse(out)
    # a later plain SET replaces the None
    again = mw.rewrite(out, "bop", [("Port Cannon", "SetPhysicalParent", ("x",))])
    assert again.startswith(AUTHOR)
    assert 'SetPhysicalParent("x")' in again and "(None)" not in again


def test_unset_leaves_other_setters_alone():
    first = mw.rewrite(PLAIN, "bop", [("Port Cannon", "SetPhysicalParent", ("wing",)),
                                      ("Port Cannon", "SetRadius", (0.5,)),
                                      ("Other", "SetPhysicalParent", ("hull",))])
    out = mw.rewrite(first, "bop", [("Port Cannon", "__unset__", "SetPhysicalParent")])
    _a, block = mw.split_block(out)
    model = mw.read_block(block)
    assert model["Port Cannon"] == [("SetRadius", (0.5,))]
    assert model["Other"] == [("SetPhysicalParent", ("hull",))]


def test_physical_parent_name_with_quote_round_trips():
    name = "Bob's left wing"
    text = w.emit(_stock([("Port Cannon", "SetPhysicalParent", (name,))]))
    back = w.read_models_from_source(text)
    assert back["bop"]["Port Cannon"] == [("SetPhysicalParent", (name,))]
    out = mw.rewrite(PLAIN, "bop", [("Port Cannon", "SetPhysicalParent", (name,))])
    _a, block = mw.split_block(out)
    assert mw.read_block(block)["Port Cannon"] == [("SetPhysicalParent", (name,))]


def test_emitted_text_is_py15_safe():
    name = "rom wing top left"
    texts = [w.emit(_stock([("A", "SetPhysicalParent", (name,))])),
             mw.rewrite(AUTHOR, "bop", [("Port Cannon", "__unset__", "SetPhysicalParent"),
                                        ("Other", "SetPhysicalParent", (name,))])]
    for text in texts:
        for line in text.splitlines():
            if "SetPhysicalParent" in line:
                assert "True" not in line and "False" not in line and " as " not in line
