#!/usr/bin/env python3
"""Rewrite Dyn sources for the 2026-11-13 standardization (docs/migrations/standard-20261113.md).

Mechanical rewrites only:
  - `name: [N]T = []` declarations lose the redundant `= []`; a declaration
    without an initializer is already zero.
  - Renamed std functions: mem.arena_create* is mem.arena_alloc*, json.make_*
    is json.push_*, ui/box's create is push_state, and the byte searches that
    std/strings forwarded (equal, find*, contains, starts_with, ends_with) and
    testing.equal_bytes are called through std/bytes. Import aliases are
    followed per module directory, and `use "std/bytes"` is added where needed.
  - fmt.write* and html.write_escaped return nothing now (check the buffer's
    failed field once instead), so `_ = fmt.write(...)` loses its `_ = `.

The compiler reports the rest with a message that names the fix: `.{...}`
literals, `#cast` from an integer to an enum, chained comparisons, shadowed
locals and pointer `#bitcast`.

Usage: tools/migrate-standard.py PATH... (directories are walked for .dyn files;
--embedded also rewrites Dyn code embedded in .py and .md files)."""
import pathlib
import re
import sys

# A typed declaration whose whole initializer is [].
DECLARATION = re.compile(r'(?m)^(?P<lead>[ \t]*(?:pub )?[A-Za-z_][A-Za-z0-9_]*[ \t]*:[ \t]*[^\n=]+?)[ \t]*=[ \t]*\[\](?P<tail>[ \t]*(?://.*)?)$')
# The same inside a Python or Markdown string: stop at a newline escape or quote.
EMBEDDED = re.compile(r'(?P<lead>(?<![\w.])[a-z_][A-Za-z0-9_]*\s*:\s*\[[^\n=\'"{}]*?)\s*=\s*\[\](?=\\n|\'|"|\n|$|\s*\}|\s+fn\b|;)')


def rewrite(text, embedded):
    lines = []
    for line in text.split('\n'):
        stripped = line.lstrip()
        if stripped.startswith('const ') or stripped.startswith('pub const '):
            lines.append(line)
            continue
        if embedded:
            line = EMBEDDED.sub(lambda m: m.group('lead'), line)
        elif '// error' not in line:
            line = DECLARATION.sub(lambda m: m.group('lead') + m.group('tail'), line)
        lines.append(line)
    return '\n'.join(lines)


USE = re.compile(r'"([^"]+)"(?:[ \t]+([A-Za-z_][A-Za-z0-9_]*))?')
RENAMES = {
    'std/mem': [('arena_try_create_bounded', 'arena_try_alloc_bounded'), ('arena_try_create', 'arena_try_alloc'),
                ('arena_create_bounded', 'arena_alloc_bounded'), ('arena_create', 'arena_alloc'),
                ('ArenaCreation', 'ArenaAllocation')],
    'std/encoding/json': [('make_' + kind, 'push_' + kind) for kind in ('null', 'bool', 'number', 'string', 'array', 'object')],
    'std/ui/box': [('create', 'push_state')],
}
TO_BYTES = {'std/strings': ['equal', 'find', 'find_byte', 'find_last', 'find_last_byte', 'contains', 'starts_with', 'ends_with'],
            'std/testing': [('equal_bytes', 'equal')]}


VOIDED = {'std/fmt': ['write', 'write_byte', 'write_u64', 'write_i64', 'write_bool', 'write_f64', 'write_f64_shortest',
                       'write_padding', 'write_quoted', 'write_u64_width', 'write_values'],
          'std/html': ['write_escaped']}


def module_aliases(directory):
    """Import path -> every alias it has in a module directory."""
    aliases = {}
    for path in sorted(directory.glob('*.dyn')):
        for line in path.read_text().split('\n'):
            stripped = line.strip()
            if not stripped.startswith('use '):
                continue
            for module, alias in USE.findall(stripped):
                aliases.setdefault(module, set()).add(alias or module.rsplit('/', 1)[-1])
    return aliases


def rename_calls(path, aliases):
    text = path.read_text()
    result = text
    for module, pairs in RENAMES.items():
        for alias in aliases.get(module, ()):
            for old, new in pairs:
                result = re.sub(r'(?<![\w.])' + re.escape(alias) + r'\.' + re.escape(old) + r'\b', alias + '.' + new, result)
    for module, names in VOIDED.items():
        for alias in aliases.get(module, ()):
            for name in names:
                result = re.sub(r'_ = (' + re.escape(alias) + r'\.' + name + r'\()', r'\1', result)
    moved = False
    byte_alias = sorted(aliases.get('std/bytes', {'bytes'}))[0]
    for module, names in TO_BYTES.items():
        for alias in aliases.get(module, ()):
            for name in names:
                old, new = name if isinstance(name, tuple) else (name, name)
                pattern = r'(?<![\w.])' + re.escape(alias) + r'\.' + re.escape(old) + r'\('
                if re.search(pattern, result):
                    moved = True
                    result = re.sub(pattern, byte_alias + '.' + new + '(', result)
    if moved and 'std/bytes' not in aliases:
        lines = result.split('\n')
        last_use = max((i for i, line in enumerate(lines) if line.startswith('use ')), default=-1)
        lines.insert(last_use + 1, 'use "std/bytes"')
        result = '\n'.join(lines)
        aliases['std/bytes'] = {'bytes'}
    if result != text:
        path.write_text(result)
        return True
    return False


def files(paths, embedded):
    suffixes = {'.dyn'} | ({'.py', '.md'} if embedded else set())
    for path in map(pathlib.Path, paths):
        if path.is_dir():
            yield from (p for p in sorted(path.rglob('*')) if (p.suffix in suffixes or p.name.endswith('.dyn.in')) and p.is_file())
        elif path.suffix in suffixes or path.name.endswith('.dyn.in'):
            yield path


def main(arguments):
    embedded = '--embedded' in arguments
    paths = [a for a in arguments if a != '--embedded']
    if not paths:
        print(__doc__)
        return 2
    changed = 0
    for path in files(paths, False):
        aliases = module_aliases(path.parent)
        if rename_calls(path, aliases):
            print(path)
            changed += 1
    for path in files(paths, embedded):
        if path.suffix != '.dyn':
            aliases = {}
            for module, alias in USE.findall('\n'.join(re.findall(r'use ("[^"]+"(?:[ \t]+\w+)?)', path.read_text()))):
                aliases.setdefault(module, set()).add(alias or module.rsplit('/', 1)[-1])
            if rename_calls(path, aliases):
                print(path)
                changed += 1
        text = path.read_text()
        result = rewrite(text, embedded and path.suffix != '.dyn')
        if result != text:
            path.write_text(result)
            changed += 1
            print(path)
    print(f'{changed} files changed', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
