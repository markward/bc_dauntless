"""TGParagraph ordered segment stream."""
import App
from engine.appc.tg_ui.widgets import TGParagraph, TGParagraph_CreateW


def test_constructor_text_is_first_segment():
    p = TGParagraph("Hello")
    assert p.iter_segments() == [("text", "Hello")]
    assert p.GetText() == "Hello"


def test_empty_constructor_has_no_segments():
    p = TGParagraph()
    assert p.iter_segments() == []
    assert p.GetText() == ""


def test_append_string_and_char_preserve_order():
    p = TGParagraph("A")
    p.AppendChar(App.WC_RETURN)
    p.AppendStringW("B")
    assert p.iter_segments() == [("text", "A"), ("char", 13), ("text", "B")]
    assert p.GetText() == "A\nB"


def test_add_child_records_segment_and_tgpane_child():
    parent = TGParagraph("Press ")
    glyph = TGParagraph("W")
    parent.AddChild(glyph)
    parent.AppendStringW(" to go")
    segs = parent.iter_segments()
    assert segs[0] == ("text", "Press ")
    assert segs[1] == ("child", glyph)
    assert segs[2] == ("text", " to go")
    # GetText flattens the child inline
    assert parent.GetText() == "Press W to go"
    # TGPane container contract still satisfied (child also in _children)
    assert glyph in [c for (c, _x, _y) in parent.GetChildren()]


def test_set_text_resets_segments():
    p = TGParagraph("A")
    p.AppendStringW("B")
    p.SetText("C")
    assert p.iter_segments() == [("text", "C")]
    assert p.GetText() == "C"


def test_createw_factory_builds_paragraph_with_flags():
    p = TGParagraph_CreateW("hi", 0.5, App.NiColorA_WHITE, "", 0.0,
                            TGParagraph.TGPF_READ_ONLY | TGParagraph.TGPF_WORD_WRAP)
    assert p.GetText() == "hi"
