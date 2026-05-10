// native/src/renderer/shader.cc
#include "renderer/shader.h"

#include <glad/glad.h>
#include <glm/gtc/type_ptr.hpp>

#include <stdexcept>
#include <string>
#include <vector>

namespace renderer {

namespace {

unsigned compile_stage(GLenum stage, const std::string& src) {
    GLuint sh = glCreateShader(stage);
    const char* p = src.c_str();
    glShaderSource(sh, 1, &p, nullptr);
    glCompileShader(sh);
    GLint ok = 0;
    glGetShaderiv(sh, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        GLint len = 0;
        glGetShaderiv(sh, GL_INFO_LOG_LENGTH, &len);
        std::vector<char> log(len > 0 ? len : 1);
        if (len > 0) glGetShaderInfoLog(sh, len, nullptr, log.data());
        glDeleteShader(sh);
        throw std::runtime_error("renderer::Shader compile failed: " + std::string(log.data()));
    }
    return sh;
}

}  // namespace

Shader::Shader(const std::string& vsrc, const std::string& fsrc) {
    GLuint vs = compile_stage(GL_VERTEX_SHADER, vsrc);
    GLuint fs;
    try {
        fs = compile_stage(GL_FRAGMENT_SHADER, fsrc);
    } catch (...) {
        glDeleteShader(vs);
        throw;
    }
    program_ = glCreateProgram();
    glAttachShader(program_, vs);
    glAttachShader(program_, fs);
    glLinkProgram(program_);
    GLint ok = 0;
    glGetProgramiv(program_, GL_LINK_STATUS, &ok);
    if (!ok) {
        GLint len = 0;
        glGetProgramiv(program_, GL_INFO_LOG_LENGTH, &len);
        std::vector<char> log(len > 0 ? len : 1);
        if (len > 0) glGetProgramInfoLog(program_, len, nullptr, log.data());
        glDeleteProgram(program_);
        glDeleteShader(vs);
        glDeleteShader(fs);
        program_ = 0;
        throw std::runtime_error("renderer::Shader link failed: " + std::string(log.data()));
    }
    glDeleteShader(vs);
    glDeleteShader(fs);
}

Shader::~Shader() {
    if (program_) glDeleteProgram(program_);
}

Shader::Shader(Shader&& o) noexcept : program_(o.program_) { o.program_ = 0; }

Shader& Shader::operator=(Shader&& o) noexcept {
    if (this != &o) {
        if (program_) glDeleteProgram(program_);
        program_ = o.program_;
        o.program_ = 0;
    }
    return *this;
}

void Shader::use() const noexcept {
    glUseProgram(program_);
}

void Shader::set_mat4(const std::string& name, const glm::mat4& v) const {
    GLint loc = glGetUniformLocation(program_, name.c_str());
    if (loc >= 0) glUniformMatrix4fv(loc, 1, GL_FALSE, glm::value_ptr(v));
}

void Shader::set_vec3(const std::string& name, const glm::vec3& v) const {
    GLint loc = glGetUniformLocation(program_, name.c_str());
    if (loc >= 0) glUniform3fv(loc, 1, glm::value_ptr(v));
}

void Shader::set_int(const std::string& name, int v) const {
    GLint loc = glGetUniformLocation(program_, name.c_str());
    if (loc >= 0) glUniform1i(loc, v);
}

void Shader::set_vec2(const std::string& name, const glm::vec2& v) const {
    GLint loc = glGetUniformLocation(program_, name.c_str());
    if (loc >= 0) glUniform2fv(loc, 1, glm::value_ptr(v));
}

void Shader::set_mat3(const std::string& name, const glm::mat3& v) const {
    GLint loc = glGetUniformLocation(program_, name.c_str());
    if (loc >= 0) glUniformMatrix3fv(loc, 1, GL_FALSE, glm::value_ptr(v));
}

void Shader::set_vec3_array(const std::string& name,
                            const glm::vec3* data,
                            int count) const {
    if (count <= 0) return;
    GLint loc = glGetUniformLocation(program_, name.c_str());
    if (loc >= 0) {
        glUniform3fv(loc, count, glm::value_ptr(*data));
    }
}

}  // namespace renderer
