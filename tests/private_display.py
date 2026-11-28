"""Keep tests off the developer's desktop display.

Importing this module removes the display variables from os.environ, so tests
and every process they start see no X11 or Wayland display and skip their
display checks. Test windows, clipboard traffic and Wine on a live session
have crashed the desktop's X server bridge (xwayland-satellite), and every X
application died with it.

Set DYN_TEST_DISPLAY=private only when DISPLAY and WAYLAND_DISPLAY name
private servers (for example Xvfb or a headless weston started for the run).
Tests that start their own private server set it for their children.
"""
import os

VARIABLES = ('DISPLAY', 'WAYLAND_DISPLAY', 'WAYLAND_SOCKET', 'NIRI_SOCKET')


def isolate():
    if os.environ.get('DYN_TEST_DISPLAY') == 'private':
        return
    for name in VARIABLES:
        os.environ.pop(name, None)


isolate()
