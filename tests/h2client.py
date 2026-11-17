"""A small HTTP/2 client for tests: frames, flow control and HPACK (decoding
the server's Huffman strings with the tables in std/net/http/hpack), with
every frame recorded so tests can check exactly what the server sent."""
from pathlib import Path
import re
import socket
import struct

ROOT = Path(__file__).resolve().parents[1]
PREFACE = b'PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n'
DATA, HEADERS, PRIORITY, RST, SETTINGS, PUSH, PING, GOAWAY, WINDOW, CONTINUATION = range(10)


def _tables():
    text = (ROOT / 'std/net/http/hpack/tables.dyn').read_text()

    def array(name):
        body = re.search(r'const %s: \[\d+\]\w+ = \[(.*?)\]' % name, text, re.S).group(1)
        return [int(v) for v in re.findall(r'\d+', body)]
    static_text = re.search(r'const StaticText: \[\]const u8 = "(.*?)"\n', text).group(1)
    names = [static_text[s:s + n] for s, n in zip(array('StaticNameStart'), array('StaticNameLength'))]
    values = [static_text[s:s + n] for s, n in zip(array('StaticValueStart'), array('StaticValueLength'))]
    codes = {}
    for symbol, (code, length) in enumerate(zip(array('HuffmanCodes'), array('HuffmanLengths'))):
        codes[(length, code)] = symbol
    return list(zip(names, values)), codes


STATIC, HUFFMAN = _tables()


def huffman_decode(data):
    out, code, length = bytearray(), 0, 0
    for byte in data:
        for bit in range(7, -1, -1):
            code = (code << 1) | ((byte >> bit) & 1)
            length += 1
            symbol = HUFFMAN.get((length, code))
            if symbol is not None:
                out.append(symbol)
                code, length = 0, 0
    assert length <= 7 and code == (1 << length) - 1, 'bad Huffman padding'
    return bytes(out)


def integer(data, at, prefix):
    mask = (1 << prefix) - 1
    value = data[at] & mask
    at += 1
    if value < mask:
        return value, at
    shift = 0
    while True:
        byte = data[at]
        at += 1
        value += (byte & 127) << shift
        shift += 7
        if not byte & 128:
            return value, at


def string(data, at):
    huffman = data[at] & 0x80
    length, at = integer(data, at, 7)
    raw = data[at:at + length]
    return (huffman_decode(raw) if huffman else raw).decode('latin1'), at + length


class Decoder:
    def __init__(self):
        self.dynamic = []

    def entry(self, index):
        return STATIC[index - 1] if index <= len(STATIC) else self.dynamic[index - len(STATIC) - 1]

    def decode(self, block):
        fields, at = [], 0
        while at < len(block):
            first = block[at]
            if first & 0x80:
                index, at = integer(block, at, 7)
                fields.append(self.entry(index))
                continue
            if first & 0xe0 == 0x20:
                size, at = integer(block, at, 5)
                continue
            prefix = 6 if first & 0xc0 == 0x40 else 4
            index, at = integer(block, at, prefix)
            name = self.entry(index)[0] if index else None
            if name is None:
                name, at = string(block, at)
            value, at = string(block, at)
            if prefix == 6:
                self.dynamic.insert(0, (name, value))
            fields.append((name, value))
        return fields


def literal(name, value):
    """A literal field without indexing, no Huffman (RFC 7541 6.2.2)."""
    def text(s):
        raw = s.encode('latin1')
        assert len(raw) < 127
        return bytes([len(raw)]) + raw
    return b'\x00' + text(name) + text(value)


