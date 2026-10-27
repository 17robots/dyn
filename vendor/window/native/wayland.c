#include "window.h"
#include "desktop_common.h"
#include "xdg-shell-client-protocol.h"
#include "text-input-unstable-v3-client-protocol.h"
#include <fcntl.h>
#include <locale.h>
#include <sys/mman.h>
#include <sys/eventfd.h>
#include <time.h>
#include <wayland-cursor.h>
#include <xkbcommon/xkbcommon-compose.h>
#include <xkbcommon/xkbcommon.h>
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <errno.h>
#include <poll.h>
#include <signal.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <wayland-client.h>
#include <wayland-egl.h>
#define WAYLAND_CLIPBOARD_LIMIT (16u * 1024u * 1024u)
typedef struct ClipboardSend {
  struct ClipboardSend *next;
  uint8_t *bytes;
  uint32_t length, offset;
  int fd;
} ClipboardSend;
typedef struct ClipboardOffer {
  struct ClipboardOffer *next;
  struct wl_data_offer *offer;
  int text;
} ClipboardOffer;
typedef struct Host {
  /* Input method (text-input-v3): pending state applies on done. */
  struct zwp_text_input_manager_v3 *text_manager;
  struct zwp_text_input_v3 *text_input;
  int text_enabled, text_focused, text_applied, text_configured;
  int32_t caret[4];
  dyn_window_composition composition;
  char pending_preedit[257];
  int32_t pending_begin, pending_end;
  int pending_has_preedit;
  char pending_commit[4096];
  size_t pending_commit_length;
  int pending_commit_overflow;
  int pending_has_delete;
  uint32_t pending_before, pending_after;
  uint32_t text_serial;
  Surrounding context_history[16];
  uint32_t context_serial[16];
  uint8_t context_valid[16];
  uint32_t surrounding_cause;
  struct wl_display *display;
  struct wl_registry *registry;
  struct wl_compositor *compositor;
  struct wl_surface *surface;
  struct xdg_wm_base *wm;
  struct xdg_surface *xdg;
  struct xdg_toplevel *toplevel;
  struct wl_seat *seat;
  struct wl_pointer *pointer;
  struct wl_keyboard *keyboard;
  struct wl_egl_window *window;
  EGLDisplay egl;
  EGLSurface target;
  EGLContext context;
  dyn_window_frame frame;
  int configured;
  int size_constrained;
  /* Desktop input: keymap, compose, repeat, clipboard, cursors and scale. */
  Desktop desktop;
  struct xkb_context *xkb;
  struct xkb_keymap *keymap;
  struct xkb_state *state;
  struct xkb_compose_table *compose_table;
  struct xkb_compose_state *compose;
  int32_t repeat_rate, repeat_delay;
  uint32_t repeat_key;
  int64_t repeat_next;
  struct wl_data_device_manager *data_manager;
  struct wl_data_device *data_device;
  struct wl_data_source *source;
  struct wl_data_offer *offer;
  int offer_text;
  int receive_fd;
  uint8_t *clipboard_owned, *clipboard_received, *clipboard_incoming;
  uint32_t clipboard_owned_length, clipboard_received_length, clipboard_incoming_length;
  int clipboard_ordered, clipboard_status;
  int64_t clipboard_deadline;
  ClipboardSend *clipboard_sends;
  ClipboardOffer *clipboard_offers;
  int wake_fd;
  uint32_t serial;
  struct wl_shm *shm;
  struct wl_cursor_theme *theme;
  struct wl_surface *cursor_surface;
  uint32_t pointer_serial;
  int cursor;
  int32_t scale;
} Host;
static int64_t now_ms(void) {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return (int64_t)t.tv_sec * 1000 + t.tv_nsec / 1000000;
}
static void apply_cursor(Host *h);
static void ping(void *p, struct xdg_wm_base *wm, uint32_t serial) {
  (void)p;
  xdg_wm_base_pong(wm, serial);
}
static const struct xdg_wm_base_listener wm_listener = {.ping = ping};
static void configure(void *p, struct xdg_surface *surface, uint32_t serial) {
  Host *h = p;
  xdg_surface_ack_configure(surface, serial);
  h->configured = 1;
}
static const struct xdg_surface_listener surface_listener = {.configure =
                                                                 configure};
static void size(void *p, struct xdg_toplevel *t, int32_t w, int32_t h,
                 struct wl_array *a) {
  (void)t;
  Host *s = p;
  uint32_t *state;
  s->size_constrained = 0;
  wl_array_for_each(state,a) {
    if (*state == XDG_TOPLEVEL_STATE_MAXIMIZED || *state == XDG_TOPLEVEL_STATE_FULLSCREEN ||
        *state == XDG_TOPLEVEL_STATE_RESIZING ||
        (*state >= XDG_TOPLEVEL_STATE_TILED_LEFT && *state <= XDG_TOPLEVEL_STATE_TILED_BOTTOM))
      s->size_constrained = 1;
  }
  if (w > 0)
    s->frame.width = w * s->scale;
  if (h > 0)
    s->frame.height = h * s->scale;
  if (s->window)
    wl_egl_window_resize(s->window, s->frame.width, s->frame.height, 0, 0);
  desktop_resize(&s->desktop,s->frame.width,s->frame.height);
}
static void closing(void *p, struct xdg_toplevel *t) {
  (void)t;
  ((Host *)p)->frame.flags |= DYN_CLOSE;
  desktop_simple(&((Host *)p)->desktop,DYN_EVENT_CLOSE);
}
static const struct xdg_toplevel_listener top_listener = {.configure = size,
                                                          .close = closing};
