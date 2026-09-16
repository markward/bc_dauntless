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
