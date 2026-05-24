// native/src/ui_cef/cef_lifecycle.cc
#include "cef_lifecycle.h"

namespace dauntless::ui_cef {

int  dispatch_subprocess(int /*argc*/, char* /*argv*/[])  { return -1; }
bool initialize(int, int, const std::string&)             { return false; }
void pump()                                                {}
void composite()                                           {}
void toggle_devtools()                                     {}
void reload()                                              {}
void shutdown()                                            {}

}  // namespace dauntless::ui_cef
