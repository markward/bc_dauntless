"""Developer "Far Tier: Vesuvi belt" mission (far-tier spec, live tuning).

Vesuvi is the only system whose radial profile authors an `asteroids` band
(0.5 from Geki at 226,000 GU to Haven at 330,000 GU from the star). This
starts the player in Vesuvi6's set at mid-band -- system position
(278,000, 0, 0), in the system plane -- looking tangentially along the band
(+Y), the view the haze_brightness default was calibrated on. The / L O keys
start on the "far" dials.

--developer -> Load Mission... -> Developer -> Far Tier: Vesuvi belt.
"""
import App

from engine.dev_missions import _far_tier_common as common

MID_BAND_GU = 278000.0


def PreLoadAssets(pMission):
    pass


def Initialize(pMission):
    import LoadBridge
    LoadBridge.Load("GalaxyBridge")

    import Systems.Vesuvi.Vesuvi6
    Systems.Vesuvi.Vesuvi6.Initialize()
    pSet = App.g_kSetManager.GetSet("Vesuvi6")

    from engine.systems import resolve
    ax, ay, az = resolve.anchor_of("Vesuvi6")
    eye = (MID_BAND_GU - ax, 0.0 - ay, 0.0 - az)          # set coordinates
    target = (eye[0], eye[1] + 10000.0, eye[2])           # along the band
    common.create_aimed_player(pSet, eye, target)

    common.start_on_far_dials()
