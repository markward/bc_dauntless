// native/src/renderer/include/renderer/pipeline.h
#pragma once

#include "renderer/shader.h"

#include <memory>

namespace renderer {

class Pipeline {
public:
    Pipeline();

    Shader& opaque_shader() noexcept { return *opaque_; }
    Shader& skybox_shader() noexcept { return *skybox_; }     // legacy; removed in cut-over
    Shader& backdrop_shader() noexcept { return *backdrop_; }

private:
    std::unique_ptr<Shader> opaque_;
    std::unique_ptr<Shader> skybox_;
    std::unique_ptr<Shader> backdrop_;
};

}  // namespace renderer
