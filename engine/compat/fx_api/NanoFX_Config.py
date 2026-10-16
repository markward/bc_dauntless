"""NanoFX 2.0's default settings, read-only (spec 2026-10-16 §8.4). Mods read
these (e.g. `if NanoFX_Config.sFX_Enabled == 1`); nothing writes them."""
TRUE = 1
FALSE = 0

bFX_Enabled = TRUE
bFX_ExpSparkFXLevel = 3
bFX_DamageSparkFXLevel = 3
bFX_DamageSparkFXDuration = 60.0
bFX_ParticleControl = 200

cFX_Enabled = TRUE
cFX_ViewScreenDefault = 8.0
cFX_ViewScreenMax = 128.0
cFX_AwayDistance = 8.0
cFX_ForwardDistance = 8.0

eFX_Enabled = TRUE
eFX_LightFlickerFX = "On"
eFX_FixBrightGlows = "On"
eFX_ExpSparkFXLevel = 3
eFX_DamageSparkFXLevel = 3
eFX_DamageSparkFXDuration = 60.0
eFX_DebrisFXLevel = 3
eFX_DebrisFXDuration = 30.0
eFX_ParticleControl = 300
eFX_RotationFX = "On"
eFX_SplashRadius = 25.0

sFX_Enabled = TRUE
sFX_AtmosphereGlowFX = "On"
sFX_PlasmaFX = "On"

wFX_Enabled = TRUE
wFX_MaxRandomDistance = 30
