#!/usr/bin/env python3
"""Differential byte searches, arbitrary alignment, and inaccessible boundaries."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn')).resolve())
SOURCE = r'''use "std/bytes" bytes
fn expect(ok: bool) { if !ok { #panic("byte search differential") } }
fn scalar(h: []const u8, n: []const u8) usize {
  if #len(n)==0 { return 0 }
  if #len(n)>#len(h) { return #len(h) }
  for i in 0..#len(h)-#len(n)+1 {
    matched:=true
    for j in 0..#len(n) { if h[i+j]!=n[j] { matched=false break } }
    if matched { return i }
  }
  return #len(h)
}
fn verify(h: []const u8, n: []const u8) {
  at:=scalar(h,n)
  expect(bytes.find(h,n)==at)
  expect(bytes.contains(h,n)==(#len(n)==0 || at<#len(h)))
}
fn main() {
  empty: []const u8
  expect(bytes.find_byte(empty,0)==0)
  verify(empty,empty) verify(empty,"a") verify("a",empty)
  backing: [160]u8
  one: [1]u8
  for offset in 0..16 {
    for size in 0..65 {
      h:=backing[offset..offset+size]
      for target in 0..256 {
        one[0]=#cast(u8,target)
        for i in 0..size { h[i]=#cast(u8,(target+1)%256) }
        expect(bytes.find_byte(h,one[0])==size)
        verify(h,one[..])
        for at in 0..size {
          h[at]=one[0]
          expect(bytes.find_byte(h,one[0])==at)
          verify(h,one[..])
          h[at]=#cast(u8,(target+1)%256)
        }
      }
    }
  }
  seed:u32=12345
  needle_storage:[40]u8
  for trial in 0..20000 {
    seed=#wrap(seed*1664525+1013904223)
    offset:=#cast(usize,seed%16)
    size:=#cast(usize,(seed>>8)%129)
    for i in 0..size { seed=#wrap(seed*1664525+1013904223) backing[offset+i]=#cast(u8,seed>>24) }
    seed=#wrap(seed*1664525+1013904223)
    noffset:=#cast(usize,seed%8)
    nsize:=#cast(usize,(seed>>8)%33)
    for i in 0..nsize { seed=#wrap(seed*1664525+1013904223) needle_storage[noffset+i]=#cast(u8,seed>>24) }
    if nsize<=size && trial%2==0 {
      at:=#cast(usize,seed)%(size-nsize+1)
      for i in 0..nsize { needle_storage[noffset+i]=backing[offset+at+i] }
    }
    verify(backing[offset..offset+size],needle_storage[noffset..noffset+nsize])
  }
  for i in 0..160 { backing[i]='a' }
  for i in 0..40 { needle_storage[i]='a' }
  needle_storage[38]='b'
  for size in 1..129 { for nsize in 0..41 { verify(backing[..size],needle_storage[..nsize]) } }
  // Linux maps three pages, leaving both surrounding pages inaccessible.
  mapped:=#syscall(9,0,12288,0,34,-1,0)
  expect(mapped>0)
  expect(#syscall(10,mapped+4096,4096,3)==0)
  page:=(#cast(*u8,mapped+4096))[..4096]
  for i in 0..4096 { page[i]=0 }
  for size in 0..129 {
    left:=page[..size]
    right:=page[4096-size..]
    expect(bytes.find_byte(left,255)==size)
    expect(bytes.find_byte(right,255)==size)
    verify(left,"ERROR") verify(right,"ERROR")
    verify(left,page[4096..]) verify(right,page[..0])
    for nsize in 0..size+2 {
      verify(left,page[4096-nsize..])
      verify(right,page[..nsize])
    }
    if size>0 {
      right[size-1]=255
      expect(bytes.find_byte(right,255)==size-1)
      verify(right,right[size-1..])
      right[size-1]=0
    }
  }
  expect(#syscall(11,mapped,12288)==0)
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-bytes-search-') as directory:
    root = Path(directory)
    (root / 'main.dyn').write_text(SOURCE)
    for mode in ([], ['--release']):
        subprocess.run([DYN, 'build', str(root), '--quiet', '--no-cache', '--output', str(root/'run'), *mode], cwd=ROOT, check=True)
        subprocess.run([str(root/'run')], check=True, timeout=60)
print('PASS byte search differential, alignment, random needles, repetition, guard pages (debug/release)')
