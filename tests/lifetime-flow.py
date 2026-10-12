#!/usr/bin/env python3
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
DYN=str(Path(os.environ.get('DYN','build/dyn')).resolve())

class LifetimeFlow(unittest.TestCase):
    def test_proven_escapes_and_invalidation(self):
        cases=[
            ('struct B { bad: []u8, good: []u8 } fn good(input: []u8) []u8 { x:[8]u8=[] b:=B{bad:x[..],good:input} c:=b return c.good }',True),
            ('fn replace(out:**i32, input:*i32) { out.*=input } fn good(input:*i32) *i32 { x:i32=1 p:=&x replace(&p,input) return p }',True),
            ('fn good(input:*i32) *i32 { x:i32=1 p:=&x q:=&p q.*=input return p }',True),
            ('fn bad() *i32 { x:i32=1 p:=&x return p }',False),
            ('fn bad() []u8 { x:[8]u8=[] p:=x[..] q:=p return q }',False),
            ('struct B { data: []u8 } fn bad() B { x:[8]u8=[] b:=B{data:x[..]} return b }',False),
            ('struct B { data: []u8 } fn bad() B { x:[8]u8=[] b:=B{} b.data=x[..] return b }',False),
            ('struct B { bad: []u8, good: []u8 } fn good(input: []u8) []u8 { x:[8]u8=[] b:=B{bad:x[..],good:input} return b.good }',True),
            ('fn good(input: []u8) []u8 { p:=input return p }',True),
            ('fn good(input: *i32) *i32 { x:i32=1 p:=&x p=input return p }',True),
            ('use "std/mem"\nfn bad() { storage:[64]u8=[] a:=mem.arena_from_buffer(storage[..]) p:=mem.arena_push(&a,8,1) mem.arena_reset(&a) p.*=7 }',False),
            ('use "std/mem"\nfn good() { storage:[64]u8=[] a:=mem.arena_from_buffer(storage[..]) _=mem.arena_push(&a,8,1) mem.arena_reset(&a) p:=mem.arena_push(&a,8,1) p.*=7 }',True),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'main.dyn'
            for source,valid in cases:
                path.write_text(source+'\nfn main() {}\n')
                result=subprocess.run([DYN,'check',directory,'--no-cache','--diagnostics','json'],capture_output=True,text=True)
                with self.subTest(source=source):
                    self.assertEqual(result.returncode,0 if valid else 1,result.stderr)
                    if not valid: self.assertTrue('borrows function-local' in result.stderr or 'after arena_reset' in result.stderr,result.stderr)

if __name__=='__main__': unittest.main()
