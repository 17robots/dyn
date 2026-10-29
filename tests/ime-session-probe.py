#!/usr/bin/env python3
"""Read-only prerequisite inventory; never declares a real IME session qualified."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess


def command(argv):
    if not shutil.which(argv[0]):
        return {'available': False}
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=10)
        return {'available': True, 'returncode': result.returncode,
                'stdout': result.stdout.strip(), 'stderr': result.stderr.strip()}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {'available': True, 'error': type(error).__name__}


def inventory():
    system = platform.system()
    report = {'schema': 1, 'platform': system, 'architecture': platform.machine(),
              'qualification': 'not-run',
              'purpose': 'Prerequisite inventory only; no input, focus or daemon changes.'}
    report['tools'] = {name: bool(shutil.which(name)) for name in
                       ('xcrun', 'ibus', 'fcitx5', 'dbus-send', 'xprop')}
    report['session'] = {name: os.environ.get(name, '') for name in
                         ('DISPLAY', 'WAYLAND_DISPLAY', 'XMODIFIERS',
                          'GTK_IM_MODULE', 'QT_IM_MODULE')}
    blockers = []
    if system == 'Darwin':
        report['macos_version'] = command(['sw_vers', '-productVersion'])
        report['macos_sdk'] = command(['xcrun', '--sdk', 'macosx', '--show-sdk-path'])
        if report['macos_sdk'].get('returncode') != 0:
            blockers.append('Native macOS SDK unavailable.')
        blockers.append('Interactive input source and end-to-end IME actions are not exercised by this probe.')
    else:
        blockers.append('Real Cocoa qualification requires a native macOS GUI session and SDK.')
    if system == 'Linux':
        report['x11_version'] = command(['pkg-config', '--modversion', 'x11'])
        report['xim_servers'] = command(['xprop', '-root', '_XIM_SERVERS'])
        bus = command(['dbus-send', '--session', '--dest=org.freedesktop.DBus',
                       '--type=method_call', '--print-reply', '/org/freedesktop/DBus',
                       'org.freedesktop.DBus.ListNames'])
        # Store only relevant names, not the user's complete session-service list.
        report['ime_bus'] = {'available': bus['available'],
                             'returncode': bus.get('returncode'),
                             'services': [line.strip().removeprefix('string ').strip('"')
                                          for line in bus.get('stdout', '').splitlines()
                                          if 'org.freedesktop.IBus' in line or 'org.fcitx.Fcitx' in line]}
        xim = report['xim_servers'].get('stdout', '')
        if report['xim_servers'].get('returncode') != 0 or 'no such atom' in xim or not xim:
            blockers.append('No advertised XIM server observed on the current X11 root.')
        if not report['ime_bus']['services']:
            blockers.append('No IBus/Fcitx service observed on the session bus; IBus may use a separate bus.')
        blockers.append('XIM surrounding conversion remains unsupported; see docs/internals/xim-surrounding-support.md.')
    report['blockers'] = blockers
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='also save the JSON inventory')
    args = parser.parse_args()
    rendered = json.dumps(inventory(), indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding='utf-8')
    print(rendered, end='')


if __name__ == '__main__':
    main()
