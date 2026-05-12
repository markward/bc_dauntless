"""LaunchObject hook for shuttle / probe / decoy emission.

Replaces Actions.ShipScriptActions.LaunchObject with a wrapper that
resolves the right emitter on the ship's PropertySet, computes the
world-frame position and orientation, and records the event in
App._emission_recorder. No real spawning — Layer 3 of the emission
design (see docs/project/superpowers/specs/2026-05-12-object-emitter-emission-design.md).

Install once at harness setup:
    from engine.appc.emission import install_launch_object_hook
    install_launch_object_hook()

Idempotent: calling twice replaces the same slot, never composes.
"""


def _launch_object(pAction, iShipID, pcName, iType):
    import App

    pShip = App.ShipClass_Cast(App.TGObject_GetTGObjectPtr(iShipID))
    if pShip is None:
        return 0

    pPropSet = pShip.GetPropertySet()
    pEmitterInstanceList = pPropSet.GetPropertiesByType(App.CT_OBJECT_EMITTER_PROPERTY)

    pEmitterInstanceList.TGBeginIteration()
    iNumItems = pEmitterInstanceList.TGGetNumItems()

    pLaunchProperty = None
    for _ in range(iNumItems):
        pInstance = pEmitterInstanceList.TGGetNext()
        pProperty = App.ObjectEmitterProperty_Cast(pInstance.GetProperty())
        if pProperty is not None and pProperty.GetEmittedObjectType() == iType:
            pLaunchProperty = pProperty
            break

    pEmitterInstanceList.TGDoneIterating()
    pEmitterInstanceList.TGDestroy()

    if pLaunchProperty is None:
        return 0

    pRotation = pShip.GetWorldRotation()

    pPosition = pLaunchProperty.GetPosition()
    pPosition.MultMatrixLeft(pRotation)
    pPosition.Add(pShip.GetWorldLocation())

    pFwd = pLaunchProperty.GetForward()
    pUp = pLaunchProperty.GetUp()
    pFwd.MultMatrixLeft(pRotation)
    pUp.MultMatrixLeft(pRotation)

    App._emission_recorder.record(
        iShipID,
        pLaunchProperty.GetName(),
        iType,
        pPosition, pFwd, pUp,
    )
    return 0


def install_launch_object_hook():
    """Replace Actions.ShipScriptActions.LaunchObject with the engine wrapper.

    Idempotent — calling twice replaces the same slot.
    Requires tools.mission_harness.setup_sdk() to have run first so the
    Actions.ShipScriptActions module is importable through the SDK finder.
    """
    import Actions.ShipScriptActions as _ssa
    _ssa.LaunchObject = _launch_object
