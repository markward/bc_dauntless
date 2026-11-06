// native/src/host/motion_write_apply.cc -- see motion_write_apply.h.
//
// Every store mirrors one of engine/appc/native_motion.py's `_store_*`
// functions, in `_STORES` order, so the same Python runs and the same
// exception comes out of the same place.

#include "motion_write_apply.h"

namespace dauntless::host {

namespace cb = dauntless::combat;

namespace {

// Interned names and the TGPoint3 class, created on first use (the GIL
// held), never released.
struct Names {
    PyObject* dict;
    PyObject* drift;
    PyObject* speed;
    PyObject* velocity;
    PyObject* cav;
    PyObject* motion_vel;
    PyObject* accel;
    PyObject* setpoint;
    PyObject* fraction;
    PyObject* turn_goal;
    PyObject* one;
    PyObject* x;
    PyObject* y;
    PyObject* z;
    PyObject* tgpoint3;
};

Names* g_names = nullptr;

const Names* names() {
    if (g_names != nullptr) return g_names;
    PyObject* mod = PyImport_ImportModule("engine.appc.math");
    if (mod == nullptr) return nullptr;
    PyObject* cls = PyObject_GetAttrString(mod, "TGPoint3");
    Py_DECREF(mod);
    if (cls == nullptr) return nullptr;
    auto* t = new Names;
    t->dict = PyUnicode_InternFromString("__dict__");
    t->drift = PyUnicode_InternFromString("_drift_velocity");
    t->speed = PyUnicode_InternFromString("_current_speed");
    t->velocity = PyUnicode_InternFromString("_velocity");
    t->cav = PyUnicode_InternFromString("_current_angular_velocity");
    t->motion_vel = PyUnicode_InternFromString("_motion_vel");
    t->accel = PyUnicode_InternFromString("_acceleration");
    t->setpoint =
        PyUnicode_InternFromString("_target_angular_velocity_setpoint");
    t->fraction =
        PyUnicode_InternFromString("_target_angular_velocity_fraction");
    t->turn_goal = PyUnicode_InternFromString("_turn_goal");
    t->one = PyLong_FromLong(1);
    t->x = PyUnicode_InternFromString("x");
    t->y = PyUnicode_InternFromString("y");
    t->z = PyUnicode_InternFromString("z");
    t->tgpoint3 = cls;
    for (PyObject* o : {t->dict, t->drift, t->speed, t->velocity, t->cav,
                        t->motion_vel, t->accel, t->setpoint, t->fraction,
                        t->turn_goal, t->one, t->x, t->y, t->z}) {
        if (o == nullptr) {
            Py_DECREF(cls);
            delete t;  // the interned strings are immortal enough: leaked
            return nullptr;
        }
    }
    g_names = t;
    return g_names;
}

// `TGPoint3(*v)`: a new reference, or nullptr with an error set.
PyObject* point(const Names* n, const cb::Vec3& v) {
    return PyObject_CallFunction(n->tgpoint3, "ddd", v[0], v[1], v[2]);
}

// `(v[0], v[1], v[2])` / `(v[0], ..., v[3])`: a new tuple of floats, or
// nullptr with an error set.
PyObject* floats3(const cb::Vec3& v) {
    return Py_BuildValue("(ddd)", v[0], v[1], v[2]);
}
PyObject* floats4(const std::array<double, 4>& v) {
    return Py_BuildValue("(dddd)", v[0], v[1], v[2], v[3]);
}

// `ship.__dict__[name] = value` (value evaluated first, as Python's
// subscript assignment does). Steals `value`. False: an error is set.
bool store(const Names* n, PyObject* ship, PyObject* name, PyObject* value) {
    if (value == nullptr) return false;
    PyObject* d = PyObject_GetAttr(ship, n->dict);
    if (d == nullptr) {
        Py_DECREF(value);
        return false;
    }
    const int rc = PyObject_SetItem(d, name, value);
    Py_DECREF(d);
    Py_DECREF(value);
    return rc == 0;
}

// `c = ship.__dict__["_current_angular_velocity"]; c.x, c.y, c.z = cav`.
bool store_cav(const Names* n, PyObject* ship, const cb::Vec3& cav) {
    PyObject* d = PyObject_GetAttr(ship, n->dict);
    if (d == nullptr) return false;
    PyObject* c = PyObject_GetItem(d, n->cav);
    Py_DECREF(d);
    if (c == nullptr) return false;
    PyObject* const axes[3] = {n->x, n->y, n->z};
    bool ok = true;
    for (int i = 0; i < 3 && ok; ++i) {
        PyObject* v = PyFloat_FromDouble(cav[static_cast<size_t>(i)]);
        ok = v != nullptr && PyObject_SetAttr(c, axes[i], v) == 0;
        Py_XDECREF(v);
    }
    Py_DECREF(c);
    return ok;
}

// native_motion._store_steer: `sp = TGPoint3(*setpoint)`, then
// `__dict__["_target_angular_velocity_setpoint"] = sp`,
// `__dict__["_target_angular_velocity_fraction"] = None` and
// `__dict__["_turn_goal"][1] = sp`, stopping at the first that raises.
bool store_steer(const Names* n, PyObject* ship, const cb::Vec3& setpoint) {
    PyObject* sp = point(n, setpoint);
    if (sp == nullptr) return false;
    PyObject* d = PyObject_GetAttr(ship, n->dict);
    bool ok = d != nullptr && PyObject_SetItem(d, n->setpoint, sp) == 0 &&
              PyObject_SetItem(d, n->fraction, Py_None) == 0;
    if (ok) {
        PyObject* goal = PyObject_GetItem(d, n->turn_goal);
        ok = goal != nullptr && PyObject_SetItem(goal, n->one, sp) == 0;
        Py_XDECREF(goal);
    }
    Py_XDECREF(d);
    Py_DECREF(sp);
    return ok;
}

}  // namespace

bool apply_motion_writes(PyObject* ships,
                         std::span<const cb::MotionWrite> w) {
    if (w.empty()) return true;
    const Names* n = names();
    if (n == nullptr) return false;
    // The first exception, held (as the reference's `first`) while the
    // rest are applied with no error set.
    PyObject *et = nullptr, *ev = nullptr, *etb = nullptr;
    bool raised = false;
    auto failed = [&] {
        if (!raised) {
            PyErr_Fetch(&et, &ev, &etb);
            raised = true;
        } else {
            PyErr_Clear();
        }
    };
    for (const cb::MotionWrite& x : w) {
        PyObject* ship =
            PySequence_GetItem(ships, static_cast<Py_ssize_t>(x.row));
        if (ship == nullptr) {
            // `ship = ships[row]` sits outside the reference's try: its
            // raise propagates at once, and the held first is dropped.
            if (raised) {
                Py_XDECREF(et);
                Py_XDECREF(ev);
                Py_XDECREF(etb);
            }
            return false;
        }
        if (x.what & cb::kDriftClear) {
            Py_INCREF(Py_None);
            if (!store(n, ship, n->drift, Py_None)) failed();
        }
        if (x.what & cb::kDriftSet)
            if (!store(n, ship, n->drift, point(n, x.drift))) failed();
        if (x.what & cb::kMotionVel)
            if (!store(n, ship, n->motion_vel, floats4(x.motion_vel)))
                failed();
        if (x.what & cb::kSpeed)
            if (!store(n, ship, n->speed, PyFloat_FromDouble(x.speed)))
                failed();
        if (x.what & cb::kVelocity)
            if (!store(n, ship, n->velocity, point(n, x.velocity))) failed();
        if (x.what & cb::kSteer)
            if (!store_steer(n, ship, x.setpoint)) failed();
        if (x.what & cb::kAngVel)
            if (!store_cav(n, ship, x.cav)) failed();
        if (x.what & cb::kAccel)
            if (!store(n, ship, n->accel, floats3(x.accel))) failed();
        Py_DECREF(ship);
    }
    if (raised) {
        PyErr_Restore(et, ev, etb);
        return false;
    }
    return true;
}

}  // namespace dauntless::host
