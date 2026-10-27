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
  DYN_KEY_PASTE = 1 << 13
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
