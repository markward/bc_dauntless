"""Developer "Rock Fields: inside Beol 4" mission (rock-fields spec, live
tuning).

Loads Beol 4 through its SDK Initialize() and starts the player 300 GU
inside "Asteroid Field 1" -- on the line from the field's centre toward
Beol 4's "Player Start", nose toward the centre, so the near/mid rock
population is all around the ship from the first frame. The field centre
and radius are read from the live SDK object at Initialize time (never
hard-coded): far_tier_field.FIELD_CENTRE documents the same point as a
cross-check only. The / L O keys start on the rock-fields group's
near_large_density.

--developer -> Load Mission... -> Developer -> Rock Fields: inside Beol 4.
"""
import App

from engine.dev_missions import _far_tier_common as common

INSIDE_GU = 300.0


def PreLoadAssets(pMission):
    pass


def Initialize(pMission):
    import LoadBridge
    LoadBridge.Load("GalaxyBridge")

    import Systems.Beol.Beol4
    Systems.Beol.Beol4.Initialize()
    pSet = App.g_kSetManager.GetSet("Beol4")

    field = pSet.GetObject("Asteroid Field 1")
    centre_loc = field.GetWorldLocation()
    centre = (centre_loc.x, centre_loc.y, centre_loc.z)
    radius = float(field.GetFieldRadius())

    start = pSet.GetObject("Player Start").GetWorldLocation()
    s = (start.x, start.y, start.z)
    toward_start = common._unit(tuple(a - c for a, c in zip(s, centre)))
    eye = tuple(c + a * (radius - INSIDE_GU) for c, a in zip(centre, toward_start))
    common.create_aimed_player(pSet, eye, centre)

    common.start_on_far_dials("near_large_density")
