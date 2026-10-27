#define WIN32_LEAN_AND_MEAN
#include "window.h"
#include <GL/gl.h>
#include <stdlib.h>
#include <windows.h>
#include <windowsx.h>
typedef struct Host {
  HWND window;
  HDC dc;
  HGLRC context;
  dyn_window_frame frame;
} Host;
static LRESULT CALLBACK procedure(HWND window, UINT message, WPARAM w,
                                  LPARAM l) {
  Host *h = (Host *)GetWindowLongPtrW(window, GWLP_USERDATA);
  if (message == WM_NCCREATE) {
    h = (Host *)((CREATESTRUCTW *)l)->lpCreateParams;
    SetWindowLongPtrW(window, GWLP_USERDATA, (LONG_PTR)h);
    h->window = window;
  }
  if (!h)
    return DefWindowProcW(window, message, w, l);
  switch (message) {
  case WM_CLOSE:
    h->frame.flags |= DYN_CLOSE;
    return 0;
  case WM_NCDESTROY:
    SetWindowLongPtrW(window, GWLP_USERDATA, 0);
    break;
  case WM_SIZE: {
    RECT r;
    if (GetClientRect(window, &r)) {
      h->frame.width = r.right;
      h->frame.height = r.bottom;
    }
    return 0;
  }
  case WM_MOUSEMOVE:
    h->frame.x = GET_X_LPARAM(l);
    h->frame.y = GET_Y_LPARAM(l);
    return 0;
  case WM_LBUTTONDOWN:
    h->frame.x = GET_X_LPARAM(l);
    h->frame.y = GET_Y_LPARAM(l);
    h->frame.flags |= DYN_DOWN | DYN_PRESSED;
    SetCapture(window);
    return 0;
  case WM_LBUTTONUP:
    h->frame.x = GET_X_LPARAM(l);
    h->frame.y = GET_Y_LPARAM(l);
    h->frame.flags &= ~DYN_DOWN;
    h->frame.flags |= DYN_RELEASED;
    if (GetCapture() == window)
      ReleaseCapture();
    return 0;
  case WM_CAPTURECHANGED:
  case WM_KILLFOCUS:
    if (h->frame.flags & DYN_DOWN)
      h->frame.flags |= DYN_RELEASED;
    h->frame.flags &= ~DYN_DOWN;
    return 0;
  case WM_KEYDOWN:
    if (w == VK_TAB)
      h->frame.flags |= DYN_TAB;
    else if (w == VK_RETURN || w == VK_SPACE)
      h->frame.flags |= DYN_ACTIVATE;
    else if (w == VK_LEFT)
      h->frame.flags |= DYN_LEFT;
    else if (w == VK_RIGHT)
      h->frame.flags |= DYN_RIGHT;
    return 0;
  }
  return DefWindowProcW(window, message, w, l);
}
void dyn_window_close(void *p) {
  Host *h = p;
  if (!h)
    return;
  if (h->context) {
    if (wglGetCurrentContext() == h->context)
      wglMakeCurrent(NULL, NULL);
    wglDeleteContext(h->context);
  }
  if (h->dc && h->window)
    ReleaseDC(h->window, h->dc);
  if (h->window)
    DestroyWindow(h->window);
  free(h);
}
void *dyn_window_proc(const char *name) {
  PROC p = wglGetProcAddress(name);
  if (p == NULL || p == (PROC)1 || p == (PROC)2 || p == (PROC)3 ||
      p == (PROC)-1)
    p = GetProcAddress(GetModuleHandleW(L"opengl32.dll"), name);
  return (void *)p;
}
void *dyn_window_open(const char *title, int32_t width, int32_t height) {
  Host *h = calloc(1, sizeof(*h));
  if (!h)
    return NULL;
  h->frame.width = width;
  h->frame.height = height;
  HINSTANCE instance = GetModuleHandleW(NULL);
  WNDCLASSW cls = {0};
  cls.style = CS_OWNDC;
  cls.lpfnWndProc = procedure;
  cls.hInstance = instance;
  cls.lpszClassName = L"DynNativeGLWindow";
  cls.hCursor = LoadCursorW(NULL, MAKEINTRESOURCEW(32512));
  if (!RegisterClassW(&cls) && GetLastError() != ERROR_CLASS_ALREADY_EXISTS)
    goto fail;
  int length =
      MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, title, -1, NULL, 0);
  if (!length)
    goto fail;
  WCHAR *wide = malloc((size_t)length * sizeof(WCHAR));
  if (!wide)
    goto fail;
  MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, title, -1, wide, length);
  RECT bounds = {0, 0, width, height};
  if (!AdjustWindowRect(&bounds, WS_OVERLAPPEDWINDOW, FALSE)) {
    free(wide);
    goto fail;
  }
  if (!CreateWindowExW(0, cls.lpszClassName, wide, WS_OVERLAPPEDWINDOW,
                       CW_USEDEFAULT, CW_USEDEFAULT, bounds.right - bounds.left,
                       bounds.bottom - bounds.top, NULL, NULL, instance, h)) {
    free(wide);
    goto fail;
  }
  free(wide);
  h->dc = GetDC(h->window);
  if (!h->dc)
    goto fail;
  PIXELFORMATDESCRIPTOR format = {0};
  format.nSize = sizeof(format);
  format.nVersion = 1;
  format.dwFlags = PFD_DRAW_TO_WINDOW | PFD_SUPPORT_OPENGL | PFD_DOUBLEBUFFER;
  format.iPixelType = PFD_TYPE_RGBA;
  format.cColorBits = 24;
  format.cAlphaBits = 8;
  format.iLayerType = PFD_MAIN_PLANE;
  int selected = ChoosePixelFormat(h->dc, &format);
  if (!selected || !SetPixelFormat(h->dc, selected, &format))
    goto fail;
  h->context = wglCreateContext(h->dc);
  if (!h->context || !wglMakeCurrent(h->dc, h->context))
    goto fail;
  typedef HGLRC(WINAPI * Create)(HDC, HGLRC, const int *);
  Create create = (Create)dyn_window_proc("wglCreateContextAttribsARB");
  if (!create)
    goto fail;
  const int attrs[] = {0x2091, 3, 0x2092, 3, 0x9126, 1, 0};
  HGLRC core = create(h->dc, NULL, attrs);
  if (!core)
    goto fail;
  wglMakeCurrent(NULL, NULL);
  wglDeleteContext(h->context);
  h->context = core;
  if (!wglMakeCurrent(h->dc, h->context))
    goto fail;
  ShowWindow(h->window, SW_SHOW);
  UpdateWindow(h->window);
  return h;
fail:
  dyn_window_close(h);
  return NULL;
}
int32_t dyn_window_poll(void *p, dyn_window_frame *out) {
  Host *h = p;
  MSG message;
  while (PeekMessageW(&message, NULL, 0, 0, PM_REMOVE)) {
    if (message.message == WM_QUIT)
      h->frame.flags |= DYN_CLOSE;
    else {
      TranslateMessage(&message);
      DispatchMessageW(&message);
    }
  }
  *out = h->frame;
  h->frame.flags &= DYN_DOWN | DYN_CLOSE;
  return 1;
}
int32_t dyn_window_current(void *p) {
  Host *h = p;
  return wglMakeCurrent(h->dc, h->context) != 0;
}
int32_t dyn_window_swap(void *p) {
  Host *h = p;
  return SwapBuffers(h->dc) != 0;
}
