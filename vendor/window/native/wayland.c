#include "window.h"
#include "xdg-shell-client-protocol.h"
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
} Host;
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
    s->frame.width = w;
  if (h > 0)
    s->frame.height = h;
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
  (void)serial;
  (void)s;
  Host *h = p;
  h->frame.x = wl_fixed_to_int(x);
  h->frame.y = wl_fixed_to_int(y);
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
  h->frame.x = wl_fixed_to_int(x);
  h->frame.y = wl_fixed_to_int(y);
}
static void button(void *p, struct wl_pointer *q, uint32_t serial,
                   uint32_t time, uint32_t button, uint32_t state) {
  (void)q;
  (void)serial;
  (void)time;
  Host *h = p;
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
  (void)p;
  (void)q;
  (void)time;
  (void)axis;
  (void)v;
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
  (void)p;
  (void)k;
  (void)format;
  (void)size;
  close(fd);
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
}
static void key(void *p, struct wl_keyboard *k, uint32_t serial, uint32_t time,
                uint32_t key, uint32_t state) {
  (void)k;
  (void)serial;
  (void)time;
  Host *h = p;
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
  (void)p;
  (void)k;
  (void)serial;
  (void)depressed;
  (void)latched;
  (void)locked;
  (void)group;
}
static void repeat(void *p, struct wl_keyboard *k, int32_t rate,
                   int32_t delay) {
  (void)p;
  (void)k;
  (void)rate;
  (void)delay;
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
  h->display = wl_display_connect(NULL);
  if (!h->display)
    goto fail;
  h->registry = wl_display_get_registry(h->display);
  wl_registry_add_listener(h->registry, &registry_listener, h);
  if (wl_display_roundtrip(h->display) < 0 || !h->wm || !h->compositor)
    goto fail;
  h->surface = wl_compositor_create_surface(h->compositor);
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
int32_t dyn_window_poll(void *p, dyn_window_frame *out) {
  Host *h = p;
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
