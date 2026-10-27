#include "window.h"
#include "desktop_common.h"
#include "xdg-shell-client-protocol.h"
#include <fcntl.h>
#include <locale.h>
#include <sys/mman.h>
#include <time.h>
#include <wayland-cursor.h>
#include <xkbcommon/xkbcommon-compose.h>
#include <xkbcommon/xkbcommon.h>
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <errno.h>
#include <poll.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <wayland-client.h>
#include <wayland-egl.h>
typedef struct Host {
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
  (void)a;
  Host *s = p;
  if (w > 0)
    s->frame.width = w * s->scale;
  if (h > 0)
    s->frame.height = h * s->scale;
  if (s->window)
    wl_egl_window_resize(s->window, s->frame.width, s->frame.height, 0, 0);
}
static void closing(void *p, struct xdg_toplevel *t) {
  (void)t;
  ((Host *)p)->frame.flags |= DYN_CLOSE;
}
static const struct xdg_toplevel_listener top_listener = {.configure = size,
                                                          .close = closing};
static void enter(void *p, struct wl_pointer *q, uint32_t serial,
                  struct wl_surface *s, wl_fixed_t x, wl_fixed_t y) {
  (void)q;
  (void)s;
  Host *h = p;
  h->frame.x = wl_fixed_to_int(x) * h->scale;
  h->frame.y = wl_fixed_to_int(y) * h->scale;
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
}
static void button(void *p, struct wl_pointer *q, uint32_t serial,
                   uint32_t time, uint32_t button, uint32_t state) {
  (void)q;
  (void)time;
  Host *h = p;
  h->serial = serial;
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
  if (axis == WL_POINTER_AXIS_VERTICAL_SCROLL)
    h->desktop.pending.scroll_y += amount;
  else
    h->desktop.pending.scroll_x += amount;
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
}
static void key(void *p, struct wl_keyboard *k, uint32_t serial, uint32_t time,
                uint32_t key, uint32_t state) {
  (void)k;
  (void)time;
  Host *h = p;
  h->serial = serial;
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
static void offer_mime(void *p, struct wl_data_offer *o, const char *mime) {
  Host *h = p;
  if (o == h->offer && (!strcmp(mime, "text/plain;charset=utf-8") || !strcmp(mime, "UTF8_STRING")))
    h->offer_text = 1;
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
  wl_data_offer_add_listener(o, &offer_listener, h);
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
    wl_data_offer_destroy(o);
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
    wl_data_offer_destroy(h->offer);
  h->offer = o;
  h->offer_text = 0;
  /* Mime offers for o arrived before this event. */
  if (o)
    h->offer_text = 1;
}
static const struct wl_data_device_listener data_listener = {
    .data_offer = data_offer, .enter = data_enter, .leave = data_leave,
    .motion = data_motion, .drop = data_drop, .selection = selection};
static void source_target(void *p, struct wl_data_source *s, const char *m) {
  (void)p;
  (void)s;
  (void)m;
}
static void source_send(void *p, struct wl_data_source *s, const char *mime, int32_t fd) {
  (void)s;
  (void)mime;
  Host *h = p;
  uint32_t written = 0;
  while (written < h->desktop.owned_length) {
    ssize_t n = write(fd, h->desktop.owned + written, h->desktop.owned_length - written);
    if (n <= 0 && errno != EINTR)
      break;
    if (n > 0)
      written += (uint32_t)n;
  }
  close(fd);
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
  if (h->receive_fd > 0)
    close(h->receive_fd);
  if (h->offer)
    wl_data_offer_destroy(h->offer);
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
static void receive_clipboard(Host *h) {
  if (h->receive_fd < 0)
    return;
  for (;;) {
    if (h->desktop.received_length >= DYN_CLIPBOARD_LIMIT)
      break;
    ssize_t n = read(h->receive_fd, h->desktop.received + h->desktop.received_length,
                     DYN_CLIPBOARD_LIMIT - h->desktop.received_length);
    if (n > 0) {
      h->desktop.received_length += (uint32_t)n;
      continue;
    }
    if (n < 0 && (errno == EAGAIN || errno == EINTR))
      return;
    break;
  }
  close(h->receive_fd);
  h->receive_fd = -1;
  desktop_deliver(&h->desktop);
}
static void repeat_keys(Host *h) {
  if (!h->repeat_key || h->repeat_rate <= 0)
    return;
  int64_t now = now_ms();
  while (now >= h->repeat_next) {
    press(h, h->repeat_key);
    h->repeat_next += 1000 / h->repeat_rate;
  }
}
int32_t dyn_window_poll(void *p, dyn_window_frame *out) {
  Host *h = p;
  repeat_keys(h);
  receive_clipboard(h);
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
void dyn_window_set_clipboard(void *p, const uint8_t *text, uint32_t length) {
  Host *h = p;
  desktop_own(&h->desktop, text, length);
  if (!h->data_manager || !h->data_device)
    return;
  if (h->source)
    wl_data_source_destroy(h->source);
  h->source = wl_data_device_manager_create_data_source(h->data_manager);
  wl_data_source_add_listener(h->source, &source_listener, h);
  wl_data_source_offer(h->source, "text/plain;charset=utf-8");
  wl_data_source_offer(h->source, "UTF8_STRING");
  wl_data_device_set_selection(h->data_device, h->source, h->serial);
  wl_display_flush(h->display);
}
void dyn_window_request_paste(void *p) {
  Host *h = p;
  if (h->source) {
    /* Our own selection needs no round trip. */
    memcpy(h->desktop.received, h->desktop.owned, h->desktop.owned_length);
    h->desktop.received_length = h->desktop.owned_length;
    desktop_deliver(&h->desktop);
    return;
  }
  if (!h->offer || !h->offer_text || h->receive_fd >= 0)
    return;
  int fds[2];
  if (pipe2(fds, O_CLOEXEC | O_NONBLOCK) != 0)
    return;
  wl_data_offer_receive(h->offer, "text/plain;charset=utf-8", fds[1]);
  close(fds[1]);
  wl_display_flush(h->display);
  h->receive_fd = fds[0];
  h->desktop.received_length = 0;
}
void dyn_window_set_cursor(void *p, int32_t cursor) {
  Host *h = p;
  if (cursor < 0 || cursor > 4 || cursor == h->cursor)
    return;
  h->cursor = cursor;
  apply_cursor(h);
}
void dyn_window_wait(void *p, int32_t timeout) {
  Host *h = p;
  if (h->repeat_key && h->repeat_rate > 0) {
    int64_t left = h->repeat_next - now_ms();
    if (left < 0)
      left = 0;
    if (timeout < 0 || left < timeout)
      timeout = (int32_t)left;
  }
  wl_display_flush(h->display);
  struct pollfd fds[2] = {{.fd = wl_display_get_fd(h->display), .events = POLLIN},
                          {.fd = h->receive_fd, .events = POLLIN}};
  poll(fds, h->receive_fd >= 0 ? 2 : 1, timeout);
}
