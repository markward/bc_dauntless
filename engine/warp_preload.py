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
    def _enqueue_ships(self):
        for sh in self._ships(self._dest):
            key = ("ship", id(sh))
            if key in self._seen:
                continue
            self._seen.add(key)
            try:
                label = str(sh.GetName())
            except Exception:
                label = repr(sh)
            self._queue.append(["ship", key, "ship " + label, sh])

    def _start(self):
        self._started = True
        for m in self._planet_models(self._dest):
            key = ("planet", m)
            if key not in self._seen:
                self._seen.add(key)
                self._queue.append(["planet", key, "planet " + str(m), m])
        self._enqueue_ships()
        if self._haze_enabled():
            self._profile = system_haze.profile_dict_for_set(self._dest)
        if self._profile is not None:
            self._r.system_nebula_prebuild(self._profile)
        if self._atlases:
            self._r.far_prefetch_atlases()
            self._atlas_pending = 1  # unknown until the first pump

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
            self._atlas_pending = self._r.far_pump_atlas_uploads(2)

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
