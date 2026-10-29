#include "desktop_common.h"
#include "window.h"
#include "cocoa_key.h"
#import <Cocoa/Cocoa.h>
#import <OpenGL/OpenGL.h>
#include <dlfcn.h>
#include <stdlib.h>
typedef struct Host Host;
@interface DynWindowDelegate : NSObject <NSWindowDelegate>
@property(nonatomic, assign) Host *host;
@end
@interface DynTextView : NSOpenGLView <NSTextInputClient>
@property(nonatomic, assign) Host *host;
@end
struct Host {
  void *window, *view, *delegate;
  dyn_window_frame frame;
  Desktop desktop;
  int clipboard_status, clipboard_requested;
  dyn_window_composition composition;
  int text_input, text_input_configured;
  NSRange marked_range, selected_range;
  void *marked_text;
  Surrounding marked_context;
  uint32_t marked_start, marked_end;
  NSRect caret;
  int cursor;
  NSInteger window_number;
  uint8_t modifier_down[128];
};
static void clear_mark(Host *h) {
  h->marked_range = NSMakeRange(NSNotFound, 0);
  h->selected_range = NSMakeRange(NSNotFound, 0);
  if (h->marked_text) (void)(__bridge_transfer NSString *)h->marked_text;
  h->marked_text = NULL;
  h->marked_context.token = 0;
}
static int cocoa_context(Host *h) {
  return h && h->desktop.surrounding.token &&
      h->desktop.surrounding.token != h->desktop.consumed_token;
}
static NSString *context_string(const Surrounding *context) {
  return [[NSString alloc] initWithBytes:context->text length:context->length encoding:NSUTF8StringEncoding];
}
static int context_range(const Surrounding *context, NSRange range, uint32_t *start, uint32_t *end) {
  if (range.location == NSNotFound || range.location > UINT32_MAX ||
      range.length > UINT32_MAX - range.location) return 0;
  return surrounding_byte(context->text, context->length, (uint32_t)range.location, start) &&
      surrounding_byte(context->text, context->length, (uint32_t)(range.location + range.length), end);
}
static NSString *client_string(Host *h) {
  if (!cocoa_context(h)) return nil;
  NSString *base = context_string(&h->desktop.surrounding);
  if (h->marked_text && h->marked_context.token == h->desktop.surrounding.token) {
    uint32_t low = surrounding_utf16(h->marked_context.text, h->marked_start);
    uint32_t high = surrounding_utf16(h->marked_context.text, h->marked_end);
    NSMutableString *value = [base mutableCopy];
    [value replaceCharactersInRange:NSMakeRange(low, high-low) withString:(__bridge NSString *)h->marked_text];
    return value;
  }
  return base;
}
@implementation DynWindowDelegate
- (BOOL)windowShouldClose:(NSWindow *)sender {
  (void)sender;
  self.host->frame.flags |= DYN_CLOSE;
  desktop_simple(&self.host->desktop, DYN_EVENT_CLOSE);
  return NO;
}
- (void)windowDidBecomeKey:(NSNotification *)notification {
  (void)notification;
  desktop_simple(&self.host->desktop, DYN_EVENT_FOCUS_GAINED);
}
- (void)windowDidResignKey:(NSNotification *)notification {
  (void)notification;
  if (self.host->frame.flags & DYN_DOWN)
    self.host->frame.flags |= DYN_RELEASED;
  self.host->frame.flags &= ~DYN_DOWN;
  self.host->desktop.pending.keys &=
      ~(uint32_t)(DYN_KEY_SHIFT | DYN_KEY_CONTROL);
  memset(self.host->modifier_down, 0, sizeof(self.host->modifier_down));
  if (self.host->desktop.surrounding.token) self.host->desktop.consumed_token = self.host->desktop.surrounding.token;
  DynTextView *text_view = (__bridge DynTextView *)self.host->view;
  [[text_view inputContext] discardMarkedText];
  if (self.host->composition.active) [text_view unmarkText];
  desktop_simple(&self.host->desktop, DYN_EVENT_FOCUS_LOST);
}
@end
static NSWindow *window(Host *h) { return (__bridge NSWindow *)h->window; }
static NSOpenGLView *view(Host *h) { return (__bridge NSOpenGLView *)h->view; }
static NSString *plain(id string) {
  return [string isKindOfClass:[NSAttributedString class]] ? [(NSAttributedString *)string string] : (NSString *)string;
}
/* The input method talks to the view through NSTextInputClient: committed
 * text arrives in insertText, preedit in setMarkedText, and the candidate
 * window asks firstRectForCharacterRange where the caret is. */
