// native/src/renderer/include/renderer/pipeline.h
#pragma once

#include "renderer/shader.h"

#include <memory>

namespace renderer {

class Pipeline {
public:
    Pipeline();

    Shader& opaque_shader() noexcept { return *opaque_; }
    Shader& backdrop_shader() noexcept { return *backdrop_; }
    Shader& sun_shader() noexcept { return *sun_; }
    Shader& dust_shader() noexcept { return *dust_; }

private:
    std::unique_ptr<Shader> opaque_;
    std::unique_ptr<Shader> backdrop_;
    std::unique_ptr<Shader> sun_;
    std::unique_ptr<Shader> dust_;
};

}  // namespace renderer
