# Nebula Ship Wake — Per-Engine Trails Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single ship-centroid wake trail with **one trail per impulse-engine pod**, each anchored at the pod's world mount, scaled to the pod's radius, and emitted **only while that pod is online** (not disabled or destroyed) — so the wake reads as real propulsion exhaust and a damaged engine visibly stops trailing.

**Architecture:** Build on the merged Plan-B additive billboard pass. Three pieces change: (1) the Python `NebulaWakeTracker` becomes **multi-emitter** — one ring buffer per pod, keyed by pod identity; (2) a new `active_impulse_emitters(player)` helper in `subsystems.py` discovers each online pod's world position + radius (reusing the existing `_is_offline` gate and the `GetNumChildSubsystems`/`GetChildSubsystem(i)` walk that `impulse_online_fraction` already uses); (3) each wake **point carries its own size**, threaded through the `set_nebula_wake` binding → `g_nebula_wake` → the billboard pass, which sizes each billboard per-point instead of by one global constant. The host loop discovers pods each tick and feeds the multi-emitter tracker. The additive billboard shader is unchanged.

**Tech Stack:** Python (tracker + host loop + subsystem helper), C++/OpenGL (the billboard pass + pybind binding), GLSL, GoogleTest (C++ FrameTest), pytest.

## Global Constraints

- **Visual-only / GPU-only.** Never touch the CPU concealment field, physics, or any gameplay state. Reading subsystem state (position/radius/disabled) is read-only.
- **Gated by the Volumetric Nebulae toggle ONLY** (`r.volumetric_nebulae_enabled()`), warp-suppressed (`_warp_streaking`), and only while in a nebula — unchanged from the merged wake. PLUS per-pod gating: a pod that `_is_offline()` (disabled OR destroyed OR ship out-of-action) emits no new trail.
- **Reuse, don't reinvent:** the gate is `engine/appc/subsystems.py:_is_offline(sub)`; the pod walk mirrors `impulse_online_fraction(ies)` in the same file (`ies.GetNumChildSubsystems()` + `ies.GetChildSubsystem(i)`); world mount is `subsystem_world_position(pod, player)`; per-pod size is `pod.GetRadius()`.
- **The billboard pass still mirrors `HullDischargePass`** GL discipline (additive `GL_ONE/GL_ONE`, depth-test on, depth-write off, cull off; restore canonical; zero GL work when empty).
- **Single build tree at `build/`.** Shader/CMake changes ⇒ `cmake -B build -S .` reconfigure; `host_bindings.cc` compiles into both `./build/dauntless` and `_dauntless_host`, so a full `cmake --build build -j` is required.
- **Pre-existing baselines (add 0 new):** ~62 pre-existing pytest failures; 7 pre-existing Scorch/Phaser C++ FrameTest failures. Prove 0 NEW.
- **Per-pod size magnitude is a live-tune unknown:** `pod.GetRadius()` is small in body units (Galaxy impulse `SetRadius(0.25)`). The billboard half-size is `point.size × kWakeSizeScale`; `kWakeSizeScale` is a renderer dial, calibrated live in Task 5. Do not hardcode an assumed GU size.

---

### Task 1: Multi-emitter wake tracker

Rework `NebulaWakeTracker` from a single position history into one ring buffer **per emitter** (pod), keyed by a caller-supplied stable key. Each point carries the emitter's size. An emitter absent from a tick's input (a pod that went offline) keeps its existing points (they fade out) but grows no new ones, and is dropped once empty.

**Files:**
- Modify: `engine/appc/nebula_wake.py`
- Test: `tests/unit/test_nebula_wake.py`

**Interfaces:**
- Consumes: nothing (pure logic).
- Produces:
  - `NebulaWakeTracker.update(in_nebula: bool, emitters: list[dict], game_time: float)` where each emitter is `{"key": hashable, "pos": (x,y,z), "size": float}` (ACTIVE emitters only — the caller filters offline pods).
  - `NebulaWakeTracker.trail_points() -> list[dict]`, each `{"pos": (x,y,z), "strength": float, "size": float}`, flattened across all emitters, strength pre-faded (fade-in × fade-out).
  - `NebulaWakeTracker.reset()`.
  - Module constants `SPACING`, `N` (per emitter), `LIFETIME`, `FRONT_RISE`.

- [ ] **Step 1: Replace the test file with the multi-emitter tests**

