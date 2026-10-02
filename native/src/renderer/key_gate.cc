// native/src/renderer/key_gate.cc
#include "renderer/key_gate.h"

namespace renderer {

void KeyGate::capture() noexcept {
    captured_ = true;
    masked_.clear();
}

void KeyGate::release(const std::vector<int>& raw_down) {
    if (!captured_) return;
    captured_ = false;
    masked_.insert(raw_down.begin(), raw_down.end());
}

bool KeyGate::report(int key, bool raw) noexcept {
    if (captured_) return false;
    auto it = masked_.find(key);
    if (it != masked_.end()) {
        if (raw) return false;
        masked_.erase(it);
    }
    return raw;
}

}  // namespace renderer
