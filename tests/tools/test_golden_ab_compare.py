"""tools/golden_ab_compare.py: pure compare-and-report on hand-built rows."""
from tools.golden_ab_compare import (SceneDiff, compare_scene, exit_code,
                                     format_report, format_value)


def _tick(t, timer="0x1p+1", extra=None):
    weapon = ["weapon", "Player/Phaser 1", False, "Enemy-1", timer]
    return (t, [weapon] + (extra or []), [], [], [], [], [])


def _rows(timers):
    return [_tick(i + 1, tm) for i, tm in enumerate(timers)]


def test_identical():
    d = compare_scene("s", _rows(["0x1p+1"] * 3), _rows(["0x1p+1"] * 3))
    assert d.status == "identical"
    assert exit_code([d]) == 0


def test_first_tick_fields_and_counts():
    base = _rows(["0x1p+0", "0x1p+1", "0x1p+1", "0x1p+1"])
    head = _rows(["0x1p+0", "0x1.4p+1", "0x1p+1", "0x1.4p+1"])
    d = compare_scene("s", base, head)
    assert d.status == "differs"
    assert (d.first_tick, d.differing_ticks, d.last_tick) == (2, 2, 4)
    assert d.first_kind == "state/weapon"
    assert "'Player/Phaser 1'" in d.fields[0]
    assert "_fire_timer" in d.fields[0]
    assert "2.0 → 2.5" in d.fields[0]


def test_fields_capped_at_20():
    extra = [["pose", "n%d" % i, "a", "b", "c"] for i in range(30)]
    base = [(1, extra, [], [], [], [], [])]
    head = [(1, [["pose", "n%d" % i, "x", "b", "c"] for i in range(30)],
             [], [], [], [], [])]
    d = compare_scene("s", base, head)
    assert len(d.fields) == 20


def test_length_mismatch():
    d = compare_scene("s", _rows(["0x1p+0"] * 3), _rows(["0x1p+0"] * 2))
    assert d.status == "differs"
    assert any("ticks" in f for f in d.fields)


def test_format_value():
    assert format_value("0x1.4p+1") == "2.5 [0x1.4p+1]"
    assert format_value("abc") == "abc"
    assert format_value(3) == "3"


def test_scene_vocabulary_used():
    row = ["ship", "P", "a", "b"]
    base = [(1, [row], [], [], [], [], [])]
    head = [(1, [["ship", "P", "a", "c"]], [], [], [], [], [])]
    d = compare_scene("native_subsystems_scene", base, head)
    assert "IsDead" not in d.fields[0]
    assert "_articulation_transitions" in d.fields[0]


def test_report_harness_warning_first_line():
    r = format_report([SceneDiff("s", "identical")],
                      ["tests/helpers/k1_fight.py"])
    first = r.splitlines()[0]
    assert first.startswith("WARNING: harness differs")
    assert "tests/helpers/k1_fight.py" in first


def test_report_differs_block():
    d = compare_scene("s", _rows(["0x1p+0", "0x1p+1"]),
                      _rows(["0x1p+0", "0x1.4p+1"]))
    r = format_report([d], [])
    assert "s: differs" in r
    assert "1 ticks differ, last at 2" in r


def test_report_only_in_and_error():
    ds = [SceneDiff("a", "only in base"), SceneDiff("b", "only in HEAD"),
          SceneDiff("c", "error", error="boom\ntrace", side="HEAD")]
    r = format_report(ds, [])
    assert "a: only in base" in r
    assert "b: only in HEAD" in r
    assert "c: error (HEAD)\n    boom\n    trace" in r
    assert exit_code(ds[:1]) == 1
    assert exit_code(ds[1:2]) == 1
    assert exit_code(ds[2:]) == 2


def test_report_error_shows_last_lines_and_names_side():
    tail = "\n".join("line %d" % i for i in range(40))
    r = format_report([SceneDiff("c", "error", error=tail, side="base")], [])
    lines = r.splitlines()
    assert lines[0] == "c: error (base)"
    assert lines[1:] == ["    line %d" % i for i in range(25, 40)]


def test_report_inherited_env_line_and_omission():
    r = format_report([SceneDiff("s", "identical")], [],
                      ["DAUNTLESS_PASSIVE_STATE=0", "DAUNTLESS_X=1"])
    assert r.splitlines()[0] == ("inherited env: DAUNTLESS_PASSIVE_STATE=0 "
                                 "DAUNTLESS_X=1")
    assert "inherited" not in format_report([SceneDiff("s", "identical")], [], [])
