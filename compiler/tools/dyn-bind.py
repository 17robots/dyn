#!/usr/bin/env python3
"""Generate conservative Dyn declarations from a small, ABI-safe C header subset.

Unsupported declarations are preserved as actionable comments. The generator
intentionally rejects unions, bitfields, anonymous fields, and complex declarators;
those require an explicit C adapter instead of an ABI guess.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import tempfile
import pathlib
import re
import sys


INTEGER_TYPES = {
    "char": "c.char", "signed char": "i8", "unsigned char": "u8",
    "int8_t": "i8", "uint8_t": "u8", "int16_t": "i16", "uint16_t": "u16",
    "int32_t": "i32", "uint32_t": "u32", "int64_t": "i64", "uint64_t": "u64",
    "short": "i16", "unsigned short": "u16", "int": "i32", "unsigned": "u32",
    "unsigned int": "u32", "long": "c.long", "unsigned long": "c.unsigned_long",
    "long long": "i64", "unsigned long long": "u64",
    "size_t": "usize", "ptrdiff_t": "isize", "float": "f32", "double": "f64",
    "void": "void",
}


def integer_literal(value: str) -> int:
    """C integer literals only; never evaluate arbitrary header expressions."""
    match = re.fullmatch(r"([+-]?)(0[xX][0-9a-fA-F]+|0[0-7]*|[1-9][0-9]*)([uUlL]*)", value.strip())
    if not match or match.group(3).lower() not in ("", "u", "l", "ul", "lu", "ll", "ull", "llu"):
        raise ValueError("unsupported integer expression")
    sign, digits, _ = match.groups()
    base = 16 if digits.lower().startswith("0x") else 8 if digits.startswith("0") else 10
    return (-1 if sign == "-" else 1) * int(digits, base)


def strip_comments(text: str) -> str:
    # C removes escaped newlines before identifying comments and string tokens.
    text = re.sub(r"\\\r?\n", "", text)
    tokens = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|/\*[\s\S]*?\*/|//[^\n]*')
    return tokens.sub(lambda m: m.group() if m.group()[0] in "\'\"" else
                      "".join("\n" if c == "\n" else " " for c in m.group()), text)


def declaration_source(text: str) -> str:
    # Macro bodies and quoted text are not declarations, even if they contain
    # strings such as "struct Fake { int value; };".
    text = re.sub(r"(?m)^[ \t]*#[^\n]*", "", text)
    return re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
                  lambda m: " " * len(m.group()), text)


def string_literal(value: str) -> str:
    """Translate ordinary C string escapes to Dyn byte escapes without eval."""
    if not re.fullmatch(r'"(?:[^"\\\n]|\\.)*"', value):
        raise ValueError("not a single ordinary C string literal")
    data = bytearray()
    at = 1
    escapes = {"a": 7, "b": 8, "f": 12, "n": 10, "r": 13, "t": 9,
               "v": 11, "\\": 92, '"': 34, "'": 39, "?": 63}
    while at < len(value) - 1:
        if value[at] != "\\":
            data.extend(value[at].encode("utf-8")); at += 1; continue
        at += 1
        char = value[at]; at += 1
        if char in escapes:
            data.append(escapes[char])
        elif char in "01234567":
            digits = char
            while at < len(value)-1 and len(digits) < 3 and value[at] in "01234567":
                digits += value[at]; at += 1
            number = int(digits, 8)
            if number > 255: raise ValueError("octal escape outside one byte")
            data.append(number)
        elif char == "x":
            start = at
            while at < len(value)-1 and value[at] in "0123456789abcdefABCDEF": at += 1
            if at == start: raise ValueError("empty hex escape")
            number = int(value[start:at], 16)
            if number > 255: raise ValueError("hex escape outside one byte")
            data.append(number)
        else:
            raise ValueError("unsupported C string escape")
    escaped = {10: r"\n", 13: r"\r", 9: r"\t", 34: r'\"', 92: r"\\"}
    return '"' + ''.join(escaped.get(byte, chr(byte) if 32 <= byte < 127 else
                                     f"\\x{byte:02x}") for byte in data) + '"'


def dyn_type(value: str, *, parameter: bool = False) -> str | None:
    # A qualifier belongs to the type immediately on its left (or the base type),
    # never to every pointer in the declarator. Top-level const is a value copy.
    pieces = [part.strip() for part in value.strip().split("*")]
    base_words = pieces[0].split()
    readonly = "const" in base_words
    base_words = [word for word in base_words if word != "const"]
    if any(word in ("volatile", "restrict", "_Atomic") for word in base_words): return None
    base = " ".join(base_words)
    if base.startswith(("struct ", "enum ")):
        name = base.split(" ", 1)[1]
        mapped = name if re.fullmatch(r"[A-Za-z_]\w*", name) else None
    elif base.startswith("union "):
        mapped = "void" if re.fullmatch(r"union [A-Za-z_]\w*", base) and len(pieces)>1 else None
    else:
        mapped = INTEGER_TYPES.get(base, base if re.fullmatch(r"[A-Za-z_]\w*", base) else None)
    if mapped is None: return None
    for qualifiers in pieces[1:]:
        if any(word != "const" for word in qualifiers.split()): return None
        mapped = "rawptr" if mapped == "void" else ("*const " if readonly else "*") + mapped
        readonly = "const" in qualifiers.split()
    return mapped


def split_params(source: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    for index, char in enumerate(source):
        if char == "(": depth += 1
        elif char == ")": depth -= 1
        elif char == "," and depth == 0:
            parts.append(source[start:index].strip())
            start = index + 1
    tail = source[start:].strip()
    if tail: parts.append(tail)
    return parts


def parse_parameter(source: str) -> tuple[str, str] | None:
    callback = re.fullmatch(r"(.+?)\(\s*\*\s*(\w+)\s*\)\s*\((.*)\)", source)
    if callback:
        if not callback.group(3).strip(): return None
        returned = dyn_type(callback.group(1))
        parameters: list[str] = []
        callback_params = split_params(callback.group(3))
        if callback_params == ["void"]: callback_params = []
        for raw in callback_params:
            mapped = dyn_type(raw)
            if mapped is None:
                parsed = parse_parameter(raw)
                if parsed is None: return None
                mapped = parsed[1]
            parameters.append(mapped)
        if returned is None: return None
        return callback.group(2), f"*fn({', '.join(parameters)})" + (f" {returned}" if returned != "void" else "")
    match = re.fullmatch(r"(.+?)([A-Za-z_]\w*)", source.strip())
    if not match or not (match.group(1)[-1].isspace() or match.group(1)[-1] == "*"): return None
    c_type = match.group(1).strip()
    name = match.group(2)
    mapped = dyn_type(c_type, parameter=True)
    return (name, mapped) if mapped else None


def field_lines(body: str) -> list[tuple[str, str]] | None:
    if re.search(r":\s*\d+", body) or re.search(r"(?:struct|union)\s*\{", body):
        return None
    fields: list[tuple[str, str]] = []
    for declaration in body.split(";"):
        declaration = declaration.strip()
        if not declaration: continue
        parsed = parse_parameter(declaration)
        if parsed is None: return None
        fields.append(parsed)
    return fields


def generate(text: str) -> str:
    text = strip_comments(text)
    declarations = declaration_source(text)
    output = ['use "std/c"', ""]
    unsupported_functions: list[str] = []
    unsupported_enums: list[str] = []
    unsupported_macros: list[str] = []
    unsupported_structs: dict[str, str] = {}
    unsupported_unions: list[str] = []

    enums = list(re.finditer(r"enum\s+(\w+)\s*\{(.*?)\}\s*;", declarations, re.S))
    for match in enums:
        name, body = match.group(1), match.group(2)
        lines = [f"pub type {name} = i32"]
        current = -1
        try:
            for item in body.split(","):
                item = item.strip()
                if not item: continue
                parts = item.split("=", 1)
                item_name = parts[0].strip()
                if not re.fullmatch(r"[A-Za-z_]\w*", item_name): raise ValueError("enumerator")
                current = integer_literal(parts[1]) if len(parts) == 2 else current + 1
                if not -(1 << 31) <= current < (1 << 31): raise ValueError("enum width")
                lines.append(f"pub const {item_name}: {name} = {current}")
        except ValueError:
            unsupported_enums.append(f"enum {name}: requires literal signed 32-bit enumerators and the default C enum ABI")
        else:
            output.extend([*lines, ""])

    macros: list[str] = []
    for match in re.finditer(r"^[ \t]*#define[ \t]+(\w+)(\([^\n]*?\))?[ \t]+([^\n]+?)[ \t]*$", text, re.M):
        name, arguments, value = match.group(1), match.group(2), match.group(3).strip()
        if arguments:
            unsupported_macros.append(f"macro {name}: function-like macros require a C wrapper")
        elif re.fullmatch(r'"(?:[^"\\]|\\.)*"', value):
            try:
                literal = string_literal(value)
            except ValueError as error:
                unsupported_macros.append(f"macro {name}: {error}")
            else:
                macros.append(f"pub const {name}: []const u8 = {literal}")
        else:
            try:
                number = integer_literal(value)
                if not 0 <= number < (1 << 64): raise ValueError("macro range")
            except ValueError:
                unsupported_macros.append(f"macro {name}: expression is not a standalone integer or string literal")
            else:
                macros.append(f"pub const {name}: u64 = {number}")
    output.extend(macros)
    if macros: output.append("")

    records: list[tuple[int, str, str]] = []
    for match in re.finditer(r"struct\s+(\w+)\s*\{((?:[^{}]|\{[^{}]*\})*)\}\s*;", declarations, re.S):
        records.append((match.start(), match.group(1), match.group(2)))
    for match in re.finditer(r"typedef\s+struct\s*\{(.*?)\}\s*(\w+)\s*;", declarations, re.S):
        records.append((match.start(), match.group(2), match.group(1)))
        unsupported_structs.setdefault("<anonymous>", "anonymous record has no stable Dyn type name")
    record_aliases: dict[str, str] = {}
    for match in re.finditer(r"typedef\s+struct\s+(\w+)\s*\{([^{}]*)\}\s*(\w+)\s*;", declarations, re.S):
        records.append((match.start(), match.group(1), match.group(2)))
        if match.group(1) != match.group(3):
            record_aliases[match.group(3)] = match.group(1)
    emitted: set[str] = set()
    for _, name, body in sorted(records):
        if name in emitted or re.search(r"struct\s+\w+\s*\{", body):
            continue
        fields = field_lines(body)
        if fields is None:
            reason = "bitfields require an explicit ABI adapter" if ":" in body else "anonymous fields are not representable"
            unsupported_structs[name] = reason
            continue
        output.append(f"pub struct {name} {{")
        output.extend(f"  {field}: {kind}," for field, kind in fields)
        output.extend(["}", ""])
        emitted.add(name)

    for alias, tag in record_aliases.items():
        if tag in emitted:
            output.extend([f"pub type {alias} = {tag}", ""])

    # Named nested tags have independent C identity; emit the tag, then parent.
    for nested in re.finditer(r"struct\s+(\w+)\s*\{\s*struct\s+(\w+)\s*\{\s*([^{}]*)\}\s*(\w+)\s*;\s*\}\s*;", declarations, re.S):
        outer, inner, body, field = nested.group(1), nested.group(2), nested.group(3), nested.group(4)
        fields = field_lines(body)
        if fields:
            output.append(f"pub struct {inner} {{")
            output.extend(f"  {field_name}: {kind}," for field_name, kind in fields)
            output.extend(["}", ""])
            output.extend([f"pub struct {outer} {{", f"  {field}: {inner},", "}", ""])

    for match in re.finditer(r"union\s+(\w+)\s*\{.*?\}\s*;", declarations, re.S):
        unsupported_unions.append(match.group(1))

    for match in re.finditer(r"^\s*([^#\n;{}]+?)\s+(\w+)\s*\((.*)\)\s*;\s*$", declarations, re.M):
        returned_c, name, parameters_c = match.group(1).strip(), match.group(2), match.group(3).strip()
        if not parameters_c:
            unsupported_functions.append(f"function {name}: non-prototype C declaration; use an explicit (void) parameter list")
            continue
        returned = dyn_type(returned_c)
        parameters: list[str] = []
        supported = returned is not None
        variadic = False
        if parameters_c and parameters_c != "void":
            for raw in split_params(parameters_c):
                if raw == "...": variadic = True; continue
                parsed = parse_parameter(raw)
                if parsed is None: supported = False; break
                parameters.append(f"{parsed[0]}: {parsed[1]}")
        if variadic: parameters.append("...")
        if not supported or returned is None:
            unsupported_functions.append(f"function {name}: parameter or return type is not representable")
            continue
        suffix = "" if returned == "void" else f" {returned}"
        output.append(f'pub extern fn {name} "{name}"({", ".join(parameters)}){suffix}')
    if output[-1] != "": output.append("")

    comments = unsupported_functions + unsupported_macros + unsupported_enums
    comments += [f"struct {name}: {unsupported_structs[name]}" for name in sorted(unsupported_structs)]
    comments += [f"union {name}: by-value union layout is not representable" for name in sorted(set(unsupported_unions))]
    if comments:
        output.append("// Unsupported declarations (write explicit bindings or a C adapter):")
        output.extend(f"// {comment}" for comment in comments)
    return "\n".join(output).rstrip() + "\n"


def report(header: pathlib.Path, source: str, generated: str) -> dict:
    omissions = []
    for kind, name, reason in re.findall(r"^// (function|macro|enum|struct|union) ([^:]+): (.+)$", generated, re.M):
        occurrence = re.search(r"\b" + re.escape(name) + r"\b", source)
        omissions.append(dict(kind=kind, name=name, reason=reason,
                              line=source.count("\n", 0, occurrence.start()) + 1 if occurrence else None))
    return dict(schema=1, source=str(header), frontend="conservative-header-text",
                completeness="subset only; includes, conditionals and unrecognized declarators require review",
                unsupported=omissions,
                preprocessing=[dict(line=source.count("\n", 0, m.start())+1,
                                    directive=m.group(0).strip(), reason="not interpreted by the text frontend")
                    for m in re.finditer(r"^[ \t]*#(?:if\w*|elif|else|endif|include|pragma)\b[^\n]*", source, re.M)],
                layout_verification="not requested")


def verify_layout(header: pathlib.Path, source: str, generated: str,
                  target: str, cc: str, dyn: str, execute: bool) -> dict:
    """Compare C sizeof/alignof/offsetof with Dyn in a linked target probe.

    The target compiler's own header parser is the layout oracle. No host layout
    is assumed. Cross-linking is reported separately from execution.
    """
    source = declaration_source(strip_comments(source))
    records = re.findall(r"^pub struct (\w+) \{\n(.*?)^\}", generated, re.M | re.S)
    if not records:
        raise ValueError("no generated records to verify")
    with tempfile.TemporaryDirectory(prefix="dyn-bind-layout-") as temporary:
        root = pathlib.Path(temporary)
        (root / "bindings.dyn").write_text(generated)
        # Include syntax uses an escaped absolute path, never a shell command.
        c = ['#include <stddef.h>', '#include ' + json.dumps(str(header.resolve()))]
        declarations, checks = [], []
        count = 0
        for name, fields in records:
            tagged = re.search(r"\bstruct\s+" + re.escape(name) + r"\s*\{", source)
            ctype = "struct " + name if tagged else name
            members = re.findall(r"^  (\w+):", fields, re.M)
            variable = "layout_" + name
            checks.append(f"{variable}: {name} = {name}{{}}")
            expressions = [(f"sizeof({ctype})", f"#sizeof({name})"),
                           (f"_Alignof({ctype})", f"#alignof({name})")]
            expressions += [(f"offsetof({ctype},{field})",
                             f"(#cast(usize) &{variable}.{field} - #cast(usize) &{variable})") for field in members]
            for cexpr, dexpr in expressions:
                symbol = f"dyn_binding_layout_{count}"
                c.append(f"size_t {symbol}(void) {{ return {cexpr}; }}")
                declarations.append(f'extern fn {symbol} "{symbol}"() usize')
                checks.append(f'if {symbol}() != {dexpr} {{ #panic("layout: {name} {cexpr}") }}')
                count += 1
        (root / "layout.c").write_text("\n".join(c) + "\n")
        (root / "main.dyn").write_text("\n".join(declarations) + "\nfn main() {\n" + "\n".join(checks) + "\n}\n")
        subprocess.run([*shlex.split(cc), '-std=c11', '-fno-stack-protector', '-fno-sanitize=all',
                        '-c', str(root/'layout.c'), '-o', str(root/'layout.o')], check=True, timeout=60)
        output = root/'probe'
        subprocess.run([dyn, 'build', str(root), '--target', target, '--no-cache', '--quiet',
                        '--link', str(root/'layout.o'), '--output', str(output)], check=True, timeout=120)
        if execute:
            subprocess.run([str(output)], check=True, timeout=15)
        return dict(target=target, compiler=shlex.split(cc), records=len(records), checks=count,
                    status="executed" if execute else "cross-linked-only")

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("header", type=pathlib.Path)
    parser.add_argument("-o", "--output", type=pathlib.Path)
    parser.add_argument("--report", type=pathlib.Path, help="write structured omissions and verification status")
    parser.add_argument("--verify-layout", metavar="DYN_TARGET", help="compile a C/Dyn record-layout probe")
    parser.add_argument("--cc", default=os.environ.get("CC", "cc"), help="target C compiler command and flags")
    parser.add_argument("--dyn", default=os.environ.get("DYN", "dyn"), help="Dyn compiler executable")
    parser.add_argument("--run-layout", action="store_true", help="execute the layout probe on a compatible host")
    arguments = parser.parse_args()
    if arguments.run_layout and not arguments.verify_layout:
        parser.error("--run-layout requires --verify-layout")
    try:
        source = arguments.header.read_text(encoding="utf-8")
        generated = generate(source)
        details = report(arguments.header, source, generated)
        if arguments.verify_layout:
            try:
                details["layout_verification"] = verify_layout(arguments.header, source, generated,
                    arguments.verify_layout, arguments.cc, arguments.dyn, arguments.run_layout)
            except (ValueError, subprocess.SubprocessError, OSError) as error:
                details["layout_verification"] = dict(status="failed", reason=str(error))
                if arguments.report:
                    arguments.report.write_text(json.dumps(details, indent=2) + "\n")
                raise ValueError(f"layout verification failed: {error}")
        if arguments.report:
            arguments.report.write_text(json.dumps(details, indent=2) + "\n")
    except (OSError, ValueError) as error:
        print(f"dyn-bind: {error}", file=sys.stderr)
        return 1
    try:
        if arguments.output:
            arguments.output.write_text(generated, encoding="utf-8")
        else:
            sys.stdout.write(generated)
    except OSError as error:
        print(f"dyn-bind: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
