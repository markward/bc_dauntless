"""RockClass: a BC asteroid as a lean body, not a ship.

Spec: docs/superpowers/specs/2026-09-30-rock-class-design.md.

A RockClass IS a ShipClass (missions ShipClass_Cast rocks: E1M2.py:1257/1314,
E2M1.py:649/1079), but the AI, motion and subsystem loops skip it
(ship_iter.iter_non_rock_ships). A ship becomes a rock when its properties
land with genus GENUS_ASTEROID -- ShipClass_Create only ever sees a name.
"""
import engine.dev_mode as dev_mode
from engine.appc.objects import PhysicsObjectClass
from engine.appc.ships import ShipClass


class RockClass(ShipClass):
    """No __slots__, no __init__: instances are made by reassigning the
    __class__ of a live ShipClass, so the layout must stay identical."""

    def _become_rock(self) -> None:
        d = self.__dict__
        d.setdefault("_model_override", None)
        d.setdefault("_rock_family", "silicate")
        d.setdefault("_angular_space", PhysicsObjectClass.DIRECTION_WORLD_SPACE)
        d.setdefault("_rock_generation", 0)
        self._ai = None
        # Spec §1: "Shield maxima are zeroed so shields_block is false" --
        # unconditionally, whatever the hardpoint authored. Stock asteroid
        # hardpoints already declare every face at MaxShields 0, but a
        # genus-3 hardpoint is not guaranteed to (a modded rock could reuse
        # a shielded template), so zero every face here rather than trust
        # the source. Idempotent: re-zeroing an already-zero face is a
        # no-op. GetShields() is None until a hardpoint declares a
        # ShieldProperty at all (SetupProperties Pass 3 scrubs the
        # default-constructed slot when none was claimed).
        shields = self.GetShields()
        if shields is not None:
            for face in range(shields.NUM_SHIELDS):
                shields.SetMaxShields(face, 0.0)
                shields.SetCurrentShields(face, 0.0)

    def SetAngularVelocity(self, v, space=PhysicsObjectClass.DIRECTION_WORLD_SPACE) -> None:
        super().SetAngularVelocity(v, space)
        self._angular_space = int(space)

    def SetAI(self, ai, *_extra) -> None:
        if ai is not None:
            dev_mode.log_swallowed(
                "SetAI on a rock ignored",
                RuntimeError(str(self.GetName())))

    def ClearAI(self, *_extra) -> None:
        self._ai = None


def is_rock(obj) -> bool:
    return isinstance(obj, RockClass)


def effective_radius(rock) -> float:
    """The rock's real size in GU: base x GetScale(). Base is GetRadius()
    when set, else the hull subsystem's radius -- headless a hardpoint rock's
    GetRadius is 0 (HullProperty.SetRadius sets only the hull), and live the
    host sets GetRadius from the mesh extent without SetScale. E1M2 scales
    its rocks 3.7-8.5x, so reading GetRadius alone plans them at ~0.8 GU."""
    base = float(rock.GetRadius())
    if base <= 0.0:
        hull = rock.GetHull()
        base = float(hull.GetRadius()) if hull is not None else 0.0
    return base * float(rock.GetScale())


def maybe_become_rock(ship) -> bool:
    """Switch `ship` to RockClass if its genus says asteroid. Idempotent."""
    import App
    if isinstance(ship, RockClass):
        ship._become_rock()
        return True
    if type(ship) is not ShipClass:
        return False          # a ShipClass subclass we don't own: leave it
    try:
        genus = int(ship.GetGenus())
    except Exception:
        return False
    if genus != App.GENUS_ASTEROID:
        return False
    ship.__class__ = RockClass
    ship._become_rock()
    return True


# ── Script-less rocks (spec §1 "Other constructors", "Hull and mass") ──

_STOCK_ASTEROID_NIFS = (
    "asteroid.nif", "asteroid1.nif", "asteroid2.nif", "asteroid3.nif",
    "asteroidh1.nif", "asteroidh2.nif", "asteroidh3.nif")

# Stock hardpoint radius (GU) per stock mesh: ships/Hardpoints/asteroid*.py
# `Asteroid.SetRadius(...)`.
_STOCK_RADIUS_GU = {
    "asteroid.nif": 0.8,
    "asteroid1.nif": 0.24,
    "asteroid2.nif": 0.744,
    "asteroid3.nif": 5.0,
    # Every ships/Asteroid*.py registers its LOD as "Asteroid" (first
    # LoadModel wins), so DamageableObject_Create("Asteroid") can resolve to
    # an h-variant mesh once Asteroidh1-3 has loaded.
    "asteroidh1.nif": 0.24,
    "asteroidh2.nif": 0.744,
    "asteroidh3.nif": 5.0,
}


def _stock_radius_gu(base: str) -> float:
    return _STOCK_RADIUS_GU[base]


def _catalogue_model(seed: str, kind: str, family: str, index=None):
    """(catalogue Rock or None, family actually used). `index` forces that
    catalogue entry (rock promotion: the generator's exact rock); an index
    out of range falls back to the seeded pick. Works with the catalogue
    toggle off: that toggle only governs redirecting stock NIFs."""
    from engine.rocks import catalogue
    if index is not None:
        rocks = catalogue.load()
        if 0 <= int(index) < len(rocks):
            r = rocks[int(index)]
            return r, getattr(r, "family", family)
    rock = catalogue.pick(seed, kind=kind, family=family)
    if rock is None:
        rock = catalogue.pick(seed, kind=kind, family="silicate")
        family = "silicate"
    if rock is None:
        return None, family
    return rock, family


