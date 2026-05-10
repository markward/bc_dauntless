// native/src/renderer/frame.cc
#include "renderer/frame.h"
#include "renderer/pipeline.h"

#include <glad/glad.h>

#include <scenegraph/world.h>
#include <scenegraph/camera.h>
#include <scenegraph/instance.h>

#include <assets/model.h>
#include <assets/mesh.h>
#include <assets/texture.h>
#include <assets/material.h>

#include <glm/gtc/matrix_transform.hpp>

#include <vector>

namespace renderer {

namespace {

void draw_model_skybox(const assets::Model& model, Shader& shader, GLuint white_fallback) {
    // Skybox models are typically a single root node with one mesh; iterate
    // for safety. No materials beyond the base-color texture per mesh.
    std::vector<glm::mat4> world_per_node(model.nodes.size(), glm::mat4(1.0f));
    if (!model.nodes.empty()) {
        world_per_node[model.root_node] = model.nodes[model.root_node].local_transform;
    }
    for (std::size_t i = 0; i < model.nodes.size(); ++i) {
        const auto& node = model.nodes[i];
        if (node.parent_index >= 0) {
            world_per_node[i] = world_per_node[node.parent_index] * node.local_transform;
        }
        for (int mesh_idx : node.meshes) {
            const auto& mesh = model.meshes[mesh_idx];
            const auto& mat = (mesh.material_index() >= 0
                ? model.materials[mesh.material_index()]
                : assets::Material{});
            const int base_tex = mat.stages[
                static_cast<std::size_t>(assets::Material::StageSlot::Base)
            ].texture_index;
            glActiveTexture(GL_TEXTURE0);
            if (base_tex >= 0) {
                glBindTexture(GL_TEXTURE_2D, model.textures[base_tex].id());
            } else {
                glBindTexture(GL_TEXTURE_2D, white_fallback);
            }
            shader.set_int("u_base_color", 0);
            glBindVertexArray(mesh.vao());
            glDrawElements(GL_TRIANGLES, mesh.index_count(), GL_UNSIGNED_INT, nullptr);
        }
    }
    glBindVertexArray(0);
}

void draw_model(const assets::Model& model,
                const glm::mat4& world,
                Shader& shader,
                GLuint white_fallback) {
    // Walk nodes; each node may reference one or more meshes by index. The
    // node's local_transform is composed with parent transforms here. The
    // asset pipeline already orders nodes such that parents precede children,
    // so a single linear pass suffices.
    std::vector<glm::mat4> world_per_node(model.nodes.size(), glm::mat4(1.0f));
    if (!model.nodes.empty()) {
        world_per_node[model.root_node] = world * model.nodes[model.root_node].local_transform;
    }
    for (std::size_t i = 0; i < model.nodes.size(); ++i) {
        const auto& node = model.nodes[i];
        if (node.parent_index >= 0) {
            world_per_node[i] = world_per_node[node.parent_index] * node.local_transform;
        }
        for (int mesh_idx : node.meshes) {
            const auto& mesh = model.meshes[mesh_idx];
            shader.set_mat4("u_model", world_per_node[i]);

            const auto& mat = (mesh.material_index() >= 0
                ? model.materials[mesh.material_index()]
                : assets::Material{});
            shader.set_vec3("u_diffuse_color", mat.diffuse);

            const int base_tex = mat.stages[
                static_cast<std::size_t>(assets::Material::StageSlot::Base)
            ].texture_index;
            glActiveTexture(GL_TEXTURE0);
            if (base_tex >= 0) {
                glBindTexture(GL_TEXTURE_2D, model.textures[base_tex].id());
            } else {
                glBindTexture(GL_TEXTURE_2D, white_fallback);
            }
            shader.set_int("u_base_color", 0);

            glBindVertexArray(mesh.vao());
            glDrawElements(GL_TRIANGLES, mesh.index_count(), GL_UNSIGNED_INT, nullptr);
        }
    }
    glBindVertexArray(0);
}

}  // namespace

FrameSubmitter::~FrameSubmitter() {
    if (white_texture_ != 0) {
        GLuint t = white_texture_;
        glDeleteTextures(1, &t);
        white_texture_ = 0;
    }
}

std::uint32_t FrameSubmitter::ensure_white_texture() {
    if (white_texture_ != 0) return white_texture_;
    GLuint t = 0;
    glGenTextures(1, &t);
    glBindTexture(GL_TEXTURE_2D, t);
    const std::uint8_t white[4] = {255, 255, 255, 255};
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, 1, 1, 0, GL_RGBA, GL_UNSIGNED_BYTE, white);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    white_texture_ = t;
    return white_texture_;
}

void FrameSubmitter::submit_opaque(const scenegraph::World& world,
                                   const scenegraph::Camera& camera,
                                   Pipeline& pipeline,
                                   const ModelLookup& lookup,
                                   const Lighting& lighting) {
    auto& shader = pipeline.opaque_shader();
    shader.use();
    shader.set_mat4("u_view", camera.view_matrix());
    shader.set_mat4("u_proj", camera.proj_matrix());

    shader.set_vec3("u_ambient_light", lighting.ambient);
    shader.set_int("u_dir_light_count", lighting.directional_count);
    if (lighting.directional_count > 0) {
        shader.set_vec3_array("u_dir_light_dir_ws",
                              lighting.directional_dir_ws,
                              lighting.directional_count);
        shader.set_vec3_array("u_dir_light_color",
                              lighting.directional_color,
                              lighting.directional_count);
    }

    const GLuint white = ensure_white_texture();

    world.for_each_visible([&](const scenegraph::Instance& inst) {
        const assets::Model* m = lookup(inst.model_handle);
        if (m) draw_model(*m, inst.world, shader, white);
    });
}

void FrameSubmitter::submit_skybox(const assets::Model* skybox_model,
                                   const scenegraph::Camera& camera,
                                   Pipeline& pipeline) {
    if (!skybox_model) return;
    auto& shader = pipeline.skybox_shader();
    shader.use();
    glm::mat4 view_no_t = glm::mat4(glm::mat3(camera.view_matrix()));
    shader.set_mat4("u_view_no_translation", view_no_t);
    shader.set_mat4("u_proj", camera.proj_matrix());

    glDepthMask(GL_FALSE);
    glDepthFunc(GL_LEQUAL);
    glDisable(GL_CULL_FACE);

    const GLuint white = ensure_white_texture();
    draw_model_skybox(*skybox_model, shader, white);

    glDepthMask(GL_TRUE);
    glDepthFunc(GL_LESS);
    glEnable(GL_CULL_FACE);
}

}  // namespace renderer
