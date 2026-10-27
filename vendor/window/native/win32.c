#define WIN32_LEAN_AND_MEAN
#include "desktop_common.h"
#include "window.h"
#include <GL/gl.h>
#include <stdlib.h>
#include <windows.h>
#include <windowsx.h>
#include <imm.h>
typedef struct Host {
  HWND window;
  HDC dc;
  HGLRC context;
  dyn_window_frame frame;
  Desktop desktop;
  WCHAR high_surrogate;
  uint32_t high_surrogate_repeats;
  HCURSOR cursors[5];
  int cursor;
  dyn_window_composition composition;
  int text_input, text_input_configured;
  RECT caret;
  /* IME-initiated selected-range reconversion. Keep the source identity until
   * END, including after rejection, so stale results never become insertions. */
  Surrounding reconvert;
  uint32_t reconvert_start, reconvert_end;
  int reconvert_pending, reconvert_active, reconvert_done;

} Host;
#define DYN_WAKE_MESSAGE (WM_APP + 983)
static uint32_t modifiers(void) {
  uint32_t value = 0;
  if (GetKeyState(VK_SHIFT) & 0x8000)
    value |= DYN_MOD_SHIFT;
  if (GetKeyState(VK_CONTROL) & 0x8000)
    value |= DYN_MOD_CONTROL;
  if (GetKeyState(VK_MENU) & 0x8000)
    value |= DYN_MOD_ALT;
  if ((GetKeyState(VK_LWIN) | GetKeyState(VK_RWIN)) & 0x8000)
    value |= DYN_MOD_SUPER;
  if (GetKeyState(VK_CAPITAL) & 1)
    value |= DYN_MOD_CAPS;
  if (GetKeyState(VK_NUMLOCK) & 1)
    value |= DYN_MOD_NUM;
  return value;
}
static uint32_t event_key(WPARAM key, LPARAM native) {
  if (key >= VK_F1 && key <= VK_F24)
    return DYN_F1 + (uint32_t)(key - VK_F1);
  switch (key) {
  case VK_ESCAPE:
    return DYN_ESCAPE;
  case VK_RETURN:
    return DYN_ENTER;
  case VK_TAB:
    return DYN_TAB_KEY;
  case VK_BACK:
    return DYN_BACKSPACE;
  case VK_DELETE:
    return DYN_DELETE;
  case VK_LEFT:
    return DYN_LEFT_KEY;
  case VK_RIGHT:
    return DYN_RIGHT_KEY;
  case VK_UP:
    return DYN_UP_KEY;
  case VK_DOWN:
    return DYN_DOWN_KEY;
  case VK_HOME:
    return DYN_HOME;
  case VK_END:
    return DYN_END;
  case VK_PRIOR:
    return DYN_PAGE_UP;
  case VK_NEXT:
    return DYN_PAGE_DOWN;
  case VK_INSERT:
    return DYN_INSERT;
  case VK_SHIFT:
  case VK_LSHIFT:
  case VK_RSHIFT:
    return DYN_SHIFT_KEY;
  case VK_CONTROL:
  case VK_LCONTROL:
  case VK_RCONTROL:
    return DYN_CONTROL_KEY;
  case VK_MENU:
  case VK_LMENU:
  case VK_RMENU:
    return DYN_ALT_KEY;
  case VK_LWIN:
  case VK_RWIN:
    return DYN_SUPER_KEY;
  default:
    break;
  }
  BYTE state[256] = {0};
  WCHAR text[4] = {0};
  /* Flag 4 leaves the layout's dead-key state unchanged (Windows 10+).
   * The zero modifier state gives layout-aware base characters. */
  int count = ToUnicodeEx((UINT)key, ((UINT)(uintptr_t)native >> 16) & 0xff,
                          state, text, 4, 4, GetKeyboardLayout(0));
  if (count == 0)
    return 0;
  uint32_t value = text[0];
  if (value >= 0xd800 && value <= 0xdbff && count > 1 && text[1] >= 0xdc00 &&
      text[1] <= 0xdfff)
    return 0x10000 + ((value - 0xd800) << 10) + text[1] - 0xdc00;
  return value >= 0xd800 && value <= 0xdfff ? 0 : value;
}
static uint32_t scan_code(LPARAM value) {
  return ((uint32_t)((uintptr_t)value >> 16) & 0xff) |
         (((uint32_t)((uintptr_t)value >> 24) & 1) << 8);
}
static int control_down(void) {
  return (GetKeyState(VK_CONTROL) & 0x8000) != 0;
}
static uint32_t message_repeats(LPARAM value) {
  uint32_t count = (uint32_t)(uintptr_t)value & 0xffff;
  /* Real key messages have a positive count; accept zero-count synthetic
   * messages as one, matching the earlier bridge behavior. */
  return count ? count : 1;
}
static void drop_events(Desktop *desktop, uint32_t count) {
  if (!desktop->event_enabled)
    return;
  uint32_t available = UINT32_MAX - desktop->event_dropped;
  desktop->event_dropped += count < available ? count : available;
}
static uint32_t event_space(const Desktop *desktop) {
  return desktop->event_enabled && !desktop->event_dropped
             ? DYN_EVENT_CAPACITY - desktop->event_count
             : 0;
}
static void repeated_key(Desktop *desktop, uint32_t key, uint32_t scan,
                         uint32_t mods, int repeated, uint32_t count) {
  uint32_t emitted = event_space(desktop);
  if (emitted > count)
    emitted = count;
  for (uint32_t i = 0; i < emitted; ++i)
    desktop_key(desktop, 1, key, scan, mods, repeated || i != 0);
  drop_events(desktop, count - emitted);
}
static void repeated_text(Desktop *desktop, uint32_t codepoint,
                          uint32_t count) {
  if (codepoint < 32 || codepoint == 127 || codepoint > 0x10ffff ||
      (codepoint >= 0xd800 && codepoint <= 0xdfff))
    return;
  uint32_t width = codepoint < 0x80      ? 1
                   : codepoint < 0x800   ? 2
                   : codepoint < 0x10000 ? 3
                                         : 4;
  uint32_t emitted = event_space(desktop);
  uint32_t summary = (DYN_TEXT_LIMIT - desktop->pending.text_length) / width;
  if (emitted < summary)
    emitted = summary;
  if (emitted > count)
    emitted = count;
  /* At most 256 iterations. Keep the legacy summary even if the ordered
   * queue is full, then account for all further dropped text in one step. */
  for (uint32_t i = 0; i < emitted; ++i)
    desktop_codepoint(desktop, codepoint);
  drop_events(desktop, count - emitted);
}
/* Unicode RECONVERTSTRING lengths are UTF-16 units, but all three offsets
 * are bytes (Microsoft RECONVERTSTRING contract). Never split a surrogate. */
