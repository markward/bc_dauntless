"""WC_* wide-char constants and wc_to_str mapping."""
import App
from engine.appc.tg_ui.widgets import wc_to_str


def test_wc_constant_values():
    assert App.WC_BACKSPACE == 8
    assert App.WC_TAB == 9
    assert App.WC_LINEFEED == 10
    assert App.WC_RETURN == 13
    assert App.WC_SPACE == 32
    # BC's own measured value (0xE098) -- it lives in BC's high function-key/
    # mouse-button band, not an invented Private-Use-Area sentinel.
    assert App.WC_CURSOR == 0xE098


def test_wc_to_str_control_codes():
    assert wc_to_str(App.WC_RETURN) == "\n"
    assert wc_to_str(App.WC_LINEFEED) == "\n"
    assert wc_to_str(App.WC_SPACE) == " "
    assert wc_to_str(App.WC_TAB) == "\t"
    assert wc_to_str(App.WC_BACKSPACE) == ""
    assert wc_to_str(App.WC_CURSOR) == ""


def test_wc_to_str_printable():
    assert wc_to_str(ord("W")) == "W"