@implementation DynTextView
- (BOOL)acceptsFirstResponder {
  return YES;
}
- (void)insertText:(id)string replacementRange:(NSRange)range {
  Host *h = self.host;
  if (!h || (h->text_input_configured && !h->text_input)) return;
  NSString *value = plain(string);
  const char *text = [value UTF8String];
  size_t length = [value lengthOfBytesUsingEncoding:NSUTF8StringEncoding];
  if (!text || length > UINT32_MAX || !surrounding_utf8((const uint8_t *)text, (uint32_t)length)) {
    desktop_loss(&h->desktop, 1); return;
  }
  int correcting = (h->marked_text && h->marked_context.token) || range.location != NSNotFound ||
      (cocoa_context(h) && h->desktop.surrounding.cursor != h->desktop.surrounding.anchor);
  if (correcting && length > DYN_SURROUND_LIMIT) { desktop_loss(&h->desktop, 1); return; }
  if (h->marked_text && h->marked_context.token) {
    /* A marked string stands in for its original document range. Partial
     * replacement inside it is not silently mapped onto unrelated bytes. */
    if (range.location != NSNotFound && !NSEqualRanges(range, h->marked_range))
      desktop_loss(&h->desktop, 1);
    else desktop_edit(&h->desktop, &h->marked_context, h->marked_start, h->marked_end,
                                  (const uint8_t *)text, (uint32_t)length);
  } else if (range.location != NSNotFound) {
    uint32_t start, end;
    if (cocoa_context(h) && context_range(&h->desktop.surrounding, range, &start, &end) && length <= DYN_SURROUND_LIMIT)
      desktop_edit(&h->desktop, &h->desktop.surrounding, start, end, (const uint8_t *)text, (uint32_t)length);
    else desktop_loss(&h->desktop, 1);
  } else if (cocoa_context(h) && h->desktop.surrounding.cursor != h->desktop.surrounding.anchor) {
    const Surrounding *context = &h->desktop.surrounding;
    uint32_t start = context->cursor < context->anchor ? context->cursor : context->anchor;
    uint32_t end = context->cursor > context->anchor ? context->cursor : context->anchor;
    desktop_edit(&h->desktop, context, start, end, (const uint8_t *)text, (uint32_t)length);
  } else if (text) desktop_text(&h->desktop, (const uint8_t *)text, length);
  clear_mark(h);
  memset(&h->composition, 0, sizeof(h->composition));
  composition_changed(&h->desktop, &h->composition);
}
- (void)setMarkedText:(id)string selectedRange:(NSRange)selected replacementRange:(NSRange)range {
  Host *h = self.host;
  if (!h || (h->text_input_configured && !h->text_input)) return;
  NSString *value = plain(string);
  const char *text = [value UTF8String];
  size_t length = [value lengthOfBytesUsingEncoding:NSUTF8StringEncoding];
  if (!text || length > DYN_SURROUND_LIMIT || !surrounding_utf8((const uint8_t *)text, (uint32_t)length)) {
    desktop_loss(&h->desktop, 1); return;
  }
  Surrounding context = h->marked_context;
  uint32_t start = h->marked_start, end = h->marked_end;
  if (h->marked_text && h->marked_context.token) {
    if (range.location != NSNotFound && !NSEqualRanges(range, h->marked_range)) {
      desktop_loss(&h->desktop, 1); return;
    }
  } else if (cocoa_context(h)) {
    context = h->desktop.surrounding;
    if (range.location != NSNotFound) {
      if (!context_range(&context, range, &start, &end)) { desktop_loss(&h->desktop, 1); return; }
    } else {
      start = context.cursor < context.anchor ? context.cursor : context.anchor;
      end = context.cursor > context.anchor ? context.cursor : context.anchor;
    }
  } else { memset(&context, 0, sizeof(context)); start = end = 0; }
  clear_mark(h);
  h->marked_context = context; h->marked_start = start; h->marked_end = end;
  h->marked_text = (__bridge_retained void *)[value copy];
  NSUInteger begin = selected.location == NSNotFound ? [value length] : MIN(selected.location, [value length]);
  NSUInteger selected_length = MIN(selected.length, [value length] - begin);
  NSUInteger finish = begin + selected_length;
  NSUInteger offset = context.token ? surrounding_utf16(context.text, start) : 0;
  h->marked_range = NSMakeRange(offset, [value length]);
  h->selected_range = NSMakeRange(offset + begin, selected_length);
  const char *prefix = [[value substringToIndex:begin] UTF8String];
  const char *through_selection = [[value substringToIndex:finish] UTF8String];
  composition_store(&h->composition, (const uint8_t *)(text ? text : ""), length,
                    prefix ? (int32_t)strlen(prefix) : -1, through_selection ? (int32_t)strlen(through_selection) : -1);
  composition_changed(&h->desktop, &h->composition);
}
- (void)unmarkText {
  if (self.host) {
    clear_mark(self.host);
    memset(&self.host->composition, 0, sizeof(self.host->composition));
    composition_changed(&self.host->desktop, &self.host->composition);
  }
}
- (BOOL)hasMarkedText {
  return self.host && self.host->composition.active;
}
- (NSRange)markedRange {
  if (![self hasMarkedText])
    return NSMakeRange(NSNotFound, 0);
  return self.host->marked_range;
}
- (NSRange)selectedRange {
  if ([self hasMarkedText]) return self.host->selected_range;
  if (!cocoa_context(self.host)) return NSMakeRange(NSNotFound, 0);
  const Surrounding *context = &self.host->desktop.surrounding;
  uint32_t begin = surrounding_utf16(context->text, context->cursor);
  uint32_t end = surrounding_utf16(context->text, context->anchor);
  return NSMakeRange(MIN(begin,end), begin > end ? begin-end : end-begin);
}
- (NSAttributedString *)attributedSubstringForProposedRange:(NSRange)range actualRange:(NSRangePointer)actual {
  if (actual) *actual = NSMakeRange(NSNotFound, 0);
  NSString *value = client_string(self.host);
  if (!value || range.location == NSNotFound || range.location > [value length]) return nil;
  NSRange bounded = NSMakeRange(range.location, MIN(range.length, [value length] - range.location));
  if (bounded.length) bounded = [value rangeOfComposedCharacterSequencesForRange:bounded];
  if (actual) *actual = bounded;
  return [[NSAttributedString alloc] initWithString:[value substringWithRange:bounded]];
}
- (NSArray<NSAttributedStringKey> *)validAttributesForMarkedText {
  return @[];
}
- (NSRect)firstRectForCharacterRange:(NSRange)range actualRange:(NSRangePointer)actual {
  if (actual) *actual = range;
  if (!self.host)
    return NSZeroRect;
  /* The caret is in backing pixels from the top; convert to screen points. */
  NSRect backing = self.host->caret;
  NSRect local = [self convertRectFromBacking:backing];
  local.origin.y = [self bounds].size.height - local.origin.y - local.size.height;
  return [[self window] convertRectToScreen:[self convertRect:local toView:nil]];
}
- (NSUInteger)characterIndexForPoint:(NSPoint)point {
  (void)point;
  return NSNotFound;
}
- (void)doCommandBySelector:(SEL)selector {
  /* Editing keys are read from key events; nothing to do here. */
  (void)selector;
}
@end
enum { DYN_WAKE_SUBTYPE = 0x4459 };
static uint32_t event_modifiers(NSEventModifierFlags flags) {
  uint32_t value = 0;
  if (flags & NSEventModifierFlagShift)
    value |= DYN_MOD_SHIFT;
  if (flags & NSEventModifierFlagControl)
    value |= DYN_MOD_CONTROL;
  if (flags & NSEventModifierFlagOption)
    value |= DYN_MOD_ALT;
  if (flags & NSEventModifierFlagCommand)
    value |= DYN_MOD_SUPER;
  if (flags & NSEventModifierFlagCapsLock)
    value |= DYN_MOD_CAPS;
  return value;
}
/* Capture from the source event before queued consumers observe later input.
 * Ctrl/Command are shortcut modifiers; retain layout, Shift, Option and Caps
 * while avoiding their control-character transformation. Dead keys stay empty.
 */
