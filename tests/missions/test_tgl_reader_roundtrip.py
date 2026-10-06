from engine.missions import tgl_reader


def test_build_tgl_bytes_round_trips_through_parse():
    data = tgl_reader.build_tgl_bytes(
        {"Galaxy": "Galaxy", "BirdOfPrey": "Bird of Prey", "Snd": "x"},
        sounds={"Snd": "sfx/x.wav"})
    got = tgl_reader._parse(data, source="test")
    assert got.strings == {"Galaxy": "Galaxy", "BirdOfPrey": "Bird of Prey", "Snd": "x"}
    assert got.sounds == {"Snd": "sfx/x.wav"}


def test_build_tgl_bytes_empty_parses_to_nothing():
    got = tgl_reader._parse(tgl_reader.build_tgl_bytes({}), source="test")
    assert got.strings == {}


def _stock_tgls():
    import pytest
    from engine import paths
    try:
        root = paths.game_root() / "data" / "TGL"  # paths-guard: stock-only corpus
    except paths.PathsUnresolved:
        pytest.skip("BC content not configured")
    found = sorted(p for p in root.rglob("*") if p.suffix.lower() == ".tgl")
    if not found:
        pytest.skip("BC content not configured")
    return found


def test_write_tgl_reproduces_every_stock_file_byte_for_byte():
    """write_tgl is the inverse of read_entries on BC's own files -- the
    proof that a TGL we generate has the exact layout stbc.exe reads."""
    mismatched = []
    for path in _stock_tgls():
        data = path.read_bytes()
        entries = tgl_reader.read_entries(data)
        if tgl_reader.write_tgl(entries) != data:
            mismatched.append(path.name)
    assert mismatched == []


def test_write_tgl_round_trips_through_read_tgl_parse():
    data = tgl_reader.write_tgl([
        ("BrexLine1", "Raise shields.", "sfx/Bridge/Crew/Engineering/BrexLine1.wav"),
        ("NoSound", "Text only.", ""),
    ])
    got = tgl_reader._parse(data, source="test")
    assert got.strings == {"BrexLine1": "Raise shields.", "NoSound": "Text only."}
    assert got.sounds == {"BrexLine1": "sfx/Bridge/Crew/Engineering/BrexLine1.wav"}
    assert data[:4] == (0x1701).to_bytes(4, "little")
