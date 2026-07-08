###############################################################################
# q11_planet_scale -- what visual size does BC render planets at?
#
# Question(s): docs/instrumented_experiments/2026-07-07-planet-render-scale.md
#              Q-P1..Q-P5 (planet GetRadius/GetScale, active tactical-view FOV,
#              player<->planet distance, predicted on-screen angular size).
# Needs combat state? NO -- but the operator MUST be flying the tactical view
#              at (or near) Haven orbit in E1M2 so the active set is Vesuvi6
#              and the camera is the normal gameplay camera. See the runbook.
# Output:      game/BCProbe_q11.cfg, section [BCProbe_q11]
#
# Run in the -TestMode REPL with:  execfile('q11_planet_scale.py')
###############################################################################
#
# PYTHON 1.5 CONSTRAINTS -- read docs/instrumented_experiments/console-probe-workflow.md
#   No "import X as Y" / no f-strings / no True/False / "except E, e:" /
#   print is a statement / only App.g_kConfigMapping writes to disk.
#
###############################################################################

import App
import sys

_cfg = App.g_kConfigMapping
_SECTION = "BCProbe_q11"
_CFG_FILE = "BCProbe_q11.cfg"
_log = []

# math is not guaranteed in the static build -- guard it. Without it we still
# record raw frustum + distances so the FOV/angles can be computed off-box.
_math = None
try:
    import math
    _math = math
except ImportError:
    _math = None

def _exc_name(e):
    try:
        return e.__class__.__name__
    except AttributeError:
        return str(type(e))

def _record(label, value):
    line = "%s = %s" % (str(label), str(value))
    _log.append(line)
    print line

def _section(title):
    bar = "-- " + str(title) + " " + ("-" * max(1, 60 - len(str(title))))
    _log.append(bar)
    print bar

def _safe(obj, name, args):
    try:
        return apply(getattr(obj, name), args)
    except:
        return None

def _deg(rad):
    if _math is None:
        return None
    return rad * 180.0 / _math.pi

def _vec3(v):
    if v is None:
        return None
    return (float(v.x), float(v.y), float(v.z))

def _dist(a, b):
    if a is None or b is None:
        return None
    dx = a[0] - b[0]; dy = a[1] - b[1]; dz = a[2] - b[2]
    return (dx * dx + dy * dy + dz * dz) ** 0.5

def _flush():
    n = len(_log)
    for i in range(n):
        _cfg.SetStringValue(_SECTION, "r%d" % i, _log[i])
    _cfg.SetIntValue(_SECTION, "n", n)
    try:
        _cfg.SaveConfigFile(_CFG_FILE)
        print "wrote " + _CFG_FILE + " with %d lines" % n
    except Exception, _e:
        print "save FAILED: " + str(_e)
    for i in range(n):
        _cfg.SetStringValue(_SECTION, "r%d" % i, "")
    _cfg.SetIntValue(_SECTION, "n", 0)

# GU -> km for readability (1 GU = 175 m = 0.175 km).
_GU_KM = 0.175

# === PROBE BODY ================================================================

