#!/usr/bin/env python3
"""std/terminal sessions and std/process/signal job-control kinds.

Type-checks a session program for the six desktop targets. Where the host has
pseudo-terminals (Linux, macOS) it runs that program as the foreground job of
a PTY under a small job-control shell and checks: raw mode on and off restores
termios exactly, TIOCSWINSZ on the master delivers WindowChange, SIGTSTP and
SIGCONT round-trip through suspend with the terminal restored while stopped,
and a panic, a memory fault and a fatal signal leave the terminal in cooked
mode with the alternate screen exited, in debug and release builds. On
Windows (and under wine) it runs the contract checks that need no console.
"""
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build' / ('dyn-release.exe' if os.name == 'nt' else 'dyn-release'))).resolve())
TARGETS = ('x86_64-linux', 'aarch64-linux', 'x86_64-macos', 'aarch64-macos', 'x86_64-windows', 'aarch64-windows')

SESSION = r'''use terminal "std/terminal"
use signal "std/process/signal"
use io "std/io"

fn fault() {
  address := #cast(*u32, #cast(usize, 8))
  address.* = 1
}

pub fn main() {
  watching := signal.watch(signal.Set{ terminate: true, window_change: true, suspend: true, continue: true }) catch {
    #panic("watch")
  }
  session: terminal.Session
  modes := terminal.Modes{
    alternate_screen: true,
    hide_cursor: true,
    bracketed_paste: true,
    mouse: true,
    mouse_motion: true,
    kitty_keyboard: true,
    crash_restore: true,
  }
  terminal.enter(&session, 0, 1, modes) catch { #panic("enter") }
  again: terminal.Session
  terminal.enter(&again, 0, 1, modes) catch err {
    case err {
      .InvalidInput => { io.print("claimed\r\n") }
      _ => { #panic("second enter") }
    }
  }
  io.print("entered\r\n")
  if CRASH == 1 { #panic("deliberate panic") }
  if CRASH == 2 { fault() }
  for true {
    kind := signal.wait(&watching) catch { #panic("wait") }
    case kind {
      .WindowChange => {
        size := terminal.size(1) catch { #panic("size") }
        io.print("resize {} {}\r\n", size.columns, size.rows)
      }
      .Suspend => {
        io.print("suspending\r\n")
        terminal.suspend(&session) catch { #panic("suspend") }
        io.print("resumed\r\n")
      }
      .Continue => { io.print("continue\r\n") }
      .Terminate => {
        terminal.leave(&session) catch { #panic("leave") }
        terminal.leave(&session) catch { #panic("leave twice") }
        io.print("left\n")
        break
      }
      _ => {}
    }
  }
  signal.close(&watching)
}
'''

# Needs no terminal: runs everywhere, standard streams redirected.
CONTRACT = r'''use terminal "std/terminal"
use signal "std/process/signal"
use io "std/io"

fn check(ok: bool, what: []const u8) {
  if !ok { #panic(what) }
}

fn suspend_invalid(session: *terminal.Session) bool {
  terminal.suspend(session) catch err {
    case err {
      .InvalidInput => { return true }
      _ => { return false }
    }
  }
  return false
}

fn enter_invalid() bool {
  terminal.enter(nil, 0, 1, terminal.Modes{}) catch err {
    case err {
      .InvalidInput => { return true }
      _ => { return false }
    }
  }
  return false
}

fn enter_fails(session: *terminal.Session, modes: terminal.Modes) bool {
  terminal.enter(session, 0, 1, modes) catch { return true }
  return false
}

fn virtual_fails() bool {
  _ = terminal.virtual_terminal(0) catch { return true }
  return false
}

fn wait_invalid(state: *signal.Watch) bool {
  _ = signal.wait(state) catch err {
    case err {
      .InvalidInput => { return true }
      _ => { return false }
    }
  }
  return false
}

pub fn main() {
  zero: terminal.Session
  check(suspend_invalid(&zero), "suspend of a zero session")
  check(enter_invalid(), "enter nil")
  terminal.leave(&zero) catch { #panic("leave of a zero session") }
  terminal.crash_restore()
  if !terminal.is_attached(0) {
    check(enter_fails(&zero, terminal.Modes{ crash_restore: true }), "enter without a terminal")
    check(!zero.active, "failed enter left the session active")
    // The failed enter released crash restore: a second attempt is refused
    // for the same reason, not because it is still claimed.
    check(enter_fails(&zero, terminal.Modes{ crash_restore: true }), "enter again")
    check(virtual_fails(), "virtual_terminal without a terminal")
  }
  closed: signal.Watch
  check(wait_invalid(&closed), "wait on a zero watch")
  watching := signal.watch(signal.Set{ window_change: true, suspend: true, continue: true }) catch { #panic("watch") }
  first := signal.poll(&watching) catch { #panic("poll") }
  check(first == signal.Kind.None, "nothing pending")
  signal.close(&watching)
  if WINDOWS {
    stopped := true
    signal.stop_job() catch err {
      case err {
        .Unsupported => { stopped = false }
        _ => {}
      }
    }
    check(!stopped, "stop_job on Windows")
  }
  io.println("contract ok")
}
'''

