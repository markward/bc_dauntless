@echo off
REM Windows build environment for a portable (no-installer) MSVC toolchain.
REM
REM There is no vcvarsall on PATH when MSVC is unpacked into a user directory
REM rather than installed, so point DAUNTLESS_MSVC at that directory. It must
REM contain setup_x64.bat, which sets INCLUDE / LIB / PATH for cl.exe.
REM
REM   set DAUNTLESS_MSVC=C:\path\to\msvc
REM   scripts\win_env.bat
REM   cmake -G Ninja -B build -S . -DDAUNTLESS_ENABLE_CEF=OFF
REM   cmake --build build --target _dauntless_host -j
REM
REM With a normal Visual Studio install, use its Developer Command Prompt
REM instead of this script.

if "%DAUNTLESS_MSVC%"=="" (
    echo [win_env] DAUNTLESS_MSVC is not set -- point it at your MSVC directory.
    echo [win_env] Expected: %%DAUNTLESS_MSVC%%\setup_x64.bat
    exit /b 1
)
if not exist "%DAUNTLESS_MSVC%\setup_x64.bat" (
    echo [win_env] No setup_x64.bat under "%DAUNTLESS_MSVC%".
    exit /b 1
)
call "%DAUNTLESS_MSVC%\setup_x64.bat"
