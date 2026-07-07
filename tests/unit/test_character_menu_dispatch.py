"""Tests: dispatch_character_menu sends ET_CHARACTER_MENU through a bridge
officer's instance handler chain on menu open/close.

This is the signal E1M1's HandleMenuEvent (registered on every officer,
E1M1.py:905-910) needs to advance the character-selection tutorial: it acts
on a menu CLOSE (GetBool()==0) with the officer as the event destination.
Without this dispatch the tutorial never progresses and player control is
never returned.
"""
from __future__ import annotations

import App
from engine.appc.characters import CharacterClass, dispatch_character_menu


_received: list = []


def _recording_handler(dispatcher, event):
    _received.append((event.GetBool(), event.GetDestination()))


def test_open_then_close_dispatches_bool_1_then_0_to_officer():
    _received.clear()
    char = CharacterClass()
    char.AddPythonFuncHandlerForInstance(
        App.ET_CHARACTER_MENU, __name__ + "._recording_handler")

    dispatch_character_menu(char, is_open=True)
    dispatch_character_menu(char, is_open=False)

    assert [b for b, _ in _received] == [1, 0]
    assert all(dest is char for _, dest in _received)


def test_dispatched_event_type_is_character_menu():
    """A handler on a DIFFERENT event type must not fire — the dispatch
    uses ET_CHARACTER_MENU specifically."""
    _received.clear()
    char = CharacterClass()
    # Register the recorder on an unrelated event type.
    char.AddPythonFuncHandlerForInstance(
        App.ET_HAIL, __name__ + "._recording_handler")

    dispatch_character_menu(char, is_open=True)

    assert _received == []


def test_none_officer_is_noop():
    # Menu with no resolvable officer must not raise.
    dispatch_character_menu(None, is_open=True)
    dispatch_character_menu(None, is_open=False)
