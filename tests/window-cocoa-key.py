#!/usr/bin/env python3
"""Portable production UTF-16 scalar conversion; AppKit runtime remains separate."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[1]
SOURCE = r'''
#include "cocoa_key.h"
#include <assert.h>
#include <stdio.h>
int main(void) {
 const uint16_t ascii[]={'A'}, option[]={0xe9}, caps[]={0x3a9};
 const uint16_t astral[]={0xd83d,0xde00};
 const uint16_t multiple[]={'a','b'}, decomposed[]={'e',0x301};
 const uint16_t high[]={0xd800}, low[]={0xdc00}, reversed[]={0xdc00,0xd800};
 const uint16_t invalid_pair[]={0xd800,'a'}, overlong[]={0xd83d,0xde00,'a'};
 const uint16_t escape[]={27}, c1[]={0x85}, function[]={0xf700}, space[]={' '};
 assert(cocoa_key_scalar(ascii,1)=='A');
 assert(cocoa_key_scalar(option,1)==0xe9);
 assert(cocoa_key_scalar(caps,1)==0x3a9);
 assert(cocoa_key_scalar(astral,2)==0x1f600);
 assert(cocoa_key_scalar(space,1)==' ');
 assert(!cocoa_key_scalar(NULL,0));
 assert(!cocoa_key_scalar(ascii,0));
 assert(!cocoa_key_scalar(multiple,2));
 assert(!cocoa_key_scalar(decomposed,2));
 assert(!cocoa_key_scalar(high,1)); assert(!cocoa_key_scalar(low,1));
 assert(!cocoa_key_scalar(reversed,2)); assert(!cocoa_key_scalar(invalid_pair,2));
 assert(!cocoa_key_scalar(overlong,3));
 assert(!cocoa_key_scalar(escape,1)); assert(!cocoa_key_scalar(c1,1));
 assert(!cocoa_key_scalar(function,1));
 puts("PASS Cocoa key UTF16 scalar conversion (portable; AppKit runtime untested)");
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-cocoa-key-') as temporary:
    work=Path(temporary)
    source=work/'scalar.c'
    source.write_text(SOURCE)
    output=work/('scalar.exe' if os.name=='nt' else 'scalar')
    subprocess.run([*shlex.split(os.environ.get('CC','cc')),'-std=c11','-Wall','-Wextra','-Werror','-I'+str(ROOT/'vendor/window/native'),str(source),'-o',str(output)],check=True)
    subprocess.run([str(output)],check=True)
