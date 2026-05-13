#include <audio/openal_backend.h>
namespace open_stbc::audio {
std::unique_ptr<IAudioBackend> make_openal_backend() { return nullptr; }
}  // namespace open_stbc::audio
