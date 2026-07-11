from engine.ui.pointer_arrow_overlay import ArrowOverlayPusher, build_arrows_script


def test_empty_clears_layer():
    js = build_arrows_script([])
    assert "#pointer-arrows" in js
    assert "innerHTML=''" in js.replace('"', "'").replace(" ", "")


def test_one_arrow_positioned_vwvh():
    js = build_arrows_script([{"x": 0.30, "y": 0.40, "w": 0.02, "h": 0.02, "dir": 0}])
    assert "30.0vw" in js and "40.0vh" in js
    assert "arrow--0" in js


def test_multiple_arrows_all_present():
    js = build_arrows_script([
        {"x": 0.1, "y": 0.2, "w": 0.02, "h": 0.02, "dir": 4},
        {"x": 0.5, "y": 0.6, "w": 0.02, "h": 0.02, "dir": 2},
    ])
    assert "arrow--4" in js
    assert "arrow--2" in js
    assert js.count("arrow--") == 2


def test_missing_dir_and_wh_do_not_raise():
    js = build_arrows_script([{"x": 0.1, "y": 0.2}])
    assert "#pointer-arrows" in js


def test_pusher_skips_unchanged_arrow_set():
    calls = []
    pusher = ArrowOverlayPusher(calls.append)
    arrows = [{"x": 0.1, "y": 0.2, "w": 0.02, "h": 0.02, "dir": 0}]

    pusher.push(arrows)
    pusher.push(list(arrows))  # same content, new list object

    assert len(calls) == 1


def test_pusher_emits_on_change_and_on_clear():
    calls = []
    pusher = ArrowOverlayPusher(calls.append)

    pusher.push([{"x": 0.1, "y": 0.2, "w": 0.02, "h": 0.02, "dir": 0}])
    pusher.push([{"x": 0.3, "y": 0.2, "w": 0.02, "h": 0.02, "dir": 0}])
    pusher.push([])  # cleared
    pusher.push([])  # still cleared -> no re-emit

    assert len(calls) == 3
    assert "innerHTML=''" in calls[-1].replace('"', "'").replace(" ", "")
