#version 330 core

in vec2 v_uv;
out vec4 frag;

uniform sampler2D u_tex;
uniform vec2 u_inv_resolution;   // (1/width, 1/height)

#define EDGE_THRESHOLD_MIN 0.0312
#define EDGE_THRESHOLD_MAX 0.125
#define ITERATIONS 12
#define SUBPIXEL_QUALITY 0.75

float rgb2luma(vec3 rgb) {
    return sqrt(dot(rgb, vec3(0.299, 0.587, 0.114)));
}

float QUALITY(int i) {
    if (i < 5)  return 1.0;
    if (i == 5) return 1.5;
    if (i < 10) return 2.0;
    if (i == 10) return 4.0;
    return 8.0;
}

void main() {
    vec2 inverseScreenSize = u_inv_resolution;
    vec3 colorCenter = texture(u_tex, v_uv).rgb;

    float lumaCenter = rgb2luma(colorCenter);
    float lumaDown  = rgb2luma(textureOffset(u_tex, v_uv, ivec2( 0, -1)).rgb);
    float lumaUp    = rgb2luma(textureOffset(u_tex, v_uv, ivec2( 0,  1)).rgb);
    float lumaLeft  = rgb2luma(textureOffset(u_tex, v_uv, ivec2(-1,  0)).rgb);
    float lumaRight = rgb2luma(textureOffset(u_tex, v_uv, ivec2( 1,  0)).rgb);

    float lumaMin = min(lumaCenter, min(min(lumaDown, lumaUp), min(lumaLeft, lumaRight)));
    float lumaMax = max(lumaCenter, max(max(lumaDown, lumaUp), max(lumaLeft, lumaRight)));
    float lumaRange = lumaMax - lumaMin;

    // Not an edge — passthrough.
    if (lumaRange < max(EDGE_THRESHOLD_MIN, lumaMax * EDGE_THRESHOLD_MAX)) {
        frag = vec4(colorCenter, 1.0);
        return;
    }

    float lumaDownLeft  = rgb2luma(textureOffset(u_tex, v_uv, ivec2(-1, -1)).rgb);
    float lumaUpRight   = rgb2luma(textureOffset(u_tex, v_uv, ivec2( 1,  1)).rgb);
    float lumaUpLeft    = rgb2luma(textureOffset(u_tex, v_uv, ivec2(-1,  1)).rgb);
    float lumaDownRight = rgb2luma(textureOffset(u_tex, v_uv, ivec2( 1, -1)).rgb);

    float lumaDownUp    = lumaDown + lumaUp;
    float lumaLeftRight = lumaLeft + lumaRight;
    float lumaLeftCorners  = lumaDownLeft + lumaUpLeft;
    float lumaDownCorners  = lumaDownLeft + lumaDownRight;
    float lumaRightCorners = lumaDownRight + lumaUpRight;
    float lumaUpCorners    = lumaUpRight + lumaUpLeft;

    float edgeHorizontal = abs(-2.0 * lumaLeft + lumaLeftCorners)
                         + abs(-2.0 * lumaCenter + lumaDownUp) * 2.0
                         + abs(-2.0 * lumaRight + lumaRightCorners);
    float edgeVertical   = abs(-2.0 * lumaUp + lumaUpCorners)
                         + abs(-2.0 * lumaCenter + lumaLeftRight) * 2.0
                         + abs(-2.0 * lumaDown + lumaDownCorners);

    bool isHorizontal = (edgeHorizontal >= edgeVertical);

    float luma1 = isHorizontal ? lumaDown : lumaLeft;
    float luma2 = isHorizontal ? lumaUp : lumaRight;
    float gradient1 = luma1 - lumaCenter;
    float gradient2 = luma2 - lumaCenter;

    bool is1Steepest = abs(gradient1) >= abs(gradient2);
    float gradientScaled = 0.25 * max(abs(gradient1), abs(gradient2));

    float stepLength = isHorizontal ? inverseScreenSize.y : inverseScreenSize.x;

    float lumaLocalAverage = 0.0;
    if (is1Steepest) {
        stepLength = -stepLength;
        lumaLocalAverage = 0.5 * (luma1 + lumaCenter);
    } else {
        lumaLocalAverage = 0.5 * (luma2 + lumaCenter);
    }

    vec2 currentUv = v_uv;
    if (isHorizontal) {
        currentUv.y += stepLength * 0.5;
    } else {
        currentUv.x += stepLength * 0.5;
    }

    vec2 offset = isHorizontal ? vec2(inverseScreenSize.x, 0.0)
                               : vec2(0.0, inverseScreenSize.y);
    vec2 uv1 = currentUv - offset;
    vec2 uv2 = currentUv + offset;

    float lumaEnd1 = rgb2luma(texture(u_tex, uv1).rgb) - lumaLocalAverage;
    float lumaEnd2 = rgb2luma(texture(u_tex, uv2).rgb) - lumaLocalAverage;

    bool reached1 = abs(lumaEnd1) >= gradientScaled;
    bool reached2 = abs(lumaEnd2) >= gradientScaled;
    bool reachedBoth = reached1 && reached2;

    if (!reached1) uv1 -= offset;
    if (!reached2) uv2 += offset;

    if (!reachedBoth) {
        for (int i = 2; i < ITERATIONS; i++) {
            if (!reached1) lumaEnd1 = rgb2luma(texture(u_tex, uv1).rgb) - lumaLocalAverage;
            if (!reached2) lumaEnd2 = rgb2luma(texture(u_tex, uv2).rgb) - lumaLocalAverage;
            reached1 = abs(lumaEnd1) >= gradientScaled;
            reached2 = abs(lumaEnd2) >= gradientScaled;
            reachedBoth = reached1 && reached2;
            if (!reached1) uv1 -= offset * QUALITY(i);
            if (!reached2) uv2 += offset * QUALITY(i);
            if (reachedBoth) break;
        }
    }

    float distance1 = isHorizontal ? (v_uv.x - uv1.x) : (v_uv.y - uv1.y);
    float distance2 = isHorizontal ? (uv2.x - v_uv.x) : (uv2.y - v_uv.y);

    bool isDirection1 = distance1 < distance2;
    float distanceFinal = min(distance1, distance2);
    float edgeThickness = (distance1 + distance2);
    float pixelOffset = -distanceFinal / edgeThickness + 0.5;

    bool isLumaCenterSmaller = lumaCenter < lumaLocalAverage;
    bool correctVariation = ((isDirection1 ? lumaEnd1 : lumaEnd2) < 0.0) != isLumaCenterSmaller;
    float finalOffset = correctVariation ? pixelOffset : 0.0;

    // Subpixel antialiasing.
    float lumaAverage = (1.0 / 12.0) * (2.0 * (lumaDownUp + lumaLeftRight)
                       + lumaLeftCorners + lumaRightCorners);
    float subPixelOffset1 = clamp(abs(lumaAverage - lumaCenter) / lumaRange, 0.0, 1.0);
    float subPixelOffset2 = (-2.0 * subPixelOffset1 + 3.0) * subPixelOffset1 * subPixelOffset1;
    float subPixelOffsetFinal = subPixelOffset2 * subPixelOffset2 * SUBPIXEL_QUALITY;

    finalOffset = max(finalOffset, subPixelOffsetFinal);

    vec2 finalUv = v_uv;
    if (isHorizontal) {
        finalUv.y += finalOffset * stepLength;
    } else {
        finalUv.x += finalOffset * stepLength;
    }

    frag = vec4(texture(u_tex, finalUv).rgb, 1.0);
}