static uint32_t event_character(NSEvent *event) {
  NSEventModifierFlags flags = [event modifierFlags];
  NSString *chars = [event characters];
  if (flags & (NSEventModifierFlagControl | NSEventModifierFlagCommand))
    chars = [event charactersByApplyingModifiers:
        flags & ~(NSEventModifierFlagControl | NSEventModifierFlagCommand)];
  NSUInteger count = [chars length];
  if (count < 1 || count > 2) return 0;
  unichar units[2] = {0};
  [chars getCharacters:units range:NSMakeRange(0,count)];
  return cocoa_key_scalar(units,count);
}
static uint32_t event_key(NSEvent *event) {
  NSString *chars = [event charactersByApplyingModifiers:0];
  if (![chars length])
    return 0;
  uint32_t key = [chars characterAtIndex:0];
  if (key >= 0xd800 && key <= 0xdbff && [chars length] > 1) {
    uint32_t low = [chars characterAtIndex:1];
    if (low >= 0xdc00 && low <= 0xdfff)
      return 0x10000 + ((key - 0xd800) << 10) + low - 0xdc00;
  }
  if (key >= NSF1FunctionKey && key <= NSF24FunctionKey)
    return DYN_F1 + key - NSF1FunctionKey;
  switch (key) {
  case 27:
    return DYN_ESCAPE;
  case 13:
  case 3:
    return DYN_ENTER;
  case 9:
  case 25:
    return DYN_TAB_KEY;
  case 127:
    return DYN_BACKSPACE;
  case NSDeleteFunctionKey:
    return DYN_DELETE;
  case NSLeftArrowFunctionKey:
    return DYN_LEFT_KEY;
  case NSRightArrowFunctionKey:
    return DYN_RIGHT_KEY;
  case NSUpArrowFunctionKey:
    return DYN_UP_KEY;
  case NSDownArrowFunctionKey:
    return DYN_DOWN_KEY;
  case NSHomeFunctionKey:
    return DYN_HOME;
  case NSEndFunctionKey:
    return DYN_END;
  case NSPageUpFunctionKey:
    return DYN_PAGE_UP;
  case NSPageDownFunctionKey:
    return DYN_PAGE_DOWN;
  case NSInsertFunctionKey:
    return DYN_INSERT;
  default:
    break;
  }
  if (key >= 0xd800 && key <= 0xdfff)
    return 0;
  if (key >= 'A' && key <= 'Z')
    key += 'a' - 'A';
  return key;
}
static void modifier_event(Host *h, NSEvent *event) {
  unsigned short scan = [event keyCode];
  uint32_t key = 0;
  switch (scan) {
  case 56:
  case 60:
    key = DYN_SHIFT_KEY;
    break;
  case 59:
  case 62:
    key = DYN_CONTROL_KEY;
    break;
  case 58:
  case 61:
    key = DYN_ALT_KEY;
    break;
  case 55:
  case 54:
    key = DYN_SUPER_KEY;
    break;
  default:
    return;
  }
  uint32_t group = key == DYN_SHIFT_KEY     ? DYN_MOD_SHIFT
                   : key == DYN_CONTROL_KEY ? DYN_MOD_CONTROL
                   : key == DYN_ALT_KEY     ? DYN_MOD_ALT
                                            : DYN_MOD_SUPER;
  h->modifier_down[scan] = (event_modifiers([event modifierFlags]) & group) &&
                           !h->modifier_down[scan];
  desktop_key(&h->desktop, h->modifier_down[scan], key, scan,
              event_modifiers([event modifierFlags]), 0);
}
static void dimensions(Host *h) {
  NSRect r = [view(h) convertRectToBacking:[view(h) bounds]];
  int32_t width = (int32_t)r.size.width, height = (int32_t)r.size.height;
  if (h->frame.width != width || h->frame.height != height)
    desktop_resize(&h->desktop, width, height);
  h->frame.width = width;
  h->frame.height = height;
  [[view(h) openGLContext] update];
}
void dyn_window_close(void *p) {
  Host *h = p;
  if (!h)
    return;
  @autoreleasepool {
    clear_mark(h);
    if (h->view) {
      NSOpenGLContext *context = [view(h) openGLContext];
      if ([NSOpenGLContext currentContext] == context)
        [NSOpenGLContext clearCurrentContext];
      [context clearDrawable];
    }
    if (h->window) {
      [window(h) setDelegate:nil];
      [window(h) orderOut:nil];
      [window(h) close];
    }
    if (h->delegate) {
      DynWindowDelegate *delegate =
          (__bridge_transfer DynWindowDelegate *)h->delegate;
      delegate.host = NULL;
    }
    if (h->view)
      ((__bridge DynTextView *)h->view).host = NULL;
    (void)(__bridge_transfer NSOpenGLView *)h->view;
    (void)(__bridge_transfer NSWindow *)h->window;
  }
  free(h);
}
void *dyn_window_open(const char *title, int32_t width, int32_t height) {
  if (![NSThread isMainThread])
    return NULL;
  Host *h = calloc(1, sizeof(*h));
  if (!h)
    return NULL;
  @autoreleasepool {
    static int application_ready = 0;
    if (!application_ready) {
      [NSApplication sharedApplication];
      [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];
      [NSApp finishLaunching];
      application_ready = 1;
    }
    NSOpenGLPixelFormatAttribute attrs[] = {
        NSOpenGLPFAOpenGLProfile, NSOpenGLProfileVersion4_1Core,
        NSOpenGLPFAColorSize,     24,
        NSOpenGLPFAAlphaSize,     8,
        NSOpenGLPFADoubleBuffer,  0};
    NSOpenGLPixelFormat *format =
        [[NSOpenGLPixelFormat alloc] initWithAttributes:attrs];
    if (!format) {
      dyn_window_close(h);
      return NULL;
    }
    NSRect rect = NSMakeRect(0, 0, width, height);
    NSWindow *w =
        [[NSWindow alloc] initWithContentRect:rect
                                    styleMask:NSWindowStyleMaskTitled |
                                              NSWindowStyleMaskClosable |
                                              NSWindowStyleMaskResizable
                                      backing:NSBackingStoreBuffered
                                        defer:NO];
    DynTextView *v = [[DynTextView alloc] initWithFrame:rect
                                              pixelFormat:format];
    if (!w || !v || ![v openGLContext]) {
      dyn_window_close(h);
      return NULL;
    }
    [w setReleasedWhenClosed:NO];
    [w setAcceptsMouseMovedEvents:YES];
    [v setWantsBestResolutionOpenGLSurface:YES];
    [w setContentView:v];
    [w setTitle:[NSString stringWithUTF8String:title] ?: @"Dyn"];
    DynWindowDelegate *d = [DynWindowDelegate new];
    d.host = h;
    v.host = h;
    [w setDelegate:d];
    h->window_number = [w windowNumber];
    h->window = (__bridge_retained void *)w;
    h->view = (__bridge_retained void *)v;
    h->delegate = (__bridge_retained void *)d;
    [w center];
    [w makeKeyAndOrderFront:nil];
    [NSApp activateIgnoringOtherApps:YES];
    dimensions(h);
    [[v openGLContext] makeCurrentContext];
    return h;
  }
}
int32_t dyn_window_poll(void *p, dyn_window_frame *out) {
  if (![NSThread isMainThread])
    return 0;
  Host *h = p;
  @autoreleasepool {
    for (;;) {
      NSEvent *event = [NSApp nextEventMatchingMask:NSEventMaskAny
                                          untilDate:[NSDate distantPast]
                                             inMode:NSDefaultRunLoopMode
                                            dequeue:YES];
      if (!event)
        break;
      id delegate = [[event window] delegate];
      Host *target = [delegate isKindOfClass:[DynWindowDelegate class]]
                         ? [(DynWindowDelegate *)delegate host]
                         : NULL;
      if (target) {
        dimensions(target);
        NSEventType type = [event type];
        if (type == NSEventTypeApplicationDefined &&
            [event subtype] == DYN_WAKE_SUBTYPE) {
          desktop_simple(&target->desktop, DYN_EVENT_WAKE);
          continue;
        }
        if (type == NSEventTypeLeftMouseDown ||
            type == NSEventTypeLeftMouseUp || type == NSEventTypeMouseMoved ||
            type == NSEventTypeLeftMouseDragged ||
            type == NSEventTypeRightMouseDown ||
            type == NSEventTypeRightMouseUp ||
            type == NSEventTypeRightMouseDragged ||
            type == NSEventTypeOtherMouseDown ||
            type == NSEventTypeOtherMouseUp ||
            type == NSEventTypeOtherMouseDragged) {
          NSPoint point = [view(target) convertPoint:[event locationInWindow]
                                            fromView:nil];
          NSPoint backing = [view(target) convertPointToBacking:point];
          target->frame.x = (int32_t)backing.x;
          target->frame.y = target->frame.height - 1 - (int32_t)backing.y;
          uint32_t kind = DYN_EVENT_POINTER_MOVE;
          if (type == NSEventTypeLeftMouseDown ||
              type == NSEventTypeRightMouseDown ||
              type == NSEventTypeOtherMouseDown)
            kind = DYN_EVENT_POINTER_DOWN;
          else if (type == NSEventTypeLeftMouseUp ||
                   type == NSEventTypeRightMouseUp ||
                   type == NSEventTypeOtherMouseUp)
            kind = DYN_EVENT_POINTER_UP;
          uint32_t button = 0;
          if (kind != DYN_EVENT_POINTER_MOVE) {
            NSInteger number = [event buttonNumber];
            button = number == 0   ? 1
                     : number == 1 ? 3
                     : number == 2 ? 2
                                   : (uint32_t)number + 1;
          }
          desktop_pointer(&target->desktop, kind, target->frame.x,
                          target->frame.y, button,
                          event_modifiers([event modifierFlags]));
          if (type == NSEventTypeLeftMouseDown)
            target->frame.flags |= DYN_DOWN | DYN_PRESSED;
          else if (type == NSEventTypeLeftMouseUp) {
            target->frame.flags &= ~DYN_DOWN;
            target->frame.flags |= DYN_RELEASED;
          }
        }
        if (type == NSEventTypeScrollWheel) {
          CGFloat factor = [event hasPreciseScrollingDeltas] ? 1.0 : 48.0;
          CGFloat scale = [window(target) backingScaleFactor];
          target->desktop.pending.scroll_x -=
              (float)([event scrollingDeltaX] * factor * scale);
          target->desktop.pending.scroll_y -=
              (float)([event scrollingDeltaY] * factor * scale);
          desktop_wheel(&target->desktop,
                        -(float)([event scrollingDeltaX] * factor * scale),
                        -(float)([event scrollingDeltaY] * factor * scale));
        }
        if (type == NSEventTypeFlagsChanged)
          modifier_event(target, event);
        if (type == NSEventTypeKeyDown || type == NSEventTypeKeyUp)
          desktop_key_character(&target->desktop, type == NSEventTypeKeyDown,
                      event_key(event), [event keyCode],
                      event_modifiers([event modifierFlags]),
                      type == NSEventTypeKeyDown && [event isARepeat],
                      event_character(event));
        if (type == NSEventTypeFlagsChanged || type == NSEventTypeKeyDown) {
          if ([event modifierFlags] & NSEventModifierFlagShift)
            target->desktop.pending.keys |= DYN_KEY_SHIFT;
          else
            target->desktop.pending.keys &= ~(uint32_t)DYN_KEY_SHIFT;
          /* Option is the platform word-motion modifier. */
          if ([event modifierFlags] & NSEventModifierFlagOption)
            target->desktop.pending.keys |= DYN_KEY_CONTROL;
          else
            target->desktop.pending.keys &= ~(uint32_t)DYN_KEY_CONTROL;
        }
        if (type == NSEventTypeKeyDown) {
          NSString *chars = [event charactersIgnoringModifiers];
          uint32_t *keys = &target->desktop.pending.keys;
          int command =
              ([event modifierFlags] & NSEventModifierFlagCommand) != 0;
          if ([chars length]) {
            unichar key = [chars characterAtIndex:0];
            if (key == 9) {
              target->frame.flags |= DYN_TAB;
              *keys |= DYN_KEY_TAB;
            } else if (key == 13 || key == 3 || key == 32) {
              target->frame.flags |= DYN_ACTIVATE;
              if (key != 32)
                *keys |= DYN_KEY_ENTER;
            } else if (key == NSLeftArrowFunctionKey) {
              target->frame.flags |= DYN_LEFT;
              *keys |= DYN_KEY_LEFT;
            } else if (key == NSRightArrowFunctionKey) {
              target->frame.flags |= DYN_RIGHT;
              *keys |= DYN_KEY_RIGHT;
            } else if (key == 127)
              *keys |= DYN_KEY_BACKSPACE;
            else if (key == NSDeleteFunctionKey)
              *keys |= DYN_KEY_DELETE;
            else if (key == NSHomeFunctionKey)
              *keys |= DYN_KEY_HOME;
            else if (key == NSEndFunctionKey)
              *keys |= DYN_KEY_END;
            else if (key == 27)
              *keys |= DYN_KEY_ESCAPE;
            else if (command && (key == 'a' || key == 'A'))
              *keys |= DYN_KEY_SELECT_ALL;
            else if (command && (key == 'c' || key == 'C'))
              *keys |= DYN_KEY_COPY;
            else if (command && (key == 'x' || key == 'X'))
              *keys |= DYN_KEY_CUT;
            else if (command && (key == 'v' || key == 'V'))
              dyn_window_request_paste(target);
          }
          if (!command && target->text_input) {
            /* The input method composes and commits through DynTextView. */
            [view(target) interpretKeyEvents:@[ event ]];
          } else if (!command && !target->text_input_configured && [chars length]) {
            unichar key = [chars characterAtIndex:0];
            if (key < 0xf700 || key > 0xf8ff) {
              const char *text = [[event characters] UTF8String];
              if (text)
                desktop_text(&target->desktop, (const uint8_t *)text,
                             strlen(text));
            }
          }
          /* The application handles keys; do not beep for unhandled ones. */
          if (!command)
            continue;
        }
      }
      [NSApp sendEvent:event];
    }
    [NSApp updateWindows];
    dimensions(h);
    *out = h->frame;
    h->frame.flags &= DYN_DOWN | DYN_CLOSE;
    return 1;
  }
}
int32_t dyn_window_set_title(void *p, const uint8_t *text, uint32_t length) {
  if (!p || ![NSThread isMainThread] || (length && !text)) return 0;
  if (length > 4096) return -2;
  if (!surrounding_utf8(text,length)) return 0;
  NSString *title = [[NSString alloc] initWithBytes:text length:length encoding:NSUTF8StringEncoding];
  if (!title) return 0;
  [window((Host *)p) setTitle:title];
  return 1;
}
int32_t dyn_window_set_size(void *p, int32_t width, int32_t height) {
  if (!p || ![NSThread isMainThread] || width <= 0 || height <= 0) return 0;
  Host *h = p;
  if (([window(h) styleMask] & NSWindowStyleMaskFullScreen) || [window(h) isZoomed]) return -1;
  CGFloat scale = [window(h) backingScaleFactor];
  if (scale <= 0) return 0;
  [window(h) setContentSize:NSMakeSize(width/scale,height/scale)];
  dimensions(h);
  return 1;
}
int32_t dyn_window_set_swap_interval(void *p, int32_t interval) {
  if (!p || ![NSThread isMainThread] || interval < 0) return 0;
  NSOpenGLContext *context = [view((Host *)p) openGLContext];
  if ([NSOpenGLContext currentContext] != context) return 0;
  GLint value = interval;
  [context setValues:&value forParameter:NSOpenGLCPSwapInterval];
  [context getValues:&value forParameter:NSOpenGLCPSwapInterval];
  return value == interval;
}
int32_t dyn_window_current(void *p) {
  if (![NSThread isMainThread])
    return 0;
  Host *h = p;
  dimensions(h);
  [[view(h) openGLContext] makeCurrentContext];
  return [NSOpenGLContext currentContext] == [view(h) openGLContext];
}
int32_t dyn_window_swap(void *p) {
  if (![NSThread isMainThread])
    return 0;
  Host *h = p;
  [[view(h) openGLContext] flushBuffer];
  return 1;
}
void *dyn_window_proc(const char *name) { return dlsym(RTLD_DEFAULT, name); }

