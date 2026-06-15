import engine.appc._stub_trace as st


def setup_function(_):
    st.reset()


def test_stub_call_records_and_is_loud(capsys):
    st.stub_call("BridgeObjectClass_Create", "nif=DBridge.nif")
    captured = capsys.readouterr()
    assert "BRIDGE-STUB" in captured.err
    assert "BridgeObjectClass_Create" in captured.err
    assert "NOT YET IMPLEMENTED" in captured.err
    assert "BridgeObjectClass_Create" in st.fired()


def test_summary_lists_each_fired_symbol_once(capsys):
    st.stub_call("BridgeSet_Create")
    st.stub_call("BridgeSet_Create")          # same symbol twice
    st.stub_call("ViewScreenObject_Create")
    capsys.readouterr()                         # clear per-call banners
    st.dump_stub_summary()
    err = capsys.readouterr().err
    assert "2 stub(s)" in err
    assert "BridgeSet_Create" in err
    assert "ViewScreenObject_Create" in err


def test_summary_when_none_fired_says_faithful(capsys):
    st.dump_stub_summary()
    assert "faithful" in capsys.readouterr().err


def test_reset_clears_fired():
    st.stub_call("BridgeSet_Create")
    st.reset()
    assert st.fired() == set()