static uint32_t event_modifiers(Host *h) {
  if (!h->state) return 0;
  uint32_t result=0;
  if (xkb_state_mod_name_is_active(h->state,XKB_MOD_NAME_SHIFT,XKB_STATE_MODS_EFFECTIVE)>0) result|=DYN_MOD_SHIFT;
  if (xkb_state_mod_name_is_active(h->state,XKB_MOD_NAME_CTRL,XKB_STATE_MODS_EFFECTIVE)>0) result|=DYN_MOD_CONTROL;
  if (xkb_state_mod_name_is_active(h->state,XKB_MOD_NAME_ALT,XKB_STATE_MODS_EFFECTIVE)>0) result|=DYN_MOD_ALT;
  if (xkb_state_mod_name_is_active(h->state,XKB_MOD_NAME_LOGO,XKB_STATE_MODS_EFFECTIVE)>0) result|=DYN_MOD_SUPER;
  if (xkb_state_mod_name_is_active(h->state,XKB_MOD_NAME_CAPS,XKB_STATE_MODS_EFFECTIVE)>0) result|=DYN_MOD_CAPS;
  if (xkb_state_mod_name_is_active(h->state,XKB_MOD_NAME_NUM,XKB_STATE_MODS_EFFECTIVE)>0) result|=DYN_MOD_NUM;
  return result;
}
static uint32_t event_key(xkb_keysym_t sym) {
  if (sym>=XKB_KEY_F1 && sym<=XKB_KEY_F24) return DYN_F1+sym-XKB_KEY_F1;
  switch(sym) {
   case XKB_KEY_Escape:return DYN_ESCAPE;
   case XKB_KEY_Return:case XKB_KEY_KP_Enter:return DYN_ENTER;
   case XKB_KEY_Tab:case XKB_KEY_ISO_Left_Tab:return DYN_TAB_KEY;
   case XKB_KEY_BackSpace:return DYN_BACKSPACE;
   case XKB_KEY_Delete:return DYN_DELETE;
   case XKB_KEY_Left:return DYN_LEFT_KEY;case XKB_KEY_Right:return DYN_RIGHT_KEY;
   case XKB_KEY_Up:return DYN_UP_KEY;case XKB_KEY_Down:return DYN_DOWN_KEY;
   case XKB_KEY_Home:return DYN_HOME;case XKB_KEY_End:return DYN_END;
   case XKB_KEY_Page_Up:return DYN_PAGE_UP;case XKB_KEY_Page_Down:return DYN_PAGE_DOWN;
   case XKB_KEY_Insert:return DYN_INSERT;
   case XKB_KEY_Shift_L:case XKB_KEY_Shift_R:return DYN_SHIFT_KEY;
   case XKB_KEY_Control_L:case XKB_KEY_Control_R:return DYN_CONTROL_KEY;
   case XKB_KEY_Alt_L:case XKB_KEY_Alt_R:return DYN_ALT_KEY;
   case XKB_KEY_Super_L:case XKB_KEY_Super_R:return DYN_SUPER_KEY;
   default:return xkb_keysym_to_utf32(sym);
  }
}
static void event_keyboard(Host *h,uint32_t key,int down,int repeated) {
  const xkb_keysym_t *syms=NULL;
  xkb_keysym_t sym=XKB_KEY_NoSymbol;
  if (h->keymap && h->state) {
    xkb_layout_index_t layout=xkb_state_key_get_layout(h->state,key+8);
    if (xkb_keymap_key_get_syms_by_level(h->keymap,key+8,layout,0,&syms)>0) sym=syms[0];
  }
  dyn_window_event event = {0};
  event.kind = down ? DYN_EVENT_KEY_DOWN : DYN_EVENT_KEY_UP;
  event.key = event_key(sym); event.scancode = key;
  event.modifiers = event_modifiers(h); event.repeated = repeated != 0;
  if (h->state) event.height = (int32_t)xkb_keysym_to_utf32(xkb_state_key_get_one_sym(h->state,key+8));
  desktop_push(&h->desktop,event);
}
static void enter(void *p, struct wl_pointer *q, uint32_t serial,
                  struct wl_surface *s, wl_fixed_t x, wl_fixed_t y) {
  (void)q;
  (void)s;
  Host *h = p;
  h->frame.x = wl_fixed_to_int(x) * h->scale;
  h->frame.y = wl_fixed_to_int(y) * h->scale;
  desktop_pointer(&h->desktop,DYN_EVENT_POINTER_MOVE,h->frame.x,h->frame.y,0,event_modifiers(h));
  h->pointer_serial = serial;
  apply_cursor(h);
}
static void leave(void *p, struct wl_pointer *q, uint32_t serial,
                  struct wl_surface *s) {
  (void)p;
  (void)q;
  (void)serial;
  (void)s;
}
static void motion(void *p, struct wl_pointer *q, uint32_t time, wl_fixed_t x,
                   wl_fixed_t y) {
  (void)q;
  (void)time;
  Host *h = p;
  h->frame.x = wl_fixed_to_int(x) * h->scale;
  h->frame.y = wl_fixed_to_int(y) * h->scale;
  desktop_pointer(&h->desktop,DYN_EVENT_POINTER_MOVE,h->frame.x,h->frame.y,0,event_modifiers(h));
}
static void button(void *p, struct wl_pointer *q, uint32_t serial,
                   uint32_t time, uint32_t button, uint32_t state) {
  (void)q;
  (void)time;
  Host *h = p;
  h->serial = serial;
  uint32_t number=button==0x110?1:button==0x112?2:button==0x111?3:button;
  desktop_pointer(&h->desktop,state?DYN_EVENT_POINTER_DOWN:DYN_EVENT_POINTER_UP,h->frame.x,h->frame.y,number,event_modifiers(h));
  if (button == 0x110) {
    if (state) {
      h->frame.flags |= DYN_DOWN | DYN_PRESSED;
    } else {
      h->frame.flags &= ~DYN_DOWN;
      h->frame.flags |= DYN_RELEASED;
    }
  }
}
static void axis(void *p, struct wl_pointer *q, uint32_t time, uint32_t axis,
                 wl_fixed_t v) {
  (void)q;
  (void)time;
  Host *h = p;
  float amount = (float)wl_fixed_to_double(v) * 3.0f * (float)h->scale;
  if (axis == WL_POINTER_AXIS_VERTICAL_SCROLL) {
    h->desktop.pending.scroll_y += amount;
    desktop_wheel(&h->desktop,0,amount);
  } else {
    h->desktop.pending.scroll_x += amount;
    desktop_wheel(&h->desktop,amount,0);
  }
}
static void pointer_frame(void *p, struct wl_pointer *q) {
  (void)p;
  (void)q;
}
static void axis_source(void *p, struct wl_pointer *q, uint32_t v) {
  (void)p;
  (void)q;
  (void)v;
}
static void axis_stop(void *p, struct wl_pointer *q, uint32_t time,
                      uint32_t axis) {
  (void)p;
  (void)q;
  (void)time;
  (void)axis;
}
static void axis_discrete(void *p, struct wl_pointer *q, uint32_t axis,
                          int32_t steps) {
  (void)p;
  (void)q;
  (void)axis;
  (void)steps;
}
static const struct wl_pointer_listener pointer_listener = {
    .enter = enter,
    .leave = leave,
    .motion = motion,
    .button = button,
    .axis = axis,
    .frame = pointer_frame,
    .axis_source = axis_source,
    .axis_stop = axis_stop,
    .axis_discrete = axis_discrete};
