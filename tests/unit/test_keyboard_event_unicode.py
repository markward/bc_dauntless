"""TGKeyboardEvent exposes BC's published GetUnicode/SetUnicode names.

sdk/Build/scripts/App.py:1062-1063 binds TGKeyboardEvent.GetUnicode and
SetUnicode. E1M1.SkipOpeningSequence calls pEvent.GetUnicode(); without the
alias it falls through TGObject.__getattr__ to a truthy _Stub and the skip-key
comparison can never match.
"""
from engine.appc.events import TGKeyboardEvent


def test_get_unicode_returns_the_key_code():
    evt = TGKeyboardEvent()
    evt.SetUnicodeKey(0x53)
    assert evt.GetUnicode() == 0x53


def test_set_unicode_writes_the_same_slot_as_set_unicode_key():
    evt = TGKeyboardEvent()
    evt.SetUnicode(0x41)
    assert evt.GetUnicodeKey() == 0x41
    assert evt.GetUnicode() == 0x41


def test_get_unicode_is_an_int_not_a_stub():
    evt = TGKeyboardEvent()
    evt.SetUnicode(0x53)
    assert isinstance(evt.GetUnicode(), int)
