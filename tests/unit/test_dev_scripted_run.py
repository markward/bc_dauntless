"""The unattended dev run: destroy a named object once the opening cutscene
has been over for a while, then quit. Exists so baseline B1
(docs/engine/perf-register.md) needs no keypress."""
from engine.dev_scripted_run import ScriptedRun


class _Destroyer:
    def __init__(self, found=True):
        self.calls = []
        self.found = found

    def __call__(self, name):
        self.calls.append(name)
        return self.found


def _run(**kw):
    kw.setdefault("target", "Facility")
    kw.setdefault("delay_s", 10.0)
    kw.setdefault("quit_after_s", 30.0)
    return ScriptedRun(**kw)


def test_from_env_is_off_without_developer_mode():
    env = {"DAUNTLESS_DEV_DESTROY": "Facility"}
    assert ScriptedRun.from_env(env, developer=False) is None


def test_from_env_is_off_without_a_target():
    assert ScriptedRun.from_env({}, developer=True) is None


def test_from_env_reads_target_delay_and_quit():
    env = {"DAUNTLESS_DEV_DESTROY": " Facility ",
           "DAUNTLESS_DEV_DESTROY_DELAY_S": "4",
           "DAUNTLESS_DEV_QUIT_AFTER_S": "25"}
    run = ScriptedRun.from_env(env, developer=True)
    assert (run.target, run.delay_s, run.quit_after_s) == ("Facility", 4.0, 25.0)


def test_from_env_defaults_delay_and_never_quits_unless_asked():
    run = ScriptedRun.from_env({"DAUNTLESS_DEV_DESTROY": "Facility"},
                               developer=True)
    assert run.delay_s == 10.0
    assert run.quit_after_s is None


def test_destroys_only_after_delay_seconds_clear_of_cutscenes():
    run, d = _run(delay_s=10.0), _Destroyer()
    run.tick(1.0, cutscene_active=True, destroy=d)
    for _ in range(9):
        run.tick(1.0, cutscene_active=False, destroy=d)
    assert d.calls == []
    run.tick(1.0, cutscene_active=False, destroy=d)
    assert d.calls == ["Facility"]


def test_a_new_cutscene_restarts_the_wait():
    run, d = _run(delay_s=10.0), _Destroyer()
    for _ in range(8):
        run.tick(1.0, cutscene_active=False, destroy=d)
    run.tick(1.0, cutscene_active=True, destroy=d)
    for _ in range(9):
        run.tick(1.0, cutscene_active=False, destroy=d)
    assert d.calls == []
    run.tick(1.0, cutscene_active=False, destroy=d)
    assert d.calls == ["Facility"]


def test_destroys_once():
    run, d = _run(delay_s=1.0, quit_after_s=None), _Destroyer()
    for _ in range(20):
        run.tick(1.0, cutscene_active=False, destroy=d)
    assert d.calls == ["Facility"]


def test_retries_while_the_target_does_not_exist_yet():
    run, d = _run(delay_s=1.0), _Destroyer(found=False)
    run.tick(1.0, cutscene_active=False, destroy=d)
    run.tick(1.0, cutscene_active=False, destroy=d)
    assert d.calls == ["Facility", "Facility"]


def test_quits_quit_after_seconds_after_the_destroy():
    run, d = _run(delay_s=1.0, quit_after_s=3.0), _Destroyer()
    assert run.tick(1.0, cutscene_active=False, destroy=d) is False  # destroy
    assert run.tick(1.0, cutscene_active=False, destroy=d) is False
    assert run.tick(1.0, cutscene_active=False, destroy=d) is False
    assert run.tick(1.0, cutscene_active=False, destroy=d) is True


def test_never_quits_without_quit_after():
    run, d = _run(delay_s=1.0, quit_after_s=None), _Destroyer()
    assert not any(run.tick(1.0, cutscene_active=False, destroy=d)
                   for _ in range(100))


def test_from_env_reads_the_view():
    env = {"DAUNTLESS_DEV_DESTROY": "Facility",
           "DAUNTLESS_DEV_VIEW": "exterior"}
    assert ScriptedRun.from_env(env, developer=True).view == "exterior"
    env.pop("DAUNTLESS_DEV_VIEW")
    assert ScriptedRun.from_env(env, developer=True).view is None


def test_the_view_is_forced_once_per_cutscene_free_stretch():
    """A cutscene may put the camera back on the bridge, so the view is
    re-applied after each one, but not every frame (that would fight any
    camera change the mission makes on its own)."""
    views = []
    run = _run(delay_s=100.0, view="exterior")
    tick = lambda active: run.tick(1.0, cutscene_active=active,
                                   destroy=_Destroyer(),
                                   force_view=views.append)
    tick(True)
    assert views == []
    tick(False); tick(False); tick(False)
    assert views == ["exterior"]
    tick(True); tick(False); tick(False)
    assert views == ["exterior", "exterior"]


def test_no_view_is_forced_unless_asked():
    views = []
    run = _run(delay_s=100.0)
    run.tick(1.0, cutscene_active=False, destroy=_Destroyer(),
             force_view=views.append)
    assert views == []


def test_events_are_reported_for_the_log():
    lines = []
    run, d = _run(delay_s=1.0, quit_after_s=1.0), _Destroyer()
    run.tick(1.0, cutscene_active=True, destroy=d, log=lines.append)
    run.tick(1.0, cutscene_active=False, destroy=d, log=lines.append)
    run.tick(1.0, cutscene_active=False, destroy=d, log=lines.append)
    run.tick(1.0, cutscene_active=False, destroy=d, log=lines.append)
    text = "\n".join(lines)
    assert "cutscene start" in text
    assert "cutscene end" in text
    assert "destroyed Facility" in text
    assert "quit" in text