static int surrounding_wide(const Surrounding *source, WCHAR *wide) {
  return source->length ? MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS,
      (const char *)source->text, (int)source->length, wide, DYN_SURROUND_LIMIT) : 0;
}
static LRESULT reconvert_request(Host *h, UINT request, RECONVERTSTRING *output) {
  const Surrounding *source = &h->desktop.surrounding;
  if (!h->text_input || !h->desktop.event_enabled || !source->token ||
      source->token == h->desktop.consumed_token || h->reconvert_active) return 0;
  uint32_t low = source->cursor < source->anchor ? source->cursor : source->anchor;
  uint32_t high = source->cursor > source->anchor ? source->cursor : source->anchor;
  /* No word-boundary heuristic: the caller selects the initial range. The
   * IME may expand it through CONFIRM; ordinary collapsed input stays basic. */
  if (request == IMR_RECONVERTSTRING &&
      (low == high || (h->reconvert_pending && !h->reconvert.token))) return 0;
  WCHAR wide[DYN_SURROUND_LIMIT + 1];
  int units = surrounding_wide(source, wide);
  if (source->length && !units) return 0;
  uint32_t size = (uint32_t)sizeof(*output) + ((uint32_t)units + 1) * sizeof(WCHAR);
  if (!output) return size;
  if (output->dwSize < size) return 0;
  RECONVERTSTRING result = {0};
  result.dwSize = size;
  result.dwStrLen = (DWORD)units;
  result.dwStrOffset = sizeof(result);
  result.dwCompStrOffset = surrounding_utf16(source->text, low) * sizeof(WCHAR);
  result.dwCompStrLen = surrounding_utf16(source->text, high) - result.dwCompStrOffset / sizeof(WCHAR);
  result.dwTargetStrOffset = result.dwCompStrOffset;
  result.dwTargetStrLen = result.dwCompStrLen;
  memcpy(output, &result, sizeof(result));
  memcpy((uint8_t *)output + result.dwStrOffset, wide, (size_t)units * sizeof(WCHAR));
  memset((uint8_t *)output + result.dwStrOffset + (size_t)units * sizeof(WCHAR), 0, sizeof(WCHAR));
  if (request == IMR_RECONVERTSTRING) {
    h->reconvert = *source;
    h->reconvert_start = low;
    h->reconvert_end = high;
    h->reconvert_pending = 1;
    h->reconvert_done = 0;
  }
  return size;
}
static LRESULT reconvert_confirm(Host *h, const RECONVERTSTRING *input) {
  if (!input || !h->text_input || !h->desktop.event_enabled || !h->reconvert_pending ||
      h->reconvert_active || !h->reconvert.token ||
      h->reconvert.token != h->desktop.surrounding.token ||
      h->reconvert.token == h->desktop.consumed_token) return 0;
  WCHAR wide[DYN_SURROUND_LIMIT + 1];
  int units = surrounding_wide(&h->reconvert, wide);
  if (input->dwVersion || input->dwSize < sizeof(*input) ||
      input->dwStrOffset < sizeof(*input) || input->dwStrOffset % sizeof(WCHAR) ||
      input->dwStrOffset > input->dwSize || input->dwStrLen != (DWORD)units ||
      input->dwStrLen > (input->dwSize - input->dwStrOffset) / sizeof(WCHAR) ||
      input->dwCompStrOffset % sizeof(WCHAR) || input->dwTargetStrOffset % sizeof(WCHAR) ||
      !input->dwCompStrLen) return 0;
  uint32_t start_units = input->dwCompStrOffset / sizeof(WCHAR);
  uint32_t target_units = input->dwTargetStrOffset / sizeof(WCHAR);
  if (start_units > (uint32_t)units || input->dwCompStrLen > (uint32_t)units - start_units ||
      target_units < start_units || target_units > start_units + input->dwCompStrLen ||
      input->dwTargetStrLen > start_units + input->dwCompStrLen - target_units ||
      memcmp((const uint8_t *)input + input->dwStrOffset, wide, (size_t)units * sizeof(WCHAR))) return 0;
  uint32_t start, end, target_start, target_end;
  if (!surrounding_byte(h->reconvert.text, h->reconvert.length, start_units, &start) ||
      !surrounding_byte(h->reconvert.text, h->reconvert.length, start_units + input->dwCompStrLen, &end) ||
      !surrounding_byte(h->reconvert.text, h->reconvert.length, target_units, &target_start) ||
      !surrounding_byte(h->reconvert.text, h->reconvert.length, target_units + input->dwTargetStrLen, &target_end)) return 0;
  h->reconvert_start = start;
  h->reconvert_end = end;
  return 1;
}
static void reconvert_result(Host *h, HWND window) {
  int accepted = 0;
  HIMC context = ImmGetContext(window);
  if (context) {
    LONG bytes = ImmGetCompositionStringW(context, GCS_RESULTSTR, NULL, 0);
    if (!h->reconvert_done && bytes >= 0 && bytes % (LONG)sizeof(WCHAR) == 0 &&
        bytes <= (LONG)(DYN_SURROUND_LIMIT * sizeof(WCHAR))) {
      WCHAR wide[DYN_SURROUND_LIMIT];
      LONG copied = bytes ? ImmGetCompositionStringW(context, GCS_RESULTSTR, wide, (DWORD)bytes) : 0;
      if (copied == bytes) {
        uint8_t utf8[DYN_SURROUND_LIMIT];
        int count = bytes ? WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, wide,
            (int)(bytes / (LONG)sizeof(WCHAR)), (char *)utf8, sizeof(utf8), NULL, NULL) : 0;
        if (!bytes || count > 0) {
          /* desktop_edit validates UTF-8/NUL, revision and queue capacity. */
          accepted = desktop_edit(&h->desktop, &h->reconvert, h->reconvert_start,
              h->reconvert_end, utf8, (uint32_t)count) ? 1 : -1;
        }
      }
    }
    ImmReleaseContext(window, context);
  }
  if (!accepted) desktop_loss(&h->desktop, 1);
  h->reconvert_done = 1;
  h->desktop.pending.keys |= DYN_KEY_IME;
}
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
  case DYN_WAKE_MESSAGE:
    desktop_simple(&h->desktop, DYN_EVENT_WAKE);
    return 0;
  case WM_SETFOCUS:
    desktop_simple(&h->desktop, DYN_EVENT_FOCUS_GAINED);
    return 0;
  case WM_CLOSE:
    desktop_simple(&h->desktop, DYN_EVENT_CLOSE);
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
      desktop_resize(&h->desktop, h->frame.width, h->frame.height);
    }
    return 0;
  }
  case WM_MOUSEMOVE:
    h->frame.x = GET_X_LPARAM(l);
    h->frame.y = GET_Y_LPARAM(l);
    desktop_pointer(&h->desktop, DYN_EVENT_POINTER_MOVE, h->frame.x, h->frame.y,
                    0, modifiers());
    return 0;
  case WM_RBUTTONDOWN:
  case WM_RBUTTONUP:
  case WM_MBUTTONDOWN:
  case WM_MBUTTONUP:
  case WM_XBUTTONDOWN:
  case WM_XBUTTONUP: {
    uint32_t button =
        message == WM_RBUTTONDOWN || message == WM_RBUTTONUP ? 3 : 2;
    if (message == WM_XBUTTONDOWN || message == WM_XBUTTONUP)
      button = GET_XBUTTON_WPARAM(w) == XBUTTON1 ? 4 : 5;
    int down = message == WM_RBUTTONDOWN || message == WM_MBUTTONDOWN ||
               message == WM_XBUTTONDOWN;
    h->frame.x = GET_X_LPARAM(l);
    h->frame.y = GET_Y_LPARAM(l);
    desktop_pointer(&h->desktop,
                    down ? DYN_EVENT_POINTER_DOWN : DYN_EVENT_POINTER_UP,
                    h->frame.x, h->frame.y, button, modifiers());
    return message == WM_XBUTTONDOWN || message == WM_XBUTTONUP ? TRUE : 0;
  }
  case WM_LBUTTONDOWN:
    h->frame.x = GET_X_LPARAM(l);
    h->frame.y = GET_Y_LPARAM(l);
    h->frame.flags |= DYN_DOWN | DYN_PRESSED;
    desktop_pointer(&h->desktop, DYN_EVENT_POINTER_DOWN, h->frame.x, h->frame.y,
                    1, modifiers());
    SetCapture(window);
    return 0;
  case WM_LBUTTONUP:
    h->frame.x = GET_X_LPARAM(l);
    h->frame.y = GET_Y_LPARAM(l);
    h->frame.flags &= ~DYN_DOWN;
    h->frame.flags |= DYN_RELEASED;
    desktop_pointer(&h->desktop, DYN_EVENT_POINTER_UP, h->frame.x, h->frame.y,
                    1, modifiers());
    if (GetCapture() == window)
      ReleaseCapture();
    return 0;
  case WM_CAPTURECHANGED:
  case WM_KILLFOCUS:
    if (message == WM_KILLFOCUS) {
      h->desktop.pending.keys &= ~(uint32_t)(DYN_KEY_SHIFT | DYN_KEY_CONTROL);
      h->high_surrogate = 0;
      h->high_surrogate_repeats = 0;
      /* Keep a cancelled pending/active identity through END. A delayed
       * START/RESULT must remain a rejected correction, never an insertion. */
      h->reconvert.token = 0;
      h->desktop.surrounding.token = 0;
      desktop_simple(&h->desktop, DYN_EVENT_FOCUS_LOST);
    }
    if (h->frame.flags & DYN_DOWN)
      h->frame.flags |= DYN_RELEASED;
    h->frame.flags &= ~DYN_DOWN;
    return 0;
  case WM_KEYDOWN:
  case WM_SYSKEYDOWN: {
    if (h->desktop.event_enabled)
      repeated_key(&h->desktop, event_key(w, l), scan_code(l), modifiers(),
                   ((uintptr_t)l & ((uintptr_t)1 << 30)) != 0,
                   message_repeats(l));
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
    if (control_down())
      *keys |= DYN_KEY_CONTROL;
    else
      *keys &= ~(uint32_t)DYN_KEY_CONTROL;
    if (message == WM_SYSKEYDOWN)
      break;
    return 0;
  }
  case WM_KEYUP:
  case WM_SYSKEYUP:
    if (h->desktop.event_enabled)
      desktop_key(&h->desktop, 0, event_key(w, l), scan_code(l), modifiers(),
                  0);
    if (w == VK_SHIFT)
      h->desktop.pending.keys &= ~(uint32_t)DYN_KEY_SHIFT;
    if (!control_down())
      h->desktop.pending.keys &= ~(uint32_t)DYN_KEY_CONTROL;
    if (message == WM_SYSKEYUP)
      break;
    return 0;
  case WM_CHAR: {
    if (h->text_input_configured && !h->text_input) return 0;
    /* WM_CHAR carries UTF-16; the IME delivers composed text here too. */
    WCHAR unit = (WCHAR)w;
    uint32_t count = message_repeats(l);
    if (control_down() && unit < 32)
      return 0;
    if (unit >= 0xd800 && unit <= 0xdbff) {
      h->high_surrogate = unit;
      h->high_surrogate_repeats = count;
      return 0;
    }
    uint32_t codepoint = unit;
    if (unit >= 0xdc00 && unit <= 0xdfff) {
      if (!h->high_surrogate)
        return 0;
      /* Paired messages normally have equal repeat counts. On malformed
       * mismatched input only complete high/low pairs produce text. */
      if (count > h->high_surrogate_repeats)
        count = h->high_surrogate_repeats;
      codepoint = 0x10000 + (((uint32_t)h->high_surrogate - 0xd800) << 10) +
                  (unit - 0xdc00);
    }
    h->high_surrogate = 0;
    h->high_surrogate_repeats = 0;
    repeated_text(&h->desktop, codepoint, count);
    return 0;
  }
  case WM_MOUSEWHEEL:
    h->desktop.pending.scroll_y -=
        (float)GET_WHEEL_DELTA_WPARAM(w) / 120.0f * 48.0f;
    desktop_wheel(&h->desktop, 0.0f,
                  -(float)GET_WHEEL_DELTA_WPARAM(w) / 120.0f * 48.0f);
    return 0;
  case WM_MOUSEHWHEEL:
    h->desktop.pending.scroll_x +=
        (float)GET_WHEEL_DELTA_WPARAM(w) / 120.0f * 48.0f;
    desktop_wheel(&h->desktop,
                  (float)GET_WHEEL_DELTA_WPARAM(w) / 120.0f * 48.0f, 0.0f);
    return 0;
  case WM_IME_REQUEST:
    if (w == IMR_DOCUMENTFEED || w == IMR_RECONVERTSTRING)
      return reconvert_request(h, (UINT)w, (RECONVERTSTRING *)l);
    if (w == IMR_CONFIRMRECONVERTSTRING)
      return reconvert_confirm(h, (const RECONVERTSTRING *)l);
    break;
  case WM_IME_SETCONTEXT:
    if (h->text_input) l &= ~(LPARAM)ISC_SHOWUICOMPOSITIONWINDOW;
    break;
  case WM_IME_STARTCOMPOSITION: {
    if (!h->reconvert_active) {
      h->reconvert_active = h->reconvert_pending;
      h->reconvert_pending = 0;
      h->reconvert_done = 0;
    }
    if (h->text_input_configured && !h->text_input) break;
    HIMC context = ImmGetContext(window);
    if (context) {
      /* Place the composition and candidate windows at the caret. */
      COMPOSITIONFORM form = {.dwStyle = CFS_FORCE_POSITION, .ptCurrentPos = {h->caret.left, h->caret.top}};
      ImmSetCompositionWindow(context, &form);
      CANDIDATEFORM candidate = {.dwIndex = 0, .dwStyle = CFS_EXCLUDE,
                                 .ptCurrentPos = {h->caret.left, h->caret.bottom}, .rcArea = h->caret};
      ImmSetCandidateWindow(context, &candidate);
      ImmReleaseContext(window, context);
    }
    break;
  }
  case WM_IME_COMPOSITION: {
    if ((l & GCS_RESULTSTR) && h->reconvert_active &&
        h->text_input_configured && !h->text_input) {
      reconvert_result(h, window);
      return 0;
    }
    if (h->text_input_configured && !h->text_input) break;
    if (l & GCS_COMPSTR) {
      HIMC context = ImmGetContext(window);
      if (context) {
        WCHAR wide[256];
        LONG bytes = ImmGetCompositionStringW(context, GCS_COMPSTR, wide, sizeof(wide));
        LONG cursor = ImmGetCompositionStringW(context, GCS_CURSORPOS, NULL, 0);
        ImmReleaseContext(window, context);
        if (bytes < 0) bytes = 0;
        if (bytes > (LONG)sizeof(wide)) bytes = sizeof(wide);
        int units = (int)(bytes / (LONG)sizeof(WCHAR));
        /* Convert the complete bounded UTF-16 prefix before clipping UTF-8;
         * converting directly into 256 bytes rejects a valid longer preedit. */
        if (units && wide[units - 1] >= 0xd800 && wide[units - 1] <= 0xdbff) units--;
        char utf8[768];
        int length = units ? WideCharToMultiByte(CP_UTF8, 0, wide, units, utf8, sizeof(utf8), NULL, NULL) : 0;
        int cursor_units = cursor < 0 ? 0 : cursor > units ? units : (int)cursor;
        if (cursor_units && cursor_units < units && wide[cursor_units - 1] >= 0xd800 && wide[cursor_units - 1] <= 0xdbff &&
            wide[cursor_units] >= 0xdc00 && wide[cursor_units] <= 0xdfff) cursor_units--;
        int position = cursor < 0 ? -1 : cursor_units ? WideCharToMultiByte(CP_UTF8, 0, wide, cursor_units, NULL, 0, NULL, NULL) : 0;
        composition_store(&h->composition, (const uint8_t *)utf8, length > 0 ? (size_t)length : 0, position, position);
        composition_changed(&h->desktop, &h->composition);
      }
    }
    if ((l & GCS_RESULTSTR) && h->reconvert_active) {
      reconvert_result(h, window);
      /* We own this result. Default processing would insert it again through
       * the IME character path instead of replacing the source selection. */
      return 0;
    }
    /* Ordinary committed text (GCS_RESULTSTR) arrives through WM_CHAR. */
    break;
  }
  case WM_IME_ENDCOMPOSITION:
    h->reconvert_pending = h->reconvert_active = h->reconvert_done = 0;
    memset(&h->composition, 0, sizeof(h->composition));
    composition_changed(&h->desktop, &h->composition);
    break;
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
    LPCWSTR shapes[5] = {MAKEINTRESOURCEW(32512), MAKEINTRESOURCEW(32513),
                         MAKEINTRESOURCEW(32649), MAKEINTRESOURCEW(32644),
                         MAKEINTRESOURCEW(32645)};
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
    if (message.message == WM_QUIT) {
      h->frame.flags |= DYN_CLOSE;
      desktop_simple(&h->desktop, DYN_EVENT_CLOSE);
    } else {
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
  Dpi dpi = (Dpi)(void *)GetProcAddress(GetModuleHandleW(L"user32.dll"),
                                        "GetDpiForWindow");
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
  int units = MultiByteToWideChar(CP_UTF8, 0, (const char *)h->desktop.owned,
                                  (int)h->desktop.owned_length, NULL, 0);
  HGLOBAL memory =
      GlobalAlloc(GMEM_MOVEABLE, ((size_t)units + 1) * sizeof(WCHAR));
  if (!memory)
    return;
  WCHAR *wide = GlobalLock(memory);
  MultiByteToWideChar(CP_UTF8, 0, (const char *)h->desktop.owned,
                      (int)h->desktop.owned_length, wide, units);
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
    int bytes =
        WideCharToMultiByte(CP_UTF8, 0, wide, -1, (char *)h->desktop.received,
                            DYN_CLIPBOARD_LIMIT, NULL, NULL);
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
  Host *h = p;
  if (!h || h->desktop.event_count || h->desktop.event_dropped)
    return;
  MsgWaitForMultipleObjects(
      0, NULL, FALSE, timeout < 0 ? INFINITE : (DWORD)timeout, QS_ALLINPUT);
}