# Under wine in a PTY, the console is the PTY: suspend runs cmd.exe in it.
# Wine redraws what it is given, so markers are single words, each written
# whole.
WINDOWS_SESSION = r'''use terminal "std/terminal"
use signal "std/process/signal"
use io "std/io"

pub fn main() {
  session: terminal.Session
  modes := terminal.Modes{ alternate_screen: true, mouse: true, crash_restore: true }
  terminal.enter(&session, 0, 1, modes) catch { #panic("enter") }
  watching := signal.watch(signal.Set{ window_change: true }) catch { #panic("watch") }
  kind := signal.poll(&watching) catch { #panic("poll") }
  signal.close(&watching)
  if kind == signal.Kind.None { io.print("quiet\r\n") }
  terminal.suspend(&session) catch { #panic("suspend") }
  io.print("resumed\r\n")
  terminal.leave(&session) catch { #panic("leave") }
  io.println("left")
  terminal.enter(&session, 0, 1, modes) catch { #panic("enter again") }
  #panic("deliberate panic")
}
'''

# A job-control shell: owns the PTY session, runs the program as the
# foreground job in its own process group (so the group is not orphaned and
# SIGTSTP stops it), and reports every state change on stdout.
SHELL = r'''
import fcntl, os, resource, signal, sys, termios
slave = int(sys.argv[1])
# The crashes are deliberate: no core files.
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
program = sys.argv[2]
os.setsid()
fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
child = os.fork()
if child == 0:
    signal.signal(signal.SIGTTOU, signal.SIG_IGN)
    os.setpgid(0, 0)
    os.tcsetpgrp(slave, os.getpid())
    for number in (signal.SIGTTOU, signal.SIGPIPE, signal.SIGINT):
        signal.signal(number, signal.SIG_DFL)
    for descriptor in (0, 1, 2):
        os.dup2(slave, descriptor)
    os.execv(program, [program])
try:
    os.setpgid(child, child)
except OSError:
    pass
print('pid', child, flush=True)
while True:
    _, status = os.waitpid(child, os.WUNTRACED | os.WCONTINUED)
    if os.WIFSTOPPED(status):
        print('stopped', os.WSTOPSIG(status), flush=True)
    elif os.WIFCONTINUED(status):
        print('continued', flush=True)
    elif os.WIFSIGNALED(status):
        print('signaled', os.WTERMSIG(status), flush=True)
        break
    else:
        print('exited', os.WEXITSTATUS(status), flush=True)
        break
'''


def build(directory, name, source, target, release=False):
    project = Path(directory) / name
    project.mkdir()
    (project / 'main.dyn').write_text(source)
    output = project / ('program.exe' if 'windows' in target else 'program')
    command = [DYN, 'build', str(project), '--no-cache', '--quiet', '--target', target, '--output', str(output)]
    if release:
        command.append('--release')
    subprocess.run(command, check=True, timeout=180)
    return output


