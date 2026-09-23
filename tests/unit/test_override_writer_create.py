"""The writer can register a template BC never had.

Until now it could only MODIFY templates the stock hardpoint file already
registered: `find("left wing")` returns None for a template that does not
exist, and the override block is skipped. An articulated part is new, so
without this the whole feature writes files that do nothing.
"""
from engine.appc import hardpoint_override_writer as w


def test_a_part_edit_emits_a_find_or_CREATE_block():
    models = {}
    w.set_part(models, "birdofprey", "left wing", [
        ("SetPivot", (-0.16, 0.0, 0.05)),
        ("SetStateAngle", ("cruise", 45.0)),
        ("SetDetachFraction", (0.20,)),
    ])
    text = w.emit(models)
    assert "left wing" in text
    assert "SetStateAngle" in text
    assert "ArticulatedPartProperty_Create" in text, (
        "the block must be able to CREATE the template, not only find it")


def test_the_emitted_file_is_valid_python():
    """emit() already ast.parses its output; a part block must not break that."""
    import ast
    models = {}
    w.set_part(models, "birdofprey", "left wing",
               [("SetStateAngle", ("cruise", 45.0))])
    ast.parse(w.emit(models))


def test_a_part_edit_round_trips_through_read_models():
    """read_models recovers a ship's model by EXECUTING its function against a
    recorder. A create-verb block has no `find` to record, so the recorder
    needs its own hook -- without this, saving twice would drop every part."""
    models = {}
    w.set_part(models, "birdofprey", "left wing",
               [("SetStateAngle", ("cruise", 45.0))])
    text = w.emit(models)
    again = w.read_models_from_source(text)
    assert "left wing" in again.get("birdofprey", {}).get("__parts__", {})