int32_t dyn_window_next_event(void *p, dyn_window_event *out) {
  Host *h = p;
  return h && out ? desktop_next(&h->desktop, out) : 0;
}
int32_t dyn_window_wake(void *p) {
  Host *h = p;
  return h && h->window && PostMessageW(h->window, DYN_WAKE_MESSAGE, 0, 0) != 0;
}

void dyn_window_listen_events(void *p, int32_t enabled) {
  Host *h = p;
  if (h) {
    if (h->desktop.event_enabled != (enabled != 0)) h->desktop.surrounding.token = 0;
    desktop_listen(&h->desktop, enabled);
  }
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
  h->caret = (RECT){x, y, x + width, y + height};
  if (!enabled && h->text_input) {
    /* ImmNotifyIME may synchronously send END, which releases the tombstone.
     * Without END, retain pending/active state to absorb delayed results. */
    h->reconvert.token = 0;
    h->desktop.surrounding.token = 0;
    HIMC context = ImmGetContext(h->window);
    if (context) {
      ImmNotifyIME(context, NI_COMPOSITIONSTR, CPS_CANCEL, 0);
      ImmReleaseContext(h->window, context);
    }
    memset(&h->composition, 0, sizeof(h->composition));
    composition_changed(&h->desktop, &h->composition);
  }
  if (!enabled) {
    h->high_surrogate = 0;
    h->high_surrogate_repeats = 0;
  }
  h->text_input = enabled != 0;
  h->text_input_configured = 1;
  ImmAssociateContextEx(h->window, NULL, enabled ? IACE_DEFAULT : 0);
  if (!enabled) {
    h->desktop.pending.keys = (h->desktop.pending.keys & ~(uint32_t)DYN_KEY_IME) | consumed_before;
    return;
  }
  HIMC context = ImmGetContext(h->window);
  if (!context)
    return;
  COMPOSITIONFORM form = {.dwStyle = CFS_FORCE_POSITION, .ptCurrentPos = {x, y}};
  ImmSetCompositionWindow(context, &form);
  CANDIDATEFORM candidate = {.dwIndex = 0, .dwStyle = CFS_EXCLUDE, .ptCurrentPos = {x, y + height}, .rcArea = h->caret};
  ImmSetCandidateWindow(context, &candidate);
  ImmReleaseContext(h->window, context);
}

uint32_t dyn_window_clipboard_get(void *p, const uint8_t **text) {
  Host *h = p;
  *text = h->desktop.received;
  return h->desktop.received_length;
}

int32_t dyn_window_set_surrounding_text(void *p, const uint8_t *text, uint32_t length,
                                        uint32_t cursor, uint32_t anchor, uint64_t token, uint32_t cause) {
  Host *h = p;
  if (!h || cause > 1) return 0;
  /* Retain a pending source across publication too: its later START/RESULT
   * must fail revision validation rather than become an ordinary insertion. */
  return desktop_surrounding(&h->desktop, text, length, cursor, anchor, token);
}