def check(directory, name, source, target):
    project = Path(directory) / f'{name}-{target}'
    project.mkdir()
    (project / 'main.dyn').write_text(source)
    result = subprocess.run([DYN, 'check', str(project), '--target', target], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, (name, target, result.stdout, result.stderr)


class Job:
    """One run of the session program on a fresh PTY."""

    def __init__(self, program):
        import pty
        import termios
        self.termios = termios
        self.master, self.slave = pty.openpty()
        self.resize(80, 24)
        self.cooked = self.masked(termios.tcgetattr(self.slave))
        self.shell = subprocess.Popen([sys.executable, '-c', SHELL, str(self.slave), str(program)],
                                      stdout=subprocess.PIPE, text=True, pass_fds=(self.slave,),
                                      cwd=Path(program).parent)
        words = self.status()
        assert words[0] == 'pid', words
        self.pid = int(words[1])
        self.output = b''

    def resize(self, columns, rows):
        import fcntl
        import struct
        import termios
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack('HHHH', rows, columns, 0, 0))

    def status(self):
        ready, _, _ = select.select([self.shell.stdout], [], [], 60)
        assert ready, 'job-control shell went quiet'
        return self.shell.stdout.readline().split()

    def read_until(self, text, timeout=60):
        deadline = time.monotonic() + timeout
        while text.encode() not in self.output:
            left = deadline - time.monotonic()
            assert left > 0, (text, self.output)
            ready, _, _ = select.select([self.master], [], [], left)
            if ready:
                try:
                    chunk = os.read(self.master, 65536)
                except OSError:
                    chunk = b''
                if not chunk:
                    assert text.encode() in self.output, (text, self.output)
                    return
                self.output += chunk

    def drain(self):
        while True:
            ready, _, _ = select.select([self.master], [], [], 0.2)
            if not ready:
                return
            try:
                chunk = os.read(self.master, 65536)
            except OSError:
                return
            if not chunk:
                return
            self.output += chunk

    def state(self):
        try:
            return self.masked(self.termios.tcgetattr(self.slave))
        except self.termios.error:
            # macOS revokes the slave once the session's last process exits;
            # the master still reports the terminal's settings there.
            if sys.platform != 'darwin':
                raise
            return self.masked(self.termios.tcgetattr(self.master))

    def masked(self, state):
        # PENDIN and FLUSHO are status bits the kernel sets itself (macOS sets
        # PENDIN when canonical mode returns with input queued); a program never
        # writes them, so restores are compared without them.
        status = getattr(self.termios, 'PENDIN', 0) | getattr(self.termios, 'FLUSHO', 0)
        state = list(state)
        state[3] &= ~status
        return state

    def assert_raw(self):
        state = self.state()
        local = state[3]
        assert not (local & self.termios.ICANON) and not (local & self.termios.ECHO), state
        assert not (local & self.termios.ISIG), state

    def assert_cooked(self, why):
        assert self.state() == self.cooked, (why, self.state(), self.cooked)

    def close(self):
        if self.shell.poll() is None:
            try:
                os.kill(self.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        self.shell.wait(timeout=30)
        os.close(self.master)
        os.close(self.slave)


LEAVE = b'\x1b[<u\x1b[?1006l\x1b[?1003l\x1b[?1002l\x1b[?1000l\x1b[?2004l\x1b[0m\x1b[?25h\x1b[?1049l'
ENTER = b'\x1b[?1049h\x1b[?25l\x1b[?2004h\x1b[?1000h\x1b[?1002h\x1b[?1003h\x1b[?1006h\x1b[>1u'


def run_wine_session(program):
    import pty
    pid, master = pty.fork()
    if pid == 0:
        os.execvp('wine', ['wine', str(program)])
    output = b''
    status = None
    deadline = time.monotonic() + 180
    leave = b'\x1b[?1006l\x1b[?1002l\x1b[?1000l\x1b[0m\x1b[?1049l'
    try:
        answered = False
        # wineserver may keep the PTY open after the program exits, so the
        # loop ends on the exit status rather than on end of file.
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], 0.5)
            if ready:
                try:
                    output += os.read(master, 65536)
                except OSError:
                    pass
            elif status is not None:
                break
            if status is None:
                done, code = os.waitpid(pid, os.WNOHANG)
                if done:
                    status = code
            # cmd.exe prompts once the session has left; leave it again.
            shell = output[output.find(b'quiet'):] if b'quiet' in output else b''
            # Typing before cmd.exe reads its first line can lose the
            # Enter, so wait a moment and press it again if nothing happens.
            if not answered and leave in shell and b'>' in shell[shell.index(leave):]:
                time.sleep(1)
                os.write(master, b'exit\r')
                answered = time.monotonic()
            elif answered and b'resumed' not in output and time.monotonic() - answered > 5:
                os.write(master, b'\r')
                answered = time.monotonic()
    finally:
        if status is None:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
        os.close(master)
    assert status is not None, ('wine session did not finish', output[-600:])
    assert os.WIFEXITED(status) and os.WEXITSTATUS(status) == 101, (status, output[-600:])
    start = output.index(b'quiet')
    assert b'\x1b[?1049h\x1b[?1000h\x1b[?1002h\x1b[?1006h' in output[:start], output[:start][-200:]
    rest = output[start:]
    resumed = rest.index(b'resumed')
    assert leave in rest[:resumed] and b'\x1b[?1049h' in rest[:resumed], rest[:resumed]
    left = rest.index(b'left')
    crash = rest.index(b'deliberate')
    assert left < crash and leave in rest[left:crash], rest[left:crash]