try:
    _section("environment")
    _record("python_version", sys.version)
    _record("has_math", _math is not None)
    _record("frame", _safe(App.g_kSystemWrapper, "GetUpdateNumber", ()))
    _record("game_time", _safe(App.g_kUtopiaModule, "GetGameTime", ()))

    # -- active set -----------------------------------------------------------
    pSet = None
    try:
        pSet = App.g_kSetManager.GetRenderedSet()
    except:
        pSet = None
    if pSet is None:
        _record("set", "NONE (GetRenderedSet returned None -- load a mission)")
        _flush()
        print "done"
    else:
        _record("set_name", _safe(pSet, "GetName", ()))

        # -- player ship ------------------------------------------------------
        _section("player")
        pPlayer = None
        try:
            pPlayer = App.Game_GetCurrentPlayer()
        except:
            pPlayer = None
        player_pos = None
        if pPlayer is not None:
            player_pos = _vec3(_safe(pPlayer, "GetWorldLocation", ()))
            _record("player_name", _safe(pPlayer, "GetName", ()))
            _record("player_radius_gu", _safe(pPlayer, "GetRadius", ()))
            _record("player_scale", _safe(pPlayer, "GetScale", ()))
            _record("player_pos_gu", player_pos)
        else:
            _record("player", "NONE")

        # -- active camera frustum -> FOV ------------------------------------
        _section("camera")
        cam = _safe(pSet, "GetActiveCamera", ())
        vfov_deg = None
        near = None
        if cam is None:
            _record("camera", "NONE (GetActiveCamera returned None)")
        else:
            _record("cam_eye_gu", _vec3(_safe(cam, "GetWorldLocation", ())))
            _record("cam_fwd", _vec3(_safe(cam, "GetWorldForward", ())))
            _record("cam_up", _vec3(_safe(cam, "GetWorldUp", ())))
            frus = _safe(cam, "GetNiFrustum", ())
            if frus is not None:
                # NiFrustum exposes plain float members (m_fLeft ...), not
                # methods -- read them via attribute access, not a call.
                try:
                    L = frus.m_fLeft; R = frus.m_fRight
                    T = frus.m_fTop;  B = frus.m_fBottom
                    near = frus.m_fNear; far = frus.m_fFar
                    _record("cam_frustum_LRTB", (L, R, T, B))
                    _record("cam_near", near)
                    _record("cam_far", far)
                    if _math is not None and near not in (None, 0.0):
                        # symmetric frustum: vfov = atan(T/near) - atan(B/near)
                        vfov = _math.atan(T / near) - _math.atan(B / near)
                        hfov = _math.atan(R / near) - _math.atan(L / near)
                        vfov_deg = _deg(vfov)
                        _record("cam_vfov_deg", vfov_deg)
                        _record("cam_hfov_deg", _deg(hfov))
                except:
                    _record("cam_frustum", "read FAILED: %s" % str(sys.exc_value))
            else:
                _record("cam_frustum", "GetNiFrustum returned None")

        # -- every planet / sun in the set -----------------------------------
        # Set iteration hands back BASE ObjectClass wrappers, so obj.__class__
        # is NOT Planet/Sun and Planet-only methods (GetAtmosphereRadius) raise
        # AttributeError. Identify + downcast with the RTTI Cast factories
        # (console-probe-workflow.md gotcha #4): Planet_Cast succeeds for planets
        # AND suns (Sun is-a Planet); Sun_Cast distinguishes suns.
        _section("bodies")
        obj = _safe(pSet, "GetFirstObject", ())
        i = 0
        n_bodies = 0
        while obj is not None and i < 300:
            p = _safe(App, "Planet_Cast", (obj,))
            if p is not None:
                is_sun = 0
                if _safe(App, "Sun_Cast", (obj,)) is not None:
                    is_sun = 1
                name = _safe(p, "GetName", ())
                radius = _safe(p, "GetRadius", ())
                scale = _safe(p, "GetScale", ())
                pos = _vec3(_safe(p, "GetWorldLocation", ()))
                atmos = _safe(p, "GetAtmosphereRadius", ())
                _record("body%d_name" % n_bodies, name)
                _record("body%d_is_sun" % n_bodies, is_sun)
                _record("body%d_radius_gu" % n_bodies, radius)
                _record("body%d_scale" % n_bodies, scale)
                _record("body%d_atmos_radius" % n_bodies, atmos)
                _record("body%d_pos_gu" % n_bodies, pos)
                # Distance + predicted on-screen size IF rendered at GetRadius.
                cdist = _dist(pos, player_pos)
                if cdist is not None and radius is not None:
                    r = float(radius)
                    _record("body%d_center_dist_gu" % n_bodies, cdist)
                    _record("body%d_center_dist_km" % n_bodies, cdist * _GU_KM)
                    _record("body%d_surface_dist_km" % n_bodies,
                            (cdist - r) * _GU_KM)
                    if _math is not None and cdist > 0.0:
                        # angular diameter if the rendered radius == GetRadius
                        ang = 2.0 * _math.atan(r / cdist)
                        _record("body%d_angdiam_deg_at_getradius" % n_bodies,
                                _deg(ang))
                        if vfov_deg not in (None, 0.0):
                            _record("body%d_screenfrac_at_getradius" % n_bodies,
                                    _deg(ang) / vfov_deg)
                n_bodies = n_bodies + 1
            obj = _safe(pSet, "GetNextObject", (obj,))
            i = i + 1
        _record("n_bodies", n_bodies)
        _record("n_objects_scanned", i)

        _flush()
        print "done"

except Exception, _err:
    _record("FATAL", "%s: %s" % (_exc_name(_err), str(_err)))
    _flush()
    print "done (fatal)"

# === END PROBE BODY ============================================================