static void keymap(void *p, struct wl_keyboard *k, uint32_t format, int32_t fd,
                   uint32_t size) {
  (void)k;
  Host *h = p;
  if (format != WL_KEYBOARD_KEYMAP_FORMAT_XKB_V1 || !h->xkb) {
    close(fd);
    return;
  }
  char *text = mmap(NULL, size, PROT_READ, MAP_PRIVATE, fd, 0);
  close(fd);
  if (text == MAP_FAILED)
    return;
  struct xkb_keymap *map = xkb_keymap_new_from_string(h->xkb, text, XKB_KEYMAP_FORMAT_TEXT_V1, XKB_KEYMAP_COMPILE_NO_FLAGS);
  munmap(text, size);
  if (!map)
    return;
  struct xkb_state *state = xkb_state_new(map);
  if (!state) {
    xkb_keymap_unref(map);
    return;
  }
  if (h->state)
    xkb_state_unref(h->state);
  if (h->keymap)
    xkb_keymap_unref(h->keymap);
  h->keymap = map;
  h->state = state;
}
static void key_enter(void *p, struct wl_keyboard *k, uint32_t serial,
                      struct wl_surface *s, struct wl_array *a) {
  (void)p;
  (void)k;
  (void)serial;
  (void)s;
  (void)a;
  desktop_simple(&((Host *)p)->desktop,DYN_EVENT_FOCUS_GAINED);
}
static void key_leave(void *p, struct wl_keyboard *k, uint32_t serial,
                      struct wl_surface *s) {
  (void)k;
  (void)serial;
  (void)s;
  Host *h = p;
  if (h->frame.flags & DYN_DOWN)
    h->frame.flags |= DYN_RELEASED;
  h->frame.flags &= ~DYN_DOWN;
  h->repeat_key = 0;
  desktop_simple(&h->desktop,DYN_EVENT_FOCUS_LOST);
  h->desktop.pending.keys &= ~(uint32_t)(DYN_KEY_SHIFT | DYN_KEY_CONTROL);
}
static void press(Host *h, uint32_t key) {
  if (!h->state)
    return;
  xkb_keysym_t sym = xkb_state_key_get_one_sym(h->state, key + 8);
  int control = xkb_state_mod_name_is_active(h->state, XKB_MOD_NAME_CTRL, XKB_STATE_MODS_EFFECTIVE) > 0;
  uint32_t *keys = &h->desktop.pending.keys;
  if (control)
    *keys |= DYN_KEY_CONTROL;
  else
    *keys &= ~(uint32_t)DYN_KEY_CONTROL;
  switch (sym) {
  case XKB_KEY_BackSpace: *keys |= DYN_KEY_BACKSPACE; return;
  case XKB_KEY_Delete: *keys |= DYN_KEY_DELETE; return;
  case XKB_KEY_Left: *keys |= DYN_KEY_LEFT; return;
  case XKB_KEY_Right: *keys |= DYN_KEY_RIGHT; return;
  case XKB_KEY_Home: *keys |= DYN_KEY_HOME; return;
  case XKB_KEY_End: *keys |= DYN_KEY_END; return;
  case XKB_KEY_Return: case XKB_KEY_KP_Enter: *keys |= DYN_KEY_ENTER; return;
  case XKB_KEY_Escape: *keys |= DYN_KEY_ESCAPE; return;
  case XKB_KEY_Tab: *keys |= DYN_KEY_TAB; return;
  default: break;
  }
  if (control) {
    if (sym == XKB_KEY_a || sym == XKB_KEY_A) *keys |= DYN_KEY_SELECT_ALL;
    else if (sym == XKB_KEY_c || sym == XKB_KEY_C) *keys |= DYN_KEY_COPY;
    else if (sym == XKB_KEY_x || sym == XKB_KEY_X) *keys |= DYN_KEY_CUT;
    else if (sym == XKB_KEY_v || sym == XKB_KEY_V) dyn_window_request_paste(h);
    return;
  }
  /* While text-input-v3 owns committed input, xkb still supplies raw keys
   * and navigation shortcuts but must not insert a second copy of the text. */
  if ((h->text_configured && !h->text_enabled) ||
      (h->text_input && h->text_focused && h->text_enabled)) return;
  char text[64];
  int length = 0;
  if (h->compose) {
    xkb_compose_state_feed(h->compose, sym);
    enum xkb_compose_status status = xkb_compose_state_get_status(h->compose);
    if (status == XKB_COMPOSE_COMPOSING)
      return;
    if (status == XKB_COMPOSE_COMPOSED) {
      length = xkb_compose_state_get_utf8(h->compose, text, sizeof(text));
      xkb_compose_state_reset(h->compose);
    } else if (status == XKB_COMPOSE_CANCELLED) {
      xkb_compose_state_reset(h->compose);
      return;
    }
  }
  if (!length)
    length = xkb_state_key_get_utf8(h->state, key + 8, text, sizeof(text));
  if (length > 0 && length < (int)sizeof(text))
    desktop_text(&h->desktop, (const uint8_t *)text, (size_t)length);
  else if (length >= (int)sizeof(text) && h->desktop.event_enabled && h->desktop.event_dropped != UINT32_MAX)
    h->desktop.event_dropped++;
}
static void key(void *p, struct wl_keyboard *k, uint32_t serial, uint32_t time,
                uint32_t key, uint32_t state) {
  (void)k;
  (void)time;
  Host *h = p;
  h->serial = serial;
  event_keyboard(h,key,state!=0,0);
  if (state) {
    press(h, key);
    /* Wayland leaves key repeat to clients. */
    if (h->keymap && xkb_keymap_key_repeats(h->keymap, key + 8) && h->repeat_rate > 0) {
      h->repeat_key = key;
      h->repeat_next = now_ms() + h->repeat_delay;
    }
  } else if (key == h->repeat_key) {
    h->repeat_key = 0;
  }
  if (state) {
    if (key == 15)
      h->frame.flags |= DYN_TAB;
    else if (key == 28 || key == 57)
      h->frame.flags |= DYN_ACTIVATE;
    else if (key == 105)
      h->frame.flags |= DYN_LEFT;
    else if (key == 106)
      h->frame.flags |= DYN_RIGHT;
  }
}
static void modifiers(void *p, struct wl_keyboard *k, uint32_t serial,
                      uint32_t depressed, uint32_t latched, uint32_t locked,
                      uint32_t group) {
  (void)k;
  (void)serial;
  Host *h = p;
  if (!h->state)
    return;
  xkb_state_update_mask(h->state, depressed, latched, locked, 0, 0, group);
  if (xkb_state_mod_name_is_active(h->state, XKB_MOD_NAME_SHIFT, XKB_STATE_MODS_EFFECTIVE) > 0)
    h->desktop.pending.keys |= DYN_KEY_SHIFT;
  else
    h->desktop.pending.keys &= ~(uint32_t)DYN_KEY_SHIFT;
  if (xkb_state_mod_name_is_active(h->state, XKB_MOD_NAME_CTRL, XKB_STATE_MODS_EFFECTIVE) > 0)
    h->desktop.pending.keys |= DYN_KEY_CONTROL;
  else
    h->desktop.pending.keys &= ~(uint32_t)DYN_KEY_CONTROL;
}
static void repeat(void *p, struct wl_keyboard *k, int32_t rate,
                   int32_t delay) {
  (void)k;
  Host *h = p;
  h->repeat_rate = rate;
  h->repeat_delay = delay;
}
static const struct wl_keyboard_listener keyboard_listener = {
    .keymap = keymap,
    .enter = key_enter,
    .leave = key_leave,
    .key = key,
    .modifiers = modifiers,
    .repeat_info = repeat};
static void capabilities(void *p, struct wl_seat *s, uint32_t caps) {
  Host *h = p;
  if ((caps & WL_SEAT_CAPABILITY_POINTER) && !h->pointer) {
    h->pointer = wl_seat_get_pointer(s);
    wl_pointer_add_listener(h->pointer, &pointer_listener, h);
  } else if (!(caps & WL_SEAT_CAPABILITY_POINTER) && h->pointer) {
    wl_pointer_release(h->pointer);
    h->pointer = NULL;
    h->frame.flags &= ~DYN_DOWN;
    h->frame.flags |= DYN_RELEASED;
  }
  if ((caps & WL_SEAT_CAPABILITY_KEYBOARD) && !h->keyboard) {
    h->keyboard = wl_seat_get_keyboard(s);
    wl_keyboard_add_listener(h->keyboard, &keyboard_listener, h);
  } else if (!(caps & WL_SEAT_CAPABILITY_KEYBOARD) && h->keyboard) {
    wl_keyboard_release(h->keyboard);
    h->keyboard = NULL;
  }
}
static void seat_name(void *p, struct wl_seat *s, const char *n) {
  (void)p;
  (void)s;
  (void)n;
}
static const struct wl_seat_listener seat_listener = {
    .capabilities = capabilities, .name = seat_name};
static void clipboard_offer_destroy(Host *h, struct wl_data_offer *offer) {
  ClipboardOffer **link = &h->clipboard_offers;
  while (*link && (*link)->offer != offer) link = &(*link)->next;
  if (*link) { ClipboardOffer *old = *link; *link = old->next; free(old); }
  wl_data_offer_destroy(offer);
}
static void offer_mime(void *p, struct wl_data_offer *o, const char *mime) {
  ClipboardOffer *offer = p;
  (void)o;
  if (!strcmp(mime, "text/plain;charset=utf-8")) offer->text = 1;
}
static void offer_actions(void *p, struct wl_data_offer *o, uint32_t a) {
  (void)p;
  (void)o;
  (void)a;
}
static void offer_action(void *p, struct wl_data_offer *o, uint32_t a) {
  (void)p;
  (void)o;
  (void)a;
}
static const struct wl_data_offer_listener offer_listener = {
    .offer = offer_mime, .source_actions = offer_actions, .action = offer_action};