def run_session(program):
    job = Job(program)
    try:
        job.read_until('entered')
        assert ENTER in job.output, job.output
        assert b'claimed' in job.output, 'a second crash-restore session was not refused'
        job.assert_raw()
        # A resize of the master reaches the foreground job as SIGWINCH.
        job.resize(100, 40)
        job.read_until('resize 100 40')
        # SIGTSTP from outside: the watch reports Suspend, suspend leaves and
        # stops the job; the terminal is cooked while it is stopped.
        os.kill(job.pid, signal.SIGTSTP)
        words = job.status()
        assert words == ['stopped', str(int(signal.SIGTSTP))], words
        job.drain()
        tail = job.output[job.output.index(b'suspending'):]
        assert LEAVE in tail, tail
        job.assert_cooked('while stopped')
        os.kill(job.pid, signal.SIGCONT)
        # macOS waitpid does not report WCONTINUED; the job's own "resumed"
        # output below shows it ran again on every platform.
        if sys.platform != 'darwin':
            assert job.status() == ['continued']
        job.read_until('resumed')
        job.read_until('continue')
        assert ENTER in job.output[job.output.index(b'suspending'):], 'suspend did not enter again'
        job.assert_raw()
        os.kill(job.pid, signal.SIGTERM)
        job.read_until('left')
        words = job.status()
        while words == ['continued'] and sys.platform == 'darwin':
            words = job.status()
        assert words == ['exited', '0'], words
        job.assert_cooked('after leave')
        assert job.output.rstrip().endswith(LEAVE + b'left'), job.output[-120:]
    finally:
        job.close()


def run_crash(program, expected, message=None, send=None):
    job = Job(program)
    try:
        job.read_until('entered')
        if send is not None:
            # A program that crashes by itself may be gone already.
            job.assert_raw()
            os.kill(job.pid, send)
        words = job.status()
        # expected may list the alternatives, as for a fault in page zero,
        # which macOS may report as SIGBUS.
        assert words == expected or words in expected, (words, expected, job.output)
        job.drain()
        job.assert_cooked(f'after {expected}')
        after = job.output[job.output.index(b'entered'):]
        assert LEAVE in after, after
        if message:
            # The report comes after the terminal is restored, on the main
            # screen.
            assert message.encode() in after[after.index(LEAVE):], after
    finally:
        job.close()


