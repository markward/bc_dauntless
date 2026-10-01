"""Fly-through responses to minor rocks (minor-rocks spec section 3):
rate-limited cosmetic puff / grit sound / shield flicker when the player's
hull brushes a minor. Purely cosmetic -- no damage, no events, no game-state
change (the native MinorField's own contact/shove response already moved the
rock; this module only decorates that touch).

Muted while the player is dashing (engine.appc.dash.is_dashing) or sitting
in the persistent "warp" set, so a dewarping or in-transit ship never spams
these. Contacts are drained from the renderer either way, so a muted frame
doesn't leave a stale backlog for the next unmuted one.

Every number lives in engine.rocks.minor_dials; see §5 there.
"""
import random

from engine.appc.math import TGPoint3

_buckets: dict = {}  # response kind -> (tokens, last game-time)


def reset() -> None:
    global _buckets
    _buckets = {}


def _take(kind: str, now: float) -> bool:
    """One token bucket per response (`kind` in puff/grit/flicker), refilled
    at `<kind>_max_per_s` tokens/s with capacity `<kind>_max_per_s`."""
    from engine.rocks import minor_dials as md
    cap = float(md.get("%s_max_per_s" % kind))
    tokens, last = _buckets.get(kind, (cap, now))
    tokens = min(cap, tokens + max(0.0, now - last) * cap)
    if tokens < 1.0:
        _buckets[kind] = (tokens, now)
        return False
    _buckets[kind] = (tokens - 1.0, now)
    return True


# ── Seams (monkeypatched by tests) ──────────────────────────────────────────

def _muted(player) -> bool:
    from engine.appc import dash
    if dash.is_dashing(player):
        return True
    from engine.systems import frames
    pSet = frames.containing_set(player)
    return pSet is not None and pSet.GetName() == "warp"


def _shields_up(player) -> bool:
    from engine.appc import combat
    return combat.shields_block(player)


def _spawn_puff(point) -> None:
    from engine.appc import hit_vfx
    from engine.appc.hit_feedback import SPARK_KIND_ROCK
    from engine.rocks import minor_dials as md
    from engine.systems import frames
    hit_vfx.spawn(TGPoint3(*point), severity=hit_vfx.Severity.CRITICAL,
                  instance_id=None, weapon_kind=SPARK_KIND_ROCK,
                  spark_count=md.get("puff_spark_count"),
                  pSet=frames.viewing_set())


def _play_grit(point, radius: float) -> bool:
    """`name` picks one of BC's "Collision 1".."Collision 8" pool
    (LoadTacticalSounds.py:123-130, loaded at boot by
    host_loop._bootstrap_firing_pipeline). A missing sound (backend down,
    name never registered) is skipped rather than raising."""
    import App
    from engine.rocks import minor_dials as md
    name = "Collision %d" % random.randint(1, 8)
    snd = App.g_kSoundManager.GetSound(name)
    if snd is None:
        return False
    old = snd.GetVolume()
    snd.SetVolume(old * md.get("grit_volume") * min(1.0, radius / 0.5))
    try:
        snd.Play(position=point)
    finally:
        snd.SetVolume(old)      # a shared pool sound: never leave it quiet
    return True


def _flicker(player, point, session) -> bool:
    if session is None:
        return False
    iid = session.ship_instances.get(player)
    if iid is None:
        return False
    from engine import host_io
    from engine.rocks import minor_dials as md
    host_io.shield_hit(iid, point, (0.0, 0.0, 0.0, 0.0),
                        md.get("flicker_intensity"), md.get("flicker_radius"))
    return True


def pump(player, contacts=None, now=None, session=None) -> dict:
    """Drain this frame's minor-rock contacts (or `contacts`, for tests) and
    emit rate-limited puff / grit / shield-flicker responses. Returns the
    counts actually emitted this call: {"puffs", "grits", "flickers"}."""
    if contacts is None:
        from engine import renderer
        contacts = renderer.minors_drain_contacts()
    out = {"puffs": 0, "grits": 0, "flickers": 0}
    if player is None or not contacts:
        return out
    if _muted(player):
        return out
    if now is None:
        import App
        now = float(App.g_kUtopiaModule.GetGameTime())
    from engine.rocks import minor_dials as md
    shields_up = _shields_up(player)
    for c in contacts:
        point = c["point"]
        radius = c["radius"]
        if radius >= md.get("puff_min_radius_gu") and _take("puff", now):
            _spawn_puff(point)
            out["puffs"] += 1
        if _take("grit", now) and _play_grit(point, radius):
            out["grits"] += 1
        if shields_up and _take("flicker", now) and \
                _flicker(player, point, session):
            out["flickers"] += 1
    return out