static void data_offer(void *p, struct wl_data_device *d, struct wl_data_offer *o) {
  (void)d;
  Host *h = p;
  ClipboardOffer *offer = calloc(1, sizeof(*offer));
  if (!offer) { wl_data_offer_destroy(o); return; }
  offer->offer = o; offer->next = h->clipboard_offers; h->clipboard_offers = offer;
  wl_data_offer_add_listener(o, &offer_listener, offer);
}
static void data_enter(void *p, struct wl_data_device *d, uint32_t serial, struct wl_surface *s,
                       wl_fixed_t x, wl_fixed_t y, struct wl_data_offer *o) {
  (void)p;
  (void)d;
  (void)serial;
  (void)s;
  (void)x;
  (void)y;
  if (o)
    clipboard_offer_destroy(p, o);
}
static void data_leave(void *p, struct wl_data_device *d) {
  (void)p;
  (void)d;
}
static void data_motion(void *p, struct wl_data_device *d, uint32_t t, wl_fixed_t x, wl_fixed_t y) {
  (void)p;
  (void)d;
  (void)t;
  (void)x;
  (void)y;
}
static void data_drop(void *p, struct wl_data_device *d) {
  (void)p;
  (void)d;
}
static void selection(void *p, struct wl_data_device *d, struct wl_data_offer *o) {
  (void)d;
  Host *h = p;
  if (h->offer && h->offer != o)
    clipboard_offer_destroy(h, h->offer);
  h->offer = o; h->offer_text = 0;
  for (ClipboardOffer *at = h->clipboard_offers; at; at = at->next)
    if (at->offer == o) h->offer_text = at->text;
}
static const struct wl_data_device_listener data_listener = {
    .data_offer = data_offer, .enter = data_enter, .leave = data_leave,
    .motion = data_motion, .drop = data_drop, .selection = selection};
static void source_target(void *p, struct wl_data_source *s, const char *m) {
  (void)p;
  (void)s;
  (void)m;
}
/* Pipe writes must neither block the GUI thread nor deliver SIGPIPE to it. */
static ssize_t clipboard_write(int fd, const uint8_t *bytes, size_t length) {
  sigset_t block, old, pending;
  sigemptyset(&block); sigaddset(&block, SIGPIPE);
  if (sigprocmask(SIG_BLOCK, &block, &old) != 0) return -1;
  sigpending(&pending);
  int was_pending = sigismember(&pending, SIGPIPE);
  ssize_t result = write(fd, bytes, length);
  int saved = errno;
  if (result < 0 && saved == EPIPE && !was_pending) {
    struct timespec zero = {0};
    while (sigtimedwait(&block, NULL, &zero) < 0 && errno == EINTR) {}
  }
  sigprocmask(SIG_SETMASK, &old, NULL); errno = saved;
  return result;
}
static void send_clipboards(Host *h) {
  ClipboardSend **link = &h->clipboard_sends;
  while (*link) {
    ClipboardSend *send = *link;
    ssize_t n = clipboard_write(send->fd, send->bytes + send->offset, send->length - send->offset);
    if (n > 0) send->offset += (uint32_t)n;
    if ((n >= 0 && send->offset == send->length) || (n < 0 && errno != EINTR && errno != EAGAIN && errno != EWOULDBLOCK)) {
      *link = send->next; close(send->fd); free(send->bytes); free(send);
    } else link = &send->next;
  }
}
static void source_send(void *p, struct wl_data_source *s, const char *mime, int32_t fd) {
  Host *h = p;
  if (s != h->source || (strcmp(mime, "text/plain;charset=utf-8") && strcmp(mime, "UTF8_STRING"))) { close(fd); return; }
  unsigned count = 0;
  for (ClipboardSend *at = h->clipboard_sends; at; at = at->next) count++;
  int flags = fcntl(fd, F_GETFL);
  ClipboardSend *send = count < 8 ? calloc(1, sizeof(*send)) : NULL;
  if (!send || flags < 0 || fcntl(fd, F_SETFL, flags | O_NONBLOCK) < 0) { free(send); close(fd); return; }
  send->bytes = malloc(h->clipboard_owned_length ? h->clipboard_owned_length : 1);
  if (!send->bytes) { free(send); close(fd); return; }
  if (h->clipboard_owned_length) memcpy(send->bytes, h->clipboard_owned, h->clipboard_owned_length);
  send->length = h->clipboard_owned_length; send->fd = fd;
  send->next = h->clipboard_sends; h->clipboard_sends = send;
  send_clipboards(h);
}
static void source_cancelled(void *p, struct wl_data_source *s) {
  Host *h = p;
  if (h->source == s)
    h->source = NULL;
  wl_data_source_destroy(s);
}
static void source_performed(void *p, struct wl_data_source *s) {
  (void)p;
  (void)s;
}
static void source_finished(void *p, struct wl_data_source *s) {
  (void)p;
  (void)s;
}
static void source_action(void *p, struct wl_data_source *s, uint32_t a) {
  (void)p;
  (void)s;
  (void)a;
}
static const struct wl_data_source_listener source_listener = {
    .target = source_target, .send = source_send, .cancelled = source_cancelled,
    .dnd_drop_performed = source_performed, .dnd_finished = source_finished, .action = source_action};
static void output_geometry(void *p, struct wl_output *o, int32_t x, int32_t y, int32_t pw, int32_t ph,
                            int32_t sub, const char *make, const char *model, int32_t t) {
  (void)p; (void)o; (void)x; (void)y; (void)pw; (void)ph; (void)sub; (void)make; (void)model; (void)t;
}
static void output_mode(void *p, struct wl_output *o, uint32_t f, int32_t w, int32_t hh, int32_t r) {
  (void)p; (void)o; (void)f; (void)w; (void)hh; (void)r;
}
static void output_done(void *p, struct wl_output *o) {
  (void)p;
  (void)o;
}
static void output_scale(void *p, struct wl_output *o, int32_t factor) {
  (void)o;
  Host *h = p;
  if (factor > h->scale)
    h->scale = factor;
}
static const struct wl_output_listener output_listener = {
    .geometry = output_geometry, .mode = output_mode, .done = output_done, .scale = output_scale};
