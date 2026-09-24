#!/usr/bin/env python3
"""Loopback UDP/TCP DNS: truncation fallback, AAAA, split frames, deadline, bounds."""
import concurrent.futures
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import time
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn')).resolve())

def exact(sock,n):
    out=b''
    while len(out)<n:
        part=sock.recv(n-len(out))
        if not part: raise AssertionError('early close')
        out+=part
    return out

def response(query, truncated=False, v6=False):
    header=query[:2]+struct.pack('!5H',0x8380 if truncated else 0x8180,1,0 if truncated else 1,0,0)
    if truncated: return header+query[12:]
    payload=bytes(range(16)) if v6 else b'\x01\x02\x03\x04'
    return header+query[12:]+b'\xc0\x0c'+struct.pack('!HHIH',28 if v6 else 1,1,60,len(payload))+payload

with tempfile.TemporaryDirectory(prefix='dyn-dns-') as tmp, concurrent.futures.ThreadPoolExecutor() as pool:
    path=Path(tmp)
    for mode in ([],['--release']):
        for scenario in ('udp','tcp','aaaa','capacity','truncated','timeout','wrong-id'):
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as udp, socket.socket() as tcp:
                udp.bind(('127.0.0.1',0)); port=udp.getsockname()[1]
                tcp.bind(('127.0.0.1',port));tcp.listen();tcp.settimeout(5);udp.settimeout(5)
                def serve():
                    query,address=udp.recvfrom(65535)
                    if scenario in ('udp','wrong-id'):
                        reply=response(query)
                        if scenario=='wrong-id': udp.sendto(bytes([reply[0]^1])+reply[1:],address)
                        udp.sendto(reply,address);return
                    udp.sendto(response(query,True),address)
                    with tcp.accept()[0] as conn:
                        conn.settimeout(5)
                        query2=exact(conn,struct.unpack('!H',exact(conn,2))[0])
                        assert query==query2
                        reply=response(query2,v6=scenario=='aaaa')
                        if scenario=='timeout': time.sleep(.2);return
                        if scenario=='capacity': conn.sendall(struct.pack('!H',4096));return
                        wire=struct.pack('!H',len(reply))+reply
                        if scenario=='truncated': conn.sendall(wire[:-1]);return
                        for byte in wire: conn.sendall(bytes([byte]))
                future=pool.submit(serve)
                v6=scenario=='aaaa'; error={'capacity':-28,'truncated':-74,'timeout':-110}.get(scenario)
                expected=f'if result.ok || result.error != {error} {{ #panic("DNS expected error") }}' if error else ('if !result.ok || result.count != 1 || addresses[0].bytes[15] != 15 { #panic("AAAA") }' if v6 else 'if !result.ok || result.count != 1 || addresses[0].a != 1 || addresses[0].d != 4 { #panic("A") }')
                (path/'main.dyn').write_text(f'''use "std/net/dns" dns
use "std/net" net
fn main() {{
 server := net.ipv4(127,0,0,1,{port})
 addresses: [4]dns.Ipv{'6' if v6 else '4'} = [] packet: [512]u8 = []
 result := dns.resolve_ipv{'6' if v6 else '4'}("example.test", &server, addresses[..], packet[..], {50 if scenario=='timeout' else 2000})
 {expected}
}}
''')
                subprocess.run([DYN,'build',str(path),'--quiet','--no-cache','--output',str(path/'run'),*mode],cwd=ROOT,check=True)
                subprocess.run([str(path/'run')],cwd=ROOT,check=True,timeout=5)
                future.result(timeout=5)
print('PASS DNS loopback: 7 transport scenarios, debug/release')
