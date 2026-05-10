// native/src/renderer/include/renderer/shader.h
#pragma once

#include <glm/glm.hpp>
#include <string>

namespace renderer {

class Shader {
public:
    Shader(const std::string& vertex_src, const std::string& fragment_src);
    ~Shader();
    Shader(const Shader&) = delete;
    Shader& operator=(const Shader&) = delete;
    Shader(Shader&&) noexcept;
    Shader& operator=(Shader&&) noexcept;

    void use() const noexcept;
    unsigned program() const noexcept { return program_; }

    void set_mat4(const std::string& name, const glm::mat4& v) const;
    void set_mat3(const std::string& name, const glm::mat3& v) const;
    void set_vec3(const std::string& name, const glm::vec3& v) const;
    void set_vec2(const std::string& name, const glm::vec2& v) const;
    void set_int(const std::string& name, int v) const;

    /// Set a `vec3[]` uniform with `count` consecutive elements. The data
    /// pointer must reference at least `count` glm::vec3 values. Pass the
    /// uniform name *without* the `[0]` suffix; GL accepts the bare name.
    void set_vec3_array(const std::string& name,
                        const glm::vec3* data,
                        int count) const;

private:
    unsigned program_ = 0;
};

}  // namespace renderer
