from engine import foundation
from engine.foundation.loader import LoadReport


def test_report_names_ships_plugins_and_failures():
    r = LoadReport(autoload=["custom/autoload/a.py"],
                   ships=["custom/ships/s.py"],
                   failures=[("custom/ships/bad.py", "ValueError: boom")])
    text = foundation.describe(r)
    assert "1 ship" in text and "1 plugin" in text
    assert "bad.py" in text and "ValueError" in text


def test_report_is_empty_when_nothing_loaded():
    assert foundation.describe(LoadReport()) == ""


def test_report_names_declared_but_absent_techs():
    """FTech itself logs and continues when a ship declares a tech that is
    not installed, so this is the ecosystem's own behaviour -- we just say
    so instead of staying silent."""
    d = foundation.FedShipDef("X", 1, {"name": "X"})
    d.dTechs = {"AutoTargeting": {}, "Ablative Armour": {}}
    text = foundation.describe(LoadReport(ships=["s.py"]))
    assert "AutoTargeting" in text and "not installed" in text
