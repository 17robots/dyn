#ifndef DYN_WINDOW_H
#define DYN_WINDOW_H
#include <stdint.h>
#ifdef _WIN32
#define DYN_WINDOW_EXPORT __declspec(dllexport)
#else
#define DYN_WINDOW_EXPORT
#endif
typedef struct dyn_window_frame {
  int32_t width, height, x, y;
  uint32_t flags;
} dyn_window_frame;
enum {
  DYN_DOWN = 1,
  DYN_PRESSED = 2,
  DYN_RELEASED = 4,
  DYN_TAB = 8,
  DYN_ACTIVATE = 16,
  DYN_LEFT = 32,
  DYN_RIGHT = 64,
  DYN_CLOSE = 128
};
/* Ordered event ABI, mirrored by vendor/window/events.Event. Text is copied
 * into caller storage; the queue survives polls. Overflow drops newest events,
 * then reports a saturating dropped count after the retained queue drains. */
enum { DYN_EVENT_NONE, DYN_EVENT_KEY_DOWN, DYN_EVENT_KEY_UP, DYN_EVENT_TEXT,
 DYN_EVENT_POINTER_MOVE, DYN_EVENT_POINTER_DOWN, DYN_EVENT_POINTER_UP,
 DYN_EVENT_WHEEL, DYN_EVENT_FOCUS_GAINED, DYN_EVENT_FOCUS_LOST,
 DYN_EVENT_RESIZE, DYN_EVENT_CLOSE, DYN_EVENT_WAKE, DYN_EVENT_OVERFLOW,
 /* A requested paste arrived, or the input method composition changed.
  * Clipboard events own text chunks: x=byte offset, width=total reply bytes,
  * button=1 on final chunk. Composition events own a snapshot: x/y=cursor
  * byte offsets (-1 hidden), width=active. The Event ABI remains 312 bytes. */
 DYN_EVENT_CLIPBOARD, DYN_EVENT_COMPOSITION, DYN_EVENT_EDIT };
enum { DYN_MOD_SHIFT=1, DYN_MOD_CONTROL=2, DYN_MOD_ALT=4, DYN_MOD_SUPER=8,
 DYN_MOD_CAPS=16, DYN_MOD_NUM=32 };
enum { DYN_ESCAPE=0x110000, DYN_ENTER, DYN_TAB_KEY, DYN_BACKSPACE,
 DYN_DELETE, DYN_LEFT_KEY, DYN_RIGHT_KEY, DYN_UP_KEY, DYN_DOWN_KEY,
 DYN_HOME, DYN_END, DYN_PAGE_UP, DYN_PAGE_DOWN, DYN_INSERT,
 DYN_F1=0x110020, DYN_SHIFT_KEY=0x110040, DYN_CONTROL_KEY,
 DYN_ALT_KEY, DYN_SUPER_KEY };
typedef struct dyn_window_event {
 uint32_t kind,key,scancode,modifiers,repeated,button,dropped;
 int32_t x,y,width,height;
 float scroll_x,scroll_y;
 uint32_t text_length;
 uint8_t text[256];
} dyn_window_event;
enum { DYN_EVENT_CAPACITY=128 };
/* Listening is opt-in, default off so summary-only clients retain idle wait.
 * Changing enabled clears the retained queue; enable before polling input. */
DYN_WINDOW_EXPORT void dyn_window_listen_events(void *, int32_t enabled);
/* GUI-thread drain; may be called independently of poll. */
DYN_WINDOW_EXPORT int32_t dyn_window_next_event(void *, dyn_window_event *);
/* The only cross-thread operation. Owner must outlive all wake callers;
 * serialize close after joining them. Wakes may coalesce, never carry data. */
DYN_WINDOW_EXPORT int32_t dyn_window_wake(void *);
/* Input method composition. Committed text still arrives as text input; the
 * composition is the in-progress preedit the application draws at its caret.
 * Cursor offsets are bytes into text; -1 hides the cursor. */
