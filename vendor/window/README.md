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
## Input methods and ordered clipboard replies

`set_text_input(&host, enabled, x, y, width, height)` enables a focused field and
places its candidate rectangle in physical window pixels. Caret-only updates
preserve composition. When focus changes between text widgets, disable the old
field before enabling the new one, even if both fields accept text. Existing
clients retain legacy text input until they configure it; explicit disable
suppresses text commits while raw keys remain available.

`composition(&host)` returns the latest polled preedit snapshot. The shared
`Composition` ABI holds 256 UTF-8 bytes, a byte length, two byte cursor offsets
and an active integer. A cursor offset of -1 hides it. Truncation preserves
code point boundaries and clamps cursor offsets. In the ordered stream, each
`Composition` event owns that exact snapshot. Decode it with
`events.composition(&event)`; later updates cannot overwrite an earlier event.
XIM callbacks are emitted in callback order, including a clear before commit.

X11 negotiates XIM callbacks, then over-the-spot placement, using the configured
locale and `XMODIFIERS`. Callback character counts, feedback-only changes and
caret directions follow the [Xlib input-method contract](https://www.x.org/releases/X11R7.6/doc/libX11/specs/libX11/libX11.pdf).
Locale multibyte strings are converted to Unicode before UTF-8 encoding. XIM
preedit storage retains at most 128 code points; over-capacity edits report
loss through the ordered overflow mechanism. Wayland uses text-input-v3 when
available and xkb compose otherwise; Win32 uses IMM; Cocoa implements
NSTextInputClient. Surrounding-text correction uses revision-checked Edit events as described below.
Applications must publish fresh context and validate each proposed edit.

`box_input` supplies preedit plus `composition_handled`, including the poll that
clears it. Text fields show a replacement preview without modifying caller
storage, suppress IME-consumed editing/submission keys, and insert only committed
text. Unchanged preedit stays idle; changed text or cursor schedules a frame.
The finalized layout supplies the candidate rectangle. `examples/box-viewer`
shows the focus/rectangle calls.

`Clipboard` events own reply chunks. `x` is the byte offset, `width` the total
reply length, and `button == 1` marks the final chunk, including an empty reply.
Assemble a complete reply before applying it. Discard incomplete assembly on
`Overflow`; the fixed queue cannot retain every large reply. `clipboard(&host)`
is a compatibility view of the latest reply, borrowed until another paste
request/reply or close. X11 and Wayland allow one outstanding remote transfer;
an overlapping request reports overflow instead of corrupting its partial data.
X11 and Wayland snapshots support up to 16 MiB; Windows and Cocoa retain a
64 KiB bound. X11 supports incremental (INCR) clipboard transfers.

Production callback and protocol mocks exercise composition, caret placement,
UTF-8 clipping and reply ordering. Real ibus/fcitx and native Windows/macOS IME
sessions are not automated here; native Cocoa execution remains CI work.

`wake(&host)` interrupts `wait`, whether ordered listening is enabled or not.
When listening, subsequent polling produces a `Wake` event; multiple wakes may
coalesce. It is the only supported cross-thread window operation. The owning
window must outlive all wake callers: stop and join workers before `close`.
Continue polling/draining on the GUI thread. Clipboard replies are available as owned ordered chunks and through the
existing compatibility snapshot API.

`tests/window-events.py` checks bounded queues, UTF-8 chunks, native C/Dyn ABI,
production XIM/compose overflow paths, X11 ordered input, Win32 repeat counts and
worker wake-ups on available hosts. `tests/window-desktop-results.py` also tests
the Dyn-to-native wake/event and owned clipboard round trips for its selected backend. Native Cocoa
and real Windows execution require their CI hosts; Wine and cross-builds are
separate evidence.

### Surrounding-text corrections

Ordered clients can publish `window.Surrounding` through
`set_surrounding_text(&host, context)`. Enable `listen_events` first. Contexts
contain owned-on-publication UTF-8 text, cursor and anchor byte offsets, a nonzero
revision token, and `std/text/edit.Cause`. The shared limit is 4096 bytes;
Wayland accepts at most 4000 bytes. Native contexts reject embedded NUL bytes.
Wayland and Cocoa support corrections. Windows supports IMM document feed and
selected-range reconversion, including IME-confirmed range expansion; collapsed
reconversion is rejected without guessing word boundaries. X11 returns `Unsupported`;
preedit and ordinary committed text remain available. See the
[XIM investigation](../../docs/internals/xim-surrounding-support.md).

`events.Kind.Edit` retains the 312-byte event ABI. `key` and `modifiers` encode
low/high halves of the context token; `x`/`y` identify the replaced byte range;
`width` is total replacement length; `scancode` is chunk offset; `button == 1`
marks the final chunk. Native producers enqueue the complete replacement or
report overflow. Feed events in order through `events.collect_edit`; its ready
replacement borrows collector storage until the next Edit. Overflow discards
partial assembly. Do not apply a correction from an aggregate keyboard summary.

`std/text/edit.Tracker` publishes bounded snapshots with stable tokens for an
unchanged owner, text and selection. Changing any of those produces a fresh
token. `apply` validates revision, UTF-8 boundaries and capacity before mutation;
rejected replacements preserve bytes and metadata. Successful replacements
consume the buffer token. Publish a fresh snapshot after every correction.
Never reuse a token for different text or selection.

The box textbox exposes its current snapshot as `State.text_context`. Pass one
assembled replacement in an isolated `Input.correction` step, without text or
editing keys. `FieldSignal.correction_error` reports rejection; successful
corrections publish `Cause.InputMethod`. Consume ordered input before publishing
that snapshot and updating native text input/caret state. On focus changes,
disable the old native context, publish the new context, then enable text input.
The summary-based box viewer does not enable surrounding corrections.

Wayland matches corrections against committed protocol serials and rejects stale
history. Cocoa maps UTF-16 native ranges to UTF-8 boundaries; partial replacement
inside active marked text reports overflow. Real macOS IME behavior still needs
native runtime qualification.

The X11 facade also exposes GUI-thread `set_title` and `set_size`. Titles use
bounded NUL-free UTF-8 conversion; dimensions must be within 1..16384. Size
requests are synchronized with Xlib and current events are polled, but a window
manager may constrain or defer the requested dimensions. Observe actual size
through subsequent polls. These metadata operations are currently X11-specific.

For prerequisites and manual real-engine acceptance, see
[IME session qualification](../../docs/internals/ime-session-qualification.md).
`tests/ime-session-probe.py` reports installed engines and display services;
its inventory is not a qualification result.

### Large X11 clipboard snapshots

X11 supports owned clipboard snapshots up to 16 MiB and four concurrent outgoing
INCR transfers. Each outgoing transfer owns its original snapshot, so changing
the offer does not change bytes already being sent. `try_set_clipboard` returns
a result before replacing the offer; the compatibility `set_clipboard` wrapper
discards that result. Use the checked operation when copying is part of a
destructive editor action.

After `request_paste`, `paste_pending` stays true until completion or failure.
`paste_status` reports the result; `clipboard` retains the previous completed
snapshot on failure. A successful empty reply replaces it with an empty view.
The ordered queue remains bounded: a large reply that cannot fit produces
Overflow without partial Clipboard events. Snapshot clients can read the full
completed value separately; ordered clients must handle overflow explicitly.
Wayland has the same 16 MiB snapshot bound; Windows and Cocoa retain 64 KiB.

`request_paste_snapshot` requests the same complete value without emitting
Clipboard chunks; use it when an ordered client deliberately reads the completed
snapshot itself. Other input and overflow events remain enabled. A live sender
that never finishes INCR can leave a request pending until owner destruction or
window closure; receive memory and simultaneous outgoing transfers stay bounded.

### X11 presentation pacing

`set_swap_interval(window, interval)` selects immediate presentation (0) or one
refresh interval (1) on the owning GLX drawable and leaves that context current.
Call on the serialized GUI thread. It checks advertised extension tokens before
loading EXT/MESA/SGI procedures; SGI alone cannot disable synchronization. Missing
capability returns `Unsupported`, while X/GLX errors return `System`. Driver or
compositor policy can still override requested pacing. See the
[Khronos swap-control contract](https://github.com/KhronosGroup/OpenGL-Registry/blob/main/extensions/EXT/EXT_swap_control.txt).

### Native controls and checked clipboard

Wayland, Windows and Cocoa expose `set_title`, `set_size` and
`set_swap_interval`. Size results reflect the actual polled frame; a compositor
may reject client sizing in constrained states. Presentation pacing is subject
to compositor and driver policy. Calls belong on the owning GUI thread.

The native facades expose `try_set_clipboard`, `request_paste_snapshot`,
`paste_pending` and `paste_status`. Checked publication validates UTF-8 and
rejects embedded NUL bytes. A failed read retains the last completed snapshot.
Snapshot requests suppress Clipboard events while retaining other queued input.
Windows and Cocoa report Capacity above 64 KiB rather than silently truncating.
The older native `set_clipboard` compatibility operation still truncates at
64 KiB; use the checked operation for editor copy/cut workflows.

Wayland owns dynamic snapshots up to 16 MiB. Eight nonblocking outgoing sends
retain immutable copies. Incoming transfers complete atomically and fail after
five seconds without progress. Ordered delivery emits all chunks or Overflow,
never an incomplete prefix. Standard Wayland selection publication requires a
valid seat input serial; publication before input returns InvalidState. Wayland
provides no declared transfer length, so EOF after a valid UTF-8 prefix cannot
prove that a sender intended more bytes.

Native Wayland, Windows and Cocoa KeyDown/KeyUp events capture a translated
Unicode scalar in `height`;
`events.character` reads it. The snapshot preserves the keyboard layout and
modifier state at production time even when later events change that state.
`key` remains the unshifted identity; the event ABI remains 312 bytes.


Windows queries the current keyboard state and layout without changing dead-key
state, using the Windows 10 version 1607+ `ToUnicodeEx` flag. Plain Ctrl shortcuts
retain their layout character; Ctrl+Alt is retained for AltGr. Coalesced repeats
copy the same snapshot. Dead-key output, malformed UTF-16 and multi-scalar
translations have no single character and report zero. WM_CHAR and IME text
remain separate. See [Microsoft's ToUnicodeEx contract](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-tounicodeex).

Cocoa reads the key event's character string, retaining Shift, Option and Caps
Lock while excluding Control/Command control-character effects. Function-key
codes, controls, malformed UTF-16 and multi-scalar strings report zero. IME text
continues through NSTextInputClient. See [Apple's event character contract](https://developer.apple.com/documentation/appkit/nsevent/characters(byapplyingmodifiers:)).
Windows production-path tests use controlled keyboard APIs under Wine; Cocoa's
UTF-16 conversion is tested portably. Neither qualifies actual desktop keyboard
layouts or IME/dead-key sessions on those hosts.