def _install_hull(ship, max_hp: float, radius_gu: float) -> None:
    from engine.appc.subsystems import HullSubsystem
    hull = HullSubsystem("Hull")
    hull.SetMaxCondition(float(max_hp))
    hull.SetCondition(float(max_hp))
    hull.SetCritical(1)
    hull.SetTargetable(1)
    hull.SetPrimary(1)
    hull.SetRadius(float(radius_gu))
    ship._hull = hull


def _install_ship_property(ship) -> None:
    """Every BC ShipClass has a ShipProperty, and the SDK dereferences it
    unguarded (ScienceCharacterHandlers.AnnounceHull, Effects.
    GetDeathExplosionSound, HelmMenuHandlers, ShieldsDisplay). A script-less
    rock gets one shaped like the stock asteroid template
    (ships/Hardpoints/asteroid.py "Asteroid Mass"), carrying this rock's own
    values so a later SetupProperties copy is a no-op."""
    from engine.appc.properties import ShipProperty_Create
    prop = ShipProperty_Create("Asteroid Mass")
    prop.SetGenus(ship.GetGenus())
    prop.SetSpecies(ship.GetSpecies())
    prop.SetMass(ship.GetMass())
    prop.SetShipName("Asteroid")
    prop.SetAffiliation(0)
    prop.SetStationary(0)
    prop.SetDeathExplosionSound("g_lsDeathExplosions")
    ship.GetPropertySet().AddToSet("Scene Root", prop)


def RockClass_Create(radius_gu, *, family="silicate", seed="", name="",
                     kind="fragment", hull=None, mass=None, catalogue_index=None,
                     exact_radius=False):
    """A rock with no ship script: stats from its size (engine.rocks.stats)
    unless the caller passes them, model from the rock catalogue.

    catalogue_index: int or None. If set, use catalogue.load()[catalogue_index]
        as the model (its family becomes _rock_family), bypassing catalogue.pick.
        Out of range falls back to the normal pick.
    exact_radius: bool. If True, the model still loads at r_q = stats.quantise_radius(radius_gu)
        (shared models), and the rock is given SetScale(radius_gu / r_q), so
        effective_radius(rock) == radius_gu (within 1e-9). Default False keeps
        today's behaviour byte-identical."""
    import App
    from engine.appc.ships import ShipClass_Create
    from engine.rocks import stats
    ship = ShipClass_Create(name)
    ship.__class__ = RockClass
    ship._become_rock()
    ship.SetGenus(App.GENUS_ASTEROID)
    ship.SetSpecies(App.SPECIES_ASTEROID)
    # Rendered, collided and damage-volume sizes share the quantised radius;
    # hull and mass use the exact one.
    r_q = stats.quantise_radius(radius_gu)
    ship.SetRadius(r_q)
    _install_hull(ship, stats.size_hull(radius_gu) if hull is None else hull,
                  r_q)
    ship.SetMass(stats.size_mass(radius_gu) if mass is None else float(mass))
    _install_ship_property(ship)
    rock, fam = _catalogue_model(seed or name, kind, family, index=catalogue_index)
    ship._rock_family = fam
    ship._model_override = (
        (str(rock.lod_paths[0]), _render_load_scale(r_q, rock))
        if rock is not None else None)
    if exact_radius and r_q > 0.0:
        # Rock promotion: models are shared at the quantised radius; the
        # scale carries the remainder so effective_radius is the exact one.
        ship.SetScale(float(radius_gu) / r_q)
    return ship


# One glTF unit is a metre and a BC model unit is 1.75 m (the loader's
# kMetresToModelUnits); every ship draws at BC_MODEL_SCALE (0.01 GU per model
# unit) x GetScale(). So a rock of bound radius B metres loaded at scale s
# draws at B / 1.75 * s * 0.01 GU, and s = r * 175 / B draws it at r GU.
# (host_loop.BC_MODEL_SCALE; not imported -- host_loop is the whole host.)
_BC_MODEL_SCALE = 0.01


def _render_load_scale(r_gu: float, rock) -> float:
    from engine.rocks.catalogue import MODEL_UNITS_PER_METRE
    return float(r_gu) / (
        rock.bound_radius_m * MODEL_UNITS_PER_METRE * _BC_MODEL_SCALE)


def DamageableObject_Create(model_name):
    """BC's lightweight rock constructor (Multi1.py:103, Multi6_S.py). A model
    name that resolves to a stock asteroid LOD becomes a RockClass sized from
    that NIF; anything else is a plain DamageableObject (out of scope beyond
    not crashing)."""
    import App
    from engine.appc.objects import DamageableObject
    lod = App.g_kLODModelManager.Get(str(model_name))
    filename = lod.lods[0].filename if (lod is not None and lod.lods) else ""
    base = filename.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if base not in _STOCK_ASTEROID_NIFS:
        return DamageableObject()
    radius = _stock_radius_gu(base)
    rock = RockClass_Create(radius, seed=str(model_name), name=str(model_name),
                            kind="major")
    rock._stock_nif_rel = filename
    return rock


def rock_model_override(ship):
    """(model path, load scale) for a rock with no ship script, else None.
    A DamageableObject_Create rock routes its stock NIF through the catalogue
    redirect like any stock asteroid; a RockClass_Create piece uses its own
    catalogue fragment."""
    if not is_rock(ship):
        return None
    rel = ship.__dict__.get("_stock_nif_rel")
    if rel:
        from engine import paths
        from engine.rocks import catalogue
        return catalogue.ship_model_source(ship.GetName(), str(paths.game_asset(rel)))
    return ship.__dict__.get("_model_override")
