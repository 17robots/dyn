/* Shared accumulation helpers for the native desktop input bridges. */
#ifndef DYN_DESKTOP_COMMON_H
#define DYN_DESKTOP_COMMON_H
#include "window.h"
#include <string.h>
typedef struct Desktop {
  dyn_window_desktop pending;
  uint8_t owned[DYN_CLIPBOARD_LIMIT];
  uint32_t owned_length;
  uint8_t received[DYN_CLIPBOARD_LIMIT];
  uint32_t received_length;
  int receiving;
} Desktop;
static inline void desktop_text(Desktop *d, const uint8_t *bytes, size_t length) {
  if (!length || bytes[0] < 32 || bytes[0] == 127)
    return;
  for (size_t i = 0; i < length && d->pending.text_length < DYN_TEXT_LIMIT; ++i)
    d->pending.text[d->pending.text_length++] = bytes[i];
}
static inline void desktop_codepoint(Desktop *d, uint32_t c) {
  uint8_t b[4];
  size_t n = 0;
  if (c < 0x80) {
    b[n++] = (uint8_t)c;
  } else if (c < 0x800) {
    b[n++] = (uint8_t)(0xc0 | c >> 6);
    b[n++] = (uint8_t)(0x80 | (c & 63));
  } else if (c < 0x10000) {
    if (c >= 0xd800 && c <= 0xdfff)
      return;
    b[n++] = (uint8_t)(0xe0 | c >> 12);
    b[n++] = (uint8_t)(0x80 | (c >> 6 & 63));
    b[n++] = (uint8_t)(0x80 | (c & 63));
  } else if (c < 0x110000) {
    b[n++] = (uint8_t)(0xf0 | c >> 18);
    b[n++] = (uint8_t)(0x80 | (c >> 12 & 63));
    b[n++] = (uint8_t)(0x80 | (c >> 6 & 63));
    b[n++] = (uint8_t)(0x80 | (c & 63));
  } else {
    return;
  }
  desktop_text(d, b, n);
}
static inline void desktop_own(Desktop *d, const uint8_t *text, uint32_t length) {
  if (length > DYN_CLIPBOARD_LIMIT)
    length = DYN_CLIPBOARD_LIMIT;
  memcpy(d->owned, text, length);
  d->owned_length = length;
}
static inline void desktop_deliver(Desktop *d) {
  d->pending.keys |= DYN_KEY_PASTE;
  d->pending.clipboard = d->received;
  d->pending.clipboard_length = d->received_length;
}
static inline void desktop_take(Desktop *d, dyn_window_desktop *out, float scale) {
  d->pending.scale = scale;
  *out = d->pending;
  uint32_t modifiers = d->pending.keys & (DYN_KEY_SHIFT | DYN_KEY_CONTROL);
  memset(&d->pending, 0, sizeof(d->pending));
  d->pending.keys = modifiers;
}
#endif
