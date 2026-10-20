/* Small, fail-closed decoder for the instruction subset emitted by Dyn.
 * It is used only to annotate exact-encoding assembly; it never changes code.
 */
#ifndef DYN_NATIVE_DECODE_H
#define DYN_NATIVE_DECODE_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static uint64_t nd_read(const unsigned char *p, unsigned n) {
  uint64_t x = 0;
  for (unsigned i = 0; i < n; ++i)
    x |= (uint64_t)p[i] << (8 * i);
  return x;
}
static const char *nd_reg(unsigned n, unsigned bits) {
  static const char *const q[] = {"rax", "rcx", "rdx", "rbx", "rsp", "rbp",
                                  "rsi", "rdi", "r8",  "r9",  "r10", "r11",
                                  "r12", "r13", "r14", "r15"};
  static const char *const d[] = {"eax",  "ecx",  "edx",  "ebx", "esp",  "ebp",
                                  "esi",  "edi",  "r8d",  "r9d", "r10d", "r11d",
                                  "r12d", "r13d", "r14d", "r15d"};
  static const char *const w[] = {"ax",   "cx",   "dx",   "bx",  "sp",   "bp",
                                  "si",   "di",   "r8w",  "r9w", "r10w", "r11w",
                                  "r12w", "r13w", "r14w", "r15w"};
  static const char *const b[] = {"al",   "cl",   "dl",   "bl",  "spl",  "bpl",
                                  "sil",  "dil",  "r8b",  "r9b", "r10b", "r11b",
                                  "r12b", "r13b", "r14b", "r15b"};
  return (bits == 64 ? q : bits == 32 ? d : bits == 16 ? w : b)[n & 15];
}
static const char *nd_byte_reg(unsigned n, unsigned bits, unsigned rex) {
  static const char *const high[] = {"ah", "ch", "dh", "bh"};
  return bits == 8 && !rex && n >= 4 && n < 8 ? high[n - 4] : nd_reg(n, bits);
}
static size_t nd_x64(const unsigned char *p, size_t n, char *out, size_t cap) {
  size_t i = 0;
  unsigned rex = 0, prefix = 0;
  bool word16 = false;
  while (i < n) {
    unsigned c = p[i];
    if (c == 0x66) {
      if (rex)
        return 0;
      word16 = true;
      ++i;
    } else if (c == 0xf2 || c == 0xf3 || c == 0xf0) {
      if (rex)
        return 0;
      prefix = c;
      ++i;
    } else if (c >= 0x40 && c <= 0x4f) {
      rex = c;
      ++i;
    } else
      break;
  }
  if (i >= n || prefix == 0xf0 || i >= 15)
    return 0;
  unsigned op = p[i++], bits = rex & 8 ? 64 : word16 ? 16 : 32, imm = 0;
  const char *name = NULL;
  if (prefix && op != 0x0f && op != 0xa4 && op != 0xaa)
    return 0;
  if (op == 0xc4 && !rex && !prefix && !word16 && n - i >= 4) {
    unsigned v2 = p[i], v3 = p[i + 1], modrm = p[i + 3];
    if ((v2 & 31) != 2 || p[i + 2] != 0xf7 || (v3 & 4) || (modrm >> 6) != 3 ||
        !(v3 & 3))
      return 0;
    unsigned dest = ((modrm >> 3) & 7) + ((v2 & 0x80) ? 0 : 8);
    unsigned source = (modrm & 7) + ((v2 & 0x20) ? 0 : 8);
    unsigned count = (~v3 >> 3) & 15, width = v3 & 0x80 ? 64 : 32;
    snprintf(out, cap, "%s %s, %s, %s",
             (v3 & 3) == 1   ? "shlx"
             : (v3 & 3) == 2 ? "sarx"
                             : "shrx",
             nd_reg(dest, width), nd_reg(source, width), nd_reg(count, width));
    return i + 4;
  }
  if (op >= 0x50 && op <= 0x5f) {
    snprintf(out, cap, "%s %s", op < 0x58 ? "push" : "pop",
             nd_reg((op & 7) + ((rex & 1) ? 8 : 0), 64));
    return i;
  }
  if (op >= 0xb8 && op <= 0xbf) {
    imm = bits / 8;
    if (n - i < imm)
      return 0;
    snprintf(out, cap, "mov %s, 0x%llx",
             nd_reg((op & 7) + ((rex & 1) ? 8 : 0), bits),
             (unsigned long long)nd_read(p + i, imm));
    return i + imm;
  }
  if (op == 0xc3 || op == 0xc9 || op == 0x90 || op == 0xcc || op == 0xfc ||
      op == 0xfd || op == 0x99) {
    snprintf(out, cap, "%s",
             op == 0xc3   ? "ret"
             : op == 0xc9 ? "leave"
             : op == 0x90 ? "nop"
             : op == 0xcc ? "int3"
             : op == 0xfc ? "cld"
             : op == 0xfd ? "std"
             : bits == 64 ? "cqo"
                          : "cdq");
    return i;
  }
  if (op == 0xa4 || op == 0xaa) {
    if (prefix && prefix != 0xf3) return 0;
    snprintf(out, cap, "%s%s", prefix == 0xf3 ? "rep " : "",
             op == 0xa4 ? "movsb" : "stosb");
    return i;
  }
  static const char *const conditions[] = {"o",  "no", "b",  "ae", "e", "ne",
                                           "be", "a",  "s",  "ns", "p", "np",
                                           "l",  "ge", "le", "g"};
  if (op == 0xe8 || op == 0xe9 || op == 0xeb || (op >= 0x70 && op <= 0x7f)) {
    imm = (op == 0xe8 || op == 0xe9) ? 4 : 1;
    if (n - i < imm)
      return 0;
    int64_t disp = imm == 4 ? (int32_t)nd_read(p + i, 4) : (int8_t)p[i];
    if (op >= 0x70 && op <= 0x7f)
      snprintf(out, cap, "j%s .%+lld", conditions[op & 15],
               (long long)(disp + i + imm));
    else
      snprintf(out, cap, "%s .%+lld", op == 0xe8 ? "call" : "jmp",
               (long long)(disp + i + imm));
    return i + imm;
  }
  bool two = false, reverse = false, xmm = false;
  unsigned source_bits = bits;
  if (op == 0x0f) {
    if (i >= n)
      return 0;
    op = p[i++];
    two = true;
    if (op == 0x05 || op == 0x0b) {
      snprintf(out, cap, "%s", op == 5 ? "syscall" : "ud2");
      return i;
    }
    if (op >= 0x80 && op <= 0x8f) {
      if (n - i < 4)
        return 0;
      snprintf(out, cap, "j%s .%+lld", conditions[op & 15],
               (long long)((int32_t)nd_read(p + i, 4) + i + 4));
      return i + 4;
    }
    if (op >= 0x90 && op <= 0x9f) {
      name = "set";
      source_bits = 8;
    } else if (op == 0xb6 || op == 0xb7 || op == 0xbe || op == 0xbf) {
      name = op < 0xbe ? "movzx" : "movsx";
      source_bits = (op & 1) ? 16 : 8;
      reverse = true;
    } else if (op == 0xaf) {
      name = "imul";
      reverse = true;
    } else if (op == 0x10 || op == 0x11 || op == 0x58 || op == 0x59 ||
               op == 0x5c || op == 0x5e || op == 0x2e || op == 0x6e ||
               op == 0x7e || op == 0x2a || op == 0x2c || op == 0x5a ||
               op == 0x57) {
      if (op == 0x57) {
        if (prefix)
          return 0;
      } else if (op == 0x2e) {
        if (prefix)
          return 0;
      } else if (op == 0x6e || op == 0x7e) {
        if (!(word16 && !prefix) && !(op == 0x7e && prefix == 0xf3 && !word16))
          return 0;
      } else if ((prefix != 0xf2 && prefix != 0xf3) || word16)
        return 0;
      xmm = true;
      source_bits = op == 0x6e || op == 0x2a ? (rex & 8 ? 64 : 32)
                    : op == 0x7e     ? (prefix == 0xf3 || (rex & 8) ? 64 : 32)
                    : op == 0x2e     ? (word16 ? 64 : 32)
                    : op == 0x57     ? 128
                    : prefix == 0xf3 ? 32
                                     : 64;
      reverse = op != 0x11 && op != 0x7e;
      name = op == 0x10 || op == 0x11   ? (prefix == 0xf3 ? "movss" : "movsd")
             : op == 0x58               ? (prefix == 0xf3 ? "addss" : "addsd")
             : op == 0x59               ? (prefix == 0xf3 ? "mulss" : "mulsd")
             : op == 0x5c               ? (prefix == 0xf3 ? "subss" : "subsd")
             : op == 0x5e               ? (prefix == 0xf3 ? "divss" : "divsd")
             : op == 0x2e               ? (word16 ? "ucomisd" : "ucomiss")
             : op == 0x6e || op == 0x7e ? (source_bits == 64 ? "movq" : "movd")
             : op == 0x57               ? (word16 ? "xorpd" : "xorps")
             : op == 0x2a ? (prefix == 0xf3 ? "cvtsi2ss" : "cvtsi2sd")
             : op == 0x2c ? (prefix == 0xf3 ? "cvttss2si" : "cvttsd2si")
                          : (prefix == 0xf3 ? "cvtss2sd" : "cvtsd2ss");
    } else if (op == 0x6f || op == 0x7f || op == 0xd4 || op == 0xfe ||
               op == 0xfb || op == 0xfa || op == 0xdb || op == 0xeb ||
               op == 0xef) {
      if (op == 0x6f || op == 0x7f) {
        if (!(prefix == 0xf3 && !word16) && !(word16 && !prefix))
          return 0;
      } else if (!word16 || prefix)
        return 0;
      xmm = true;
      source_bits = 128;
      reverse = op != 0x7f;
      name = op == 0x6f || op == 0x7f ? (prefix == 0xf3 ? "movdqu" : "movdqa")
             : op == 0xd4             ? "paddq"
             : op == 0xfe             ? "paddd"
             : op == 0xfb             ? "psubq"
             : op == 0xfa             ? "psubd"
             : op == 0xdb             ? "pand"
             : op == 0xeb             ? "por"
                                      : "pxor";
    } else
      return 0;
  } else {
    switch (op) {
    case 0x88:
    case 0x89:
    case 0x8a:
    case 0x8b:
      name = "mov";
      reverse = op == 0x8a || op == 0x8b;
      if (op == 0x88 || op == 0x8a)
        bits = source_bits = 8;
      break;
    case 0x8d:
      name = "lea";
      reverse = true;
      break;
    case 0x63:
      if (!(rex & 8))
        return 0;
      name = "movsxd";
      reverse = true;
      source_bits = 32;
      break;
    case 0x01:
    case 0x03:
      name = "add";
      reverse = op == 3;
      break;
    case 0x29:
    case 0x2b:
      name = "sub";
      reverse = op == 0x2b;
      break;
    case 0x20:
    case 0x21:
    case 0x23:
      name = "and";
      reverse = op == 0x23;
      if (op == 0x20)
        bits = source_bits = 8;
      break;
    case 0x08:
    case 0x09:
    case 0x0b:
      name = "or";
      reverse = op == 0x0b;
      if (op == 8)
        bits = source_bits = 8;
      break;
    case 0x31:
    case 0x33:
      name = "xor";
      reverse = op == 0x33;
      break;
    case 0x39:
    case 0x3b:
      name = "cmp";
      reverse = op == 0x3b;
      break;
    case 0x85:
      name = "test";
      break;
    case 0x80:
    case 0xc6:
    case 0x81:
    case 0x83:
    case 0xc1:
    case 0xd3:
    case 0xf7:
    case 0xff:
    case 0xc7:
    case 0x69:
    case 0x6b:
      break;
    case 0xa8:
      if (rex || word16 || n - i < 1)
        return 0;
      snprintf(out, cap, "test al, 0x%x", p[i]);
      return i + 1;
    case 0x05:
    case 0x25:
    case 0x2d:
    case 0x3d:
    case 0xa9:
      imm = word16 ? 2 : 4;
      if (n - i < imm)
        return 0;
      name = op == 5      ? "add"
             : op == 0x25 ? "and"
             : op == 0x2d ? "sub"
             : op == 0x3d ? "cmp"
                          : "test";
      if (bits == 64)
        snprintf(out, cap, "%s %s, %lld", name, nd_reg(0, bits),
                 (long long)(int32_t)nd_read(p + i, imm));
      else
        snprintf(out, cap, "%s %s, 0x%llx", name, nd_reg(0, bits),
                 (unsigned long long)nd_read(p + i, imm));
      return i + imm;
    default:
      return 0;
    }
  }
  if (i >= n)
    return 0;
  unsigned modrm = p[i++], mod = modrm >> 6, group = (modrm >> 3) & 7,
           r = group + ((rex & 4) ? 8 : 0),
           base = (modrm & 7) + ((rex & 1) ? 8 : 0);
  if (!two && (op == 0x80 || op == 0xc6))
    bits = source_bits = 8;
  if (!two && op == 0xff && (group == 2 || group == 4 || group == 6)) {
    if (word16) return 0;
    bits = source_bits = 64;
  }
  if (!two && (op == 0xc6 || op == 0xc7) && group != 0)
    return 0;
  char operand[128], reg[24];
  int64_t disp = 0;
  unsigned disp_size = mod == 1 ? 1 : mod == 2 ? 4 : 0;
  if (mod == 3)
    snprintf(operand, sizeof operand, "%s",
             nd_byte_reg(base, source_bits, rex));
  else {
    char address[80];
    bool absent = false;
    if ((modrm & 7) == 4) {
      if (i >= n)
        return 0;
      unsigned sib = p[i++], index = ((sib >> 3) & 7) + ((rex & 2) ? 8 : 0);
      base = (sib & 7) + ((rex & 1) ? 8 : 0);
      absent = mod == 0 && (sib & 7) == 5;
      if (absent)
        disp_size = 4;
      if (index == 4)
        snprintf(address, sizeof address, "%s", absent ? "" : nd_reg(base, 64));
      else
        snprintf(address, sizeof address, "%s%s%s*%u",
                 absent ? "" : nd_reg(base, 64), absent ? "" : "+",
                 nd_reg(index, 64), 1u << (sib >> 6));
    } else if (mod == 0 && (modrm & 7) == 5) {
      strcpy(address, "rip");
      disp_size = 4;
    } else
      snprintf(address, sizeof address, "%s", nd_reg(base, 64));
    if (n - i < disp_size)
      return 0;
    if (disp_size) {
      disp = disp_size == 1 ? (int8_t)p[i] : (int32_t)nd_read(p + i, 4);
      i += disp_size;
    }
    const char *size = (!two && op == 0x8d) ? ""
                       : source_bits == 8   ? "byte ptr "
                       : source_bits == 16  ? "word ptr "
                       : source_bits == 32  ? "dword ptr "
                       : source_bits == 64  ? "qword ptr "
                                            : "xmmword ptr ";
    snprintf(operand, sizeof operand, "%s[%s%+lld]", size, address,
             (long long)disp);
  }
  if (xmm && mod == 3 && op != 0x6e && op != 0x2a &&
      !(op == 0x7e && prefix != 0xf3))
    snprintf(operand, sizeof operand, "xmm%u", base);
  if (xmm && op == 0x7e && prefix == 0xf3)
    reverse = true;
  if (xmm && op != 0x2c)
    snprintf(reg, sizeof reg, "xmm%u", r);
  else
    snprintf(reg, sizeof reg, "%s", nd_byte_reg(r, bits, rex));
  if (two && op >= 0x90 && op <= 0x9f) {
    snprintf(out, cap, "set%s %s", conditions[op & 15], operand);
    return i;
  }
  if (!two && (op == 0x80 || op == 0x81 || op == 0x83)) {
    static const char *const names[] = {"add", "or",  "adc", "sbb",
                                        "and", "sub", "xor", "cmp"};
    name = names[group];
    imm = op == 0x80 || op == 0x83 ? 1 : bits == 16 ? 2 : 4;
  }
  if (!two && (op == 0xc1 || op == 0xd3)) {
    name = group == 4 ? "shl" : group == 5 ? "shr" : group == 7 ? "sar" : NULL;
    if (!name)
      return 0;
    if (op == 0xc1)
      imm = 1;
    else {
      snprintf(out, cap, "%s %s, cl", name, operand);
      return i;
    }
  }
  if (!two && op == 0xf7) {
    name = group == 2   ? "not"
           : group == 3 ? "neg"
           : group == 4 ? "mul"
           : group == 5 ? "imul"
           : group == 6 ? "div"
           : group == 7 ? "idiv"
           : group == 0 ? "test"
                        : NULL;
    if (!name)
      return 0;
    if (group == 0)
      imm = word16 ? 2 : 4;
    else {
      snprintf(out, cap, "%s %s", name, operand);
      return i;
    }
  }
  if (!two && op == 0xff) {
    name = group == 0   ? "inc"
           : group == 1 ? "dec"
           : group == 2 ? "call"
           : group == 4 ? "jmp"
           : group == 6 ? "push"
                        : NULL;
    if (!name)
      return 0;
    snprintf(out, cap, "%s %s", name, operand);
    return i;
  }
  if (!two && (op == 0xc6 || op == 0xc7 || op == 0x69 || op == 0x6b)) {
    name = op == 0x69 || op == 0x6b ? "imul" : "mov";
    imm = op == 0xc6 || op == 0x6b ? 1 : bits == 16 ? 2 : 4;
  }
  if (imm) {
    if (n - i < imm)
      return 0;
    bool sign = op == 0x83 || op == 0x6b || (bits == 64 && imm == 4);
    int64_t signed_value = imm == 1   ? (int8_t)p[i]
                           : imm == 2 ? (int16_t)nd_read(p + i, 2)
                                      : (int32_t)nd_read(p + i, 4);
    if ((op == 0x69 || op == 0x6b) && sign)
      snprintf(out, cap, "%s %s, %s, %lld", name, reg, operand,
               (long long)signed_value);
    else if (op == 0x69)
      snprintf(out, cap, "%s %s, %s, 0x%llx", name, reg, operand,
               (unsigned long long)nd_read(p + i, imm));
    else if (sign)
      snprintf(out, cap, "%s %s, %lld", name, operand, (long long)signed_value);
    else
      snprintf(out, cap, "%s %s, 0x%llx", name, operand,
               (unsigned long long)nd_read(p + i, imm));
    return i + imm;
  }
  if (!name)
    return 0;
  snprintf(out, cap, "%s %s, %s", name, reverse ? reg : operand,
           reverse ? operand : reg);
  return i;
}
static const char *nd_arm_reg(char out[8], unsigned n, bool wide, bool stack) {
  if (n == 31)
    snprintf(out, 8, "%s",
             stack ? (wide ? "sp" : "wsp") : (wide ? "xzr" : "wzr"));
  else
    snprintf(out, 8, "%c%u", wide ? 'x' : 'w', n);
  return out;
}
static size_t nd_a64(const unsigned char *p, size_t n, char *out, size_t cap) {
  if (n < 4)
    return 0;
  uint32_t w = (uint32_t)nd_read(p, 4);
  unsigned d = w & 31, r = (w >> 5) & 31, m = (w >> 16) & 31;
  if (w == 0xd503201f) {
    snprintf(out, cap, "nop");
    return 4;
  }
  if ((w & 0xfffffc1f) == 0xd65f0000 || (w & 0xfffffc1f) == 0xd63f0000 ||
      (w & 0xfffffc1f) == 0xd61f0000) {
    snprintf(out, cap, "%s x%u",
             (w & 0xfffffc1f) == 0xd65f0000   ? "ret"
             : (w & 0xfffffc1f) == 0xd63f0000 ? "blr"
                                              : "br",
             r);
    return 4;
  }
  if ((w & 0xffe0001f) == 0xd4000001) {
    snprintf(out, cap, "svc #%u", (w >> 5) & 65535);
    return 4;
  }
  if ((w & 0x7c000000) == 0x14000000) {
    int32_t v = (int32_t)(w << 6) >> 4;
    snprintf(out, cap, "%s .%+d", w >> 31 ? "bl" : "b", v);
    return 4;
  }
  if ((w & 0xff000010) == 0x54000000) {
    static const char *const c[] = {"eq", "ne", "cs", "cc", "mi", "pl",
                                    "vs", "vc", "hi", "ls", "ge", "lt",
                                    "gt", "le", "al", "nv"};
    int32_t v = (int32_t)(w << 8) >> 13;
    snprintf(out, cap, "b.%s .%+d", c[w & 15], v * 4);
    return 4;
  }
  if ((w & 0x1f800000) == 0x12800000) {
    unsigned op = (w >> 29) & 3;
    if (op == 1 || (!(w >> 31) && (w & (1u << 22))))
      return 0;
    char reg[8];
    snprintf(out, cap, "%s %s, #0x%x, lsl #%u",
             op == 0   ? "movn"
             : op == 2 ? "movz"
                       : "movk",
             nd_arm_reg(reg, d, w >> 31, false), (w >> 5) & 65535,
             ((w >> 21) & 3) * 16);
    return 4;
  }
  if ((w & 0x1f800000) == 0x11000000) {
    char a[8], b[8];
    nd_arm_reg(a, d, w >> 31, !(w & (1u << 29)));
    nd_arm_reg(b, r, w >> 31, true);
    unsigned imm = ((w >> 10) & 4095) << ((w & (1u << 22)) ? 12 : 0);
    if ((w & (1u << 29)) && d == 31)
      snprintf(out, cap, "%s %s, #%u", w & (1u << 30) ? "cmp" : "cmn", b, imm);
    else
      snprintf(out, cap, "%s%s %s, %s, #%u", w & (1u << 30) ? "sub" : "add",
               w & (1u << 29) ? "s" : "", a, b, imm);
    return 4;
  }
  if ((w & 0x1f200000) == 0x0b000000 || (w & 0x1f000000) == 0x0a000000) {
    const char *name;
    bool logic = (w & 0x1f000000) == 0x0a000000;
    unsigned op = (w >> 29) & 3;
    name = logic ? (op == 0   ? "and"
                    : op == 1 ? "orr"
                    : op == 2 ? "eor"
                              : "ands")
                 : (w & (1u << 30) ? (w & (1u << 29) ? "subs" : "sub")
                                   : (w & (1u << 29) ? "adds" : "add"));
    if (logic && (w & (1u << 21))) {
      static const char *const inverted[] = {"bic", "orn", "eon", "bics"};
      name = inverted[op];
    }
    if (!(w >> 31) && ((w >> 10) & 63) >= 32)
      return 0;
    if (!logic && ((w >> 22) & 3) == 3)
      return 0;
    char dst[8], left[8], right[8];
    snprintf(out, cap, "%s %s, %s, %s, %s #%u", name,
             nd_arm_reg(dst, d, w >> 31, false),
             nd_arm_reg(left, r, w >> 31, false),
             nd_arm_reg(right, m, w >> 31, false),
             ((w >> 22) & 3) == 0   ? "lsl"
             : ((w >> 22) & 3) == 1 ? "lsr"
             : ((w >> 22) & 3) == 2 ? "asr"
                                    : "ror",
             (w >> 10) & 63);
    return 4;
  }
  if ((w & 0x3a000000) == 0x28000000) {
    unsigned kind = w >> 30, mode = (w >> 23) & 3;
    bool fp = (w & (1u << 26)) != 0;
    if ((fp && kind > 2) || (!fp && kind != 0 && kind != 2))
      return 0;
    unsigned scale = fp ? kind + 2 : kind == 2 ? 3 : 2;
    char type = fp          ? (kind == 0   ? 's'
                               : kind == 1 ? 'd'
                                           : 'q')
                : kind == 2 ? 'x'
                            : 'w';
    int offset = ((int32_t)(w << 10) >> 25) * (1 << scale);
    char base[8];
    if (r == 31)
      strcpy(base, "sp");
    else
      snprintf(base, sizeof base, "x%u", r);
    char first[8], second[8];
    if (fp) {
      snprintf(first, sizeof first, "%c%u", type, d);
      snprintf(second, sizeof second, "%c%u", type, (w >> 10) & 31);
    } else {
      nd_arm_reg(first, d, kind == 2, false);
      nd_arm_reg(second, (w >> 10) & 31, kind == 2, false);
    }
    const char *name =
        w & (1u << 22) ? (mode ? "ldp" : "ldnp") : (mode ? "stp" : "stnp");
    if (mode == 1)
      snprintf(out, cap, "%s %s, %s, [%s], #%d", name, first, second, base,
               offset);
    else
      snprintf(out, cap, "%s %s, %s, [%s, #%d]%s", name, first, second, base,
               offset, mode == 3 ? "!" : "");
    return 4;
  }
  if ((w & 0x3b200000) == 0x38000000) {
    unsigned scale = w >> 30, op = (w >> 22) & 3, mode = (w >> 10) & 3;
    bool fp = (w & (1u << 26)) != 0;
    if ((!fp && op > 1) ||
        (fp && ((op > 1 && scale != 0) || (op < 2 && scale < 2))) || mode == 2)
      return 0;
    int offset = (int32_t)(w << 11) >> 23;
    char base[8];
    if (r == 31)
      strcpy(base, "sp");
    else
      snprintf(base, sizeof base, "x%u", r);
    const char *name =
        op & 1 ? (mode ? "ldr" : "ldur") : (mode ? "str" : "stur");
    const char *suffix = !fp && scale == 0 ? "b" : !fp && scale == 1 ? "h" : "";
    char reg[8];
    if (fp)
      snprintf(reg, sizeof reg, "%c%u",
               op > 1       ? 'q'
               : scale == 3 ? 'd'
                            : 's',
               d);
    else
      nd_arm_reg(reg, d, scale == 3, false);
    if (mode == 1)
      snprintf(out, cap, "%s%s %s, [%s], #%d", name, suffix, reg, base, offset);
    else
      snprintf(out, cap, "%s%s %s, [%s, #%d]%s", name, suffix, reg, base,
               offset, mode == 3 ? "!" : "");
    return 4;
  }
  if ((w & 0x3b000000) == 0x39000000) {
    unsigned scale = w >> 30, op = (w >> 22) & 3;
    bool fp = (w & (1u << 26)) != 0;
    if ((!fp && op > 1) ||
        (fp && ((op > 1 && scale != 0) || (op < 2 && scale < 2))))
      return 0;
    char base[8], reg[8];
    nd_arm_reg(base, r, true, true);
    if (fp)
      snprintf(reg, sizeof reg, "%c%u",
               op > 1       ? 'q'
               : scale == 3 ? 'd'
                            : 's',
               d);
    else
      nd_arm_reg(reg, d, scale == 3, false);
    snprintf(out, cap, "%s%s %s, [%s, #%u]", op & 1 ? "ldr" : "str",
             !fp && scale == 0   ? "b"
             : !fp && scale == 1 ? "h"
                                 : "",
             reg, base, ((w >> 10) & 4095) << (fp && op > 1 ? 4 : scale));
    return 4;
  }
  uint32_t simd = w & 0xffe0fc00;
  const char *vector = simd == 0x4ea08400 || simd == 0x4ee08400   ? "add"
                       : simd == 0x6ea08400 || simd == 0x6ee08400 ? "sub"
                       : simd == 0x4e201c00                       ? "and"
                       : simd == 0x4ea01c00                       ? "orr"
                       : simd == 0x6e201c00                       ? "eor"
                                                                  : NULL;
  if (vector) {
    const char *lanes = simd == 0x4ea08400 || simd == 0x6ea08400   ? "4s"
                        : simd == 0x4ee08400 || simd == 0x6ee08400 ? "2d"
                                                                   : "16b";
    snprintf(out, cap, "%s v%u.%s, v%u.%s, v%u.%s", vector, d, lanes, r, lanes,
             m, lanes);
    return 4;
  }
  return 0;
}
static size_t nd_rv64(const unsigned char *p, size_t n, char *out, size_t cap) {
  if(n<4)return 0;
  uint32_t w=(uint32_t)nd_read(p,4);unsigned op=w&127,d=(w>>7)&31,f=(w>>12)&7,a=(w>>15)&31,b=(w>>20)&31,h=w>>25;
  int imm=(int32_t)w>>20;
  const char *name=NULL;
  if(op==0x13||op==0x1b) {
    if(f==0)name=op==0x1b?"addiw":"addi";
    if(f==1)name=op==0x1b?"slliw":"slli";
    if(f==5)name=h&32?(op==0x1b?"sraiw":"srai"):(op==0x1b?"srliw":"srli");
    if(op==0x13&&f==3)name="sltiu";
    if(op==0x13&&f==4)name="xori";
    if(op==0x13&&f==7)name="andi";
    if(!name)return 0;
    snprintf(out,cap,"%s x%u, x%u, %d",name,d,a,(f==1||f==5)?(int)((w>>20)&(op==0x1b?31:63)):imm);return 4;
  }
  if(op==0x33) {
    static const char *const basic[]={"add","sll","slt","sltu","xor","srl","or","and"};
    static const char *const mul[]={"mul","mulh","mulhsu","mulhu","div","divu","rem","remu"};
    name=h==1?mul[f]:h==0?basic[f]:h==32&&f==0?"sub":h==32&&f==5?"sra":NULL;
    if(!name)return 0;
    snprintf(out,cap,"%s x%u, x%u, x%u",name,d,a,b);return 4;
  }
  if(op==3||op==7||op==0x23||op==0x27) {
    bool store=op==0x23||op==0x27,fp=op==7||op==0x27;
    static const char *const loads[]={"lb","lh","lw","ld","lbu","lhu","lwu",NULL};
    static const char *const stores[]={"sb","sh","sw","sd",NULL,NULL,NULL,NULL};
    name=fp?(f==2?(store?"fsw":"flw"):f==3?(store?"fsd":"fld"):NULL):store?stores[f]:loads[f];
    if(!name)return 0;
    if(store)imm=((int32_t)(w&0xfe000000)>>20)|((w>>7)&31);
    snprintf(out,cap,"%s %c%u, %d(x%u)",name,fp?'f':'x',store?b:d,imm,a);return 4;
  }
  if(op==0x17||op==0x37) {snprintf(out,cap,"%s x%u, 0x%x",op==0x17?"auipc":"lui",d,w>>12);return 4;}
  if(op==0x67&&f==0) {snprintf(out,cap,"jalr x%u, %d(x%u)",d,imm,a);return 4;}
  if(op==0x63) {
    static const char *const branches[]={"beq","bne",NULL,NULL,"blt","bge","bltu","bgeu"};name=branches[f];if(!name)return 0;
    imm=((int32_t)(w&0x80000000)>>19)|((w>>20)&0x7e0)|((w>>7)&0x1e)|((w<<4)&0x800);
    snprintf(out,cap,"%s x%u, x%u, .%+d",name,a,b,imm);return 4;
  }
  if(w==0x73||w==0x100073) {snprintf(out,cap,"%s",w==0x73?"ecall":"ebreak");return 4;}
  if(op==0x53) {
    bool single=(h&1)==0;unsigned base=h&~1u;
    if(base==0||base==4||base==8||base==12) {
      name=base==0?"fadd":base==4?"fsub":base==8?"fmul":"fdiv";
      static const char *const rm[]={"rne","rtz","rdn","rup","rmm",NULL,NULL,"dyn"};if(!rm[f])return 0;
      snprintf(out,cap,"%s.%c f%u, f%u, f%u, %s",name,single?'s':'d',d,a,b,rm[f]);return 4;
    }
    if(base==0x50&&f<=2) {snprintf(out,cap,"%s.%c x%u, f%u, f%u",f==0?"fle":f==1?"flt":"feq",single?'s':'d',d,a,b);return 4;}
    if((base==0x70||base==0x78)&&b==0&&f==0) {snprintf(out,cap,base==0x70?"fmv.x.%c x%u, f%u":"fmv.%c.x f%u, x%u",single?'w':'d',d,a);return 4;}
  }
  return 0;
}
#endif
