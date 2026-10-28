// Native macOS-only regression: one poll pumps events for multiple windows.
#import "../vendor/window/native/cocoa.m"
#include <assert.h>
int main(void) {
  @autoreleasepool {
    Host *a = dyn_window_open("Dyn first", 64, 64);
    Host *b = dyn_window_open("Dyn second", 64, 64);
    assert(a && b);
    dyn_window_frame first, second;
    // Drain activation/creation events before injecting content-area input.
    assert(dyn_window_poll(a, &first));
    assert(dyn_window_poll(b, &second));
    dyn_window_listen_events(b, 1);
    for (int i = 0; i < 2; ++i) {
      NSEvent *event = [NSEvent mouseEventWithType:i ? NSEventTypeLeftMouseUp
                                                     : NSEventTypeLeftMouseDown
                                          location:NSMakePoint(32, 32)
                                     modifierFlags:0
                                         timestamp:0
                                      windowNumber:[window(b) windowNumber]
                                           context:nil
                                       eventNumber:i
                                        clickCount:1
                                          pressure:i ? 0 : 1];
      assert(event && [event window] == window(b));
      [NSApp postEvent:event atStart:NO];
    }
    assert(dyn_window_poll(a, &first));
    assert(dyn_window_poll(b, &second));
    assert(!(first.flags & (DYN_PRESSED | DYN_RELEASED)));
    dyn_window_event event;
    unsigned presses = 0, releases = 0;
    while (dyn_window_next_event(b, &event)) {
      if (event.kind == DYN_EVENT_POINTER_DOWN && event.button == 1) ++presses;
      if (event.kind == DYN_EVENT_POINTER_UP && event.button == 1) ++releases;
    }
    assert(presses == 1 && releases == 1);
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
