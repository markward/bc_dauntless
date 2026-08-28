"""Guard against a panel setting that changes without ever redrawing.

THE BUG THIS EXISTS FOR. Every CEF panel here snapshot-diffs in render_payload
and returns None when the snapshot compares equal, so an unchanged panel emits
nothing. A setting left OUT of that snapshot tuple therefore toggles
*invisibly*: the flag flips, the underlying feature really does change, and the
control keeps rendering its old state forever because no payload is ever pushed.

It shipped exactly that way on Developer Options -> Diagnostics -> Frame
Profiler: the profiler turned on and started reporting to the terminal while the
button still read "Off".

It is easy to write tests that miss this, and the ones written at the time did:
they asserted the panel's own mirror ("the flag is now True") rather than the
observable behaviour ("the UI is told"). This helper asserts the second.
"""
import json
from typing import Any, Callable, Optional


def payload_body(js: Optional[str]) -> dict:
    """The JSON dict out of a `setSomething({...});` payload."""
    assert js is not None, "panel emitted no payload"
    start = js.index("(") + 1
    end = js.rindex(")")
    return json.loads(js[start:end])


def _resolve(panel: Any, key: str, aliases: dict):
    """Find the attribute backing a payload key, across the conventions the
    panels actually use: a private mirror (_key), a public field (key), or a
    field on a settings object (panel._settings.key). `aliases` covers panels
    whose payload key differs from the attribute name (the SPV reports
    show_glow_regions as "show_glow")."""
    key = aliases.get(key, key)
    for owner, name in ((panel, "_" + key),
                        (panel, key),
                        (getattr(panel, "_settings", None), key)):
        if owner is not None and hasattr(owner, name):
            return owner, name
    return None, None


def assert_boolean_settings_redraw(panel: Any,
                                   settings_of: Callable[[dict], dict],
                                   skip: tuple = (),
                                   aliases: Optional[dict] = None) -> None:
    """Flip every boolean the panel reports and require a fresh payload.

    `settings_of` picks the settings dict out of the parsed payload, because
    panels differ: some nest under "settings", some report at the top level.
    `skip` names keys whose backing state is genuinely derived rather than
    stored -- say so explicitly rather than letting the guard quietly miss them.
    `aliases` maps a payload key to its attribute name where they differ.
    """
    aliases = aliases or {}
    body = payload_body(panel.render_payload())
    settings = settings_of(body)
    panel.render_payload()          # drain, so the next call reflects one change

    checked = 0
    for key, value in settings.items():
        if key in skip or not isinstance(value, bool):
            continue
        owner, name = _resolve(panel, key, aliases)
        assert owner is not None, (
            f"payload reports '{key}' but no backing attribute was found; "
            f"extend _resolve or add it to `skip` with a reason")
        setattr(owner, name, not getattr(owner, name))
        assert panel.render_payload() is not None, (
            f"flipping '{key}' produced no new payload -- it is missing from "
            f"render_payload's snapshot tuple, so the control will never show "
            f"it change even though the underlying setting did")
        panel.render_payload()      # drain again
        checked += 1

    assert checked, "no boolean settings were checked — the guard is vacuous"