class Client:
    def __init__(self, port, settings=None, window=None, tls=None):
        self.sock = socket.create_connection(('127.0.0.1', port), timeout=10)
        if tls is not None:
            self.sock = tls.wrap_socket(self.sock, server_hostname='127.0.0.1')
            assert self.sock.selected_alpn_protocol() == 'h2', self.sock.selected_alpn_protocol()
        self.buffer = b''
        self.decoder = Decoder()
        self.frames = []
        self.next_id = 1
        self.streams = {}
        self.settings = {}
        payload = b''.join(struct.pack('!HI', k, v) for k, v in (settings or {}).items())
        self.sock.sendall(PREFACE + self.frame(SETTINGS, 0, 0, payload))
        if window:
            self.sock.sendall(self.frame(WINDOW, 0, 0, struct.pack('!I', window)))
        self.auto_window = True

    @staticmethod
    def frame(kind, flags, stream, payload):
        return struct.pack('!I', len(payload))[1:] + bytes([kind, flags]) + struct.pack('!I', stream) + payload

    def send(self, kind, flags, stream, payload=b''):
        self.sock.sendall(self.frame(kind, flags, stream, payload))

    def request(self, method, path, body=None, headers=(), end=True):
        stream = self.next_id
        self.next_id += 2
        block = literal(':method', method) + literal(':scheme', 'http') + literal(':path', path) + \
            literal(':authority', 'test')
        for name, value in headers:
            block += literal(name, value)
        flags = 0x4 | (0x1 if body is None and end else 0)
        self.send(HEADERS, flags, stream, block)
        self.streams[stream] = {'headers': None, 'data': b'', 'ended': False, 'reset': None}
        if body is not None:
            for at in range(0, max(len(body), 1), 16384):
                last = at + 16384 >= len(body)
                self.send(DATA, 0x1 if last and end else 0, stream, body[at:at + 16384])
        return stream

    def read_frame(self):
        while len(self.buffer) < 9:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise EOFError('server closed')
            self.buffer += chunk
        length = int.from_bytes(self.buffer[:3], 'big')
        while len(self.buffer) < 9 + length:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise EOFError('server closed mid-frame')
            self.buffer += chunk
        kind, flags = self.buffer[3], self.buffer[4]
        stream = int.from_bytes(self.buffer[5:9], 'big') & 0x7fffffff
        payload = self.buffer[9:9 + length]
        self.buffer = self.buffer[9 + length:]
        self.frames.append((kind, flags, stream, len(payload)))
        self.handle(kind, flags, stream, payload)
        return kind, flags, stream, payload

    def handle(self, kind, flags, stream, payload):
        state = self.streams.get(stream)
        if kind == SETTINGS and not flags & 1:
            for at in range(0, len(payload), 6):
                key, value = struct.unpack('!HI', payload[at:at + 6])
                self.settings[key] = value
            self.send(SETTINGS, 1, 0)
        elif kind == PING and not flags & 1:
            self.send(PING, 1, 0, payload)
        elif kind == HEADERS:
            block = payload
            while not flags & 0x4:
                kind2, flags, _, more = self.read_frame_raw()
                assert kind2 == CONTINUATION
                block += more
            fields = self.decoder.decode(block)
            if state is not None:
                state['headers'] = fields
                state['ended'] = bool(flags & 1)
        elif kind == DATA and state is not None:
            state['data'] += payload
            state['ended'] = bool(flags & 1)
            if self.auto_window and payload:
                self.send(WINDOW, 0, 0, struct.pack('!I', len(payload)))
                if not flags & 1:
                    self.send(WINDOW, 0, stream, struct.pack('!I', len(payload)))
        elif kind == RST and state is not None:
            state['reset'] = struct.unpack('!I', payload)[0]

    def read_frame_raw(self):
        while len(self.buffer) < 9:
            self.buffer += self.sock.recv(65536)
        length = int.from_bytes(self.buffer[:3], 'big')
        while len(self.buffer) < 9 + length:
            self.buffer += self.sock.recv(65536)
        frame = (self.buffer[3], self.buffer[4], int.from_bytes(self.buffer[5:9], 'big') & 0x7fffffff,
                 self.buffer[9:9 + length])
        self.buffer = self.buffer[9 + length:]
        self.frames.append((frame[0], frame[1], frame[2], len(frame[3])))
        return frame

    def wait(self, stream):
        state = self.streams[stream]
        while not state['ended'] and state['reset'] is None:
            self.read_frame()
        return state

    def response(self, stream):
        state = self.wait(stream)
        headers = dict(state['headers'] or [])
        return int(headers.get(':status', 0)), headers, state['data']

    def close(self):
        self.sock.close()
