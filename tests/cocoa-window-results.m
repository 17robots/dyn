// Native macOS-only regression: one poll pumps events for multiple windows.
#import "../vendor/window/native/cocoa.m"
#include <assert.h>
int main(void) {
  @autoreleasepool {
    Host *a = dyn_window_open("Dyn first", 64, 64);
    Host *b = dyn_window_open("Dyn second", 64, 64);
    assert(a && b);
    for (int i = 0; i < 2; ++i) {
      NSEvent *event = [NSEvent mouseEventWithType:i ? NSEventTypeLeftMouseUp
                                                     : NSEventTypeLeftMouseDown
                                          location:NSMakePoint(4, 4)
                                     modifierFlags:0
                                         timestamp:0
                                      windowNumber:[window(b) windowNumber]
                                           context:nil
                                       eventNumber:i
                                        clickCount:1
                                          pressure:i ? 0 : 1];
      [NSApp postEvent:event atStart:NO];
    }
    dyn_window_frame first, second;
    assert(dyn_window_poll(a, &first));
    assert(dyn_window_poll(b, &second));
    assert((second.flags & (DYN_PRESSED | DYN_RELEASED)) ==
           (DYN_PRESSED | DYN_RELEASED));
    assert(!(second.flags & DYN_DOWN));
    assert(dyn_window_poll(b, &second));
    assert(!(second.flags & (DYN_PRESSED | DYN_RELEASED)));
    dyn_window_close(b);
    dyn_window_close(a);
  }
  return 0;
}
