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
DYN_WINDOW_EXPORT void *dyn_window_open(const char *, int32_t, int32_t);
DYN_WINDOW_EXPORT void dyn_window_close(void *);
DYN_WINDOW_EXPORT int32_t dyn_window_poll(void *, dyn_window_frame *);
DYN_WINDOW_EXPORT int32_t dyn_window_current(void *);
DYN_WINDOW_EXPORT int32_t dyn_window_swap(void *);
DYN_WINDOW_EXPORT void *dyn_window_proc(const char *);
#endif
