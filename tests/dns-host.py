#!/usr/bin/env python3
"""Local DNS transport/entropy contracts. No external DNS or randomness-quality claims."""
import argparse
from contextlib import ExitStack
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build' /
                              ('dyn-release.exe' if os.name == 'nt' else 'dyn-release'))).resolve())
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--cross', action='store_true', help='cross-link all four native targets; do not execute')
options = parser.parse_args()
SOURCE = r'''use "std/net" net
use "std/net/dns" dns
use "std/mem" mem
use "std/crypto/random" random
fn require(value: bool, message: []const u8) { if !value { #panic(message) } }
fn main() {
  bytes: [515]u8 = []
  sizes: [4]usize = [0,1,257,513]
  for size in sizes {
    for i in 0..515 { bytes[i] = 42 }
    require(random.fill(bytes[1..size+1]),"native random failed")
    require(bytes[0] == 42,"random prefix clobbered")
    for i in size+1..515 { require(bytes[i] == 42,"random suffix clobbered") }
  }
  server := net.ipv4(127,0,0,1,PORT)
  arena: mem.Arena
  defer mem.arena_release(&arena)
  result := dns.resolve_ipv4(&arena,"a.test",&server,4000)
  require(result.ok && #len(result.value) == 1,"A response")
  require(result.value[0].a == 1 && result.value[0].b == 2 && result.value[0].c == 3 && result.value[0].d == 4,"A value / nonce filtering")
  result6 := dns.resolve_ipv6(&arena,"aaaa.test",&server,4000)
  require(result6.ok && #len(result6.value) == 1,"AAAA response")
  for i in 0..16 { require(result6.value[0].bytes[i] == #cast(u8, i),"AAAA value") }
  result = dns.resolve_ipv4(&arena,"missing.test",&server,4000)
  require(!result.ok && result.error == -3,"NXDOMAIN response")
  result = dns.resolve_ipv4(&arena,"large.test",&server,4000)
  require(result.ok && #len(result.value) == 1,"UDP truncation TCP fallback")
  require(result.value[0].a == 9 && result.value[0].b == 8 && result.value[0].c == 7 && result.value[0].d == 6,"TCP response value")
}
'''

def question(packet, expected_name, expected_kind):
    assert len(packet) >= 17, 'short query'
    nonce, flags, questions, answers, authority, extra = struct.unpack('!6H', packet[:12])
    assert (flags, questions, answers, authority, extra) == (0x100, 1, 0, 0, 0)
    offset, labels = 12, []
    while True:
        size = packet[offset]
        offset += 1
        if size == 0:
            break
        assert 0 < size <= 63 and offset + size <= len(packet), 'invalid query label'
        labels.append(packet[offset:offset+size].decode('ascii'))
        offset += size
    assert '.'.join(labels) == expected_name
    assert packet[offset:] == struct.pack('!HH', expected_kind, 1), 'query kind/class/trailing bytes'
    return nonce, packet[12:]


def response(nonce, query, kind, payload=None, rcode=0):
    header = struct.pack('!6H', nonce, 0x8180 | rcode, 1, int(payload is not None), 0, 0)
    if payload is None:
        return header + query
    return header + query + b'\xc0\x0c' + struct.pack('!HHIH', kind, 1, 60, len(payload)) + payload


def receive_exact(connection, size):
    data = bytearray()
    while len(data) < size:
        chunk = connection.recv(size-len(data))
        assert chunk, 'truncated TCP query'
        data.extend(chunk)
    return bytes(data)



def paired_sockets():
    """Reserve UDP first: Windows may reserve much of TCP's ephemeral range
    for UDP. Retry if the selected UDP port is unavailable to TCP."""
    for _ in range(50):
        tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            udp.bind(('127.0.0.1', 0))
            port = udp.getsockname()[1]
            tcp.bind(('127.0.0.1', port))
        except OSError:
            udp.close()
            tcp.close()
            continue
        return tcp, udp, port
    raise RuntimeError('no port free for both TCP and UDP')

