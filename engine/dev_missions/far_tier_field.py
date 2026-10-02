"""Developer "Far Tier: Beol 4 field" mission (far-tier spec, live tuning).

Loads Beol 4 through its SDK Initialize() (which places "Asteroid Field 1",
centre (797.7, 977.2, 1268.9), radius 1,000 GU) and starts the player on the
line from Beol 4's "Player Start" to the field centre, 2,500 GU from the
centre (~1,500 GU outside the edge), nose on the centre: the whole tile haze
and its specks are in view. One ~2 GU rock sits 250 GU ahead and 40 GU to
starboard -- a mesh at the start; backing away walks it down the ladder
(impostor ~300 GU, speck ~2,000 GU). The / L O keys start on the "far" dials.

--developer -> Load Mission... -> Developer -> Far Tier: Beol 4 field.
"""
import math

import App
import MissionLib

from engine.dev_missions import _far_tier_common as common

FIELD_CENTRE = (797.714355, 977.248474, 1268.854858)
VIEW_DISTANCE_GU = 2500.0
ROCK_AHEAD_GU = 250.0
ROCK_SIDE_GU = 40.0
ROCK_SCALE = 9.0                 # Asteroidh1 (~0.24 GU) -> ~2 GU, Vesuvi 4 size


def PreLoadAssets(pMission):
    pass


def Initialize(pMission):
    import LoadBridge
    LoadBridge.Load("GalaxyBridge")

    import Systems.Beol.Beol4
    Systems.Beol.Beol4.Initialize()
    pSet = App.g_kSetManager.GetSet("Beol4")

    start = pSet.GetObject("Player Start").GetWorldLocation()
    s = (start.x, start.y, start.z)
    away = common._unit(tuple(a - c for a, c in zip(s, FIELD_CENTRE)))
    eye = tuple(c + a * VIEW_DISTANCE_GU for c, a in zip(FIELD_CENTRE, away))
    player = common.create_aimed_player(pSet, eye, FIELD_CENTRE)

    fwd = tuple(-a for a in away)
    right = common._unit(common._cross(fwd, (0.0, 0.0, 1.0)))
    rock_at = tuple(e + f * ROCK_AHEAD_GU + r * ROCK_SIDE_GU
                    for e, f, r in zip(eye, fwd, right))
    common.aimed_placement("Far Tier Rock Spot", pSet.GetName(), rock_at,
                           FIELD_CENTRE)
    import loadspacehelper
    rock = loadspacehelper.CreateShip("Asteroidh1", pSet, "Far Tier Test Rock",
                                      "Far Tier Rock Spot")
    if rock is not None:
        rock.SetScale(ROCK_SCALE)

    common.start_on_far_dials()
