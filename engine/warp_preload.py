"""Destination preload spread over the warp tunnel.

One ``Preload`` owns a single warp's destination work: it kicks the async
work (haze table prebuild, rock atlas prefetch) on the first step, then does
at most ONE GL model load per tunnel frame through injected loaders, so no
single frame pays for the whole destination.  All collaborators are injected
(the renderer included) so this module stays pure Python.
"""
from engine import dev_mode, system_haze


class Preload:
    def __init__(self, dest_set_name, *, renderer, haze_enabled, planet_models,
                 load_planet, ships, load_ship, atlases=True):
        self._dest = dest_set_name
        self._r = renderer
        self._haze_enabled = haze_enabled
        self._planet_models = planet_models
        self._load_planet = load_planet
        self._ships = ships
        self._load_ship = load_ship
        self._atlases = atlases
        self._started = False
        self._profile = None
        self._atlas_pending = 0
        self._queue = []        # [kind, key, label, payload] still to load
        self._seen = set()      # keys ever queued (done work is kept)

    # -- planning ---------------------------------------------------------
    # Every planning section is guarded on its own: one raising (a bad map
    # entry, a broken set) must never drop another -- above all the haze
    # prebuild, whose miss is a multi-second main-thread build on arrival.
    def _enqueue_ships(self):
        try:
            ships = list(self._ships(self._dest))
        except Exception as exc:
            dev_mode.log_swallowed("warp_preload ships", exc)
            return
        for sh in ships:
            # Keyed on the ship itself (ships are hashable): an id() is only
            # unique among live objects, so a recycled one could skip a ship.
            key = ("ship", sh)
            if key in self._seen:
                continue
            self._seen.add(key)
            try:
                label = str(sh.GetName())
            except Exception:
                label = repr(sh)
            self._queue.append(["ship", key, "ship " + label, sh])

    def _enqueue_planets(self):
        try:
            models = list(self._planet_models(self._dest))
        except Exception as exc:
            dev_mode.log_swallowed("warp_preload planets", exc)
            return
        for m in models:
            key = ("planet", m)
            if key not in self._seen:
                self._seen.add(key)
                self._queue.append(["planet", key, "planet " + str(m), m])

    def _kick_haze(self):
        try:
            if self._haze_enabled():
                profile = system_haze.profile_dict_for_set(self._dest)
                if profile is not None:
                    self._r.system_nebula_prebuild(profile)
                    self._profile = profile   # awaited only once kicked
        except Exception as exc:
            dev_mode.log_swallowed("warp_preload haze", exc)

    def _kick_atlases(self):
        if not self._atlases:
            return
        try:
            self._r.far_prefetch_atlases()
            self._atlas_pending = 1  # unknown until the first pump
        except Exception as exc:
            dev_mode.log_swallowed("warp_preload atlases", exc)
            self._atlases = False    # fail open: arrival takes the lazy path

    def _start(self):
        self._started = True
        self._enqueue_planets()
        self._enqueue_ships()
        self._kick_haze()
        self._kick_atlases()

    # -- per-frame --------------------------------------------------------
    def step(self):
        if not self._started:
            self._start()
        if self._queue:
            kind, _key, label, payload = self._queue.pop(0)
            try:
                if kind == "planet":
                    self._load_planet(payload)
                else:
                    self._load_ship(payload)
            except Exception as exc:  # counted as done; never blocks the warp
                dev_mode.log_swallowed("warp_preload " + label, exc)
        if self._atlases:
            try:
                self._atlas_pending = self._r.far_pump_atlas_uploads(2)
            except Exception as exc:  # fail open: never blocks the warp
                dev_mode.log_swallowed("warp_preload atlas pump", exc)
                self._atlas_pending = 0

    def replan(self):
        if self._started:
            self._enqueue_ships()

    def _haze_done(self):
        if self._profile is None:
            return True
        return bool(self._r.system_nebula_prebuilt(self._profile))

    def ready(self):
        if not self._started:
            return False
        if self._queue:
            return False
        if self._atlases and self._atlas_pending:
            return False
        return self._haze_done()

    def pending(self):
        out = [item[2] for item in self._queue]
        if self._atlases and self._atlas_pending:
            out.append("rock atlases")
        if self._started and not self._haze_done():
            out.append("system haze")
        return out


_active = None


def begin(dest_set_name, **deps):
    global _active
    _active = Preload(dest_set_name, **deps)
    return _active


def active():
    return _active


def end():
    global _active
    _active = None