static void text_apply_state(Host *h) {
  if (!h->text_input || !h->text_focused)
    return;
  if (h->text_enabled) {
    if (!h->text_applied) {
      zwp_text_input_v3_enable(h->text_input);
      zwp_text_input_v3_set_content_type(h->text_input, ZWP_TEXT_INPUT_V3_CONTENT_HINT_NONE,
                                         ZWP_TEXT_INPUT_V3_CONTENT_PURPOSE_NORMAL);
      h->text_applied = 1;
    }
    if (h->desktop.surrounding.token) {
      zwp_text_input_v3_set_text_change_cause(h->text_input, h->surrounding_cause ? ZWP_TEXT_INPUT_V3_CHANGE_CAUSE_INPUT_METHOD : ZWP_TEXT_INPUT_V3_CHANGE_CAUSE_OTHER);
      zwp_text_input_v3_set_surrounding_text(h->text_input,
          (const char *)h->desktop.surrounding.text,
          (int32_t)h->desktop.surrounding.cursor, (int32_t)h->desktop.surrounding.anchor);
    }
    /* The protocol uses surface-local (logical) coordinates. */
    int32_t s = h->scale > 0 ? h->scale : 1;
    zwp_text_input_v3_set_cursor_rectangle(h->text_input, h->caret[0] / s, h->caret[1] / s, h->caret[2] / s, h->caret[3] / s);
  } else {
    if (!h->text_applied) return;
    zwp_text_input_v3_disable(h->text_input);
    h->text_applied = 0;
  }
  zwp_text_input_v3_commit(h->text_input);
  h->text_serial++;
  uint32_t slot = h->text_serial % 16;
  h->context_history[slot] = h->desktop.surrounding;
  h->context_serial[slot] = h->text_serial;
  h->context_valid[slot] = h->desktop.surrounding.token != 0;
}
static void text_enter(void *p, struct zwp_text_input_v3 *t, struct wl_surface *s) {
  (void)t;
  Host *h = p;
  h->text_focused = s == h->surface;
  h->text_applied = 0;
  text_apply_state(h);
}
static void text_leave(void *p, struct zwp_text_input_v3 *t, struct wl_surface *s) {
  (void)t;
  (void)s;
  Host *h = p;
  h->text_focused = 0;
  if (h->desktop.surrounding.token) h->desktop.consumed_token = h->desktop.surrounding.token;
  h->text_applied = 0;
  h->pending_has_preedit = 0;
  h->pending_has_delete = 0;
  h->pending_commit_length = 0;
  h->pending_commit_overflow = 0;
  memset(&h->composition, 0, sizeof(h->composition));
  composition_changed(&h->desktop, &h->composition);
}
static void text_preedit(void *p, struct zwp_text_input_v3 *t, const char *text, int32_t begin, int32_t end) {
  (void)t;
  Host *h = p;
  size_t length = text ? strlen(text) : 0;
  if (length >= sizeof(h->pending_preedit)) {
    length = sizeof(h->pending_preedit) - 1;
    while (length && (text[length] & 0xc0) == 0x80) length--;
  }
  memcpy(h->pending_preedit, text ? text : "", length);
  h->pending_preedit[length] = 0;
  h->pending_begin = begin;
  h->pending_end = end;
  h->pending_has_preedit = 1;
}
static void text_commit(void *p, struct zwp_text_input_v3 *t, const char *text) {
  (void)t;
  Host *h = p;
  size_t length = text ? strlen(text) : 0;
  /* Protocol state is double buffered: a later commit_string replaces the
   * pending string; it does not concatenate another transaction. */
  h->pending_commit_overflow = length > sizeof(h->pending_commit);
  h->pending_commit_length = h->pending_commit_overflow ? 0 : length;
  if (h->pending_commit_length) memcpy(h->pending_commit, text, length);
}
static void text_delete(void *p, struct zwp_text_input_v3 *t, uint32_t before, uint32_t after) {
  (void)t;
  Host *h = p;
  h->pending_has_delete = 1;
  h->pending_before = before;
  h->pending_after = after;
}
static void text_done(void *p, struct zwp_text_input_v3 *t, uint32_t serial) {
  (void)t;
  /* Even stale serials apply the input transaction. This handler sends no
   * client-side protocol state; caret updates are committed separately. */
  (void)serial;
  Host *h = p;
  if (!h->text_enabled || !h->text_focused) {
    h->pending_commit_length = 0;
    h->pending_commit_overflow = 0;
    h->pending_has_preedit = 0;
    h->pending_has_delete = 0;
    return;
  }
  /* A done transaction removes the prior preedit before committing text. */
  if (h->composition.active) {
    memset(&h->composition, 0, sizeof(h->composition));
    composition_changed(&h->desktop, &h->composition);
  }
  uint32_t slot = serial % 16;
  const Surrounding *snapshot = h->context_valid[slot] && h->context_serial[slot] == serial
      ? &h->context_history[slot] : NULL;
  int selected = snapshot && snapshot->cursor != snapshot->anchor;
  int correction = h->pending_has_delete || (selected && h->pending_commit_length);
  if (h->pending_commit_overflow) desktop_loss(&h->desktop, 1);
  else if (correction) {
    if (!snapshot) desktop_loss(&h->desktop, 1);
    else {
      uint32_t low = snapshot->cursor < snapshot->anchor ? snapshot->cursor : snapshot->anchor;
      uint32_t high = snapshot->cursor > snapshot->anchor ? snapshot->cursor : snapshot->anchor;
      if (h->pending_before > low || h->pending_after > snapshot->length - high)
        desktop_loss(&h->desktop, 1);
      else desktop_edit(&h->desktop, snapshot, low - h->pending_before, high + h->pending_after,
                        (const uint8_t *)h->pending_commit, (uint32_t)h->pending_commit_length);
    }
  } else if (h->pending_commit_length) {
    desktop_text(&h->desktop, (const uint8_t *)h->pending_commit, h->pending_commit_length);
  }
  h->pending_commit_overflow = 0;
  h->pending_commit_length = 0;
  h->pending_has_delete = 0;
  h->pending_before = h->pending_after = 0;
  if (h->pending_has_preedit) {
    composition_store(&h->composition, (const uint8_t *)h->pending_preedit, strlen(h->pending_preedit),
                      h->pending_begin, h->pending_end);
    composition_changed(&h->desktop, &h->composition);
  }
  h->pending_has_preedit = 0;
}
static const struct zwp_text_input_v3_listener text_listener = {
    .enter = text_enter, .leave = text_leave, .preedit_string = text_preedit,
    .commit_string = text_commit, .delete_surrounding_text = text_delete, .done = text_done};
static void global(void *p, struct wl_registry *r, uint32_t name,
                   const char *interface, uint32_t version) {
  Host *h = p;
  if (!strcmp(interface, "wl_compositor"))
    h->compositor = wl_registry_bind(r, name, &wl_compositor_interface,
                                     version < 4 ? version : 4);
  else if (!strcmp(interface, "xdg_wm_base")) {
    h->wm = wl_registry_bind(r, name, &xdg_wm_base_interface, 1);
    xdg_wm_base_add_listener(h->wm, &wm_listener, h);
  } else if (!strcmp(interface, "wl_seat") && !h->seat && version >= 5) {
    h->seat = wl_registry_bind(r, name, &wl_seat_interface, 5);
    wl_seat_add_listener(h->seat, &seat_listener, h);
  } else if (!strcmp(interface, "zwp_text_input_manager_v3") && !h->text_manager) {
    h->text_manager = wl_registry_bind(r, name, &zwp_text_input_manager_v3_interface, 1);
  } else if (!strcmp(interface, "wl_data_device_manager") && !h->data_manager && version >= 3) {
    h->data_manager = wl_registry_bind(r, name, &wl_data_device_manager_interface, 3);
  } else if (!strcmp(interface, "wl_shm") && !h->shm) {
    h->shm = wl_registry_bind(r, name, &wl_shm_interface, 1);
  } else if (!strcmp(interface, "wl_output") && version >= 2) {
    struct wl_output *output = wl_registry_bind(r, name, &wl_output_interface, 2);
    wl_output_add_listener(output, &output_listener, h);
  }
}
static void removed(void *p, struct wl_registry *r, uint32_t name) {
  (void)p;
  (void)r;
  (void)name;
}
static const struct wl_registry_listener registry_listener = {
    .global = global, .global_remove = removed};
