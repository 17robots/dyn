#include "window.h"
#import <Cocoa/Cocoa.h>
#import <OpenGL/OpenGL.h>
#include <dlfcn.h>
#include <stdlib.h>
typedef struct Host Host;
@interface DynWindowDelegate : NSObject <NSWindowDelegate>
@property(nonatomic, assign) Host *host;
@end
struct Host {
  void *window, *view, *delegate;
  dyn_window_frame frame;
};
@implementation DynWindowDelegate
- (BOOL)windowShouldClose:(NSWindow *)sender {
  (void)sender;
  self.host->frame.flags |= DYN_CLOSE;
  return NO;
}
- (void)windowDidResignKey:(NSNotification *)notification {
  (void)notification;
  if (self.host->frame.flags & DYN_DOWN)
    self.host->frame.flags |= DYN_RELEASED;
  self.host->frame.flags &= ~DYN_DOWN;
}
@end
static NSWindow *window(Host *h) { return (__bridge NSWindow *)h->window; }
static NSOpenGLView *view(Host *h) { return (__bridge NSOpenGLView *)h->view; }
static void dimensions(Host *h) {
  NSRect r = [view(h) convertRectToBacking:[view(h) bounds]];
  h->frame.width = (int32_t)r.size.width;
  h->frame.height = (int32_t)r.size.height;
  [[view(h) openGLContext] update];
}
void dyn_window_close(void *p) {
  Host *h = p;
  if (!h)
    return;
  @autoreleasepool {
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
    NSOpenGLView *v = [[NSOpenGLView alloc] initWithFrame:rect
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
    [w setDelegate:d];
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
        if (type == NSEventTypeLeftMouseDown ||
            type == NSEventTypeLeftMouseUp || type == NSEventTypeMouseMoved ||
            type == NSEventTypeLeftMouseDragged) {
          NSPoint point = [view(target) convertPoint:[event locationInWindow]
                                            fromView:nil];
          NSPoint backing = [view(target) convertPointToBacking:point];
          target->frame.x = (int32_t)backing.x;
          target->frame.y = target->frame.height - 1 - (int32_t)backing.y;
          if (type == NSEventTypeLeftMouseDown)
            target->frame.flags |= DYN_DOWN | DYN_PRESSED;
          else if (type == NSEventTypeLeftMouseUp) {
            target->frame.flags &= ~DYN_DOWN;
            target->frame.flags |= DYN_RELEASED;
          }
        }
        if (type == NSEventTypeKeyDown) {
          NSString *chars = [event charactersIgnoringModifiers];
          if ([chars length]) {
            unichar key = [chars characterAtIndex:0];
            if (key == 9)
              target->frame.flags |= DYN_TAB;
            else if (key == 13 || key == 32)
              target->frame.flags |= DYN_ACTIVATE;
            else if (key == NSLeftArrowFunctionKey)
              target->frame.flags |= DYN_LEFT;
            else if (key == NSRightArrowFunctionKey)
              target->frame.flags |= DYN_RIGHT;
          }
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
