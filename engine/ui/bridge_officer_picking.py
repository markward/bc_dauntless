"""Click a bridge officer in the 3D view to open their crew menu.

In bridge (first-person) view the five station officers — Helm, Tactical,
Commander/XO, Science, Engineering — sit at their stations, and a mission may
seat a guest (BC's Picard/Data/Saalek) among them. This module lets the player
aim at any of them and left-click to open that character's crew menu, the same
effect as the F1-F5 hotkeys and F6.

On the bridge the cursor is LOCKED for mouse-look (GLFW_CURSOR_DISABLED — see
_apply_view_mode_side_effects / set_cursor_locked), so there is no free pointer:
the player aims by *looking*. The aim point is therefore the screen-centre
reticle, not a hardware cursor. The picker is a pure forward projection: each
officer's posed HEAD centre (``renderer.get_instance_head_center`` — the same
point the bridge zoom aims at) is projected to framebuffer pixels with the live
bridge camera, and the officer nearest screen centre within a pixel radius wins.
No ray-cast, no native code.

Opening reuses ``crew_menu_hotkeys.open_menu_for_character`` so behaviour is
identical to the hotkey path — and matches BC, whose bridge-character click seam
(``BridgeHandlers.TalkToGeneric``) likewise raises the character's OWN menu
rather than looking one up by name. The host loop (engine/host_loop.py) owns the
mouse-edge handling and the open/switch / click-off-to-close semantics; this
module only answers "which character is under the cursor".

Projection math mirrors engine/ui/ship_property_viewer.py's project()/pick_pin().
"""
from __future__ import annotations

import logging
import math
from typing import Optional, Tuple

from engine.ui import crew_menu_hotkeys

_logger = logging.getLogger(__name__)

Vec3 = Tuple[float, float, float]

# Aim tolerance: how close an officer's projected head must be to the screen-
# centre reticle to count as "aimed at", as a fraction of framebuffer HEIGHT
# (resolution-independent — a fixed pixel radius felt far too tight on a 1440p
# framebuffer). Generous, because roughly facing an officer should be enough and
# overlaps resolve to the nearest-to-centre anyway. Tunable.
PICK_RADIUS_FRAC = 0.16


# --- minimal world->screen projection (framebuffer-pixel space) -------------

def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (a[1]*b[2] - a[2]*b[1], a[2]*b[0] - a[0]*b[2], a[0]*b[1] - a[1]*b[0])


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]


def _norm(a: Vec3) -> Vec3:
    m = math.sqrt(_dot(a, a)) or 1.0
    return (a[0]/m, a[1]/m, a[2]/m)


def _look_at(eye: Vec3, target: Vec3, up: Vec3):
    """Right-handed view matrix as a 4x4 row-major list."""
    f = _norm(_sub(target, eye))      # forward
    s = _norm(_cross(f, up))          # right
    u = _cross(s, f)                  # true up
    return [
        [ s[0],  s[1],  s[2], -_dot(s, eye)],
        [ u[0],  u[1],  u[2], -_dot(u, eye)],
        [-f[0], -f[1], -f[2],  _dot(f, eye)],
        [ 0.0,   0.0,   0.0,   1.0],
    ]


def _perspective(fov_y: float, aspect: float):
    """Projection matrix; only the x/y/w rows matter for cursor picking, so
    near/far are fixed (depth clamping is irrelevant to a 2D hit test)."""
    fy = 1.0 / math.tan(fov_y / 2.0)
    fx = fy / aspect
    return [
        [fx,  0.0,  0.0, 0.0],
        [0.0, fy,   0.0, 0.0],
        [0.0, 0.0, -1.0, 0.0],   # placeholder depth row (unused by the xy pick)
        [0.0, 0.0, -1.0, 0.0],   # w = -view_z  (>0 in front of the camera)
    ]


def _project(vp, world: Vec3, fb_w: int, fb_h: int):
    """Project a world point through view-proj `vp` to framebuffer pixels
    (top-left origin). Returns (sx, sy, in_front)."""
    v = [world[0], world[1], world[2], 1.0]
    clip = [sum(vp[r][c] * v[c] for c in range(4)) for r in range(4)]
    w = clip[3]
    if w <= 1e-6:                       # behind / on the camera plane
        return (0.0, 0.0, False)
    ndc_x, ndc_y = clip[0]/w, clip[1]/w
    sx = (ndc_x * 0.5 + 0.5) * fb_w
    sy = (1.0 - (ndc_y * 0.5 + 0.5)) * fb_h   # flip Y to top-left origin
    return (sx, sy, True)


