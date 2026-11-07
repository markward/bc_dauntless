// FireScript's arithmetic -- see ai_fire.h. Each function names the engine
// body (engine/appc/math.py, engine/appc/ships.py) or SDK statement
// (AI/Preprocessors.py) it stands for; the operand order is that body's.
#if defined(__clang__)
#pragma clang fp contract(off)
#endif

#include "dauntless/combat/ai_fire.h"

#include <cmath>

namespace dauntless::combat {

long long fire_cycle(long long last, long long n_weapons) {
    // ((self.iLastUpdate + 3) % (len(self.lWeapons) + 2)) - 2
    const long long a = last + 3;
    const long long b = n_weapons + 2;
    long long r = a % b;
    if (r < 0) r += b;  // Python's modulo takes the divisor's sign
    return r - 2;
}

void fire_subtract(FireVec& self, const FireVec& other) {
    self.x -= other.x;
    self.y -= other.y;
    self.z -= other.z;
}

void fire_add(FireVec& self, const FireVec& other) {
    self.x += other.x;
    self.y += other.y;
    self.z += other.z;
}

double fire_sqr_length(const FireVec& v) { return v.x * v.x + v.y * v.y + v.z * v.z; }

double fire_dot(const FireVec& a, const FireVec& b) { return a.x * b.x + a.y * b.y + a.z * b.z; }

double fire_unitize(FireVec& v) {
    // n = self.Length(); if n > 1e-12: self.x /= n ...; return n
    const double n = std::sqrt(v.x * v.x + v.y * v.y + v.z * v.z);
    if (n > 1e-12) {
        v.x /= n;
        v.y /= n;
        v.z /= n;
    }
    return n;
}

void fire_mult_matrix_left(FireVec& v, const FireMat& m) {
    const double* e = m.m;
    const double x = e[0] * v.x + e[1] * v.y + e[2] * v.z;
    const double y = e[3] * v.x + e[4] * v.y + e[5] * v.z;
    const double z = e[6] * v.x + e[7] * v.y + e[8] * v.z;
    v.x = x;
    v.y = y;
    v.z = z;
}

FireMat fire_transpose(const FireMat& m) {
    const double* e = m.m;
    return FireMat{{e[0], e[3], e[6], e[1], e[4], e[7], e[2], e[5], e[8]}};
}

FireVec fire_predicted_position(const FireVec& p, const FireVec& v, const FireVec& a, double t) {
    const double t2_half = 0.5 * t * t;
    return FireVec{p.x + v.x * t + a.x * t2_half, p.y + v.y * t + a.y * t2_half,
                   p.z + v.z * t + a.z * t2_half};
}

double fire_div(double a, double b) { return a / b; }

bool fire_sqr_within(double sqr_length, double max_range) {
    return sqr_length <= max_range * max_range;
}

bool fire_at_least(double dot, double threshold) { return dot >= threshold; }

bool fire_in_range(const FireVec& target, const FireVec& ship, double max_range) {
    // vDiff = pTarget.GetWorldLocation(); vDiff.Subtract(pShip.GetWorldLocation())
    FireVec d = target;
    fire_subtract(d, ship);
    // if fSqrLength <= (self.fMaxFiringRange * self.fMaxFiringRange): return 1
    return fire_sqr_within(fire_sqr_length(d), max_range);
}

bool fire_predict_target_location(const PredictInputs& in, FireVec& out) {
    // vDiff = pTarget.GetWorldLocation(); vDiff.Subtract(ours); fDistance = vDiff.Unitize()
    FireVec diff = in.target_pos;
    fire_subtract(diff, in.our_pos);
    const double distance = fire_unitize(diff);
    // fTime = fDistance / fSpeed
    if (in.speed == 0.0) return false;
    const double time = distance / in.speed;
    // vPredicted = pTarget.GetWorldLocation(); vPredicted.Set(GetPredictedPosition(...))
    FireVec predicted = in.target_pos;
    if (in.physics)
        predicted = fire_predicted_position(in.target_pos, in.velocity, in.acceleration, time);
    if (in.subsystem) {
        // vSubsystemPos.MultMatrixLeft(pTarget.GetWorldRotation()); vPredicted.Add(...)
        FireVec sub = in.subsystem_pos;
        fire_mult_matrix_left(sub, in.target_rot);
        fire_add(predicted, sub);
    }
    out = predicted;
    return true;
}

FireVec fire_to_local_unit(FireVec predicted, const FireVec& our_pos, const FireMat& our_rot) {
    fire_subtract(predicted, our_pos);
    fire_mult_matrix_left(predicted, fire_transpose(our_rot));
    fire_unitize(predicted);
    return predicted;
}

int fire_good_shot_direction(const FireVec& predicted, const FireVec& our_pos,
                             const FireMat& our_rot, const FireVec* dirs, std::size_t n,
                             double threshold) {
    const FireVec local = fire_to_local_unit(predicted, our_pos, our_rot);
    for (std::size_t i = 0; i < n; ++i)
        if (fire_at_least(fire_dot(local, dirs[i]), threshold)) return static_cast<int>(i);
    return -1;
}

// RateSubsystemForTargeting (AI/Preprocessors.py:959-1015), after its reads.
double fire_subsystem_rating(const SubsystemRatingInputs& in) {
    double damage_to_disable = 0.0;
    const double disabled_condition = in.disabled_percentage * in.max_condition;
    if (in.condition > disabled_condition) damage_to_disable = in.condition - disabled_condition;
    // The factor table is built first (-3.0 * self.bDisableFirst), then summed.
    const double disabled_importance = -3.0 * in.disable_first;
    double rating = 0.0;
    rating = rating + in.critical * 6.0;
    rating = rating + damage_to_disable * -0.0005;
    rating = rating + in.is_disabled * disabled_importance;
    rating = rating + in.condition * -0.0005;
    rating = rating + in.hittable * 1.0;
    rating = rating + in.system_rating * 1.0;
    return rating;
}

double fire_system_rating(int first_match) {
    static const double kRatings[kFireSystemRatingRows] = {5.0, 5.0, 5.0, 4.0, 3.0, -200.0};
    if (first_match < 0 || first_match >= kFireSystemRatingRows) return 0.0;
    return kRatings[first_match];
}

// PickTargetSubsystemFromList (:1017-1045).
double fire_pick_rating(double is_target, double healthy, double disabled) {
    double rating = 0.0;
    rating = rating + is_target * 1.0;
    rating = rating + healthy * -1.0;
    rating = rating + disabled * -1.0;
    return rating;
}

bool fire_greater(double a, double b) { return a > b; }

// ChooseTorpType (:533-640): one ammo type's ideals.
TorpIdeals fire_torp_ideals(double launch_speed, double power_cost, double damage,
                            double guidance_lifetime, double turn_rate) {
    TorpIdeals t{0.0, 0.0, 0.0, 0.0, 0.0};
    if (guidance_lifetime > 0) t.dist_max = guidance_lifetime * launch_speed;
    if ((guidance_lifetime > 0) || (launch_speed > 0)) t.speed_max = (turn_rate * 4.0) + launch_speed;
    t.rating = damage - power_cost;
    return t;
}

double fire_torp_far(double min, double max) {
    if (min > 0) return (max - min) * 1.5;
    return max * 1.5;
}

double fire_torp_score(double rating, double dist_low, double dist_high, double speed_low,
                       double speed_high) {
    const double dist_score = rating * (dist_low + dist_high);
    const double speed_score = rating * (speed_low + speed_high);
    return (0.25 * dist_score) + speed_score;
}

}  // namespace dauntless::combat
