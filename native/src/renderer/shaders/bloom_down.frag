#version 330 core
in vec2 v_uv; out vec4 frag_color;
uniform sampler2D u_src;
uniform vec2 u_texel;          // 1/source_size
void main() {
    vec2 t = u_texel;
    vec3 a = texture(u_src, v_uv + vec2(-2,-2)*t).rgb;
    vec3 b = texture(u_src, v_uv + vec2( 0,-2)*t).rgb;
    vec3 c = texture(u_src, v_uv + vec2( 2,-2)*t).rgb;
    vec3 d = texture(u_src, v_uv + vec2(-2, 0)*t).rgb;
    vec3 e = texture(u_src, v_uv + vec2( 0, 0)*t).rgb;
    vec3 f = texture(u_src, v_uv + vec2( 2, 0)*t).rgb;
    vec3 g = texture(u_src, v_uv + vec2(-2, 2)*t).rgb;
    vec3 h = texture(u_src, v_uv + vec2( 0, 2)*t).rgb;
    vec3 i = texture(u_src, v_uv + vec2( 2, 2)*t).rgb;
    vec3 j = texture(u_src, v_uv + vec2(-1,-1)*t).rgb;
    vec3 k = texture(u_src, v_uv + vec2( 1,-1)*t).rgb;
    vec3 l = texture(u_src, v_uv + vec2(-1, 1)*t).rgb;
    vec3 m = texture(u_src, v_uv + vec2( 1, 1)*t).rgb;
    vec3 col = e*0.125;
    col += (a+c+g+i)*0.03125;
    col += (b+d+f+h)*0.0625;
    col += (j+k+l+m)*0.125;
    frag_color = vec4(col, 1.0);
}