void dyn_window_close(void *p) {
  Host *h = p;
  if (!h)
    return;
  if (h->text_input)
    zwp_text_input_v3_destroy(h->text_input);
  if (h->text_manager)
    zwp_text_input_manager_v3_destroy(h->text_manager);
  if (h->egl != EGL_NO_DISPLAY) {
    if (eglGetCurrentContext() == h->context)
      eglMakeCurrent(h->egl, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
    if (h->target != EGL_NO_SURFACE)
      eglDestroySurface(h->egl, h->target);
    if (h->context != EGL_NO_CONTEXT)
      eglDestroyContext(h->egl, h->context);
    eglTerminate(h->egl);
  }
  if (h->window)
    wl_egl_window_destroy(h->window);
  if (h->toplevel)
    xdg_toplevel_destroy(h->toplevel);
  if (h->xdg)
    xdg_surface_destroy(h->xdg);
  if (h->surface)
    wl_surface_destroy(h->surface);
  if (h->receive_fd >= 0) close(h->receive_fd);
  free(h->clipboard_owned); free(h->clipboard_received); free(h->clipboard_incoming);
  while (h->clipboard_sends) {
    ClipboardSend *send = h->clipboard_sends; h->clipboard_sends = send->next;
    close(send->fd); free(send->bytes); free(send);
  }
  while (h->clipboard_offers)
    clipboard_offer_destroy(h, h->clipboard_offers->offer);
  if (h->source)
    wl_data_source_destroy(h->source);
  if (h->data_device)
    wl_data_device_release(h->data_device);
  if (h->data_manager)
    wl_data_device_manager_destroy(h->data_manager);
  if (h->cursor_surface)
    wl_surface_destroy(h->cursor_surface);
  if (h->theme)
    wl_cursor_theme_destroy(h->theme);
  if (h->shm)
    wl_shm_destroy(h->shm);
  if (h->compose)
    xkb_compose_state_unref(h->compose);
  if (h->compose_table)
    xkb_compose_table_unref(h->compose_table);
  if (h->state)
    xkb_state_unref(h->state);
  if (h->keymap)
    xkb_keymap_unref(h->keymap);
  if (h->xkb)
    xkb_context_unref(h->xkb);
  if (h->keyboard)
    wl_keyboard_release(h->keyboard);
  if (h->pointer)
    wl_pointer_release(h->pointer);
  if (h->seat)
    wl_seat_release(h->seat);
  if (h->wm)
    xdg_wm_base_destroy(h->wm);
  if (h->compositor)
    wl_compositor_destroy(h->compositor);
  if (h->registry)
    wl_registry_destroy(h->registry);
  if (h->display)
    wl_display_disconnect(h->display);
  if (h->wake_fd>=0) close(h->wake_fd);
  free(h);
}
void *dyn_window_open(const char *title, int32_t width, int32_t height) {
  Host *h = calloc(1, sizeof(*h));
  if (!h)
    return NULL;
  h->frame.width = width;
  h->frame.height = height;
  h->scale = 1;
  h->receive_fd = -1;
  h->clipboard_status = -4;
  h->wake_fd = eventfd(0,EFD_CLOEXEC|EFD_NONBLOCK);
  if (h->wake_fd<0) goto fail;
  h->xkb = xkb_context_new(XKB_CONTEXT_NO_FLAGS);
  if (h->xkb) {
    const char *locale = getenv("LC_ALL");
    if (!locale || !*locale)
      locale = getenv("LC_CTYPE");
    if (!locale || !*locale)
      locale = getenv("LANG");
    if (!locale || !*locale)
      locale = "C";
    h->compose_table = xkb_compose_table_new_from_locale(h->xkb, locale, XKB_COMPOSE_COMPILE_NO_FLAGS);
    if (h->compose_table)
      h->compose = xkb_compose_state_new(h->compose_table, XKB_COMPOSE_STATE_NO_FLAGS);
  }
  h->display = wl_display_connect(NULL);
  if (!h->display)
    goto fail;
  h->registry = wl_display_get_registry(h->display);
  wl_registry_add_listener(h->registry, &registry_listener, h);
  if (wl_display_roundtrip(h->display) < 0 || !h->wm || !h->compositor)
    goto fail;
  /* Output scale events arrive on this round trip. */
  if (wl_display_roundtrip(h->display) < 0)
    goto fail;
  if (h->text_manager && h->seat) {
    h->text_input = zwp_text_input_manager_v3_get_text_input(h->text_manager, h->seat);
    zwp_text_input_v3_add_listener(h->text_input, &text_listener, h);
  }
  if (h->data_manager && h->seat) {
    h->data_device = wl_data_device_manager_get_data_device(h->data_manager, h->seat);
    wl_data_device_add_listener(h->data_device, &data_listener, h);
  }
  if (h->shm) {
    h->theme = wl_cursor_theme_load(NULL, 24 * h->scale, h->shm);
    h->cursor_surface = wl_compositor_create_surface(h->compositor);
  }
  h->surface = wl_compositor_create_surface(h->compositor);
  /* Render at the output scale; the window reports physical pixels. */
  wl_surface_set_buffer_scale(h->surface, h->scale);
  h->xdg = xdg_wm_base_get_xdg_surface(h->wm, h->surface);
  xdg_surface_add_listener(h->xdg, &surface_listener, h);
  h->toplevel = xdg_surface_get_toplevel(h->xdg);
  xdg_toplevel_add_listener(h->toplevel, &top_listener, h);
  xdg_toplevel_set_title(h->toplevel, title);
  xdg_toplevel_set_app_id(h->toplevel, "dyn.native");
  wl_surface_commit(h->surface);
  while (!h->configured)
    if (wl_display_dispatch(h->display) < 0)
      goto fail;
  h->frame.width *= h->scale;
  h->frame.height *= h->scale;
  h->window = wl_egl_window_create(h->surface, h->frame.width, h->frame.height);
  if (!h->window)
    goto fail;
  h->egl = eglGetDisplay((EGLNativeDisplayType)h->display);
  if (h->egl == EGL_NO_DISPLAY || !eglInitialize(h->egl, NULL, NULL) ||
      !eglBindAPI(EGL_OPENGL_API))
    goto fail;
  EGLint attrs[] = {EGL_SURFACE_TYPE,
                    EGL_WINDOW_BIT,
                    EGL_RENDERABLE_TYPE,
                    EGL_OPENGL_BIT,
                    EGL_RED_SIZE,
                    8,
                    EGL_GREEN_SIZE,
                    8,
                    EGL_BLUE_SIZE,
                    8,
                    EGL_ALPHA_SIZE,
                    8,
                    EGL_NONE};
  EGLConfig config;
  EGLint count;
  if (!eglChooseConfig(h->egl, attrs, &config, 1, &count) || count != 1)
    goto fail;
  EGLint ctx[] = {EGL_CONTEXT_MAJOR_VERSION,
                  3,
                  EGL_CONTEXT_MINOR_VERSION,
                  3,
                  EGL_CONTEXT_OPENGL_PROFILE_MASK,
                  EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT,
                  EGL_NONE};
  h->context = eglCreateContext(h->egl, config, EGL_NO_CONTEXT, ctx);
  if (h->context == EGL_NO_CONTEXT)
    goto fail;
  h->target = eglCreateWindowSurface(h->egl, config,
                                     (EGLNativeWindowType)h->window, NULL);
  if (h->target == EGL_NO_SURFACE || !dyn_window_current(h))
    goto fail;
  return h;
fail:
  dyn_window_close(h);
  return NULL;
}
static void clipboard_loss(Host *h) {
  if (h->desktop.event_enabled && h->desktop.event_dropped != UINT32_MAX) h->desktop.event_dropped++;
}
static void clipboard_deliver(Host *h) {
  Desktop *d = &h->desktop;
  d->pending.keys |= DYN_KEY_PASTE;
  d->pending.clipboard = h->clipboard_received;
  d->pending.clipboard_length = h->clipboard_received_length;
  uint32_t at = 0, chunks = 0;
  do {
    uint32_t count = h->clipboard_received_length - at;
    if (count > 256) { count = 256; while ((h->clipboard_received[at + count] & 0xc0) == 0x80) count--; }
    at += count; chunks++;
  } while (at < h->clipboard_received_length);
  if (!d->event_enabled) return;
  if (d->event_dropped || chunks > DYN_EVENT_CAPACITY - d->event_count) { clipboard_loss(h); return; }
  at = 0;
  do {
    dyn_window_event event = {0}; event.kind = DYN_EVENT_CLIPBOARD;
    uint32_t count = h->clipboard_received_length - at;
    if (count > 256) { count = 256; while ((h->clipboard_received[at + count] & 0xc0) == 0x80) count--; }
    event.x = (int32_t)at; event.width = (int32_t)h->clipboard_received_length; event.text_length = count;
    if (count) memcpy(event.text, h->clipboard_received + at, count);
    at += count; event.button = at == h->clipboard_received_length; desktop_push(d, event);
  } while (at < h->clipboard_received_length);
}
static void clipboard_publish(Host *h, uint8_t *bytes, uint32_t length) {
  free(h->clipboard_received); h->clipboard_received = bytes; h->clipboard_received_length = length;
  /* Legacy pending state must not retain a pointer to the released snapshot. */
  if (h->desktop.pending.keys & DYN_KEY_PASTE) {
    h->desktop.pending.clipboard = bytes; h->desktop.pending.clipboard_length = length;
  }
}
static void clipboard_finish(Host *h, int status) {
  close(h->receive_fd); h->receive_fd = -1;
  if (status == 1 && !surrounding_utf8(h->clipboard_incoming, h->clipboard_incoming_length)) status = -3;
  h->clipboard_status = status;
  if (status == 1) {
    clipboard_publish(h, h->clipboard_incoming, h->clipboard_incoming_length);
    h->clipboard_incoming = NULL;
    if (h->clipboard_ordered) clipboard_deliver(h);
  } else if (h->clipboard_ordered) clipboard_loss(h);
  free(h->clipboard_incoming); h->clipboard_incoming = NULL; h->clipboard_incoming_length = 0;
}
static void receive_clipboard(Host *h) {
  if (h->receive_fd < 0) return;
  if (now_ms() >= h->clipboard_deadline) { clipboard_finish(h, 0); return; }
  uint8_t bytes[16384];
  for (;;) {
    ssize_t n = read(h->receive_fd, bytes, sizeof(bytes));
    if (n > 0) {
      if ((uint32_t)n > WAYLAND_CLIPBOARD_LIMIT - h->clipboard_incoming_length) { clipboard_finish(h, -2); return; }
      uint32_t length = h->clipboard_incoming_length + (uint32_t)n;
      uint8_t *next = realloc(h->clipboard_incoming, length);
      if (!next) { clipboard_finish(h, 0); return; }
      h->clipboard_incoming = next; memcpy(next + h->clipboard_incoming_length, bytes, (size_t)n);
      h->clipboard_incoming_length = length; h->clipboard_deadline = now_ms() + 5000; continue;
    }
    if (n < 0 && errno == EINTR) continue;
    if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) return;
    clipboard_finish(h, n == 0 ? 1 : 0); return;
  }
}
static void repeat_keys(Host *h) {
  if (!h->repeat_key || h->repeat_rate <= 0)
    return;
  int64_t now = now_ms();
  while (now >= h->repeat_next) {
    event_keyboard(h,h->repeat_key,1,1);
    press(h, h->repeat_key);
    int64_t interval=1000/h->repeat_rate;
    if (interval<1) interval=1;
    h->repeat_next += interval;
  }
}
int32_t dyn_window_poll(void *p, dyn_window_frame *out) {
  Host *h = p;
  uint64_t wake_count;
  if (read(h->wake_fd,&wake_count,sizeof(wake_count))==(ssize_t)sizeof(wake_count)) desktop_simple(&h->desktop,DYN_EVENT_WAKE);
  repeat_keys(h);
  receive_clipboard(h);
  send_clipboards(h);
  while (wl_display_prepare_read(h->display) != 0) {
    if (wl_display_dispatch_pending(h->display) < 0)
      return 0;
  }
  if (wl_display_flush(h->display) < 0 && errno != EAGAIN) {
    wl_display_cancel_read(h->display);
    return 0;
  }
  struct pollfd fd = {.fd = wl_display_get_fd(h->display), .events = POLLIN};
  int ready = poll(&fd, 1, 0);
  if (ready < 0) {
    wl_display_cancel_read(h->display);
    if (errno != EINTR)
      return 0;
  } else if (ready > 0 && (fd.revents & POLLIN)) {
    if (wl_display_read_events(h->display) < 0)
      return 0;
  } else {
    wl_display_cancel_read(h->display);
    if (ready > 0 && (fd.revents & (POLLERR | POLLHUP | POLLNVAL)))
      return 0;
  }
  if (wl_display_dispatch_pending(h->display) < 0)
    return 0;
  *out = h->frame;
  h->frame.flags &= DYN_DOWN | DYN_CLOSE;
  return 1;
}
int32_t dyn_window_set_title(void *p, const uint8_t *text, uint32_t length) {
  Host *h = p;
  if (!h || !h->toplevel || (length && !text)) return 0;
  if (length > 4096) return -2;
  if (!surrounding_utf8(text,length)) return 0;
  char title[4097];
  if (length) memcpy(title,text,length);
  title[length] = 0;
  xdg_toplevel_set_title(h->toplevel,title);
  return 1;
}
int32_t dyn_window_set_size(void *p, int32_t width, int32_t height) {
  Host *h = p;
  if (!h || !h->window || width <= 0 || height <= 0 || h->scale <= 0 ||
      width % h->scale || height % h->scale) return 0;
  if (h->size_constrained) return -1;
  h->frame.width = width; h->frame.height = height;
  wl_egl_window_resize(h->window,width,height,0,0);
  desktop_resize(&h->desktop,width,height);
  return 1;
}
int32_t dyn_window_set_swap_interval(void *p, int32_t interval) {
  Host *h = p;
  if (!h || interval < 0 || eglGetCurrentContext() != h->context ||
      eglGetCurrentDisplay() != h->egl || eglGetCurrentSurface(EGL_DRAW) != h->target) return 0;
  return eglSwapInterval(h->egl,interval) == EGL_TRUE;
}
int32_t dyn_window_current(void *p) {
  Host *h = p;
  return eglMakeCurrent(h->egl, h->target, h->target, h->context) == EGL_TRUE;
}
int32_t dyn_window_swap(void *p) {
  Host *h = p;
  return eglSwapBuffers(h->egl, h->target) == EGL_TRUE;
}
void *dyn_window_proc(const char *name) {
  return (void *)eglGetProcAddress(name);
}