Replace the entire contents of `tests/unit/test_nebula_wake.py` with:
```python
from engine.appc.nebula_wake import NebulaWakeTracker, SPACING, N, LIFETIME, FRONT_RISE


def _em(key, x, y=0.0, z=0.0, size=0.25):
    return {"key": key, "pos": (x, y, z), "size": size}


def test_no_points_outside_nebula():
    w = NebulaWakeTracker()
    for i in range(100):
        w.update(False, [_em("a", float(i) * 100.0)], i / 60.0)
    assert w.trail_points() == []


def test_no_points_when_no_emitters():
    w = NebulaWakeTracker()
    for i in range(100):
        w.update(True, [], i / 60.0)
    assert w.trail_points() == []


def test_records_by_distance_not_per_tick():
    w = NebulaWakeTracker()
    t = 0.0
    step = SPACING / 100.0          # cumulative travel stays < SPACING
    for i in range(50):
        t += 1.0 / 60.0
        w.update(True, [_em("a", i * step)], t)
    assert len(w.trail_points()) == 1            # only the initial drop


def test_records_a_new_point_each_spacing():
    w = NebulaWakeTracker()
    t = 0.0
    for i in range(10):
        t += 1.0 / 60.0
        w.update(True, [_em("a", i * SPACING)], t)
    assert len(w.trail_points()) == 10


def test_two_emitters_are_independent():
    w = NebulaWakeTracker()
    t = 0.0
    # Two pods at different offsets, each moving by SPACING per tick.
    for i in range(8):
        t += 1.0 / 60.0
        w.update(True, [_em("port", i * SPACING, y=-1.0, size=0.25),
                        _em("star", i * SPACING, y=+1.0, size=0.40)], t)
    pts = w.trail_points()
    assert len(pts) == 16                          # 8 from each pod
    ys = sorted({round(p["pos"][1], 3) for p in pts})
    assert ys == [-1.0, 1.0]                        # both trails present
    # Each pod's points carry that pod's size.
    assert {p["size"] for p in pts if p["pos"][1] == -1.0} == {0.25}
    assert {p["size"] for p in pts if p["pos"][1] == +1.0} == {0.40}


def test_caps_at_N_per_emitter():
    w = NebulaWakeTracker()
    t = 0.0
    for i in range(N * 3):
        t += 1.0 / 60.0
        w.update(True, [_em("a", i * SPACING)], t)
    assert len(w.trail_points()) <= N


def test_point_carries_emitter_size():
    w = NebulaWakeTracker()
    w.update(True, [_em("a", 0.0, size=0.33)], 0.0)
    w.update(True, [_em("a", SPACING, size=0.33)], 0.1)
    pts = w.trail_points()
    assert pts and all(p["size"] == 0.33 for p in pts)


def test_strength_rises_then_fades_and_expires():
    w = NebulaWakeTracker()
    w.update(True, [_em("a", 0.0)], 0.0)
    born = w.trail_points()
    assert born and born[0]["strength"] == 0.0          # invisible at birth (no pop)
    w.update(True, [_em("a", 0.0)], FRONT_RISE * 0.5)
    rising = w.trail_points()
    assert rising and 0.0 < rising[0]["strength"] < 1.0
    w.update(True, [_em("a", 0.0)], FRONT_RISE)
    peak = w.trail_points()
    assert peak and peak[0]["strength"] > rising[0]["strength"]
    w.update(True, [_em("a", 0.0)], LIFETIME * 0.9)
    late = w.trail_points()
    assert late and late[0]["strength"] < peak[0]["strength"]
    w.update(True, [_em("a", 0.0)], LIFETIME + 0.1)
    assert w.trail_points() == []


def test_offline_emitter_trail_fades_then_drops_others_continue():
    w = NebulaWakeTracker()
    t = 0.0
    # Both pods lay a trail while moving.
    for i in range(5):
        t += 1.0 / 60.0
        w.update(True, [_em("port", i * SPACING, y=-1.0),
                        _em("star", i * SPACING, y=+1.0)], t)
    assert any(p["pos"][1] == -1.0 for p in w.trail_points())
    # "port" goes offline: only "star" is fed now. Port's points must fade out
    # over LIFETIME (not vanish instantly), while star keeps growing.
    start = t
    while t - start < LIFETIME + 0.2:
        t += 1.0 / 60.0
        w.update(True, [_em("star", (t * 60.0) * SPACING, y=+1.0)], t)
    pts = w.trail_points()
    assert pts and all(p["pos"][1] == +1.0 for p in pts)   # port fully faded; star remains


def test_clears_on_leaving_nebula():
    w = NebulaWakeTracker()
    t = 0.0
    for i in range(10):
        t += 1.0 / 60.0
        w.update(True, [_em("a", i * SPACING)], t)
    assert w.trail_points()
    w.update(False, [_em("a", 999.0)], t + 0.1)
    assert w.trail_points() == []


def test_reset_clears():
    w = NebulaWakeTracker()
    t = 0.0
    for i in range(10):
        t += 1.0 / 60.0
        w.update(True, [_em("a", i * SPACING)], t)
    w.reset()
    assert w.trail_points() == []


def test_deterministic():
    a = NebulaWakeTracker()
    b = NebulaWakeTracker()
    t = 0.0
    for i in range(60):
        t += 1.0 / 60.0
        ems = [_em("p", i * 0.5, y=-1.0), _em("s", i * 0.5, y=1.0)]
        a.update(True, ems, t)
        b.update(True, ems, t)
    assert a.trail_points() == b.trail_points()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_nebula_wake.py -q`
