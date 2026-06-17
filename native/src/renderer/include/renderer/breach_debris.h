#pragma once
#include <renderer/frame.h>
#include <scenegraph/breach_events.h>
#include <vector>

namespace renderer {

/// Build analytic billboard-sprite debris ParticleEmitterDescriptors from all
/// active breach events on a single instance.
///
/// Mirrors build_venting_descriptors: descriptors are ATTACHED (instance_id =
/// the ship's id), emit_pos and emit_dir are body-frame, effect_age = now -
/// birth_time, stop_age = kDebrisLife (short burst via stop_age=0.6f, long
/// drift via emit_life=10.0f).
///
/// Returns an empty vector when no events are active or all have aged past
/// kDebrisLife.
std::vector<ParticleEmitterDescriptor> build_debris_descriptors(
    const scenegraph::BreachEventRing& ring,
    scenegraph::InstanceId             instance_id,
    float                              now);

} // namespace renderer