def _mat_mul(a, b):
    return [[sum(a[r][k] * b[k][c] for k in range(4)) for c in range(4)]
            for r in range(4)]


# --- picking ----------------------------------------------------------------

def _candidates(bridge):
    """Every bridge character the player can aim at: the five station officers,
    plus the guest if one is aboard.

    The guest comes from crew_menu_hotkeys.resolve_guest() — BC's own
    Picard/Data/Saalek hunt, the same one F6 uses — because a guest holds no
    station and so can never appear in the five-station table."""
    import App
    out = []
    for _key, char_name in crew_menu_hotkeys._KEY_TO_CHARACTER.items():
        officer = App.CharacterClass_GetObject(bridge, char_name)
        if officer is not None:
            out.append(officer)
    guest = crew_menu_hotkeys.resolve_guest()
    if guest is not None:
        out.append(guest)
    return out


def pick(h, r, bridge_camera) -> Optional[dict]:
    """Return ``{"officer": <CharacterClass>}`` for the bridge character the
    player is aiming at (head projects within PICK_RADIUS_FRAC·height of
    centre), or None.
    Pure: reads camera / instance state but never consumes any input edge.

    The character, not a menu label: guests have no station label, and the
    consumers (menu open, tooltip owner) both want the character anyway.

    `h` is the _dauntless_host module, `r` the renderer wrapper, `bridge_camera`
    the live _BridgeCamera (compute_camera() is pure)."""
    if h is None or r is None or bridge_camera is None:
        return None
    if not hasattr(h, "framebuffer_size") or not hasattr(r, "get_instance_head_center"):
        return None
    import App
    bridge = App.g_kSetManager.GetSet("bridge")
    if bridge is None:
        return None

    fb_w, fb_h = h.framebuffer_size()
    if fb_w <= 0 or fb_h <= 0:
        return None
    eye, target, up, fov = bridge_camera.compute_camera()
    vp = _mat_mul(_perspective(fov, fb_w / fb_h), _look_at(eye, target, up))
    # Aim point is the look reticle = screen centre (cursor is locked for
    # mouse-look on the bridge).
    cx, cy = fb_w * 0.5, fb_h * 0.5

    best_officer = None
    radius_px = PICK_RADIUS_FRAC * fb_h
    best_d2 = radius_px * radius_px
    for off in _candidates(bridge):
        iid = getattr(off, "_render_instance", None)
        if iid is None:
            continue
        if hasattr(off, "IsHidden") and off.IsHidden():
            continue
        head = r.get_instance_head_center(iid)
        if not head:
            continue
        sx, sy, in_front = _project(vp, (head[0], head[1], head[2]), fb_w, fb_h)
        if not in_front:
            continue
        dx, dy = sx - cx, sy - cy
        d2 = dx*dx + dy*dy
        if d2 < best_d2:
            best_d2 = d2
            best_officer = off

    if best_officer is None:
        return None
    return {"officer": best_officer}


# --- click handling ---------------------------------------------------------

def handle_click(h, r, bridge_camera, crew_menu_panel, pick_active: bool) -> bool:
    """Process a bridge left-click for the crew menus and return the updated
    `pick_active` latch. Called once per frame from the host loop (bridge view,
    unpaused) just before _poll_mouse_buttons.

    Semantics:
      - No menu open: aim an officer (screen centre) + left-press → open it.
        A press with no officer aimed is left for _poll_mouse_buttons → phasers.
      - Menu open: a left-press closes it. Presses over the CEF menu panel are
        consumed earlier by the panel mouse-forwarding, so a press still seen
        here is off-menu.

    The press is intercepted with the edge-consuming mouse_button_pressed only
    once we've decided to act, so empty-space clicks (no menu, no officer) keep
    firing phasers. `pick_active` records that an intercepted press is in flight
    so its matching release is swallowed (never split a real phaser press/release
    pair, never leak a stray OnKeyUp)."""
    if h is None:
        return pick_active
    left = h.keys.MOUSE_BUTTON_LEFT
    if crew_menu_panel.has_open_menu():
        if h.mouse_button_pressed(left):
            pick_active = True
            crew_menu_panel.close_open_menu()
    else:
        aimed = pick(h, r, bridge_camera)
        if aimed is not None and h.mouse_button_pressed(left):
            pick_active = True
            crew_menu_hotkeys.open_menu_for_character(
                crew_menu_panel, aimed["officer"])
    # Swallow the release matching an intercepted press. Gated on the latch so a
    # genuine phaser press/release pair is never split.
    if pick_active and h.mouse_button_released(left):
        pick_active = False
    return pick_active