Expected: FAIL — `update()` takes the old `(in_nebula, pos, game_time)` signature / `size` not in output.

- [ ] **Step 3: Rewrite the tracker as multi-emitter**

Replace the entire contents of `engine/appc/nebula_wake.py` with:
```python
"""Nebula ship wake — multi-emitter trail tracker.

One ring buffer PER emitter (impulse-engine pod), keyed by a caller-supplied
stable key. Each point records the pod's world position, birth time, and size.
Strength fades IN over FRONT_RISE (no pop) then OUT to 0 over LIFETIME. A pod
absent from a tick's input (went offline) keeps its existing points — they fade
out — but grows no new ones, and is dropped once empty. Pure logic, no GL,
deterministic from the emitter inputs (no RNG). The renderer draws each point
as an additive billboard sized by point["size"] × a renderer dial.
"""

SPACING = 1.0       # GU a pod must move before a new trail point is laid;
                    # fine spacing = many small puffs, small/fast per-birth steps
N = 120             # max trail points PER EMITTER; bounds trail length + draw cost
LIFETIME = 12.0     # seconds a point lives; at impulse this sets the trail length
FRONT_RISE = 0.5    # seconds the newest point fades IN over (kills the pop/strobe)


class _Point:
    __slots__ = ("pos", "born", "size")

    def __init__(self, pos, born, size):
        self.pos = pos
        self.born = born
        self.size = size


class _Emitter:
    __slots__ = ("points", "last")

    def __init__(self):
        self.points = []      # oldest first
        self.last = None      # last recorded position for this emitter


def _dist2(a, b):
    dx, dy, dz = a[0] - b[0], a[1] - b[1], a[2] - b[2]
    return dx * dx + dy * dy + dz * dz


class NebulaWakeTracker:
    def __init__(self):
        self._emitters = {}    # key -> _Emitter
        self._out = []

    def reset(self):
        self._emitters = {}
        self._out = []

    def update(self, in_nebula, emitters, game_time):
        """emitters: list of {"key", "pos":(x,y,z), "size":float} — ACTIVE pods
        only (the caller filters offline ones)."""
        if not in_nebula:
            if self._emitters or self._out:
                self._emitters = {}
                self._out = []
            return

        # Record by distance for each active emitter.
        active_keys = set()
        for em in emitters:
            key = em["key"]
            pos = em["pos"]
            size = em["size"]
            active_keys.add(key)
            st = self._emitters.get(key)
            if st is None:
                st = _Emitter()
                self._emitters[key] = st
            if st.last is None or _dist2(pos, st.last) >= SPACING * SPACING:
                st.points.append(_Point((pos[0], pos[1], pos[2]), game_time, size))
                st.last = (pos[0], pos[1], pos[2])
                if len(st.points) > N:
                    st.points = st.points[-N:]

        # Expire + build the flattened output. Inactive emitters (not fed this
        # tick) keep fading; drop them once empty.
        out = []
        dead = []
        for key, st in self._emitters.items():
            alive = []
            for p in st.points:
                age = game_time - p.born
                if age < 0.0 or age >= LIFETIME:
                    continue
                alive.append(p)
                fade = 1.0 - age / LIFETIME             # 1 -> 0 over the lifetime
                rise = age / FRONT_RISE if age < FRONT_RISE else 1.0  # 0 -> 1 ease-in
                out.append({"pos": p.pos, "strength": fade * rise, "size": p.size})
            st.points = alive
            if not alive and key not in active_keys:
                dead.append(key)
        for key in dead:
            del self._emitters[key]

        self._out = out

    def trail_points(self):
        return self._out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_nebula_wake.py -q`
