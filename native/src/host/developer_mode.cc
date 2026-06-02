// native/src/host/developer_mode.cc
#include "developer_mode.h"

namespace dauntless {

namespace {
bool g_developer_mode = false;
}

bool is_developer_mode() { return g_developer_mode; }
void set_developer_mode(bool enabled) { g_developer_mode = enabled; }

}  // namespace dauntless
