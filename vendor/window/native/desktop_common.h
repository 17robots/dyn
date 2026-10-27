/* Shared accumulation helpers for the native desktop input bridges. */
#ifndef DYN_DESKTOP_COMMON_H
#define DYN_DESKTOP_COMMON_H
#include "window.h"
#include <string.h>
enum { DYN_SURROUND_LIMIT = 4096 };
typedef struct Surrounding {
  uint8_t text[DYN_SURROUND_LIMIT + 1];
  uint32_t length, cursor, anchor;
  uint64_t token;
} Surrounding;
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
  Surrounding surrounding;
  uint64_t consumed_token;
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
static inline void desktop_key_character(Desktop *d, int down, uint32_t key, uint32_t scan, uint32_t modifiers, int repeated, uint32_t character) {
  dyn_window_event event={0}; event.kind=down?DYN_EVENT_KEY_DOWN:DYN_EVENT_KEY_UP;
  event.key=key; event.scancode=scan; event.modifiers=modifiers; event.repeated=(uint32_t)(repeated!=0);
  if (character <= 0x10ffff && !(character >= 0xd800 && character <= 0xdfff))
    event.height=(int32_t)character;
  desktop_push(d,event);
}
static inline void desktop_key(Desktop *d, int down, uint32_t key, uint32_t scan, uint32_t modifiers, int repeated) {
  desktop_key_character(d,down,key,scan,modifiers,repeated,0);
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
static inline void desktop_deliver_mode(Desktop *d, int emit) {
  d->pending.keys |= DYN_KEY_PASTE;
  d->pending.clipboard = d->received;
  d->pending.clipboard_length = d->received_length;
  if (!emit) return;
  /* Each event owns its reply bytes even when another reply arrives before
   * the application drains this queue. x is the byte offset, width the total
   * reply size, and button marks the final chunk (also emitted for empty text). */
  size_t at = 0;
  do {
    size_t count = d->received_length - at;
    if (count > sizeof(((dyn_window_event *)0)->text)) {
      count = sizeof(((dyn_window_event *)0)->text);
      while (count && (d->received[at + count] & 0xc0) == 0x80) count--;
      /* Invalid clipboard encodings must still make bounded progress. */
      if (!count) count = sizeof(((dyn_window_event *)0)->text);
    }
    dyn_window_event event = {0};
    event.kind = DYN_EVENT_CLIPBOARD;
    event.x = (int32_t)at;
    event.width = (int32_t)d->received_length;
    event.text_length = (uint32_t)count;
    memcpy(event.text, d->received + at, count);
    at += count;
    event.button = at == d->received_length;
    desktop_push(d, event);
  } while (at < d->received_length);
}
static inline void desktop_deliver(Desktop *d) { desktop_deliver_mode(d, 1); }
/* UTF-8 validation is independent of process locale and rejects embedded NUL,
 * since the Wayland surrounding-text wire value is a NUL-terminated string. */
static inline int surrounding_utf8(const uint8_t *text, uint32_t length) {
  if (!text && length) return 0;
  for (uint32_t at = 0; at < length;) {
    uint32_t first = text[at++], value, width;
    if (!first) return 0;
    if (first < 0x80) continue;
    if (first >= 0xc2 && first <= 0xdf) { value = first & 31; width = 1; }
    else if (first >= 0xe0 && first <= 0xef) { value = first & 15; width = 2; }
    else if (first >= 0xf0 && first <= 0xf4) { value = first & 7; width = 3; }
    else return 0;
    if (width > length - at) return 0;
    for (uint32_t i = 0; i < width; i++) {
      uint32_t byte = text[at++];
      if ((byte & 0xc0) != 0x80) return 0;
      value = (value << 6) | (byte & 63);
    }
    if ((width == 1 && value < 0x80) || (width == 2 && value < 0x800) ||
        (width == 3 && value < 0x10000) || value > 0x10ffff ||
        (value >= 0xd800 && value <= 0xdfff)) return 0;
  }
  return 1;
}
static inline int surrounding_boundary(const uint8_t *text, uint32_t length, uint32_t at) {
  return at <= length && (at == length || (text[at] & 0xc0) != 0x80);
}
/* Convert validated UTF-8 byte boundaries to Cocoa UTF-16 positions and back.
 * A UTF-16 offset inside a surrogate pair is not a document boundary. */
static inline uint32_t surrounding_utf16(const uint8_t *text, uint32_t at) {
  uint32_t units = 0;
  for (uint32_t byte = 0; byte < at;) {
    uint8_t c = text[byte];
    uint32_t width = c < 0x80 ? 1 : c < 0xe0 ? 2 : c < 0xf0 ? 3 : 4;
    units += width == 4 ? 2 : 1;
    byte += width;
  }
  return units;
}
static inline int surrounding_byte(const uint8_t *text, uint32_t length, uint32_t units, uint32_t *out) {
  uint32_t byte = 0, used = 0;
  while (byte < length && used < units) {
    uint8_t c = text[byte];
    uint32_t width = c < 0x80 ? 1 : c < 0xe0 ? 2 : c < 0xf0 ? 3 : 4;
    uint32_t count = width == 4 ? 2 : 1;
    if (count > units - used) return 0;
    used += count; byte += width;
  }
  if (used != units) return 0;
  *out = byte;
  return 1;
}
static inline int32_t desktop_surrounding(Desktop *d, const uint8_t *text, uint32_t length,
                                        uint32_t cursor, uint32_t anchor, uint64_t token) {
  if (length > DYN_SURROUND_LIMIT) return -2;
  if (!d->event_enabled || !token || token == d->consumed_token ||
      !surrounding_utf8(text, length) || !surrounding_boundary(text, length, cursor) ||
      !surrounding_boundary(text, length, anchor)) return 0;
  if (token == d->surrounding.token) {
    return d->surrounding.length == length && d->surrounding.cursor == cursor &&
      d->surrounding.anchor == anchor && (!length || !memcmp(d->surrounding.text, text, length));
  }
  if (length) memmove(d->surrounding.text, text, length);
  d->surrounding.text[length] = 0;
  d->surrounding.length = length;
  d->surrounding.cursor = cursor;
  d->surrounding.anchor = anchor;
  d->surrounding.token = token;
  return 1;
}
static inline void desktop_loss(Desktop *d, uint32_t count) {
  if (d->event_enabled) {
    if (UINT32_MAX - d->event_dropped < count) d->event_dropped = UINT32_MAX;
    else d->event_dropped += count;
  }
}
static inline size_t edit_chunk(const uint8_t *text, size_t length, size_t at) {
  size_t count = length - at;
  if (count > sizeof(((dyn_window_event *)0)->text)) {
    count = sizeof(((dyn_window_event *)0)->text);
    while (count && (text[at + count] & 0xc0) == 0x80) count--;
  }
  return count;
}
static inline int desktop_edit(Desktop *d, const Surrounding *snapshot,
                               uint32_t start, uint32_t end, const uint8_t *text, uint32_t length) {
  if (!d->event_enabled || !snapshot->token || snapshot->token != d->surrounding.token ||
      snapshot->token == d->consumed_token || start > end ||
      !surrounding_boundary(snapshot->text, snapshot->length, start) ||
      !surrounding_boundary(snapshot->text, snapshot->length, end) ||
      length > DYN_SURROUND_LIMIT || !surrounding_utf8(text, length)) {
    desktop_loss(d, 1); return 0;
  }
  uint32_t chunks = 0;
  size_t at = 0;
  do { at += edit_chunk(text, length, at); chunks++; } while (at < length);
  if (d->event_dropped || chunks > DYN_EVENT_CAPACITY - d->event_count) {
    desktop_loss(d, chunks); return 0;
  }
  at = 0;
  do {
    size_t count = edit_chunk(text, length, at);
    dyn_window_event event = {0}; event.kind = DYN_EVENT_EDIT;
    event.key = (uint32_t)snapshot->token;
    event.modifiers = (uint32_t)(snapshot->token >> 32);
    event.x = (int32_t)start; event.y = (int32_t)end; event.width = (int32_t)length;
    event.scancode = (uint32_t)at; event.text_length = (uint32_t)count;
    if (count) memcpy(event.text, text + at, count);
    at += count; event.button = at == length;
    desktop_push(d, event);
  } while (at < length);
  d->consumed_token = snapshot->token;
  d->pending.keys |= DYN_KEY_IME;
  return 1;
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
static inline void composition_changed(Desktop *d, const dyn_window_composition *composition) {
  dyn_window_event event = {0};
  d->pending.keys |= DYN_KEY_IME;
  event.kind = DYN_EVENT_COMPOSITION;
  event.text_length = composition->text_length;
  memcpy(event.text, composition->text, event.text_length);
  event.x = composition->cursor_begin;
  event.y = composition->cursor_end;
  event.width = composition->active != 0;
  desktop_push(d, event);
}
static inline int32_t composition_cursor(const uint8_t *text, size_t length, int32_t offset) {
  if (offset < 0) return -1;
  size_t at = (size_t)offset;
  if (at > length) at = length;
  while (at && at < length && (text[at] & 0xc0) == 0x80) at--;
  return (int32_t)at;
}
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
  out->cursor_begin = composition_cursor(out->text, length, begin);
  out->cursor_end = composition_cursor(out->text, length, end);
  out->active = length > 0;
}
#endif