static void apply_cursor(Host *h) {
  static const char *names[5] = {"left_ptr", "xterm", "hand2", "sb_h_double_arrow", "sb_v_double_arrow"};
  if (!h->theme || !h->pointer || !h->cursor_surface)
    return;
  struct wl_cursor *cursor = wl_cursor_theme_get_cursor(h->theme, names[h->cursor]);
  if (!cursor && h->cursor)
    cursor = wl_cursor_theme_get_cursor(h->theme, names[0]);
  if (!cursor || !cursor->image_count)
    return;
  struct wl_cursor_image *image = cursor->images[0];
  struct wl_buffer *buffer = wl_cursor_image_get_buffer(image);
  if (!buffer)
    return;
  wl_surface_set_buffer_scale(h->cursor_surface, h->scale);
  wl_pointer_set_cursor(h->pointer, h->pointer_serial, h->cursor_surface,
                        (int32_t)image->hotspot_x / h->scale, (int32_t)image->hotspot_y / h->scale);
  wl_surface_attach(h->cursor_surface, buffer, 0, 0);
  wl_surface_damage(h->cursor_surface, 0, 0, (int32_t)image->width, (int32_t)image->height);
  wl_surface_commit(h->cursor_surface);
}
void dyn_window_desktop_take(void *p, dyn_window_desktop *out) {
  Host *h = p;
  desktop_take(&h->desktop, out, (float)h->scale);
}
int32_t dyn_window_try_set_clipboard(void *p, const uint8_t *text, uint32_t length) {
  Host *h = p;
  if (!h) return 0;
  if (length > WAYLAND_CLIPBOARD_LIMIT) return -2;
  if (!surrounding_utf8(text, length)) return -3;
  if (!h->data_manager || !h->data_device) return -1;
  if (!h->serial) return -4;
  uint8_t *owned = malloc(length ? length : 1);
  if (!owned) return 0;
  if (length) memcpy(owned, text, length);
  struct wl_data_source *source = wl_data_device_manager_create_data_source(h->data_manager);
  if (!source) { free(owned); return 0; }
  if (wl_data_source_add_listener(source, &source_listener, h) < 0) { wl_data_source_destroy(source); free(owned); return 0; }
  wl_data_source_offer(source, "text/plain;charset=utf-8"); wl_data_source_offer(source, "UTF8_STRING");
  wl_data_device_set_selection(h->data_device, source, h->serial);
  if (wl_display_flush(h->display) < 0 && errno != EAGAIN) {
    wl_data_source_destroy(source); free(owned); return 0;
  }
  if (h->source) wl_data_source_destroy(h->source);
  h->source = source; free(h->clipboard_owned); h->clipboard_owned = owned; h->clipboard_owned_length = length;
  return 1;
}
void dyn_window_set_clipboard(void *p, const uint8_t *text, uint32_t length) {
  (void)dyn_window_try_set_clipboard(p, text, length);
}
static void clipboard_request(Host *h, int ordered) {
  if (h->receive_fd >= 0) { if (ordered) clipboard_loss(h); return; }
  h->clipboard_ordered = ordered; h->clipboard_status = 0;
  if (h->source) {
    uint8_t *snapshot = malloc(h->clipboard_owned_length ? h->clipboard_owned_length : 1);
    if (!snapshot) { if (ordered) clipboard_loss(h); return; }
    if (h->clipboard_owned_length) memcpy(snapshot, h->clipboard_owned, h->clipboard_owned_length);
    clipboard_publish(h, snapshot, h->clipboard_owned_length); h->clipboard_status = 1;
    if (ordered) clipboard_deliver(h);
    return;
  }
  if (!h->data_device) { h->clipboard_status = -1; return; }
  if (!h->offer) {
    clipboard_publish(h, NULL, 0);
    h->clipboard_status = 1; if (ordered) clipboard_deliver(h); return;
  }
  if (!h->offer_text) { h->clipboard_status = -1; return; }
  int fds[2];
  /* Only our reader is nonblocking: the peer controls its writer policy. */
  if (pipe2(fds, O_CLOEXEC) != 0) return;
  if (fcntl(fds[0], F_SETFL, O_NONBLOCK) < 0) { close(fds[0]); close(fds[1]); return; }
  wl_data_offer_receive(h->offer, "text/plain;charset=utf-8", fds[1]); close(fds[1]);
  h->receive_fd = fds[0]; h->clipboard_incoming_length = 0; h->clipboard_status = -4;
  h->clipboard_deadline = now_ms() + 5000;
  if (wl_display_flush(h->display) < 0 && errno != EAGAIN) clipboard_finish(h, 0);
}
void dyn_window_request_paste(void *p) { if (p) clipboard_request(p, 1); }
void dyn_window_request_paste_snapshot(void *p) { if (p) clipboard_request(p, 0); }
int32_t dyn_window_paste_pending(void *p) { return p && ((Host *)p)->receive_fd >= 0; }
int32_t dyn_window_paste_status(void *p) { return p ? ((Host *)p)->clipboard_status : 0; }
void dyn_window_set_cursor(void *p, int32_t cursor) {
  Host *h = p;
  if (cursor < 0 || cursor > 4 || cursor == h->cursor)
    return;
  h->cursor = cursor;
  apply_cursor(h);
}
void dyn_window_listen_events(void *p,int32_t enabled) {
  if (p) desktop_listen(&((Host *)p)->desktop,enabled);
}
int32_t dyn_window_next_event(void *p,dyn_window_event *out) {
  return p && out ? desktop_next(&((Host *)p)->desktop,out):0;
}
int32_t dyn_window_wake(void *p) {
  if (!p) return 0;
  uint64_t one=1;
  return write(((Host *)p)->wake_fd,&one,sizeof(one))==(ssize_t)sizeof(one) || errno==EAGAIN;
}
void dyn_window_wait(void *p, int32_t timeout) {
  Host *h = p;
  if (h->desktop.event_count || h->desktop.event_dropped) return;
  if (h->repeat_key && h->repeat_rate > 0) {
    int64_t left = h->repeat_next - now_ms();
    if (left < 0)
      left = 0;
    if (timeout < 0 || left < timeout)
      timeout = (int32_t)left;
  }
  wl_display_flush(h->display);
  if (h->receive_fd >= 0) {
    int64_t left = h->clipboard_deadline - now_ms();
    if (left < 0) left = 0;
    if (timeout < 0 || left < timeout) timeout = (int32_t)left;
  }
  struct pollfd fds[11] = {{.fd = wl_display_get_fd(h->display), .events = POLLIN},
                          {.fd = h->wake_fd, .events = POLLIN},
                          {.fd = h->receive_fd, .events = POLLIN}};
  unsigned count = 3;
  for (ClipboardSend *send = h->clipboard_sends; send && count < 11; send = send->next)
    fds[count++] = (struct pollfd){.fd = send->fd, .events = POLLOUT};
  poll(fds, count, timeout);
}

