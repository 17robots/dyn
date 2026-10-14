"""Recognizes batch syntax diagnostics reported by the handwritten parser.

Reference compilers built on Tree-sitter report invalid sources differently, so
differential checks require only that both reject them."""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
_messages = sorted({m for name in ('parser.c', 'source.inc')
                    for m in re.findall(r'fail\(&?p, [^,]+, "([^"]+)"', (HERE/name).read_text())})
# dyn_source_report_syntax rewrites the generic token messages.
_pattern = re.compile(r"^(expected '.*', found |unexpected |(%s)(, found |$))" %
                      '|'.join(map(re.escape, _messages)))


def messages(stderr):
    text = stderr.decode() if isinstance(stderr, bytes) else stderr
    found = []
    for line in text.split('\n'):
        line = line.strip()
        if line.startswith('{'):
            try:
                found.append(json.loads(line).get('message', ''))
            except ValueError:
                return None
        elif ': error: ' in line:
            found.append(re.sub(r' \[range [^]]*\]$', '', line.split(': error: ', 1)[1]))
    return found


def is_syntax_rejection(returncode, stderr):
    """Only parser diagnostics (at most 20, from recovery) and a user-error exit."""
    found = messages(stderr)
    return returncode == 1 and found is not None and 1 <= len(found) <= 20 and \
        all(_pattern.match(m) or m == 'syntax nesting exceeds 1024 tree levels' for m in found)


def _location(stderr):
    text = stderr.decode() if isinstance(stderr, bytes) else stderr
    match = re.search(r'"range":\{"start":\{"line":(\d+),"column":(\d+)\}', text) or \
        re.search(r'\.dyn:(\d+):(\d+): error: ', text)
    return (int(match.group(1)), int(match.group(2))) if match else None


def _string_spans_line(source, location):
    """The pinned grammar lets whitespace and comments precede a closing quote,
    so Tree-sitter accepts string literals that span lines."""
    if not location:
        return False
    lines = source.split(b'\n')
    line, column = location
    if line > len(lines):
        return False
    offset = sum(len(item) + 1 for item in lines[:line - 1]) + column - 1
    if source[offset:offset + 1] != b'"':
        return False
    end = offset + 1
    while end < len(source) and source[end:end + 1] not in (b'"', b'\n'):
        end += 2 if source[end:end + 1] == b'\\' else 1
    return source[end:end + 1] == b'\n'


def equivalent(reference, candidate, source=b''):
    """(returncode, stdout, stderr) pairs: identical, or both reject invalid syntax.

    Tree-sitter references skip syntax errors in files whose #target excludes the
    host; the handwritten parser cannot read the target of an unparsable file."""
    if reference == candidate:
        return True
    # The pinned lexer can choose a comment inside a string literal at its start
    # or after an escape, rejecting valid sources such as "//x".
    if reference[0] == 1 and candidate[0] == 0 and \
            re.search(rb'"(?:[^"\\\n]|\\.)*(//|/\*)', source):
        return True
    if not is_syntax_rejection(candidate[0], candidate[2]):
        return False
    # Tree-sitter references may also exit 2 without a diagnostic, e.g. for a
    # truncated import path.
    if reference[0] == 1 or (reference[0] == 2 and not reference[2]):
        return True
    if reference[0] != 0:
        return False
    if re.search(rb'(?m)^#target\(', source):
        return True
    # The depth limit is measured on the compact tree, whose bound can exceed
    # the raw Tree-sitter depth by one terminal edge.
    if messages(candidate[2]) == ['syntax nesting exceeds 1024 tree levels']:
        return True
    # Tree-sitter accepts invalid UTF-8 inside literals and comments.
    if 'invalid UTF-8' in messages(candidate[2]):
        try:
            source.decode('utf-8')
        except UnicodeDecodeError:
            return True
        return False
    return messages(candidate[2])[:1] == ['unterminated literal'] and \
        _string_spans_line(source, _location(candidate[2]))
