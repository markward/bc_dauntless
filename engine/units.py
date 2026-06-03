"""Unit conversions between BC's internal "game units" and display SI units.

BC's Appc.dll uses a single internal unit — "game units" (GU) — for
every spatial quantity: positions, velocities, distances, sphere
radii. Conversion only happens at the display boundary, via
``Appc.UtopiaModule_ConvertGameUnitsToKilometers``. The factor is
baked into Appc.dll and never exposed; we derived it from the helm
tooltip arithmetic in stock BC:

  Galaxy ``SetMaxSpeed(6.300000)`` GU/s shown as ``3969 kph`` in
  ``sdk/Build/scripts/BridgeHandlers.py:1389``:
      fVel = ConvertGameUnitsToKilometers(velocity.Length()) * 3600

  ⇒ ConvertGameUnitsToKilometers(6.3) = 1.1025 km
  ⇒ 1 GU = 175 m = 0.175 km
  ⇒ 1 GU/s = 175 m/s = 630 km/h

Use these constants whenever crossing the display boundary; do **not**
convert inside the physics/renderer/camera path — everything internal
stays in GU.
"""
from __future__ import annotations

GU_TO_M: float = 175.0
GU_TO_KM: float = 0.175
GUPS_TO_KPH: float = 630.0   # game-units-per-second → kilometres-per-hour
