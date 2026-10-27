# Shared desktop UI and DNA migration

The migration keeps application rendering and platform replacement separate.
DNA first uses shared box layout while retaining SDL/SDL_ttf and its editor,
terminal and preview drawing. Native window and font replacement follows in
separate steps, with real application checks at each step.

## Shared implementation

`std/ui/box` provides keyed state, layout, animation, virtual lists and widgets.
Text fields support UTF-8 byte-boundary editing, mouse and Shift selection,
Unicode 17 word boundaries, selected copy/cut/paste and horizontal scrolling.
Accepted replacement input is copied before mutation, including when a paste
view aliases the field buffer. Invalid UTF-8, multiline input and replacements
that exceed capacity preserve the original text and selection. Copy and cut
without a selection retain the original whole-field behavior.

Tab and Shift-Tab traverse controls from the previous frame's tree. Enter
activates focused buttons; sliders and splitters accept Left/Right. Focus
traversal does not implement a modal focus trap or accessibility integration.
Menus close through their trigger, an item or Escape; outside-click dismissal
and tooltip delay remain application policy. Overlays should be built last.

`layout(state)` finalizes geometry and input without emitting draw commands;
`render(state, context)` emits the finalized tree. `end` combines them.
Container padding uses physical pixels. `AbsoluteX`/`AbsoluteY` position floating
children in screen coordinates. `GreedyShrink` opts a container into consuming
zero-strictness children in build order before proportional shrinking. These
options let DNA retain its established panel geometry at the adapter boundary.

`std/font/system` scans standard platform directories or caller-selected
roots, returns arena-owned family/style metadata, and matches weight and slant.
Fallback selection checks the actual cmap. Directory traversal skips unreadable
files, is capped by entry count and depth, and does not follow symlink
directories. Only faces supported by `std/font` are returned: CFF OpenType,
collections and variable-font behavior remain unsupported. Platform font
registries and fontconfig configuration are not interpreted. Fallback order
is caller-controlled; otherwise enumeration follows filesystem order.

The box-viewer demo now discovers its default font instead of using a fixed
Linux font path. Native keyboard transports expose Ctrl for word editing on
Linux/Windows and Option on Cocoa.

## Verification

Focused contracts cover font metadata ownership and malformed UTF-16,
truncated font tables, recursive discovery, caps, weight/slant matching and
actual glyph coverage. Editing contracts cover mouse release movement,
selection replacement, aliased paste, word edits, clipping, focus traversal,
and padded/absolute/ordered-shrink geometry. They execute on Linux, emulated
ARM64/RISC-V64, Wine and WASI where applicable, with desktop cross-builds.

A separate review found and corrected hit-testing of absolute children under
unclipped parents and paste corruption from aliasing. DNA's adapter review
found and corrected later panels overwriting earlier panels' geometry; its
production UI regression checks multiple roots in one frame.

The native-host qualification runner now includes the new UI and font
contracts: 21 fixtures, each in debug, O2 and O3. Native macOS and real Windows
execution still require their CI hosts; cross-builds and Wine do not establish
native OS behavior. On 2026-10-27 the registered compiler regression suite passed. Its early UI
checks preceded the final pointer-release adjustment; the box, editing, extras
and batched-renderer gates were rerun successfully on the final UI source.
The optional Unicorn check skipped in the default environment and passed
separately through an isolated `uv --with unicorn` run. This is emulation,
not physical board execution. Local logs are retained under
`build/ui-dna-qualification/`.

## Remaining platform work

DNA now builds persistent shared boxes directly. Its private key hashing,
linear identity lookup, temporary geometry arrays, fixed label buffer and hit
scan are removed. The shared cache supplies current-frame lookup, numeric/raw
identities, caller handles and expiry/recycling. DNA retains only indexed
application metadata, configurable tweens and its custom SDL renderer. The
production cache oracle checks 40 KB owned text, stable duplicate identities,
multiple panels, bounded key churn and release/rebuild.

DNA's application records and custom drawing remain intentional during this
transition. Completing native presentation requires replacing SDL window,
event and rendering calls one platform at a time, preserving editor/terminal
rendering, input methods, clipboard and font shaping/fallback behavior. Offscreen
Vulkan is not an onscreen presentation backend. Collection/CFF fonts need a
separate supported-font path before platform font parity can be claimed.
