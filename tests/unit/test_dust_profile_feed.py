from engine import host_loop
from engine.systems import profile as P


class _R:
    def __init__(self):
        self.dust = None

    def __getattr__(self, name):
        if name == "set_dust_profile":
            return lambda v: setattr(self, "dust", v)
        return lambda *a, **k: None


def test_dust_sample_is_pushed_for_the_player(monkeypatch):
    monkeypatch.setattr(P, "sample_for_object", lambda obj: P.Sample(dust=0.3))
    r = _R()
    host_loop._push_dust_profile(r, player=object(), warp_streaking=False)
    assert r.dust == 0.3


def test_no_player_or_warp_tunnel_pushes_zero(monkeypatch):
    monkeypatch.setattr(P, "sample_for_object", lambda obj: P.Sample(dust=0.3))
    r = _R()
    host_loop._push_dust_profile(r, player=None, warp_streaking=False)
    assert r.dust == 0.0
    host_loop._push_dust_profile(r, player=object(), warp_streaking=True)
    assert r.dust == 0.0