void dyn_window_desktop_take(void *p, dyn_window_desktop *out) {
  Host *h = p;
  float scale = h->window ? (float)[window(h) backingScaleFactor] : 1.0f;
  desktop_take(&h->desktop, out, scale);
}
int32_t dyn_window_try_set_clipboard(void *p, const uint8_t *text, uint32_t length) {
  Host *h = p;
  if (!h || ![NSThread isMainThread]) return -4;
  if (length > DYN_CLIPBOARD_LIMIT) return -2;
  if (!surrounding_utf8(text, length)) return -3;
  @autoreleasepool {
    NSString *value = [[NSString alloc] initWithBytes:length ? text : (const uint8_t *)""
        length:length encoding:NSUTF8StringEncoding];
    if (!value) return -3;
    NSPasteboard *board = [NSPasteboard generalPasteboard];
    if (!board) return 0;
    [board clearContents];
    if (![board setString:value forType:NSPasteboardTypeString]) return 0;
    if (length) memcpy(h->desktop.owned, text, length);
    h->desktop.owned_length = length;
    return 1;
  }
}
void dyn_window_set_clipboard(void *p, const uint8_t *text, uint32_t length) {
  (void)dyn_window_try_set_clipboard(p, text, length);
}
static void clipboard_request(Host *h, int emit) {
  if (!h) return;
  h->clipboard_requested = 1;
  h->clipboard_status = -4;
  if (![NSThread isMainThread]) return;
  h->clipboard_status = 0;
  @autoreleasepool {
    NSString *value = [[NSPasteboard generalPasteboard] stringForType:NSPasteboardTypeString];
    if (!value) return;
    NSData *data = [value dataUsingEncoding:NSUTF8StringEncoding allowLossyConversion:NO];
    if (!data) { h->clipboard_status = -3; return; }
    NSUInteger length = [data length];
    if (length > DYN_CLIPBOARD_LIMIT) { h->clipboard_status = -2; return; }
    const uint8_t *text = [data bytes];
    if (!surrounding_utf8(text, (uint32_t)length)) { h->clipboard_status = -3; return; }
    if (length) memcpy(h->desktop.received, text, length);
    h->desktop.received_length = (uint32_t)length;
    h->clipboard_status = 1;
    desktop_deliver_mode(&h->desktop, emit);
  }
}
void dyn_window_request_paste(void *p) { clipboard_request(p, 1); }
void dyn_window_request_paste_snapshot(void *p) { clipboard_request(p, 0); }
int32_t dyn_window_paste_pending(void *p) { (void)p; return 0; }
int32_t dyn_window_paste_status(void *p) {
  Host *h = p;
  return h && h->clipboard_requested ? h->clipboard_status : -4;
}
void dyn_window_set_cursor(void *p, int32_t cursor) {
  Host *h = p;
  if (cursor < 0 || cursor > 4)
    return;
  h->cursor = cursor;
  NSCursor *shapes[5] = {[NSCursor arrowCursor],
                         [NSCursor IBeamCursor],
                         [NSCursor pointingHandCursor],
                         [NSCursor resizeLeftRightCursor],
                         [NSCursor resizeUpDownCursor]};
  [shapes[cursor] set];
}
void dyn_window_wait(void *p, int32_t timeout) {
  Host *h = p;
  if (!h || ![NSThread isMainThread] || h->desktop.event_count ||
      h->desktop.event_dropped)
    return;
  @autoreleasepool {
    NSDate *until =
        timeout < 0 ? [NSDate distantFuture]
                    : [NSDate dateWithTimeIntervalSinceNow:timeout / 1000.0];
    (void)[NSApp nextEventMatchingMask:NSEventMaskAny
                             untilDate:until
                                inMode:NSDefaultRunLoopMode
                               dequeue:NO];
  }
}