void dyn_window_composition_get(void *p, dyn_window_composition *out) {
  Host *h = p;
  *out = h->composition;
}
void dyn_window_set_text_input(void *p, int32_t enabled, int32_t x, int32_t y, int32_t width, int32_t height) {
  Host *h = p;
  /* Focus changes can cancel preedit synchronously, but that cancellation
   * is not evidence that a later keyboard edit was consumed by the IME. */
  uint32_t consumed_before = h->desktop.pending.keys & DYN_KEY_IME;
  int changed = (enabled != 0) != h->text_enabled || h->caret[0] != x || h->caret[1] != y ||
                h->caret[2] != width || h->caret[3] != height;
  if (!enabled && h->text_enabled && h->desktop.surrounding.token)
    h->desktop.consumed_token = h->desktop.surrounding.token;
  h->text_enabled = enabled != 0;
  h->text_configured = 1;
  if (!enabled) {
    h->pending_commit_length = 0;
    h->pending_commit_overflow = 0;
    h->pending_has_preedit = 0;
    h->pending_has_delete = 0;
  }
  h->caret[0] = x;
  h->caret[1] = y;
  h->caret[2] = width;
  h->caret[3] = height;
  if (!enabled && h->composition.active) {
    memset(&h->composition, 0, sizeof(h->composition));
    composition_changed(&h->desktop, &h->composition);
  }
  if (changed) {
    text_apply_state(h);
    wl_display_flush(h->display);
  }
  if (!enabled)
    h->desktop.pending.keys = (h->desktop.pending.keys & ~(uint32_t)DYN_KEY_IME) | consumed_before;
}

uint32_t dyn_window_clipboard_get(void *p, const uint8_t **text) {
  Host *h = p;
  *text = h->clipboard_received;
  return h->clipboard_received_length;
}

int32_t dyn_window_set_surrounding_text(void *p, const uint8_t *text, uint32_t length,
                                        uint32_t cursor, uint32_t anchor, uint64_t token, uint32_t cause) {
  Host *h = p;
  if (!h || cause > 1) return 0;
  /* Wayland strings and protocol messages impose a stricter limit. */
  if (length > 4000) return -2;
  if (!h->text_input) return -1;
  uint64_t previous = h->desktop.surrounding.token;
  int32_t result = desktop_surrounding(&h->desktop, text, length, cursor, anchor, token);
  if (result == 1 && previous != token) {
    h->surrounding_cause = cause;
    text_apply_state(h);
    wl_display_flush(h->display);
  }
  return result;
}
