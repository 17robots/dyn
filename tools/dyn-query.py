#!/usr/bin/env python3
"""Build and query a compiler-resolved SQLite program database."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def compiler_path(value):
    return str(Path(shutil.which(value) or value).resolve())


def build(module, output, dyn, target):
    compiler_digest = digest(dyn)
    result = subprocess.run([dyn, 'query', str(module.resolve()), '--target', target,
                             '--no-cache', '--diagnostics', 'json'], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr or 'compiler query failed')
    report = json.loads(result.stdout)
    sources = {p: digest(p) for p in report['sources']}
    directories = {str(Path(p).parent): sorted(f.name for f in Path(p).parent.glob('*.dyn')) for p in sources}
    # Discover dependencies first, then index again between source checks. This
    # rejects ordinary edits during extraction rather than labeling old ASTs with
    # new source hashes. Keep the workspace quiescent while building a snapshot.
    verified = subprocess.run([dyn, 'query', str(module.resolve()), '--target', target,
                               '--no-cache', '--diagnostics', 'json'], capture_output=True, text=True)
    if verified.returncode:
        raise RuntimeError(verified.stderr or 'compiler query failed')
    report = json.loads(verified.stdout)
    if set(report['sources']) != set(sources) or any(digest(p) != h for p, h in sources.items()):
        raise RuntimeError('sources changed during indexing; rerun')
    if any(sorted(f.name for f in Path(p).glob('*.dyn')) != names for p, names in directories.items()):
        raise RuntimeError('module files changed during indexing; rerun')
    if digest(dyn) != compiler_digest:
        raise RuntimeError('compiler changed during indexing; rerun')
    report['compiler_sha256'] = compiler_digest
    report['compiler_path'] = dyn
    report['source_sha256'] = sources
    report['source_directories'] = directories
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.dyn-query-', dir=output.parent)
    os.close(fd)
    try:
        with sqlite3.connect(temporary) as db:
            db.execute('create table metadata(key text primary key, value text not null)')
            for key, value in report.items():
                if key not in ('symbols', 'references', 'calls', 'types', 'dependencies', 'fields', 'parameters'):
                    db.execute('insert into metadata values (?,?)', (key, json.dumps(value)))
            schemas = {
                'symbols': 'id text primary key, kind text, name text, resolved_name text, type_id integer, type text, public integer, path text, line integer, column integer, source_comments text',
                'references': 'symbol_id text, type_id integer, path text, line integer, column integer',
                'calls': 'caller_id text, callee_id text, kind text, effects text, path text, line integer, column integer',
                'types': 'id integer primary key, name text',
                'dependencies': 'source text, dependency text',
                'fields': 'owner_type integer, position integer, type_id integer, name text',
                'parameters': 'function_id text, position integer, type_id integer, name text',
            }
            for table, schema in schemas.items():
                db.execute(f'create table "{table}" ({schema})')
                columns = [part.strip().split()[0] for part in schema.split(',')]
                placeholders = ','.join('?' for _ in columns)
                db.executemany(f'insert into "{table}" values ({placeholders})',
                               [[row.get(c) for c in columns] for row in report[table]])
            db.execute('create index refs_symbol on "references"(symbol_id)')
            db.execute('create index calls_callee on calls(callee_id)')
            db.execute('create index symbols_name on symbols(name)')
        # Refuse a snapshot if files changed during extraction/database construction.
        if any(digest(p) != h for p, h in sources.items()):
            raise RuntimeError('sources changed during indexing; rerun')
        os.replace(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)


def query(path, sql, parameters):
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute('pragma query_only=on')
        meta = {r['key']: json.loads(r['value']) for r in db.execute('select * from metadata')}
        if digest(meta['compiler_path']) != meta['compiler_sha256']:
            raise RuntimeError('stale database: compiler changed; rebuild index')
        for directory, expected_files in meta.get('source_directories', {}).items():
            if sorted(p.name for p in Path(directory).glob('*.dyn')) != expected_files:
                raise RuntimeError('stale database: module files changed: ' + directory)
        for source, expected in meta['source_sha256'].items():
            if digest(source) != expected:
                raise RuntimeError('stale database: source changed: ' + source)
        allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}
        db.set_authorizer(lambda action, *_: sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY)
        return [dict(row) for row in db.execute(sql, parameters)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    default = Path(__file__).resolve().with_name('dyn')
    parser.add_argument('--dyn', default=os.environ.get('DYN', str(default) if default.exists() else 'dyn'))
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('build')
    create.add_argument('module', type=Path)
    create.add_argument('--output', type=Path, required=True)
    create.add_argument('--target', default='x86_64-linux')
    read = commands.add_parser('sql')
    read.add_argument('database', type=Path)
    read.add_argument('statement')
    read.add_argument('parameters', nargs='*')
    for command in ('symbol', 'callers', 'references'):
        sub = commands.add_parser(command)
        sub.add_argument('database', type=Path)
        sub.add_argument('name')
    args = parser.parse_args()
    try:
        if args.command == 'build':
            build(args.module, args.output, compiler_path(args.dyn), args.target)
            print(json.dumps({'database': str(args.output), 'status': 'indexed'}))
        else:
            statements = {
                'symbol': 'select * from symbols where name=?',
                'callers': 'select c.*,s.name as caller from calls c left join symbols s on s.id=c.caller_id where c.callee_id in (select id from symbols where name=?)',
                'references': 'select r.* from "references" r join symbols s on s.id=r.symbol_id where s.name=?',
            }
            sql = args.statement if args.command == 'sql' else statements[args.command]
            params = args.parameters if args.command == 'sql' else [args.name]
            print(json.dumps(query(args.database, sql, params), indent=2))
    except (OSError, RuntimeError, sqlite3.Error, ValueError) as error:
        parser.exit(1, f'error: {error}\n')


if __name__ == '__main__':
    main()
