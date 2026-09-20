// native/src/platform/folder_picker_win.cc
//
// Windows IFileDialog folder chooser. See folder_picker.h for the contract.
//
// Its own translation unit, like exe_path.cc, so <windows.h> never reaches
// the header that CEF translation units include (see the NOMINMAX note in
// this directory's CMakeLists.txt).

#ifdef _WIN32

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

#include <objbase.h>
#include <shobjidl.h>

#include "folder_picker.h"

namespace dauntless::platform {

namespace {

std::wstring widen(const std::string& s) {
    if (s.empty()) return {};
    const int n = ::MultiByteToWideChar(CP_UTF8, 0, s.data(),
                                        static_cast<int>(s.size()), nullptr, 0);
    std::wstring out(static_cast<size_t>(n), L'\0');
    ::MultiByteToWideChar(CP_UTF8, 0, s.data(), static_cast<int>(s.size()),
                          out.data(), n);
    return out;
}

std::string narrow(const wchar_t* s) {
    const int n = ::WideCharToMultiByte(CP_UTF8, 0, s, -1, nullptr, 0,
                                        nullptr, nullptr);
    if (n <= 1) return {};
    std::string out(static_cast<size_t>(n - 1), '\0');
    ::WideCharToMultiByte(CP_UTF8, 0, s, -1, out.data(), n, nullptr, nullptr);
    return out;
}

// Releases a COM interface pointer on scope exit. Small enough that pulling
// in <wrl/client.h> for ComPtr is not worth the extra header.
template <typename T>
struct Release {
    T* p = nullptr;
    ~Release() {
        if (p) p->Release();
    }
};

}  // namespace

std::optional<std::string> pick_folder(const std::string& title,
                                       const std::string& message) {
    // CEF (and GLFW, via OLE drag-drop) may already have initialised COM on
    // this thread in either apartment model. RPC_E_CHANGED_MODE means "already
    // initialised, different model" -- the dialog still works, we just must
    // not balance an init that was never ours.
    const HRESULT init_hr = ::CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    const bool we_initialised = SUCCEEDED(init_hr);
    if (FAILED(init_hr) && init_hr != RPC_E_CHANGED_MODE) {
        return std::nullopt;
    }
    struct Uninit {
        bool armed;
        ~Uninit() {
            if (armed) ::CoUninitialize();
        }
    } uninit{we_initialised};

    Release<IFileOpenDialog> dialog;
    if (FAILED(::CoCreateInstance(CLSID_FileOpenDialog, nullptr,
                                  CLSCTX_INPROC_SERVER,
                                  IID_PPV_ARGS(&dialog.p)))) {
        return std::nullopt;
    }

    DWORD options = 0;
    dialog.p->GetOptions(&options);
    dialog.p->SetOptions(options | FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM |
                         FOS_PATHMUSTEXIST | FOS_NOCHANGEDIR);

    const std::wstring wtitle = widen(title);
    if (!wtitle.empty()) dialog.p->SetTitle(wtitle.c_str());
    // IFileDialog has no body-text slot; the nearest home for the message
    // is the label on the OK button's row. Callers pass "" today anyway.
    const std::wstring wmessage = widen(message);
    if (!wmessage.empty()) dialog.p->SetFileNameLabel(wmessage.c_str());

    // Own the dialog with whichever of our windows is active on this thread
    // (the GLFW host window when called from the host loop), so it opens in
    // front of the game rather than behind it. Null is fine when there is
    // none -- the dialog then just floats unowned.
    const HRESULT show_hr = dialog.p->Show(::GetActiveWindow());
    if (FAILED(show_hr)) {
        // HRESULT_FROM_WIN32(ERROR_CANCELLED) is the player's cancel; every
        // other failure is treated identically by contract.
        return std::nullopt;
    }

    Release<IShellItem> item;
    if (FAILED(dialog.p->GetResult(&item.p)) || item.p == nullptr) {
        return std::nullopt;
    }
    PWSTR wpath = nullptr;
    if (FAILED(item.p->GetDisplayName(SIGDN_FILESYSPATH, &wpath)) ||
        wpath == nullptr) {
        return std::nullopt;
    }
    std::string chosen = narrow(wpath);
    ::CoTaskMemFree(wpath);
    if (chosen.empty()) return std::nullopt;
    return chosen;
}

}  // namespace dauntless::platform

#endif  // _WIN32
