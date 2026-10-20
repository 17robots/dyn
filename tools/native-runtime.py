#!/usr/bin/env python3
"""Assemble Dyn's deliberately small runtime assembly dialect without target tools.

This is not a general purpose assembler. Unknown instructions/directives fail
closed; runtime source remains the authority, rather than prebuilt object blobs.
"""
import argparse
import ast
from dataclasses import dataclass, field
from pathlib import Path
import re
import struct

ROOT = Path(__file__).resolve().parents[1]


def pack(fmt, *args):
    return struct.pack('<' + fmt, *args)


def align(n, a):
    return (n + a - 1) & -a


@dataclass
class Section:
    name: str
    data: bytearray = field(default_factory=bytearray)
    alignment: int = 1
    relocs: list = field(default_factory=list)


class Assembler:
    def __init__(self, target):
        self.target = target
        self.rv64 = target.startswith('riscv64')
        self.a64 = target.startswith('aarch64')
        self.macho = target.endswith('macos')
        self.coff = target.endswith('windows')
        self.sections = {}
        self.symbols = {}
        self.globals = set()
        self.weak = set()
        self.hidden = set()
        self.aliases = {}
        self.current = self.section('.text')
        self.fixups = []
        self.numeric = {}

    def section(self, name):
        if name not in self.sections:
            self.sections[name] = Section(name)
        self.current = self.sections[name]
        return self.current

    def emit(self, data):
        self.current.data.extend(data)

    def word(self, n):
        self.emit(pack('I', n & 0xffffffff))

    def relocation(self, name, kind, addend=0, offset=None):
        if offset is None:
            offset = len(self.current.data)
        self.current.relocs.append((offset, name, kind, addend))

    def preprocess(self, path, defines):
        active = [True]
        result = []
        for line in path.read_text().splitlines():
            text = line.strip()
            match = re.match(r'#(ifdef|ifndef)\s+(\w+)', text)
            if match:
                yes = match[2] in defines
                active.append(active[-1] and (yes if match[1] == 'ifdef' else not yes))
            elif text == '#else':
                active[-1] = active[-2] and not active[-1]
            elif text == '#endif':
                active.pop()
            elif active[-1]:
                match = re.match(r'#include "(.*?)"', text)
                if match:
                    result.extend(self.preprocess(path.parent / match[1], defines))
                elif not text.startswith('#'):
                    result.append(line.split('//', 1)[0].strip())
        if len(active) != 1:
            raise ValueError('unclosed preprocessor conditional')
        return result

    def assemble(self, path, defines=()):
        lines = self.preprocess(path, set(defines))
        macros = {}
        expanded = []
        i = 0
        while i < len(lines):
            line = lines[i]
            i += 1
            if line.startswith('.macro '):
                head = line[7:].split(None, 1)
                args = [s.strip() for s in head[1].split(',')] if len(head) > 1 else []
                body = []
                while i < len(lines) and lines[i] != '.endm':
                    body.append(lines[i])
                    i += 1
                i += 1
                macros[head[0]] = (args, body)
            elif line and line.split()[0] in macros:
                name, *tail = line.split(None, 1)
                args, body = macros[name]
                values = [s.strip() for s in tail[0].split(',')] if tail else []
                for item in body:
                    for arg, value in zip(args, values):
                        item = item.replace('\\' + arg, value)
                    expanded.append(item)
            else:
                expanded.append(line)
        # Numeric labels are local in GAS: resolve to unique names by line index.
        flattened = []
        for line in expanded:
            flattened.extend(s.strip() for s in line.split(';') if s.strip())
        labels = {}
        for i, line in enumerate(flattened):
            m = re.match(r'^(\d+):', line)
            if m:
                labels.setdefault(m[1], []).append(i)
        for i, line in enumerate(flattened):
            line = re.sub(r'^(\d+):', lambda m: f'.Lnumeric_{m[1]}_{i}:', line)
            def numeric(m):
                candidates = [j for j in labels[m[1]] if j > i] if m[2] == 'f' else [j for j in labels[m[1]] if j <= i]
                j = min(candidates) if m[2] == 'f' else max(candidates)
                return f'.Lnumeric_{m[1]}_{j}'
            line = re.sub(r'\b(\d+)([fb])\b', numeric, line)
            try:
                self.line(line)
            except Exception as error:
                raise ValueError(f'{path.name}: {line}: {error}') from error
        for alias, original in self.aliases.items():
            self.symbols[alias] = self.symbols[original]
        # Branch displacements within a section need no linker relocation.
        for section, offset, name, kind in self.fixups:
            target_section, target = self.symbols[name]
            if section != target_section:
                raise ValueError(f'cross-section local branch {name}')
            data = self.sections[section].data
            if kind == 'x8':
                value = target - offset - 1
                data[offset:offset + 1] = pack('b', value)
            elif kind == 'rvb':
                value=target-offset
                if value&1 or not -4096<=value<4096:raise ValueError('RISC-V branch range')
                insn,=struct.unpack_from('<I',data,offset)
                insn|=((value>>11)&1)<<7|((value>>1)&15)<<8|((value>>5)&63)<<25|((value>>12)&1)<<31
                struct.pack_into('<I',data,offset,insn)
            elif kind == 'x32':
                data[offset:offset + 4] = pack('i', target - offset - 4)
            else:
                bits, shift = kind
                value = (target - offset) // 4
                if not -(1 << (bits - 1)) <= value < (1 << (bits - 1)):
                    raise ValueError('branch displacement overflow')
                instruction, = struct.unpack_from('<I', data, offset)
                struct.pack_into('<I', data, offset, instruction | ((value & ((1 << bits) - 1)) << shift))
        return self

    def line(self, line):
        if not line:
            return
        if ':' in line and re.match(r'^[\w.]+:', line):
            name, line = line.split(':', 1)
            self.symbols[name] = (self.current.name, len(self.current.data))
            line = line.strip()
            if not line:
                return
        if line.startswith('.'):
            op, *tail = line.split(None, 1)
            arg = tail[0] if tail else ''
            if op == '.section':
                self.section(arg.split(',')[0])
            elif op in ('.text', '.data', '.bss'):
                self.section(op)
            elif op in ('.global', '.globl'):
                self.globals.add(arg)
            elif op == '.weak':
                self.weak.add(arg)
            elif op in ('.hidden', '.private_extern'):
                self.hidden.add(arg)
                if op == '.private_extern':
                    self.globals.add(arg)
            elif op == '.type':
                pass
            elif op == '.option':
                if not self.rv64 or arg not in ('norelax', 'norvc'):
                    raise ValueError('unsupported assembler option ' + arg)
            elif op == '.set':
                alias, original = map(str.strip, arg.split(','))
                self.aliases[alias] = original
            elif op == '.comm':
                name, size, alignment = arg.split(',')
                old = self.current
                self.section('.bss')
                self.pad(int(alignment))
                self.symbols[name] = ('.bss', len(self.current.data))
                self.globals.add(name)
                self.emit(bytes(int(size)))
                self.current = old
            elif op == '.p2align':
                self.pad(1 << int(arg))
            elif op in ('.ascii', '.asciz'):
                self.emit(ast.literal_eval(arg).encode() + (b'\0' if op == '.asciz' else b''))
            elif op in ('.byte', '.short', '.long', '.quad'):
                width = {'.byte': 1, '.short': 2, '.long': 4, '.quad': 8}[op]
                for n in arg.split(','):
                    if width == 8 and re.fullmatch(r'[A-Za-z_.$][\w.$]*', n.strip()):
                        self.relocation(n.strip(), 'abs64')
                        self.emit(bytes(8))
                    else:
                        self.emit((int(n, 0) & ((1 << (width * 8)) - 1)).to_bytes(width, 'little'))
            elif op == '.rva':
                self.relocation(arg, 'rva')
                self.word(0)
            else:
                raise ValueError(f'unsupported directive {op}')
            return
        if self.rv64:
            self.riscv(line)
        elif self.a64:
            self.arm(line)
        else:
            self.x86(line)

    def pad(self, alignment):
        self.current.alignment = max(self.current.alignment, alignment)
        self.emit(bytes(align(len(self.current.data), alignment) - len(self.current.data)))

    def branch(self, name, kind):
        self.fixups.append((self.current.name, len(self.current.data), name, kind))

    @staticmethod
    def operands(text):
        return [s.strip() for s in re.split(r',(?![^()\[]*[)\]])', text)]

    @staticmethod
    def reg(text):
        text = text.lstrip('%')
        groups = [('rax rcx rdx rbx rsp rbp rsi rdi'.split(), 64),
                  ('eax ecx edx ebx esp ebp esi edi'.split(), 32),
                  ('al cl dl bl spl bpl sil dil'.split(), 8)]
        for regs, width in groups:
            if text in regs:
                return regs.index(text), width
        m = re.fullmatch(r'r(\d+)([dbw]?)', text)
        if m:
            return int(m[1]), {'': 64, 'd': 32, 'b': 8, 'w': 16}[m[2]]
        if text.startswith('xmm'):
            return int(text[3:]), 128
        raise ValueError('unknown register ' + text)

    def modrm(self, opcode, register, operand, width=64, prefix=b''):
        # Reg field is either a physical register or a fixed opcode extension.
        rex = (8 if width == 64 else 0) | (4 if register >= 8 else 0)
        reloc = None
        if operand.startswith('%'):
            rm, _ = self.reg(operand)
            rex |= rm >> 3
            body = bytes([0xc0 | ((register & 7) << 3) | (rm & 7)])
        else:
            m = re.fullmatch(r'(.*?)\((.*?)\)', operand)
            if not m:
                raise ValueError('unsupported memory ' + operand)
            displacement, parts = m[1], m[2].split(',')
            if parts[0] == '%rip':
                body = bytes([((register & 7) << 3) | 5]) + bytes(4)
                reloc = (displacement, len(body) - 4)
            else:
                base = self.reg(parts[0])[0] if parts[0] else None
                index = self.reg(parts[1])[0] if len(parts) > 1 and parts[1] else None
                scale = int(parts[2]) if len(parts) > 2 else 1
                disp = int(displacement, 0) if displacement else 0
                mode = 0 if disp == 0 and base is not None and base & 7 != 5 else 1 if -128 <= disp < 128 else 2
                if base is None:
                    mode = 0
                rex |= ((base or 0) >> 3) | (2 if index is not None and index >= 8 else 0)
                sib = base is None or base & 7 == 4 or index is not None
                body = bytes([(mode << 6) | ((register & 7) << 3) | (4 if sib else base & 7)])
                if sib:
                    body += bytes([({1: 0, 2: 1, 4: 2, 8: 3}[scale] << 6) | ((index & 7 if index is not None else 4) << 3) | (base & 7 if base is not None else 5)])
                if base is None or mode == 2:
                    body += pack('i', disp)
                elif mode == 1:
                    body += pack('b', disp)
        prefix += bytes([0x40 | rex]) if rex else b''
        start = len(self.current.data)
        self.emit(prefix + opcode + body)
        if reloc:
            name, at = reloc
            kind = 'got' if name.endswith('@GOTPCREL') else 'pc32'
            name = name.removesuffix('@GOTPCREL')
            self.relocation(name, kind, -4, start + len(prefix) + len(opcode) + at)

    def x86(self, line):
        lock = line.startswith('lock ')
        if lock:
            line = line[5:]
        op, *tail = line.split(None, 1)
        args = self.operands(tail[0]) if tail else []
        if line in ('rep movsb', 'rep stosb'):
            self.emit(b'\xf3\xa4' if line == 'rep movsb' else b'\xf3\xaa'); return
        fixed = {'syscall': b'\x0f\x05', 'ud2': b'\x0f\x0b', 'ret': b'\xc3', 'retq': b'\xc3'}
        if op in fixed:
            self.emit(fixed[op]); return
        suffix = op[-1] if op[-1] in 'qlb' else ''
        base = op[:-1] if suffix and op not in ('call', 'shl', 'sub') else op
        if base in ('call', 'jmp'):
            if args[0].startswith('*'):
                self.modrm(b'\xff', 2 if base == 'call' else 4, args[0][1:], 32)
            else:
                self.emit(b'\xe8' if base == 'call' else b'\xe9')
                self.relocation(args[0], 'call', -4)
                self.word(0)
            return
        conditions = {'je': 4, 'jz': 4, 'jne': 5, 'jnz': 5, 'jb': 2, 'jae': 3, 'jbe': 6, 'ja': 7}
        if op in conditions:
            self.emit(bytes([0x0f, 0x80 | conditions[op]]))
            self.branch(args[0], 'x32'); self.word(0); return
        if op == 'loop':
            self.emit(b'\xe2'); self.branch(args[0], 'x8'); self.emit(b'\0'); return
        if base in ('push', 'pop'):
            r, _ = self.reg(args[0])
            self.emit((b'\x41' if r >= 8 else b'') + bytes([(0x50 if base == 'push' else 0x58) + (r & 7)])); return
        if op == 'sete':
            self.modrm(b'\x0f\x94', 0, args[0], 8); return
        if op == 'movzbl':
            r, _ = self.reg(args[1]); self.modrm(b'\x0f\xb6', r, args[0], 32); return
        if op == 'movdqu':
            source_reg = args[0].startswith('%xmm')
            r, _ = self.reg(args[0] if source_reg else args[1])
            self.modrm(b'\x0f\x7f' if source_reg else b'\x0f\x6f', r, args[1] if source_reg else args[0], 32, b'\xf3'); return
        if op in ('stmxcsr', 'ldmxcsr', 'fnstcw', 'fldcw'):
            instruction, extension = {'stmxcsr': (b'\x0f\xae', 3), 'ldmxcsr': (b'\x0f\xae', 2), 'fnstcw': (b'\xd9', 7), 'fldcw': (b'\xd9', 5)}[op]
            self.modrm(instruction, extension, args[0], 32); return
        width = {'q': 64, 'l': 32, 'b': 8}.get(suffix) if base != op else None
        if width is None:
            width = next((self.reg(arg)[1] for arg in args if arg.startswith('%')), 64)
        prefix = b'\xf0' if lock else b''
        if base == 'neg':
            self.modrm(b'\xf7', 3, args[0], width); return
        if base in ('inc', 'dec'):
            self.modrm(b'\xff', 0 if base == 'inc' else 1, args[0], width); return
        if base == 'shl':
            self.modrm(b'\xc1', 4, args[1], width); self.emit(bytes([int(args[0][1:], 0)])); return
        if base == 'lea':
            r, _ = self.reg(args[1]); self.modrm(b'\x8d', r, args[0], width); return
        if base in ('cmova',):
            r, _ = self.reg(args[1]); self.modrm(b'\x0f\x47', r, args[0], width); return
        if args[0].startswith('$'):
            value = int(args[0][1:], 0)
            if base == 'mov' and args[1].startswith('%') and width != 8:
                r, _ = self.reg(args[1])
                if width == 64 and not -(1 << 31) <= value < (1 << 31):
                    self.emit(bytes([0x48 | (r >> 3), 0xb8 | (r & 7)]) + pack('Q', value)); return
                if width == 32:
                    self.emit((b'\x41' if r >= 8 else b'') + bytes([0xb8 | (r & 7)]) + pack('I', value & 0xffffffff)); return
            extensions = {'mov': 0, 'add': 0, 'and': 4, 'sub': 5, 'xor': 6, 'cmp': 7, 'test': 0}
            extension = extensions[base]
            instruction = 0xc6 if base == 'mov' else 0xf6 if base == 'test' else 0x80
            if width != 8:
                instruction += 1
            self.modrm(bytes([instruction]), extension, args[1], width, prefix)
            self.emit((value & ((1 << (8 if width == 8 else 32)) - 1)).to_bytes(1 if width == 8 else 4, 'little')); return
        if base in ('xadd', 'cmpxchg'):
            r, _ = self.reg(args[0]); self.modrm(b'\x0f' + bytes([0xc1 if base == 'xadd' else 0xb1]), r, args[1], width, prefix); return
        opcodes = {'mov': (0x88, 0x8a), 'add': (0x00, 0x02), 'sub': (0x28, 0x2a), 'cmp': (0x38, 0x3a), 'xor': (0x30, 0x32), 'test': (0x84, None), 'xchg': (0x86, None)}
        if base not in opcodes:
            raise ValueError('unsupported x86 instruction ' + op)
        store = args[0].startswith('%')
        r, _ = self.reg(args[0] if store else args[1])
        opcode = opcodes[base][0 if store else 1]
        self.modrm(bytes([opcode + (width != 8)]), r, args[1] if store else args[0], width, prefix)

    @staticmethod
    def ar(text):
        if text in ('sp', 'xzr', 'wzr'):
            return 31
        return int(text[1:])

    def arm(self, line):
        op, *tail = line.split(None, 1)
        a = self.operands(tail[0]) if tail else []
        r = self.ar
        number = lambda s: int(s.lstrip('#'), 0)
        if op == 'ret': self.word(0xd65f03c0); return
        if op == 'clrex': self.word(0xd5033f5f); return
        if op in ('svc', 'brk'):
            self.word((0xd4000001 if op == 'svc' else 0xd4200000) | (number(a[0]) << 5)); return
        if op in ('b', 'bl'):
            self.relocation(a[0], 'jump26' if op == 'b' else 'call26')
            self.word(0x14000000 if op == 'b' else 0x94000000); return
        if op == 'blr': self.word(0xd63f0000 | (r(a[0]) << 5)); return
        if op.startswith('b.'):
            condition = {'eq': 0, 'ne': 1, 'cs': 2, 'cc': 3, 'ls': 9}[op[2:]]
            self.branch(a[0], (19, 5)); self.word(0x54000000 | condition); return
        if op in ('br','blr'):
            self.word((0xd61f0000 if op == 'br' else 0xd63f0000) | r(a[0]) << 5); return
        if op in ('cbz', 'cbnz'):
            self.branch(a[1], (19, 5)); self.word((0xb4000000 if a[0][0] == 'x' else 0x34000000) | (0x1000000 if op == 'cbnz' else 0) | r(a[0])); return
        if op == 'adrp':
            symbol = a[1].removeprefix(':got:')
            self.relocation(symbol, 'gotpage' if a[1].startswith(':got:') else 'page')
            self.word(0x90000000 | r(a[0])); return
        wide = a and (a[0].startswith('x') or a[0] == 'sp')
        sf = 0x80000000 if wide else 0
        if op == 'mov':
            if a[1].startswith('#'):
                self.word(sf | 0x52800000 | (number(a[1]) << 5) | r(a[0]))
            elif 'sp' in a:
                self.word(sf | 0x11000000 | (r(a[1]) << 5) | r(a[0]))
            else:
                self.word(sf | 0x2a0003e0 | (r(a[1]) << 16) | r(a[0]))
            return
        if op == 'movk':
            shift = number(a[2].split()[1]) if len(a) > 2 else 0
            self.word(sf | 0x72800000 | ((shift // 16) << 21) | (number(a[1]) << 5) | r(a[0])); return
        if op in ('add', 'sub', 'cmp', 'neg'):
            if op == 'cmp':
                a = ['xzr' if wide else 'wzr', *a]
            if op == 'neg':
                a = [a[0], 'xzr' if wide else 'wzr', a[1]]
            subtract = op in ('sub', 'cmp', 'neg')
            base = sf | (0x40000000 if subtract else 0) | (0x20000000 if op == 'cmp' else 0)
            if a[2].startswith('#') or a[2].startswith(':lo12:'):
                value = 0 if a[2].startswith(':lo12:') else number(a[2])
                if a[2].startswith(':lo12:'):
                    self.relocation(a[2][6:], 'lo12')
                self.word(base | 0x11000000 | (value << 10) | (r(a[1]) << 5) | r(a[0]))
            else:
                self.word(base | 0x0b000000 | (r(a[2]) << 16) | (r(a[1]) << 5) | r(a[0]))
            return
        if op == 'orr':
            shift = number(a[3].split()[1]) if len(a) == 4 else 0
            self.word(sf | 0x2a000000 | (r(a[2]) << 16) | (shift << 10) | (r(a[1]) << 5) | r(a[0])); return
        if op == 'and' and a[2] == '#255':
            self.word((0x92401c00 if wide else 0x12001c00) | (r(a[1]) << 5) | r(a[0])); return
        if op == 'and' and a[2] == '#-16':
            self.word(0x927cec00 | (r(a[1]) << 5) | r(a[0])); return
        if op in ('stp', 'ldp'):
            pre = a[2].endswith('!')
            post = len(a) == 4
            mem = a[2].strip('[]!').split(',')
            base_reg = r(mem[0].strip())
            disp = number(a[3]) if post else number(mem[1].strip()) if len(mem) > 1 else 0
            floating = a[0].startswith('d')
            base = 0x6d000000 if floating else 0xa9000000
            if op == 'ldp': base |= 0x400000
            if pre: base |= 0x800000
            if post: base -= 0x800000
            self.word(base | (((disp // 8) & 127) << 15) | (r(a[1]) << 10) | (base_reg << 5) | r(a[0])); return
        if op in ('ldr', 'ldrb', 'str', 'strb', 'ldar', 'stlr', 'ldaxr', 'stlxr'):
            mem = a[-1].strip('[]').split(',')
            base_reg = r(mem[0].strip())
            if op in ('ldar', 'stlr', 'ldaxr', 'stlxr'):
                bases = {'ldar': 0x88dffc00, 'stlr': 0x889ffc00, 'ldaxr': 0x885ffc00, 'stlxr': 0x8800fc00}
                data_reg = a[1] if op == 'stlxr' else a[0]
                word = bases[op] | (0x40000000 if data_reg.startswith('x') else 0) | (base_reg << 5) | r(data_reg)
                if op == 'stlxr': word |= r(a[0]) << 16
                self.word(word); return
            disp = mem[1].strip() if len(mem) > 1 else '#0'
            byte = op in ('strb', 'ldrb')
            if disp.startswith(':got_lo12:'):
                self.relocation(disp[10:], 'gotlo12'); value = 0
            elif disp.startswith(':lo12:'):
                self.relocation(disp[6:], 'loadlo12'); value = 0
            else:
                value = number(disp)
            size = 1 if byte else 8 if wide else 4
            base = 0x39000000 if byte else 0xf9000000 if wide else 0xb9000000
            if op in ('ldr', 'ldrb'): base |= 0x400000
            self.word(base | ((value // size) << 10) | (base_reg << 5) | r(a[0])); return
        raise ValueError('unsupported AArch64 instruction ' + line)

    def symbol_names(self):
        referenced = {name for section in self.sections.values() for _, name, _, _ in section.relocs}
        all_names = self.symbols.keys() | referenced | self.globals | self.weak
        local = sorted(n for n in all_names if n in self.symbols and n not in self.globals and n not in self.weak)
        external = sorted(all_names - set(local))
        return local, external

    @staticmethod
    def rr(text):
        names = {'zero':0,'ra':1,'sp':2,'gp':3,'tp':4,'t0':5,'t1':6,'t2':7,
                 'fp':8,'s0':8,'s1':9,'t3':28,'t4':29,'t5':30,'t6':31}
        if text in names: return names[text]
        if text.startswith('a'): return 10+int(text[1:])
        if text.startswith('s'): return 16+int(text[1:])
        if text.startswith('fs'): return 8+int(text[2:]) if int(text[2:])<2 else 16+int(text[2:])
        if text.startswith(('x','f')): return int(text[1:])
        raise ValueError('unknown RISC-V register '+text)

    def riscv(self, line):
        op,*tail=line.split(None,1)
        a=self.operands(tail[0]) if tail else []
        r=self.rr
        def i(rd,rs,n,f3=0,opcode=0x13): self.word(opcode|rd<<7|f3<<12|rs<<15|(n&4095)<<20)
        def rr(rd,rs,rt,f3=0,f7=0,opcode=0x33): self.word(opcode|rd<<7|f3<<12|rs<<15|rt<<20|f7<<25)
        def li(rd,n):
            n &= (1<<64)-1
            signed=n if n<(1<<63) else n-(1<<64)
            if -2048<=signed<=2047: i(rd,0,signed); return
            lo=(n&4095);lo=lo if lo<2048 else lo-4096
            li(rd,((n-lo)&((1<<64)-1))>>12);i(rd,rd,12,1)
            if lo:i(rd,rd,lo)
        if op=='li':li(r(a[0]),int(a[1],0));return
        if op=='mv':i(r(a[0]),r(a[1]),0);return
        if op in ('ret','jr','jalr'):
            i(0 if op!='jalr' else 1,1 if op=='ret' else r(a[0]),0,0,0x67);return
        if op in ('call','j','tail'):
            rd=1 if op=='call' else 5
            self.relocation(a[0],'rvcall');self.word(rd<<7|0x17);i(1 if op=='call' else 0,rd,0,0,0x67);return
        if op in ('la','lga'):
            anchor=f'.Lrv_anchor_{len(self.symbols)}';at=len(self.current.data)
            self.symbols[anchor]=(self.current.name,at)
            self.relocation(a[1],'rvgot' if op=='lga' else 'rvhi');self.word(r(a[0])<<7|0x17)
            self.relocation(anchor,'rvlo');i(r(a[0]),r(a[0]),0,3 if op=='lga' else 0,3 if op=='lga' else 0x13);return
        if op in ('beq','bne','bltu','bgeu','blt','bge'):
            f3={'beq':0,'bne':1,'blt':4,'bge':5,'bltu':6,'bgeu':7}[op]
            self.branch(a[2],'rvb');self.word(0x63|f3<<12|r(a[0])<<15|r(a[1])<<20);return
        if op in ('addi','andi','xori','slli','srli','srai'):
            n=int(a[2],0);f3={'addi':0,'andi':7,'xori':4,'slli':1,'srli':5,'srai':5}[op]
            i(r(a[0]),r(a[1]),n+(0x400 if op=='srai' else 0),f3);return
        if op in ('add','sub','xor','or','and','sltu'):
            rr(r(a[0]),r(a[1]),r(a[2]),{'add':0,'sub':0,'xor':4,'or':6,'and':7,'sltu':3}[op],32 if op=='sub' else 0);return
        if op in ('ld','lw','lwu','lbu','sd','sw','sb','fld','fsd'):
            m=re.fullmatch(r'(-?\d+)\((\w+)\)',a[1]);n=int(m[1]);base=r(m[2]);reg=r(a[0]);store=op in ('sd','sw','sb','fsd')
            f3={'ld':3,'lw':2,'lwu':6,'lbu':4,'sd':3,'sw':2,'sb':0,'fld':3,'fsd':3}[op]
            if store:self.word((0x27 if op=='fsd' else 0x23)|(n&31)<<7|f3<<12|base<<15|reg<<20|((n&4095)>>5)<<25)
            else:i(reg,base,n,f3,7 if op=='fld' else 3)
            return
        if op=='ecall':self.word(0x73);return
        if op=='ebreak':self.word(0x100073);return
        if op=='fence':self.word(0x0330000f);return
        if op.startswith(('amo','lr.','sc.')):
            parts=op.split('.');baseop=parts[0];width=parts[1];aq='aq' in parts or 'aqrl' in parts;rl='rl' in parts or 'aqrl' in parts
            rd=r(a[0]);rs2=0 if baseop=='lr' else r(a[1]);memory=a[1] if baseop=='lr' else a[2];rs1=r(memory.strip('()'))
            f5={'amoswap':1,'amoadd':0,'lr':2,'sc':3}[baseop]
            self.word(0x2f|rd<<7|(2 if width=='w' else 3)<<12|rs1<<15|rs2<<20|int(rl)<<25|int(aq)<<26|f5<<27);return
        raise ValueError('unsupported RISC-V instruction '+line)

    def elf(self):
        sections = list(self.sections.values())
        ids = {s.name: i + 1 for i, s in enumerate(sections)}
        local, external = self.symbol_names()
        names = local + external
        symids = {name: i + 1 for i, name in enumerate(names)}
        strings = bytearray(b'\0')
        symtab = bytearray(24)
        for name in names:
            at = len(strings); strings.extend(name.encode() + b'\0')
            sec, offset = self.symbols.get(name, (None, 0))
            binding = 0 if name in local else 2 if name in self.weak else 1
            kind = 2 if sec and sec.startswith('.text') else 1 if sec else 0
            symtab.extend(pack('IBBHQQ', at, binding << 4 | kind, 2 if name in self.hidden else 0, ids.get(sec, 0), offset, 0))
        # name, type, flags, data, link, info, alignment, entry size
        records = []
        for section in sections:
            executable = section.name.startswith('.text')
            writable = section.name.startswith(('.data', '.bss'))
            flags = 0 if section.name == '.note.GNU-stack' else 2 | (4 if executable else 0) | (1 if writable else 0)
            records.append([section.name, 1, flags, section.data, 0, 0, max(section.alignment, 4 if executable and (self.a64 or self.rv64) else 1), 0])
        symtab_id = len(sections) + 1 + sum(bool(s.relocs) for s in sections)
        for section in sections:
            if not section.relocs: continue
            data = bytearray()
            kinds = {'abs64': 1, 'pc32': 2, 'call': 4, 'got': 9} if not self.a64 else {'abs64': 257, 'call26': 283, 'jump26': 282, 'page': 275, 'lo12': 277, 'gotpage': 311, 'gotlo12': 312}
            if self.rv64: kinds = {'abs64':2,'rvcall':19,'rvgot':20,'rvhi':23,'rvlo':24}
            for offset, name, kind, addend in section.relocs:
                data.extend(pack('QQq', offset, (symids[name] << 32) | kinds[kind], addend))
            records.append(['.rela' + section.name, 4, 0, data, symtab_id, ids[section.name], 8, 24])
        records.append(['.symtab', 2, 0, symtab, symtab_id + 1, len(local) + 1, 8, 24])
        records.append(['.strtab', 3, 0, strings, 0, 0, 1, 0])
        shstr = bytearray(b'\0'); shnames = []
        for record in records:
            shnames.append(len(shstr)); shstr.extend(record[0].encode() + b'\0')
        shnames.append(len(shstr)); shstr.extend(b'.shstrtab\0')
        records.append(['.shstrtab', 3, 0, shstr, 0, 0, 1, 0])
        data = bytearray(64)
        headers = bytearray(64)
        for name_offset, record in zip(shnames, records):
            _, kind, flags, content, link, info, alignment, entsize = record
            data.extend(bytes(align(len(data), alignment) - len(data)))
            offset = len(data); data.extend(content)
            headers.extend(pack('IIQQQQIIQQ', name_offset, kind, flags, 0, offset, len(content), link, info, alignment, entsize))
        data.extend(bytes(align(len(data), 8) - len(data)))
        shoff = len(data); data.extend(headers)
        data[:64] = pack('16sHHIQQQIHHHHHH', b'\x7fELF\x02\x01\x01' + bytes(9), 1, 243 if self.rv64 else 183 if self.a64 else 62, 1, 0, 0, shoff, 4 if self.rv64 else 0, 64, 0, 0, 64, len(records) + 1, len(records))
        return data

    def pe(self):
        sections = list(self.sections.values())
        ids = {s.name: i + 1 for i, s in enumerate(sections)}
        local, external = self.symbol_names(); names = local + external
        symids = {name: i for i, name in enumerate(names)}
        strings = bytearray(4)
        def string(name):
            at = len(strings); strings.extend(name.encode() + b'\0'); return at
        def symbol_name(name):
            return name.encode().ljust(8, b'\0') if len(name) <= 8 else pack('II', 0, string(name))
        data = bytearray(20 + 40 * len(sections))
        headers = []
        for section in sections:
            data.extend(bytes(align(len(data), 4) - len(data)))
            offset = len(data)
            contents = bytearray(section.data)
            relocs = bytearray()
            for at, name, kind, addend in section.relocs:
                if self.a64:
                    reloc_kind = {'rva': 2, 'call26': 3, 'jump26': 3, 'page': 4, 'lo12': 6, 'loadlo12': 7, 'abs64': 14}.get(kind)
                else:
                    reloc_kind = 3 if kind == 'rva' else 4 if kind in ('pc32', 'call') else None
                if reloc_kind is None: raise ValueError('COFF relocation ' + kind)
                if not self.a64 or kind in ('rva','abs64'):
                    struct.pack_into('<q' if kind == 'abs64' else '<i', contents, at, addend + (4 if not self.a64 and reloc_kind == 4 else 0))
                elif addend:
                    raise ValueError('ARM64 runtime relocation addend')
                relocs.extend(pack('IIH', at, symids[name], reloc_kind))
            data.extend(contents)
            rel_offset = len(data); data.extend(relocs)
            code = section.name.startswith('.text')
            readonly = section.name.startswith('.rdata')
            characteristics = (0x60000020 if code else 0x40000040 if readonly else 0xc0000040)
            characteristics |= (max(1, section.alignment).bit_length() << 20)
            name = section.name.encode().ljust(8, b'\0') if len(section.name) <= 8 else ('/' + str(string(section.name))).encode().ljust(8, b'\0')
            headers.append(pack('8sIIIIIIHHI', name, 0, 0, len(contents), offset, rel_offset if relocs else 0, 0, len(section.relocs), 0, characteristics))
        symbol_offset = len(data)
        for name in names:
            section, offset = self.symbols.get(name, (None, 0))
            data.extend(pack('8sIhHBB', symbol_name(name), offset, ids.get(section, 0), 0x20 if section and section.startswith('.text') else 0, 3 if name in local else 2, 0))
        struct.pack_into('<I', strings, 0, len(strings))
        data.extend(strings)
        data[:20] = pack('HHIIIHH', 0xaa64 if self.a64 else 0x8664, len(sections), 0, symbol_offset, len(names), 0, 0)
        data[20:20 + 40 * len(sections)] = b''.join(headers)
        return data

    def mach(self):
        sections = list(self.sections.values())
        ids = {s.name: i + 1 for i, s in enumerate(sections)}
        local, external = self.symbol_names(); names = local + external
        symids = {name: i for i, name in enumerate(names)}
        segment_size = 72 + 80 * len(sections)
        command_size = segment_size + 24
        data = bytearray(32 + command_size)
        addresses = {}; address = 0
        offsets = {}
        for section in sections:
            alignment = max(section.alignment, 4)
            address = align(address, alignment)
            addresses[section.name] = address
            address += len(section.data)
            data.extend(bytes(align(len(data), alignment) - len(data)))
            offsets[section.name] = len(data)
            data.extend(section.data)
        reloc_offsets = {}
        for section in sections:
            data.extend(bytes(align(len(data), 4) - len(data)))
            reloc_offsets[section.name] = len(data)
            for at, name, kind, addend in reversed(section.relocs):
                if self.a64 and addend: raise ValueError('Mach-O nonzero addend')
                types = {'call26': 2, 'jump26': 2, 'page': 3, 'lo12': 4, 'gotpage': 5, 'gotlo12': 6}
                if not self.a64:
                    types = {'call': 2, 'pc32': 1, 'got': 3, 'abs64': 0}
                    width = 8 if kind == 'abs64' else 4
                    value = addend + (0 if width == 8 else 4)
                    data[offsets[section.name]+at:offsets[section.name]+at+width] = (value & ((1 << (width*8))-1)).to_bytes(width, 'little')
                relative = kind in ('call26', 'jump26', 'page', 'gotpage', 'call', 'pc32', 'got')
                bits = symids[name] | (int(relative) << 24) | ((3 if kind == 'abs64' else 2) << 25) | (1 << 27) | (types[kind] << 28)
                data.extend(pack('II', at, bits))
        data.extend(bytes(align(len(data), 8) - len(data)))
        symbol_offset = len(data)
        strings = bytearray(b'\0')
        for name in names:
            at = len(strings); strings.extend(name.encode() + b'\0')
            section, offset = self.symbols.get(name, (None, 0))
            data.extend(pack('IBBHQ', at, (0x0e if section else 0) | (0 if name in local else 1) | (0x10 if name in self.hidden else 0), ids.get(section, 0), 0, addresses.get(section, 0) + offset))
        string_offset = len(data); data.extend(strings)
        data[:32] = pack('IIIIIIII', 0xfeedfacf, 0x100000c if self.a64 else 0x1000007, 0 if self.a64 else 3, 1, 2, command_size, 0, 0)
        file_offset = min(offsets.values())
        file_end = max(offsets[s.name] + len(s.data) for s in sections)
        data[32:104] = pack('II16sQQQQIIII', 0x19, segment_size, bytes(16), 0, address, file_offset, file_end - file_offset, 7, 7, len(sections), 0)
        for i, section in enumerate(sections):
            code = section.name.startswith('.text')
            name = b'__text' if code else b'__data' if section.name.startswith(('.data', '.bss')) else b'__const'
            segment = b'__TEXT' if code or name == b'__const' else b'__DATA'
            at = 104 + i * 80
            data[at:at + 80] = pack('16s16sQQIIIIIIII', name, segment, addresses[section.name], len(section.data), offsets[section.name], max(section.alignment, 4).bit_length() - 1, reloc_offsets[section.name], len(section.relocs), 0x80000400 if code else 0, 0, 0, 0)
        at = 32 + segment_size
        data[at:at + 24] = pack('IIIIII', 2, 24, symbol_offset, len(names), string_offset, len(strings))
        return data

    def object(self):
        return self.pe() if self.coff else self.mach() if self.macho else self.elf()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    name = args.output.name
    valid = {'dynrt_start.o', 'dynrt_release.o', 'dynrt_shared.o',
             'dynrt_aarch64_start.o', 'dynrt_aarch64_release.o', 'dynrt_aarch64_shared.o',
             'dynrt_windows_start.o', 'dynrt_windows_shared.o',
             'dynrt_macos_start.o', 'dynrt_macos_shared.o',
             'dynrt_macos_x64_start.o', 'dynrt_macos_x64_shared.o',
             'dynrt_windows_arm64_start.o', 'dynrt_windows_arm64_shared.o',
             'dynrt_riscv64_start.o', 'dynrt_riscv64_release.o', 'dynrt_riscv64_shared.o'}
    if name not in valid:
        parser.error('unknown startup runtime output: ' + name)
    if 'riscv64' in name:
        target, source = 'riscv64-linux', 'linux_riscv64_start.S'
    elif 'windows_arm64' in name:
        target, source = 'aarch64-windows', 'windows_aarch64_start.S'
    elif 'macos_x64' in name:
        target, source = 'x86_64-macos', 'macos_x86_64_start.S'
    elif 'aarch64' in name:
        target, source = 'aarch64-linux', 'linux_aarch64_start.S'
    elif 'windows' in name:
        target, source = 'x86_64-windows', 'windows_x86_64_start.S'
    elif 'macos' in name:
        target, source = 'aarch64-macos', 'macos_aarch64_start.S'
    else:
        target, source = 'x86_64-linux', 'linux_x86_64_start.S'
    defines = {'__ELF__'} if target.endswith('linux') else set()
    if 'release' in name or ('shared' in name and target != 'x86_64-linux'):
        defines.add('DYN_RELEASE')
    if 'shared' in name:
        defines.add('DYN_SHARED')
    assembler = Assembler(target).assemble(ROOT / 'runtime' / source, defines)
    assembler.assemble(ROOT / 'runtime' / ('native_memory_riscv64.S' if assembler.rv64 else 'native_memory_aarch64.S' if assembler.a64 else 'native_memory_x86_64.S'), defines | ({'DYN_WINDOWS'} if assembler.coff else set()) | ({'DYN_MACOS'} if assembler.macho else set()))
    if assembler.coff and not assembler.a64:
        assembler.assemble(ROOT / 'runtime/native_windows_imports.S')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix('.tmp')
    temporary.write_bytes(assembler.object())
    temporary.replace(args.output)


if __name__ == '__main__':
    main()
