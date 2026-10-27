# Native windows

`vendor/window` selects X11/GLX on Linux, Win32/WGL on Windows, and Cocoa/OpenGL
on macOS. Linux callers can explicitly import `vendor/window/wayland` for native
Wayland/EGL; the default X11 path can also use XWayland. No backend uses SDL.

Keep each owning `Window` on its GUI thread, never copy a live owner, and destroy
its GPU resources before closing it. Cocoa requires the process main thread.
`open`, `poll`, `make_current`, `swap`, `gl_proc`, and `close` form the common API.
`poll` updates framebuffer `width`/`height`, UI `input`, and `close_requested`.
A close request leaves the window alive until the caller calls `close`.
Input coordinates use framebuffer pixels. Press/release edges can coexist in
one poll. Keyboard input exposes the existing UI navigation keys, not a general
text-input/IME API. Platform-native error text is not retained.

X11 links system X11/GL and requests GL 3.3 core, as do Wayland and WGL.
X11 creation is serialized on the GUI thread while a temporary global X error
handler catches asynchronous native failures. Cocoa requests the
Apple-supported GL 4.1 core profile. The GL table and renderer belong to their
current context. Restore a window's context before using its renderer.

The Wayland, Windows and Cocoa paths use a small native ABI bridge. Build it on
the target host, then pass its output to Dyn:

```sh
python3 vendor/window/native/build.py --output build/window/libdyn_window.so
dyn build example --link build/window/libdyn_window.so
```

Use `libdyn_window.dylib` on macOS and `dyn_window.dll` on Windows. The Windows
build also writes `libdyn_window.dll.a`; pass that import library to Dyn and keep
the DLL beside the executable. The Windows build script expects a GNU-compatible
C toolchain. Linux needs Wayland/EGL development headers, `wayland-scanner`, and
`wayland-protocols`; macOS needs the Xcode command tools. OpenGL is deprecated by
Apple but remains the backend implemented here.

`tests/native-ui-results.py` performs actual GL pixel comparisons on available
X11/Wayland displays, Windows under Wine when Zig/Wine are available, and native
macOS/Windows when run there. Cross-object generation is distinct from native
backend compilation and execution. Native Cocoa compilation/execution and real
Windows qualification remain platform CI work.
