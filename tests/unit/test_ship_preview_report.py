"""engine.dev_missions.ship_preview's asset report: a stock ship script is
reported at its place in the install (the listed .pyc), never the SDK."""
from engine import mods, paths


def test_stock_script_lines_name_the_install_pyc(monkeypatch, capsys):
    from engine.dev_missions import ship_preview

    def _no_sdk(*_a, **_k):
        raise AssertionError("ship_preview must not read the SDK")
    monkeypatch.setattr(paths, "sdk_scripts", _no_sdk)
    monkeypatch.setattr(mods, "sdk_override", lambda rel: None)

    ship_preview._report_resolution("ZZNoSuchShip")

    err = capsys.readouterr().err
    scripts = paths.stock_scripts()
    for rel in ("ships/ZZNoSuchShip.pyc", "ships/Hardpoints/ZZNoSuchShip.pyc"):
        assert "stock  %s" % (scripts / rel) in err, err
