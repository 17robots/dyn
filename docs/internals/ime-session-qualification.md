# Real input-method qualification

The production callback and protocol oracles are useful regression checks. They
do not qualify an operating system input method running in an interactive
session. `tests/ime-session-probe.py` inventories prerequisites without opening
windows, changing focus, starting services or sending input. Its JSON always
reports `qualification: not-run`; exit status zero means the inventory completed.

Run:

```sh
python3 tests/ime-session-probe.py --output build/ime-session-prerequisites.json
```

## Local evidence, 2026-10-27

The development host is Linux x86_64 with libX11 1.8.14, an X11 display and a
Wayland display. `xcrun`, `ibus` and `fcitx5` are absent from PATH. No IBus/Fcitx
process was found. The X11 root has no `_XIM_SERVERS` atom, and the session bus
advertises no IBus/Fcitx names. IBus can use a separate bus, so session-bus absence
alone does not prove absence; the combined observations provide no real engine
available to qualify here. Native macOS execution is unavailable on this host.

The macOS host workflow runs `tests/window-surround-native.py`, including its
Cocoa production callback oracle. That oracle validates embedded-NUL rejection
without mutating the original context. It does not select a system input source
or exercise native candidate UI. CI registration alone is not evidence that a
particular remote run passed.

## Native session acceptance procedure

Use a disposable test document in an interactive native desktop session. Record
OS version, input-source name/version, display scale, compiler revision and the
prerequisite inventory. Use an ordered-event client that publishes surrounding
contexts and consumes Edit transactions; the existing aggregate-input box viewer
does not enable surrounding corrections.

1. Compose non-ASCII text, move the preedit caret, choose a candidate and commit.
   Check the candidate window follows the application caret, including after
   resize and scale changes. Verify preedit is not inserted into document text.
2. Cancel composition with Escape and switch focus between two text fields.
   Verify no stale preedit, duplicated commit or command-key action occurs.
3. Select text containing a supplementary character, then trigger an input-method
   correction/reconversion that replaces the selection or neighboring text.
   Verify the exact UTF-8 replacement range and one committed Edit transaction.
4. Change document text or selection after publication, then deliver an older
   correction. Verify revision rejection and unchanged document bytes.
5. Exercise clipboard delivery during composition and repeated focus changes.
   Verify event order, complete clipboard contents and refreshed context tokens.
6. Capture the ordered event trace and final bytes for each case. Mark a feature
   unqualified when the chosen input source cannot trigger it. A callback mock,
   Wine run or cross-build must remain a separately labeled result.

The Cocoa adapter rejects partial replacement inside active marked text. Record
that case as an explicit limitation rather than a passing full-reconversion test.

## X11 alternative transport

The [audited XIM reply path](xim-surrounding-support.md) still contains unsafe
serialization and feedback handling in the pinned upstream source. The installed
version number does not establish that a downstream build fixes those defects.
The backend must keep returning `Unsupported` until a safe transport is shipped
and qualified.

A direct IBus client is a plausible separate backend: its public
[InputContext API](https://ibus.github.io/docs/ibus-1.5/IBusInputContext.html)
provides surrounding text and selection publication plus deletion notifications.
It uses character offsets, requiring explicit mapping to the shared UTF-8 byte
ranges. This is not a drop-in XIM callback: it needs its own context ownership,
key filtering, focus, asynchronous replies, event-loop integration and engine
qualification. No IBus adapter currently exists in this repository. Advertising
X11 correction support before implementing those pieces would be misleading.