with tempfile.TemporaryDirectory(prefix='dyn-terminal-session-') as directory:
    session = SESSION.replace('CRASH', '0')
    for target in TARGETS:
        check(directory, 'session', session, target)
        check(directory, 'contract', CONTRACT.replace('WINDOWS', 'true' if 'windows' in target else 'false'), target)
    host = {'linux': 'linux', 'darwin': 'macos'}.get(sys.platform)
    machine = {'x86_64': 'x86_64', 'AMD64': 'x86_64', 'arm64': 'aarch64', 'aarch64': 'aarch64'}.get(os.uname().machine if hasattr(os, 'uname') else '')
    ran = []
    if host and machine:
        target = f'{machine}-{host}'
        contract = build(directory, 'contract', CONTRACT.replace('WINDOWS', 'false'), target)
        result = subprocess.run([str(contract)], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        assert result.returncode == 0 and 'contract ok' in result.stdout, result
        for release in (False, True):
            mode = 'release' if release else 'debug'
            program = build(directory, f'session-{mode}', session, target, release)
            run_session(program)
            panic = build(directory, f'panic-{mode}', SESSION.replace('CRASH', '1'), target, release)
            run_crash(panic, ['exited', '101'], 'deliberate panic')
            fault = build(directory, f'fault-{mode}', SESSION.replace('CRASH', '2'), target, release)
            if release:
                run_crash(fault, [['signaled', str(int(signal.SIGSEGV))], ['signaled', str(int(signal.SIGBUS))]])
            else:
                # Debug programs report a memory fault; the session's handler
                # restores first, then runs the runtime's.
                run_crash(fault, ['exited', '101'], 'memory fault')
            for number in (signal.SIGABRT, signal.SIGHUP, signal.SIGQUIT):
                run_crash(program, ['signaled', str(int(number))], send=number)
            ran.append(f'{target} {mode}')
        if sys.platform == 'linux':
            # User-mode QEMU checks the translated sigaction layouts and
            # restorers; it does not pass SIGABRT on, so that one is skipped.
            for arch, emulator in (('aarch64', 'qemu-aarch64'), ('riscv64', 'qemu-riscv64')):
                if arch == machine or not shutil.which(emulator):
                    continue
                for release in (False, True):
                    mode = 'release' if release else 'debug'

                    def emulated(name, source):
                        built = build(directory, f'{name}-{arch}-{mode}', source, f'{arch}-linux', release)
                        wrapper = built.parent / 'run.sh'
                        wrapper.write_text(f'#!/bin/sh\nexec {emulator} {built}\n')
                        wrapper.chmod(0o755)
                        return wrapper
                    program = emulated('session', session)
                    run_session(program)
                    run_crash(emulated('panic', SESSION.replace('CRASH', '1')), ['exited', '101'], 'deliberate panic')
                    fault = emulated('fault', SESSION.replace('CRASH', '2'))
                    if release:
                        run_crash(fault, ['signaled', str(int(signal.SIGSEGV))])
                    else:
                        run_crash(fault, ['exited', '101'], 'memory fault')
                    run_crash(program, ['signaled', str(int(signal.SIGHUP))], send=signal.SIGHUP)
                    ran.append(f'{arch}-linux {mode} (qemu)')
    elif sys.platform == 'win32':
        contract = build(directory, 'contract', CONTRACT.replace('WINDOWS', 'true'), 'x86_64-windows')
        result = subprocess.run([str(contract)], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        assert result.returncode == 0 and 'contract ok' in result.stdout, result
        ran.append('x86_64-windows contract')
    if sys.platform == 'linux' and shutil.which('wine'):
        contract = build(directory, 'contract-wine', CONTRACT.replace('WINDOWS', 'true'), 'x86_64-windows')
        result = subprocess.run(['wine', str(contract)], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=180)
        assert result.returncode == 0 and 'contract ok' in result.stdout, result
        ran.append('x86_64-windows contract (wine)')
        windows = build(directory, 'session-wine', WINDOWS_SESSION, 'x86_64-windows')
        run_wine_session(windows)
        ran.append('x86_64-windows session, suspend and panic (wine PTY console)')
print('PASS terminal session: six cross-checks; ran ' + (', '.join(ran) or 'nothing on this host'))