def serve(udp, tcp, failures, observed):
    try:
        for name, kind, payload in (
            ('a.test', 1, bytes([1,2,3,4])),
            ('aaaa.test', 28, bytes(range(16))),
            ('missing.test', 1, None),
            ('large.test', 1, bytes([9,8,7,6])),
        ):
            packet, peer = udp.recvfrom(4096)
            nonce, query = question(packet, name, kind)
            observed.append(('udp', name))
            if name == 'a.test':
                # A valid-looking answer with another transaction ID must be ignored.
                udp.sendto(response(nonce ^ 0x8000, query, kind, bytes([8,8,8,8])), peer)
            if name == 'large.test':
                # The resolver owns full protocol-sized storage now. Explicit TC
                # forces TCP rather than relying on a small caller packet buffer.
                oversized = bytearray(response(nonce, query, kind, bytes([2,2,2,2])))
                oversized[2] |= 2
                udp.sendto(oversized + bytes(1024-len(oversized)), peer)
                connection, _ = tcp.accept()
                with connection:
                    connection.settimeout(5)
                    length = struct.unpack('!H', receive_exact(connection, 2))[0]
                    tcp_packet = receive_exact(connection, length)
                    tcp_nonce, tcp_query = question(tcp_packet, name, kind)
                    assert tcp_nonce == nonce and tcp_query == query, 'TCP changed transaction/question'
                    observed.append(('tcp', name))
                    answer = response(nonce, query, kind, payload)
                    framed = struct.pack('!H', len(answer)) + answer
                    # Exercise partial prefix and body transfers.
                    for byte in framed:
                        connection.sendall(bytes([byte]))
                        time.sleep(0.001)
            else:
                udp.sendto(response(nonce, query, kind, payload,
                                    3 if name == 'missing.test' else 0), peer)
    except Exception as error:
        failures.append(error)


def build(project, output, mode, target=None):
    command = [DYN, 'build', str(project), mode, '--no-cache', '--quiet', '--output', str(output)]
    if target:
        command += ['--target', target]
    subprocess.run(command, check=True, timeout=90)


with tempfile.TemporaryDirectory(prefix='dyn-dns-host-') as temporary:
    root = Path(temporary)
    project = root/'source'
    project.mkdir()
    if options.cross:
        (project/'main.dyn').write_text(SOURCE.replace('PORT', '5353'))
        for target in ('x86_64-linux', 'aarch64-linux', 'aarch64-macos', 'x86_64-windows'):
            for mode in ('--debug', '--release'):
                build(project, root/(target+mode+'.exe'), mode, target)
        print('PASS DNS/random four-target cross-link (debug/release; not executed)')
    else:
        for mode in ('--debug', '--release'):
            with ExitStack() as resources:
                tcp, udp, port = paired_sockets()
                resources.enter_context(tcp)
                resources.enter_context(udp)
                tcp.listen(1)
                tcp.settimeout(5)
                udp.settimeout(5)
                (project/'main.dyn').write_text(SOURCE.replace('PORT', str(port)))
                output = root/('program.exe' if os.name == 'nt' else 'program')
                build(project, output, mode)
                failures, observed = [], []
                worker = threading.Thread(target=serve, args=(udp, tcp, failures, observed), daemon=True)
                worker.start()
                result = subprocess.run([str(output)], capture_output=True, timeout=20)
                worker.join(timeout=6)
                assert not worker.is_alive(), 'DNS server failed to terminate'
                assert result.returncode == 0, (mode, result.returncode, result.stdout, result.stderr, failures)
                assert not failures, failures
                assert observed == [('udp','a.test'), ('udp','aaaa.test'), ('udp','missing.test'),
                                    ('udp','large.test'), ('tcp','large.test')], observed
        print('PASS native local DNS A/AAAA/NXDOMAIN/nonce/TCP fallback and random bounds (debug/release)')
