#pragma once
#include <vector>
#include <scenegraph/breach_events.h>
#include <scenegraph/instance.h>   // InstanceId
#include <renderer/frame.h>        // ParticleEmitterDescriptor

namespace renderer {

/// Build analytic venting-jet ParticleEmitterDescriptors from all active breach
/// events on a single instance.
///
/// Each descriptor is ATTACHED (instance_id = the ship's id) so its emit_pos
/// and emit_dir are body-frame and track the ship. effect_age = now - birth_time;
/// stop_age = kVentLife (emission cuts off at stop_age, per ParticlePass model).
///
/// Returns an empty vector when no events are active, or when all active events
/// have aged past kVentLife.
std::vector<ParticleEmitterDescriptor> build_venting_descriptors(
    const scenegraph::BreachEventRing& ring,
    scenegraph::InstanceId             instance_id,
    float                              now);

} // namespace renderer
