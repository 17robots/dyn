/* Shared accumulation helpers for the native desktop input bridges. */
#ifndef DYN_DESKTOP_COMMON_H
#define DYN_DESKTOP_COMMON_H
#include "window.h"
#include <string.h>
typedef struct Desktop {
  dyn_window_desktop pending;
  dyn_window_event events[DYN_EVENT_CAPACITY];
  uint32_t event_head, event_count, event_dropped;
  int event_enabled;
  uint8_t owned[DYN_CLIPBOARD_LIMIT];
  uint32_t owned_length;
  uint8_t received[DYN_CLIPBOARD_LIMIT];
  uint32_t received_length;
  int receiving;
} Desktop;
static inline void desktop_listen(Desktop *d,int enabled) {
  enabled=enabled!=0;
  if (d->event_enabled!=enabled) {
    d->event_enabled=enabled; d->event_head=d->event_count=d->event_dropped=0;
  }
}
static inline void desktop_push(Desktop *d, dyn_window_event event) {
  if (!d->event_enabled) return;
  if (d->event_count == DYN_EVENT_CAPACITY || d->event_dropped) {
    if (d->event_dropped != UINT32_MAX) d->event_dropped++;
    return;
  }
  d->events[(d->event_head+d->event_count)%DYN_EVENT_CAPACITY]=event;
  d->event_count++;
}
static inline int desktop_next(Desktop *d, dyn_window_event *out) {
  if (d->event_count) {
    *out=d->events[d->event_head];
    d->event_head=(d->event_head+1)%DYN_EVENT_CAPACITY;
    d->event_count--;
    return 1;
  }
  if (d->event_dropped) {
    memset(out,0,sizeof(*out)); out->kind=DYN_EVENT_OVERFLOW;
    out->dropped=d->event_dropped; d->event_dropped=0; return 1;
  }
  return 0;
}
static inline void desktop_simple(Desktop *d, uint32_t kind) {
  dyn_window_event event={0}; event.kind=kind; desktop_push(d,event);
}
static inline void desktop_key(Desktop *d, int down, uint32_t key, uint32_t scan, uint32_t modifiers, int repeated) {
  dyn_window_event event={0}; event.kind=down?DYN_EVENT_KEY_DOWN:DYN_EVENT_KEY_UP;
  event.key=key; event.scancode=scan; event.modifiers=modifiers; event.repeated=(uint32_t)(repeated!=0); desktop_push(d,event);
}
static inline void desktop_pointer(Desktop *d, uint32_t kind, int32_t x, int32_t y, uint32_t button, uint32_t modifiers) {
  dyn_window_event event={0}; event.kind=kind; event.x=x; event.y=y; event.button=button; event.modifiers=modifiers; desktop_push(d,event);
}
static inline void desktop_wheel(Desktop *d, float x, float y) {
  dyn_window_event event={0}; event.kind=DYN_EVENT_WHEEL; event.scroll_x=x; event.scroll_y=y; desktop_push(d,event);
}
static inline void desktop_resize(Desktop *d, int32_t width, int32_t height) {
  dyn_window_event event={0}; event.kind=DYN_EVENT_RESIZE; event.width=width; event.height=height; desktop_push(d,event);
}
static inline void desktop_text(Desktop *d, const uint8_t *bytes, size_t length) {
  if (!length || bytes[0] < 32 || bytes[0] == 127) return;
  /* Summary clients keep the leading UTF-8 prefix that fits, independently
   * of ordered chunk boundaries. Never skip a head chunk and append its tail. */
  size_t prefix=length;
  if (prefix>DYN_TEXT_LIMIT-d->pending.text_length) prefix=DYN_TEXT_LIMIT-d->pending.text_length;
  if (prefix<length) while(prefix && (bytes[prefix]&0xc0)==0x80) prefix--;
  memcpy(d->pending.text+d->pending.text_length,bytes,prefix);
  d->pending.text_length+=(uint32_t)prefix;
  size_t at=0;
  while (at<length) {
    size_t count=length-at;
    if (count>256) {
      count=256;
      while (count && (bytes[at+count]&0xc0)==0x80) count--;
    }
    if (!count) return;
    dyn_window_event event={0}; event.kind=DYN_EVENT_TEXT; event.text_length=(uint32_t)count;
    memcpy(event.text,bytes+at,count); desktop_push(d,event);
    at+=count;
  }
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
/* Copies UTF-8 preedit into a composition snapshot, truncated at a code point
 * boundary; cursor offsets past the cut are clamped. */
static inline void composition_store(dyn_window_composition *out, const uint8_t *text, size_t length,
                                     int32_t begin, int32_t end) {
  if (length > sizeof(out->text)) {
    length = sizeof(out->text);
    /* Never split a code point: back off while the next byte continues one. */
    while (length > 0 && (text[length] & 0xc0) == 0x80)
      length--;
  }
  memcpy(out->text, text, length);
  out->text_length = (uint32_t)length;
  out->cursor_begin = begin < 0 ? -1 : (size_t)begin > length ? (int32_t)length : begin;
  out->cursor_end = end < 0 ? -1 : (size_t)end > length ? (int32_t)length : end;
  out->active = length > 0;
}
#endif
