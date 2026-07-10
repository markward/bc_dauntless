import engine.dev_mode as dev_mode


def test_probe_handler_importable():
    from engine.dev_viewscreen_probe import watch_current_target
    assert callable(watch_current_target)


def test_probe_handler_no_player_is_safe(monkeypatch, capsys):
    import engine.dev_viewscreen_probe as probe
    import engine.core.game as game_mod
    monkeypatch.setattr(game_mod, "Game_GetCurrentGame", lambda: None)
    probe.watch_current_target()
    assert "no current player" in capsys.readouterr().out