Expected: all pass (11 tests).

> **Note:** `engine/host_loop.py` still calls the OLD `update(in_nebula, pos, game_time)` signature. That call lives inside the per-frame sim function, so `import engine.host_loop` and the wider pytest suite stay green (the wake path isn't exercised in tests). Task 4 updates the call. Do not touch host_loop in this task.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/nebula_wake.py tests/unit/test_nebula_wake.py
git commit -m "feat(nebula-wake): multi-emitter tracker (one trail per pod, sized)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `active_impulse_emitters` discovery helper

A pure helper that turns the player ship into the list of active wake emitters — one per online impulse pod, at its world mount, sized by its radius — reusing the existing `_is_offline` gate and child-walk.

**Files:**
- Modify: `engine/appc/subsystems.py` (add the helper next to `impulse_online_fraction`)
- Test: `tests/unit/test_impulse_emitters.py` (new)

**Interfaces:**
- Consumes: `_is_offline(sub)`, `subsystem_world_position(pod, ship)` (same file); `player.GetImpulseEngineSubsystem()`, `ies.GetNumChildSubsystems()`, `ies.GetChildSubsystem(i)`, `pod.GetRadius()`.
- Produces: `active_impulse_emitters(player) -> list[dict]`, each `{"key": int, "pos": (x,y,z), "size": float}`. Empty when no player / no impulse subsystem / impulse offline. Falls back to ONE emitter at the master impulse mount when the ship models impulse with no child pods.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_impulse_emitters.py`:
```python
from engine.appc.subsystems import active_impulse_emitters, ShipSubsystem
from engine.appc.math import TGPoint3


class _Ship:
    def __init__(self, ies):
        self._ies = ies
        self._loc = TGPoint3(10.0, 20.0, 30.0)

    def GetImpulseEngineSubsystem(self):
        return self._ies

    def GetWorldLocation(self):
        return self._loc

    def GetWorldRotation(self):
        return None        # identity: world mount == ship_loc + local offset


def _pod(name, x, y, z, radius, disabled=False, destroyed=False):
    s = ShipSubsystem(name)
    s._radius = radius
    s._position = TGPoint3(x, y, z)
    s._disabled = disabled
    s._destroyed = destroyed
    return s


def _make_ies(pods, disabled=False):
    ies = ShipSubsystem("Impulse Engines")
    ies._disabled = disabled
    ies._position = TGPoint3(0.0, -0.98, -0.45)
    ies._radius = 0.25
    for p in pods:
        ies.AddChildSubsystem(p)
    return ies


def test_no_player_returns_empty():
    assert active_impulse_emitters(None) == []


def test_no_impulse_subsystem_returns_empty():
    class _S:
        def GetImpulseEngineSubsystem(self):
            return None
    assert active_impulse_emitters(_S()) == []


def test_offline_master_returns_empty():
    ies = _make_ies([_pod("Port", -1.0, 0.0, 0.0, 0.25)], disabled=True)
    assert active_impulse_emitters(_Ship(ies)) == []


def test_two_online_pods_yield_two_emitters():
    pods = [_pod("Port", -1.0, 0.0, 0.0, 0.25),
            _pod("Star", +1.0, 0.0, 0.0, 0.40)]
    ems = active_impulse_emitters(_Ship(_make_ies(pods)))
    assert len(ems) == 2
    sizes = sorted(e["size"] for e in ems)
    assert sizes == [0.25, 0.40]
    assert len({e["key"] for e in ems}) == 2            # distinct keys
    # world mount = ship_loc + local (identity rotation)
    port = next(e for e in ems if e["size"] == 0.25)
    assert port["pos"] == (10.0 - 1.0, 20.0, 30.0)


def test_offline_pod_is_skipped():
    pods = [_pod("Port", -1.0, 0.0, 0.0, 0.25, disabled=True),
            _pod("Star", +1.0, 0.0, 0.0, 0.40)]
    ems = active_impulse_emitters(_Ship(_make_ies(pods)))
    assert len(ems) == 1
    assert ems[0]["size"] == 0.40


def test_destroyed_pod_is_skipped():
    pods = [_pod("Port", -1.0, 0.0, 0.0, 0.25, destroyed=True),
            _pod("Star", +1.0, 0.0, 0.0, 0.40)]
    ems = active_impulse_emitters(_Ship(_make_ies(pods)))
    assert [e["size"] for e in ems] == [0.40]


def test_no_child_pods_falls_back_to_master():
    ies = _make_ies([])                                  # online master, no pods
    ems = active_impulse_emitters(_Ship(ies))
    assert len(ems) == 1
    assert ems[0]["pos"] == (10.0 + 0.0, 20.0 - 0.98, 30.0 - 0.45)
    assert ems[0]["size"] == 0.25
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_impulse_emitters.py -q`
Expected: FAIL — `active_impulse_emitters` not defined.

> **Before implementing, confirm the `ShipSubsystem` test scaffold matches the real shim.** Read `engine/appc/subsystems.py` for the attribute names the stub uses for disabled/destroyed (`IsDisabled()`/`IsDestroyed()` read which fields?) and for `AddChildSubsystem`. The test above assumes `_disabled`/`_destroyed` back `IsDisabled()`/`IsDestroyed()` and that `AddChildSubsystem` appends to `_children`. If the real field names differ, adjust the TEST scaffold (not the production gate) to set the fields `IsDisabled()`/`IsDestroyed()` actually read.

- [ ] **Step 3: Implement the helper**

In `engine/appc/subsystems.py`, immediately after the `impulse_online_fraction` function, add:
```python
def active_impulse_emitters(player) -> list:
    """Active impulse-engine pods as wake emitters.

    Returns ``[{"key": int, "pos": (x, y, z), "size": float}]`` — one entry per
    ONLINE pod (not ``_is_offline``), positioned at its world mount and sized by
    its radius. Empty when there is no player, no impulse subsystem, or the
    master impulse subsystem is offline. When the master is online but exposes
    no child pods, falls back to a single emitter at the master's own mount so
    such ships still trail a wake. Read-only; safe to call every frame.
    """
    if player is None or not hasattr(player, "GetImpulseEngineSubsystem"):
        return []
    ies = player.GetImpulseEngineSubsystem()
    if ies is None or _is_offline(ies):
        return []

    emitters = []
    n = ies.GetNumChildSubsystems() if hasattr(ies, "GetNumChildSubsystems") else 0
    for i in range(n):
        pod = ies.GetChildSubsystem(i)
        if pod is None or _is_offline(pod):
            continue
        wp = subsystem_world_position(pod, player)
        radius = float(pod.GetRadius()) if hasattr(pod, "GetRadius") else 0.0
        emitters.append({"key": id(pod), "pos": (wp.x, wp.y, wp.z), "size": radius})

    if not emitters:
        # No discoverable online pods — fall back to the master mount so the
        # ship still trails a single wake while impulse is online.
        wp = subsystem_world_position(ies, player)
        radius = float(ies.GetRadius()) if hasattr(ies, "GetRadius") else 0.0
        emitters.append({"key": id(ies), "pos": (wp.x, wp.y, wp.z), "size": radius})
    return emitters
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_impulse_emitters.py -q`
Expected: all pass (7 tests).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/subsystems.py tests/unit/test_impulse_emitters.py
git commit -m "feat(nebula-wake): active_impulse_emitters pod discovery helper

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Per-point size through the renderer data path

Give each wake point its own size. `g_nebula_wake` becomes a struct vector `{pos, strength, size}`; the `set_nebula_wake` binding reads a `size` field; the billboard pass sizes each billboard `point.size × kWakeSizeScale` (a new dial) instead of the global `kWakeSize`.

**Files:**
- Modify: `native/src/renderer/include/renderer/nebula_wake_pass.h` (point struct + render() signature)
- Modify: `native/src/renderer/nebula_wake_pass.cc` (per-point size + `kWakeSizeScale`)
- Modify: `native/src/host/host_bindings.cc` (`g_nebula_wake` type + `set_nebula_wake` binding + the render call)
- Modify: `engine/renderer.py` (docstring for the new point shape)
- Test: `native/tests/renderer/frame_test.cc` (`NebulaWakeAdditiveTrail` — new point type)

**Interfaces:**
- Consumes: the host feed (Task 4) sends `[{"pos":(x,y,z), "strength":float, "size":float}]`.
- Produces:
  - `struct renderer::NebulaWakePoint { glm::vec3 pos; float strength; float size; };`
  - `NebulaWakePass::render(const scenegraph::Camera&, Pipeline&, const std::vector<NebulaWakePoint>& wake, float time_s)`.
  - `g_nebula_wake` is `std::vector<renderer::NebulaWakePoint>`.

- [ ] **Step 1: Add the point struct + update the pass signature (header)**

In `native/src/renderer/include/renderer/nebula_wake_pass.h`, add the struct above the class (after the `namespace renderer {` open) and change the `wake` parameter type:
```cpp
/// One wake trail point: world position, age-faded strength (0..1), and the
/// emitting pod's size (radius). The billboard half-size is size × a dial.
struct NebulaWakePoint {
    glm::vec3 pos{0.0f};
    float     strength = 0.0f;
    float     size     = 0.0f;
};
```
Change the `render` declaration's wake parameter from `const std::vector<glm::vec4>& wake` to `const std::vector<NebulaWakePoint>& wake` (keep `float time_s` last).

- [ ] **Step 2: Update the pass implementation for per-point size**

In `native/src/renderer/nebula_wake_pass.cc`:
1. Replace the `kWakeSize` constant with a scale dial:
```cpp
constexpr float kWakeSizeScale = 24.0f;              // billboard half-size = point.size × this
                                                     // (pod radius is small; tune live)
```
   (Keep `kWakeGlow`, `kWakeSoft`, `kWakeColor` as-is.)
2. Change the `render` signature's wake type to `const std::vector<NebulaWakePoint>& wake`.
3. In the per-point loop, replace the body with per-point size:
```cpp
    for (const auto& p : wake) {
        if (p.strength <= 0.0f) continue;        // skip just-born (faded-in) points
        shader.set_vec3 ("u_center",   p.pos);
        shader.set_float("u_size",     p.size * kWakeSizeScale);
        shader.set_float("u_strength", p.strength);
        glDrawArrays(GL_TRIANGLES, 0, 6);
    }
```

- [ ] **Step 3: Update the host binding + global + render call**

In `native/src/host/host_bindings.cc`:
1. Change the global (around line 166):
```cpp
std::vector<renderer::NebulaWakePoint> g_nebula_wake;   // world pos, faded strength, pod size
```
2. Replace the `set_nebula_wake` binding body to read the `size` field:
```cpp
    m.def("set_nebula_wake",
          [](const std::vector<py::dict>& pts) {
              g_nebula_wake.clear();
              g_nebula_wake.reserve(pts.size());
              for (const auto& d : pts) {
                  auto p = d["pos"].cast<std::tuple<float,float,float>>();
                  renderer::NebulaWakePoint wp;
                  wp.pos      = glm::vec3(std::get<0>(p), std::get<1>(p), std::get<2>(p));
                  wp.strength = d["strength"].cast<float>();
                  wp.size     = d["size"].cast<float>();
                  g_nebula_wake.push_back(wp);
              }
          },
          py::arg("points"), "Set the player's nebula wake trail points (pos, strength, size).");
```
   (The `g_nebula_wake.clear()` calls in init/shutdown and the gated render call at ~line 630 need no change — `g_nebula_wake` is still the same variable name, now a different element type; the render call already passes `g_nebula_wake`.)

- [ ] **Step 4: Update the renderer.py docstring**

In `engine/renderer.py`, update the `set_nebula_wake` wrapper docstring to the new point shape:
```python
def set_nebula_wake(points: list) -> None:
    """Player nebula wake trail points for the additive billboard pass.
    Each: {"pos": (x,y,z), "strength": float, "size": float}. Empty = no wake."""
    _h.set_nebula_wake(points)
```
(If the wrapper body differs, change only the docstring; keep the call.)

- [ ] **Step 5: Update the FrameTest to the new point type**

In `native/tests/renderer/frame_test.cc`, the `NebulaWakeAdditiveTrail` test builds `std::vector<glm::vec4>` wake points. Change it to `std::vector<renderer::NebulaWakePoint>`, constructing each with `{pos, strength, size}`. For the brightening case use one point `{glm::vec3(0,0,0), 1.0f, <size that subtends visibly>}` — pick the size so `size × kWakeSizeScale` matches the visible half-size the old test used (the old test used `kWakeSize = 6` effectively, so `size = 6.0f / 24.0f = 0.25f`). The empty-list byte-identity case is unchanged in intent (empty `std::vector<NebulaWakePoint>{}` → memcmp-identical to not invoking the pass). Read the current test to adapt the exact construction; do not weaken either assertion.

- [ ] **Step 6: Reconfigure + build**

Run: `cmake -B build -S . && cmake --build build -j 2>&1 | tail -3`
Expected: `Built target dauntless` + `_dauntless_host` + `renderer_tests`, no errors.

- [ ] **Step 7: Run the FrameTest — passes, 0 new failures**

Run:
```bash
ctest --test-dir build -R "NebulaWakeAdditiveTrail" -V 2>&1 | tail -12
ctest --test-dir build -R "FrameTest" 2>&1 | tail -6
```
Expected: `NebulaWakeAdditiveTrail` passes; only the 7 pre-existing Scorch/Phaser failures remain (0 new).

- [ ] **Step 8: Commit**

```bash
git add native/src/renderer/include/renderer/nebula_wake_pass.h \
        native/src/renderer/nebula_wake_pass.cc \
        native/src/host/host_bindings.cc \
        engine/renderer.py \
        native/tests/renderer/frame_test.cc
git commit -m "feat(nebula-wake): per-point billboard size through the data path

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Host-loop integration — discover pods + feed the multi-emitter tracker

Replace the single ship-centroid feed with per-pod emitter discovery.

**Files:**
- Modify: `engine/host_loop.py`

**Interfaces:**
- Consumes: `active_impulse_emitters(player)` (Task 2); `NebulaWakeTracker.update(in_nebula, emitters, game_time)` + `trail_points()` (Task 1); `r.set_nebula_wake(points)` (Task 3); the existing `in_neb`/`player`/`_gt` locals + `r.volumetric_nebulae_enabled()` + `_warp_streaking`.
- Produces: per-frame per-engine wake feed; reset on swap (unchanged).

- [ ] **Step 1: Update the wake tick to feed per-pod emitters**

In `engine/host_loop.py`, the wake tick block currently reads (around lines 4420-4429):
```python
                    global _nebula_wake
                    if r.volumetric_nebulae_enabled():
                        if _nebula_wake is None:
                            from engine.appc.nebula_wake import NebulaWakeTracker
                            _nebula_wake = NebulaWakeTracker()
                        _wpos = None
                        if in_neb and player is not None:
                            _loc = player.GetWorldLocation()
                            _wpos = (_loc.x, _loc.y, _loc.z)
                        _nebula_wake.update(in_neb, _wpos, _gt)
```
Replace the `_wpos` computation and the `update` call with per-pod emitter discovery:
```python
                    global _nebula_wake
                    if r.volumetric_nebulae_enabled():
                        if _nebula_wake is None:
                            from engine.appc.nebula_wake import NebulaWakeTracker
                            _nebula_wake = NebulaWakeTracker()
                        _emitters = []
                        if in_neb and player is not None:
                            from engine.appc.subsystems import active_impulse_emitters
                            _emitters = active_impulse_emitters(player)
                        _nebula_wake.update(in_neb, _emitters, _gt)
```
(Match the real indentation. The `import` is lazy inside the tick, mirroring the sibling drivers. The per-frame feed block near line 4825 — `r.set_nebula_wake(_nebula_wake.trail_points())` — needs NO change: `trail_points()` now returns sized points and the binding consumes them.)

- [ ] **Step 2: Verify the wake feed sends sized points (read the feed block)**

Read the feed block (around line 4822-4825) and confirm it calls `r.set_nebula_wake(_nebula_wake.trail_points())` gated by `r.volumetric_nebulae_enabled() and not _warp_streaking`. No code change expected — just confirm the contract holds (sized dicts flow straight through). Note in the report if the feed needs any adjustment.

- [ ] **Step 3: Verify imports + no regressions**

Run:
```bash
uv run python -c "import engine.host_loop"
uv run pytest tests/unit/test_nebula_wake.py tests/unit/test_impulse_emitters.py tests/unit/test_nebula.py -q
```
Expected: clean import; all listed tests pass.

- [ ] **Step 4: Full suite — 0 new failures**

Capture the pre-existing baseline first (e.g. `git stash` the change, run `bash scripts/run_tests.sh`, save the failing-test set, restore), then run again with the change and diff the failure sets. Expected: 0 NEW failures vs the ~62 pre-existing baseline. The suite is memory-sensitive — use `bash scripts/run_tests.sh` (the watchdog-capped runner).

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py
git commit -m "feat(nebula-wake): drive per-engine wake trails from the host loop

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Live verification + tuning (human-gated)

Hand off to Mark to fly a nebula and tune. The key new dial is `kWakeSizeScale` (maps pod radius → billboard GU), unknown until seen live.

**Files (tuning only):**
- `native/src/renderer/nebula_wake_pass.cc` — `kWakeSizeScale`, `kWakeGlow`, `kWakeSoft`, `kWakeColor` (rebuild `cmake --build build -j`).
- `engine/appc/nebula_wake.py` — `SPACING`, `N`, `LIFETIME`, `FRONT_RISE` (relaunch).

- [ ] **Step 1: Build is current**

```bash
cmake --build build -j 2>&1 | grep -E "Built target dauntless|error:"
./build/dauntless
```

- [ ] **Step 2: Live checklist (Mark)**

Fly into a nebula (Volumetric Nebulae on) and confirm:
- A separate luminous trail streams off **each** impulse engine, scaled to that engine (small, fine), not one fat ship-sized trail.
- Trails are smooth/continual (no strobe), correct brightness (tune `kWakeSizeScale`/`kWakeGlow`).
- **Disable or destroy an engine** (combat / dev cheat) → that engine's trail stops and fades while the others keep going.
- Volumetric Nebulae off → wake gone; warp → no streak; framerate holds.

- [ ] **Step 3: Tune**

`kWakeSizeScale` is the headline dial (pod radius → GU). If trails are too thin, raise it; too fat, lower it. `kWakeGlow` for brightness (additive stacking — keep low). `SPACING`/`N`/`LIFETIME` for trail density/length (Python; relaunch). If you lower `SPACING` further, the tracker test derives its sub-SPACING step from `SPACING`, so it stays valid.

- [ ] **Step 4: Record chosen dials + mark the feature done**

Commit tuned constants; update `docs/superpowers/specs/2026-06-24-nebula-wake-design.md` (note the per-engine evolution) and the `project_nebula_pockets` memory.

---

## Self-Review

**Spec coverage:** "one trail per impulse engine" → Task 1 (multi-emitter tracker) + Task 2 (`active_impulse_emitters`) + Task 4 (host feed). "scaled to the size of the impulse engine" → Task 2 emits `size = pod.GetRadius()`, Task 3 threads per-point size to the billboard (`size × kWakeSizeScale`). "gate to only impulse engines which are not disabled or destroyed" → Task 2 skips `_is_offline(pod)` (disabled OR destroyed OR ship out-of-action); a pod going offline stops emitting and its trail fades (Task 1's inactive-emitter handling). Visual-only/GPU-only and the Volumetric/warp gating are preserved (Task 4 leaves them unchanged).

**Placeholder scan:** Task 2 Step 2 and Task 3 Step 5 intentionally instruct "read the real shim field names / the current FrameTest and adapt the test scaffold" rather than inventing exact lines that depend on code the implementer must read — the production code and the test intent are fully pinned; only the test scaffolding adapts to existing names. All production steps carry complete code.

**Type consistency:** the emitter dict shape `{"key","pos","size"}` is produced by `active_impulse_emitters` (Task 2) and consumed by `NebulaWakeTracker.update` (Task 1); the point dict shape `{"pos","strength","size"}` is produced by `trail_points()` (Task 1) and consumed by `set_nebula_wake` (Task 3) → `NebulaWakePoint{pos,strength,size}` → the pass loop. `render(..., const std::vector<NebulaWakePoint>& wake, float time_s)`, the `g_nebula_wake` element type, and the FrameTest construction all use `NebulaWakePoint` consistently. Module constants `SPACING`/`N`/`LIFETIME`/`FRONT_RISE` are imported by both the tracker and its tests.
