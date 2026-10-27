#define WIN32_LEAN_AND_MEAN
#include "window.h"
#include "desktop_common.h"
#include <GL/gl.h>
#include <stdlib.h>
#include <windows.h>
#include <windowsx.h>
typedef struct Host {
  HWND window;
  HDC dc;
  HGLRC context;
  dyn_window_frame frame;
  Desktop desktop;
  WCHAR high_surrogate;
  HCURSOR cursors[5];
  int cursor;
} Host;
static int control_down(void) { return (GetKeyState(VK_CONTROL) & 0x8000) != 0; }
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
  case WM_SYSKEYDOWN: {
    uint32_t *keys = &h->desktop.pending.keys;
    if (w == VK_TAB) {
      h->frame.flags |= DYN_TAB;
      *keys |= DYN_KEY_TAB;
    } else if (w == VK_RETURN || w == VK_SPACE) {
      h->frame.flags |= DYN_ACTIVATE;
      if (w == VK_RETURN)
        *keys |= DYN_KEY_ENTER;
    } else if (w == VK_LEFT) {
      h->frame.flags |= DYN_LEFT;
      *keys |= DYN_KEY_LEFT;
    } else if (w == VK_RIGHT) {
      h->frame.flags |= DYN_RIGHT;
      *keys |= DYN_KEY_RIGHT;
    } else if (w == VK_BACK)
      *keys |= DYN_KEY_BACKSPACE;
    else if (w == VK_DELETE)
      *keys |= DYN_KEY_DELETE;
    else if (w == VK_HOME)
      *keys |= DYN_KEY_HOME;
    else if (w == VK_END)
      *keys |= DYN_KEY_END;
    else if (w == VK_ESCAPE)
      *keys |= DYN_KEY_ESCAPE;
    else if (control_down() && w == 'A')
      *keys |= DYN_KEY_SELECT_ALL;
    else if (control_down() && w == 'C')
      *keys |= DYN_KEY_COPY;
    else if (control_down() && w == 'X')
      *keys |= DYN_KEY_CUT;
    else if (control_down() && w == 'V')
      dyn_window_request_paste(h);
    if (GetKeyState(VK_SHIFT) & 0x8000)
      *keys |= DYN_KEY_SHIFT;
    else
      *keys &= ~(uint32_t)DYN_KEY_SHIFT;
    if (message == WM_SYSKEYDOWN)
      break;
    return 0;
  }
  case WM_KEYUP:
    if (w == VK_SHIFT)
      h->desktop.pending.keys &= ~(uint32_t)DYN_KEY_SHIFT;
    return 0;
  case WM_CHAR: {
    /* WM_CHAR carries UTF-16; the IME delivers composed text here too. */
    WCHAR unit = (WCHAR)w;
    if (control_down() && unit < 32)
      return 0;
    if (unit >= 0xd800 && unit <= 0xdbff) {
      h->high_surrogate = unit;
      return 0;
    }
    uint32_t codepoint = unit;
    if (unit >= 0xdc00 && unit <= 0xdfff) {
      if (!h->high_surrogate)
        return 0;
      codepoint = 0x10000 + (((uint32_t)h->high_surrogate - 0xd800) << 10) + (unit - 0xdc00);
    }
    h->high_surrogate = 0;
    desktop_codepoint(&h->desktop, codepoint);
    return 0;
  }
  case WM_MOUSEWHEEL:
    h->desktop.pending.scroll_y -= (float)GET_WHEEL_DELTA_WPARAM(w) / 120.0f * 48.0f;
    return 0;
  case WM_MOUSEHWHEEL:
    h->desktop.pending.scroll_x += (float)GET_WHEEL_DELTA_WPARAM(w) / 120.0f * 48.0f;
    return 0;
  case WM_SETCURSOR:
    if (LOWORD(l) == HTCLIENT && h->cursors[h->cursor]) {
      SetCursor(h->cursors[h->cursor]);
      return TRUE;
    }
    break;
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
  {
    LPCWSTR shapes[5] = {MAKEINTRESOURCEW(32512), MAKEINTRESOURCEW(32513), MAKEINTRESOURCEW(32649), MAKEINTRESOURCEW(32644), MAKEINTRESOURCEW(32645)};
    for (int i = 0; i < 5; ++i)
      h->cursors[i] = LoadCursorW(NULL, shapes[i]);
  }
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

static float window_scale(Host *h) {
  typedef UINT(WINAPI * Dpi)(HWND);
  Dpi dpi = (Dpi)(void *)GetProcAddress(GetModuleHandleW(L"user32.dll"), "GetDpiForWindow");
  if (dpi && h->window) {
    UINT value = dpi(h->window);
    if (value)
      return (float)value / 96.0f;
  }
  HDC screen = GetDC(NULL);
  int value = screen ? GetDeviceCaps(screen, LOGPIXELSX) : 96;
  if (screen)
    ReleaseDC(NULL, screen);
  return value > 0 ? (float)value / 96.0f : 1.0f;
}
void dyn_window_desktop_take(void *p, dyn_window_desktop *out) {
  Host *h = p;
  desktop_take(&h->desktop, out, window_scale(h));
}
void dyn_window_set_clipboard(void *p, const uint8_t *text, uint32_t length) {
  Host *h = p;
  desktop_own(&h->desktop, text, length);
  int units = MultiByteToWideChar(CP_UTF8, 0, (const char *)h->desktop.owned, (int)h->desktop.owned_length, NULL, 0);
  HGLOBAL memory = GlobalAlloc(GMEM_MOVEABLE, ((size_t)units + 1) * sizeof(WCHAR));
  if (!memory)
    return;
  WCHAR *wide = GlobalLock(memory);
  MultiByteToWideChar(CP_UTF8, 0, (const char *)h->desktop.owned, (int)h->desktop.owned_length, wide, units);
  wide[units] = 0;
  GlobalUnlock(memory);
  if (!OpenClipboard(h->window)) {
    GlobalFree(memory);
    return;
  }
  EmptyClipboard();
  if (!SetClipboardData(CF_UNICODETEXT, memory))
    GlobalFree(memory);
  CloseClipboard();
}
void dyn_window_request_paste(void *p) {
  Host *h = p;
  if (!OpenClipboard(h->window))
    return;
  HANDLE memory = GetClipboardData(CF_UNICODETEXT);
  const WCHAR *wide = memory ? GlobalLock(memory) : NULL;
  if (wide) {
    int bytes = WideCharToMultiByte(CP_UTF8, 0, wide, -1, (char *)h->desktop.received, DYN_CLIPBOARD_LIMIT, NULL, NULL);
    h->desktop.received_length = bytes > 0 ? (uint32_t)bytes - 1 : 0;
    GlobalUnlock(memory);
    desktop_deliver(&h->desktop);
  }
  CloseClipboard();
}
void dyn_window_set_cursor(void *p, int32_t cursor) {
  Host *h = p;
  if (cursor < 0 || cursor > 4)
    return;
  h->cursor = cursor;
  SetCursor(h->cursors[cursor]);
}
void dyn_window_wait(void *p, int32_t timeout) {
  (void)p;
  MsgWaitForMultipleObjects(0, NULL, FALSE, timeout < 0 ? INFINITE : (DWORD)timeout, QS_ALLINPUT);
}
