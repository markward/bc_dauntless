# ThorVG 1.0.4 (MIT): software rasteriser + Lottie loader only. See UPSTREAM_VERSION.
# Meson generates config.h; here the same switches are written by hand.
set(THORVG_ROOT ${CMAKE_CURRENT_SOURCE_DIR})
set(THORVG_GEN ${CMAKE_CURRENT_BINARY_DIR}/gen)
file(MAKE_DIRECTORY ${THORVG_GEN})
file(WRITE ${THORVG_GEN}/config.h.tmp
"#define THORVG_VERSION_STRING \"1.0.4\"
#define THORVG_CPU_ENGINE_SUPPORT 1
#define THORVG_PARTIAL_RENDER_SUPPORT 1
#define THORVG_LOTTIE_LOADER_SUPPORT 1
")
configure_file(${THORVG_GEN}/config.h.tmp ${THORVG_GEN}/config.h COPYONLY)

add_library(thorvg STATIC
    src/common/tvgColor.cpp
    src/common/tvgCompressor.cpp
    src/common/tvgMath.cpp
    src/common/tvgStr.cpp
    src/renderer/tvgAccessor.cpp
    src/renderer/tvgAnimation.cpp
    src/renderer/tvgCanvas.cpp
    src/renderer/tvgFill.cpp
    src/renderer/tvgInitializer.cpp
    src/renderer/tvgLoaderMgr.cpp
    src/renderer/tvgPaint.cpp
    src/renderer/tvgPicture.cpp
    src/renderer/tvgRender.cpp
    src/renderer/tvgSaver.cpp
    src/renderer/tvgScene.cpp
    src/renderer/tvgShape.cpp
    src/renderer/tvgTaskScheduler.cpp
    src/renderer/tvgText.cpp
    src/renderer/cpu_engine/tvgSwFill.cpp
    src/renderer/cpu_engine/tvgSwImage.cpp
    src/renderer/cpu_engine/tvgSwMath.cpp
    src/renderer/cpu_engine/tvgSwMemPool.cpp
    src/renderer/cpu_engine/tvgSwPostEffect.cpp
    src/renderer/cpu_engine/tvgSwRaster.cpp
    src/renderer/cpu_engine/tvgSwRenderer.cpp
    src/renderer/cpu_engine/tvgSwRle.cpp
    src/renderer/cpu_engine/tvgSwShape.cpp
    src/renderer/cpu_engine/tvgSwStroke.cpp
    src/loaders/raw/tvgRawLoader.cpp
    src/loaders/lottie/tvgLottieAnimation.cpp
    src/loaders/lottie/tvgLottieBuilder.cpp
    src/loaders/lottie/tvgLottieExpressions.cpp
    src/loaders/lottie/tvgLottieInterpolator.cpp
    src/loaders/lottie/tvgLottieLoader.cpp
    src/loaders/lottie/tvgLottieModel.cpp
    src/loaders/lottie/tvgLottieModifier.cpp
    src/loaders/lottie/tvgLottieParserHandler.cpp
    src/loaders/lottie/tvgLottieParser.cpp
)
target_include_directories(thorvg
    PUBLIC  ${THORVG_ROOT}/inc
    PRIVATE ${THORVG_GEN}
            ${THORVG_ROOT}/src/common
            ${THORVG_ROOT}/src/renderer
            ${THORVG_ROOT}/src/renderer/cpu_engine
            ${THORVG_ROOT}/src/loaders/raw
            ${THORVG_ROOT}/src/loaders/lottie
)
target_compile_features(thorvg PRIVATE cxx_std_17)
target_compile_definitions(thorvg PUBLIC TVG_STATIC)
if(MSVC)
    target_compile_definitions(thorvg PRIVATE NOMINMAX WIN32_LEAN_AND_MEAN _USE_MATH_DEFINES)
    target_compile_options(thorvg PRIVATE /w)
else()
    target_compile_options(thorvg PRIVATE -w)
endif()
set_target_properties(thorvg PROPERTIES POSITION_INDEPENDENT_CODE ON)
