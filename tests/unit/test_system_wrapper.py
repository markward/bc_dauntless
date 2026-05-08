import App


def test_system_wrapper_singleton_exists():
    assert App.g_kSystemWrapper is not None


def test_get_random_number_returns_int_in_range():
    for _ in range(50):
        n = App.g_kSystemWrapper.GetRandomNumber(10)
        assert isinstance(n, int)
        assert 0 <= n < 10


def test_get_random_number_zero_returns_zero():
    """Defensive: Effects.py occasionally passes computed counts that may be 0."""
    assert App.g_kSystemWrapper.GetRandomNumber(0) == 0


def test_get_random_number_one_always_returns_zero():
    for _ in range(20):
        assert App.g_kSystemWrapper.GetRandomNumber(1) == 0


def test_set_random_seed_makes_sequence_deterministic():
    App.g_kSystemWrapper.SetRandomSeed(42)
    a = [App.g_kSystemWrapper.GetRandomNumber(100) for _ in range(10)]
    App.g_kSystemWrapper.SetRandomSeed(42)
    b = [App.g_kSystemWrapper.GetRandomNumber(100) for _ in range(10)]
    assert a == b