typedef struct dyn_window_composition {
  uint8_t text[256];
  uint32_t text_length;
  int32_t cursor_begin, cursor_end;
  uint32_t active;
} dyn_window_composition;
/* Snapshot of the current composition; inactive when none. */
DYN_WINDOW_EXPORT void dyn_window_composition_get(void *, dyn_window_composition *);
/* The most recent pasted text, borrowed until the next paste request/reply or close. */
DYN_WINDOW_EXPORT uint32_t dyn_window_clipboard_get(void *, const uint8_t **);
/* Enables or disables text input, and places the caret rectangle (physical
 * window pixels) where the input method shows its candidate window. Call when
 * a text field gains focus and whenever its caret moves. */
DYN_WINDOW_EXPORT void dyn_window_set_text_input(void *, int32_t enabled, int32_t x, int32_t y, int32_t width, int32_t height);
/* Publishes an owned UTF-8 document snapshot for ordered IME corrections.
 * Requires ordered listening and a nonzero fresh context token. Cursor/anchor
 * are byte boundaries. 1 success, 0 invalid/state, -1 unsupported, -2 capacity.
 * Edit events retain the 312-byte ABI: key/modifiers hold token low/high32,
 * x/y replacement range, width replacement byte length, scancode chunk offset,
 * button final chunk. A complete edit is queued atomically or reports overflow. */
DYN_WINDOW_EXPORT int32_t dyn_window_set_surrounding_text(void *, const uint8_t *, uint32_t length, uint32_t cursor, uint32_t anchor, uint64_t token, uint32_t cause);
/* Desktop input since the last dyn_window_desktop call, which clears it. */
enum {
  DYN_KEY_BACKSPACE = 1 << 0,
  DYN_KEY_DELETE = 1 << 1,
  DYN_KEY_LEFT = 1 << 2,
  DYN_KEY_RIGHT = 1 << 3,
  DYN_KEY_HOME = 1 << 4,
  DYN_KEY_END = 1 << 5,
  DYN_KEY_ENTER = 1 << 6,
  DYN_KEY_ESCAPE = 1 << 7,
  DYN_KEY_TAB = 1 << 8,
  DYN_KEY_SHIFT = 1 << 9,
  DYN_KEY_SELECT_ALL = 1 << 10,
  DYN_KEY_COPY = 1 << 11,
  DYN_KEY_CUT = 1 << 12,
  DYN_KEY_PASTE = 1 << 13,
  /* Ctrl on X11/Wayland/Win32; Option on Cocoa for word movement. */
  DYN_KEY_CONTROL = 1 << 14,
  /* Composition consumed keyboard editing during this poll. */
  DYN_KEY_IME = 1 << 15
};
enum { DYN_TEXT_LIMIT = 256, DYN_CLIPBOARD_LIMIT = 65536 };
typedef struct dyn_window_desktop {
  uint8_t text[DYN_TEXT_LIMIT];
  uint32_t text_length;
  uint32_t keys;
  float scroll_x, scroll_y;
  float scale;
  /* Borrowed until the next call; set when keys has DYN_KEY_PASTE. */
  const uint8_t *clipboard;
  uint32_t clipboard_length;
} dyn_window_desktop;
/* Cursor shapes: arrow, text, hand, horizontal resize, vertical resize. */
enum { DYN_CURSOR_ARROW, DYN_CURSOR_TEXT, DYN_CURSOR_HAND, DYN_CURSOR_RESIZE_X, DYN_CURSOR_RESIZE_Y };
DYN_WINDOW_EXPORT void dyn_window_desktop_take(void *, dyn_window_desktop *);
DYN_WINDOW_EXPORT void dyn_window_set_clipboard(void *, const uint8_t *, uint32_t);
DYN_WINDOW_EXPORT void dyn_window_request_paste(void *);
DYN_WINDOW_EXPORT void dyn_window_set_cursor(void *, int32_t);
/* Blocks until input or timeout milliseconds; negative waits indefinitely. */
DYN_WINDOW_EXPORT void dyn_window_wait(void *, int32_t);
DYN_WINDOW_EXPORT void *dyn_window_open(const char *, int32_t, int32_t);
DYN_WINDOW_EXPORT void dyn_window_close(void *);
DYN_WINDOW_EXPORT int32_t dyn_window_poll(void *, dyn_window_frame *);
DYN_WINDOW_EXPORT int32_t dyn_window_current(void *);
DYN_WINDOW_EXPORT int32_t dyn_window_swap(void *);
DYN_WINDOW_EXPORT void *dyn_window_proc(const char *);
#endif
