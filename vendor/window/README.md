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
one poll. `box_input` remains a per-poll summary for widgets. Ordered raw input is an
explicit opt-in; platform-native error text is not retained.

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

## Ordered events and worker wake-ups

After opening a window, call `listen_events(&host, true)` before polling. Drain
`next_event(&host, &event)` after `poll`. `vendor/window/events` defines kinds,
modifier bits and normalized special keys. `window.Event` owns its text bytes,
so copying an event retains its text across later polls and drains. Text chunks
end on UTF-8 code point boundaries and hold at most 256 bytes. Printable committed
text is distinct from raw key events; editing/control keys arrive as keys.
Native scancodes are platform-specific. Unknown legacy X11 keysyms may have key
zero while retaining the native scancode and any committed text.

The queue retains 128 events across polls. On exhaustion it drops new arrivals
until the retained queue and one `Overflow` event have been drained. The
saturating `dropped` counter counts dropped records; rejecting an oversized
native commit before chunking counts one lost commit, rather than lost bytes.
Treat overflow as input loss, including possible key transitions; it cannot
reconstruct the lost input. Switching listening on or off clears the queue.
Listening starts disabled, so applications using only `box_input` retain their
existing idle behavior. Listening applications must drain the queue before
blocking in `wait`.

X11 accepts input-method commits up to 4096 bytes. Wayland compose results must
fit 63 bytes plus a NUL terminator; larger commits report overflow explicitly.
Win32 expands native coalesced repeat counts while retaining bounded overflow
accounting. Cocoa retains the native repeat indication; Wayland generates
repeats using compositor-provided rate and delay. X11 uses detectable repeat
when the server supports it; other servers may deliver release/press pairs.
No backend
exposes IME preedit text, selection or candidate-window placement through this
API. Wayland provides xkb compose input, not the text-input protocol. This API
therefore does not yet establish DNA's full input-method parity.

`wake(&host)` interrupts `wait`, whether ordered listening is enabled or not.
When listening, subsequent polling produces a `Wake` event; multiple wakes may
coalesce. It is the only supported cross-thread window operation. The owning
window must outlive all wake callers: stop and join workers before `close`.
Continue polling/draining on the GUI thread. Clipboard retrieval still uses the
existing clipboard/`box_input` API, rather than an ordered clipboard event.

`tests/window-events.py` checks bounded queues, UTF-8 chunks, native C/Dyn ABI,
production XIM/compose overflow paths, X11 ordered input, Win32 repeat counts and
worker wake-ups on available hosts. `tests/window-desktop-results.py` also tests
the Dyn-to-native wake/event round trip for its selected backend. Native Cocoa
and real Windows execution require their CI hosts; Wine and cross-builds are
separate evidence.
