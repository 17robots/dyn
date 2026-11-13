#!/usr/bin/env python3
"""Caller-owned SQLite serialization is explicit; default opening stays unchanged."""
import os,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];DYN=Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve()
SOURCE=r'''
use "std/io"
use "vendor/sqlite" sqlite
extern fn db_mutex "sqlite3_db_mutex"(database:rawptr) rawptr
extern fn threadsafe "sqlite3_threadsafe"() i32
fn main() {
  scratch:[128]u8
  defaults:=sqlite.open_with_options(":memory:",scratch[..],sqlite.OpenOptions{})
  if io.failed(defaults.failure) { #panic("default open") }
  defer _=sqlite.close(defaults.database)
  if threadsafe()==1 && db_mutex(defaults.database)==nil { #panic("default changed") }
  owned:=sqlite.open_with_options(":memory:",scratch[..],sqlite.OpenOptions{caller_serialized:true})
  if io.failed(owned.failure) || db_mutex(owned.database)!=nil { #panic("caller serialized flag") }
  defer _=sqlite.close(owned.database)
  if sqlite.execute(owned.database,"CREATE TABLE counter(value INTEGER); INSERT INTO counter VALUES(0); UPDATE counter SET value=value+1",scratch[..])!=0 { #panic("execute") }
  prepared:=sqlite.prepare(owned.database,"SELECT value FROM counter")
  if io.failed(prepared.failure) { #panic("prepare") }
  statement:=prepared.statement
  defer _=sqlite.finalize(&statement)
  if sqlite.step(&statement).state!=sqlite.State.Row || sqlite.column(&statement,0).integer!=1 { #panic("query") }
  if !io.failed(sqlite.open_with_options("bad\0name",scratch[..],sqlite.OpenOptions{caller_serialized:true}).failure) { #panic("nul") }
  if !io.failed(sqlite.open_with_options(":memory:",scratch[..0],sqlite.OpenOptions{caller_serialized:true}).failure) { #panic("capacity") }
  if !io.failed(sqlite.open_with_options("/no-such-dyn-test-directory-7341/file.sqlite3",scratch[..],sqlite.OpenOptions{caller_serialized:true}).failure) { #panic("provider error") }
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-sqlite-open-') as tmp:
    p=Path(tmp);(p/'main.dyn').write_text(SOURCE)
    for mode in ['--debug','--release']:
        out=p/'app';subprocess.run([str(DYN),'build',str(p),mode,'--quiet','--no-cache','--output',str(out)],check=True,env={**os.environ,'DYN_SDK':str(ROOT)});subprocess.run([str(out)],check=True)
    # A failed provider open can return an owned handle. Close it once, never
    # close a null handle, and pass only the documented per-connection flags.
    stub=p/'provider.c'
    stub.write_text('''#include <stdint.h>
static int mode, closes, flags_ok;
void set_mode(int value){mode=value;}
int close_count(void){return closes;}
int flag_check(void){return flags_ok;}
int sqlite3_open_v2(const char *name, void **out, int flags, const char *vfs){(void)name;flags_ok=(flags==0x8006 && vfs==0);*out=mode?0:(void *)(uintptr_t)0x123;return 14;}
int sqlite3_close(void *db){if(db==(void *)(uintptr_t)0x123)closes++;return 0;}
''')
    obj=p/'provider.o';subprocess.run(['cc','-c',str(stub),'-o',str(obj)],check=True)
    (p/'main.dyn').write_text(r'''use "vendor/sqlite" sqlite
use "std/io"
extern fn set_mode(value:i32)
extern fn close_count() i32
extern fn flag_check() i32
fn main(){
 scratch:[64]u8
 first:=sqlite.open_with_options(":memory:",scratch[..],sqlite.OpenOptions{caller_serialized:true})
 if !io.failed(first.failure) || first.code!=14 || first.database!=nil || close_count()!=1 || flag_check()!=1 { #panic("owned failure cleanup") }
 set_mode(1)
 second:=sqlite.open_with_options(":memory:",scratch[..],sqlite.OpenOptions{caller_serialized:true})
 if !io.failed(second.failure) || second.code!=14 || close_count()!=1 { #panic("null failure cleanup") }
}
''')
    for mode in ['--debug','--release']:
        out=p/'failure';subprocess.run([str(DYN),'build',str(p),mode,'--quiet','--no-cache','--link',str(obj),'--output',str(out)],check=True,env={**os.environ,'DYN_SDK':str(ROOT)});subprocess.run([str(out)],check=True)
print('PASS SQLite open options: unchanged default, explicit connection mutex policy, query and failure cleanup paths (debug/release)')