int32_t dyn_window_next_event(void *p, dyn_window_event *out) {
  Host *h = p;
  if (!h || !out || ![NSThread isMainThread])
    return 0;
  return desktop_next(&h->desktop, out);
}
int32_t dyn_window_wake(void *p) {
  Host *h = p;
  if (!h || !NSApp)
    return 0;
  @autoreleasepool {
    NSEvent *event = [NSEvent otherEventWithType:NSEventTypeApplicationDefined
                                        location:NSZeroPoint
                                   modifierFlags:0
                                       timestamp:0
                                    windowNumber:h->window_number
                                         context:nil
                                         subtype:DYN_WAKE_SUBTYPE
                                           data1:0
                                           data2:0];
    if (!event)
      return 0;
    /* NSApplication postEvent is thread-safe. No NSWindow method runs here. */
    [NSApp postEvent:event atStart:NO];
  }
  return 1;
}

void dyn_window_listen_events(void *p, int32_t enabled) {
  Host *h = p;
  if (h && [NSThread isMainThread])
    desktop_listen(&h->desktop, enabled);
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
  h->caret = NSMakeRect(x, y, width, height);
  if (!enabled && (h->text_input || h->composition.active)) {
    [[view(h) inputContext] discardMarkedText];
    memset(&h->composition, 0, sizeof(h->composition));
    composition_changed(&h->desktop, &h->composition);
  }
  if (!enabled) {
    if (h->text_input && h->desktop.surrounding.token)
      h->desktop.consumed_token = h->desktop.surrounding.token;
    clear_mark(h);
  }
  h->text_input = enabled != 0;
  h->text_input_configured = 1;
  if (enabled) {
    [window(h) makeFirstResponder:view(h)];
    [[view(h) inputContext] invalidateCharacterCoordinates];
  }
  if (!enabled)
    h->desktop.pending.keys = (h->desktop.pending.keys & ~(uint32_t)DYN_KEY_IME) | consumed_before;
}

uint32_t dyn_window_clipboard_get(void *p, const uint8_t **text) {
  Host *h = p;
  *text = h->desktop.received;
  return h->desktop.received_length;
}

int32_t dyn_window_set_surrounding_text(void *p, const uint8_t *text, uint32_t length,
                                        uint32_t cursor, uint32_t anchor, uint64_t token, uint32_t cause) {
  Host *h = p;
  if (!h || ![NSThread isMainThread] || cause > 1) return 0;
  uint64_t previous = h->desktop.surrounding.token;
  int32_t result = desktop_surrounding(&h->desktop, text, length, cursor, anchor, token);
  if (result == 1 && previous != token && h->marked_text && h->marked_context.token != token) {
    uint32_t consumed = h->desktop.pending.keys & DYN_KEY_IME;
    [[view(h) inputContext] discardMarkedText];
    clear_mark(h);
    memset(&h->composition, 0, sizeof(h->composition));
    composition_changed(&h->desktop, &h->composition);
    h->desktop.pending.keys = (h->desktop.pending.keys & ~(uint32_t)DYN_KEY_IME) | consumed;
  }
  return result;
}
