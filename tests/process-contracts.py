#!/usr/bin/env python3
"""Drain >pipe capacity concurrently, explicit environment, exact limits, arena failure."""
import os,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn')).resolve())
with tempfile.TemporaryDirectory(prefix='dyn-process-') as tmp:
 p=Path(tmp)
 # Alternating output writes exceed kernel pipe capacity on both streams.
 (p/'child.py').write_text('import os\nfor i in range(128):\n os.write(1,b"o"*4096)\n os.write(2,b"e"*4096)\nassert os.environ["DYN_PROCESS_VALUE"]=="hello world"\n')
 (p/'main.dyn').write_text('''use "std/process" process
use "std/mem" mem
fn main() {
 allocated := mem.arena_create(2*1024*1024) if !allocated.ok { #panic("arena") }
 defer _ = mem.arena_release(&allocated.arena)
 output := mem.arena_push_uninit(&allocated.arena,524288,1)[..524288]
 errors := mem.arena_push_uninit(&allocated.arena,524288,1)[..524288]
 args: [3][]const u8 = ["python3","-S","CHILD"]
 environment: [1][]const u8 = ["DYN_PROCESS_VALUE=hello world"]
 options := process.options() options.environment = environment[..]
 result := process.capture(&allocated.arena,"PYTHON",args[..],options,output,errors,10000)
 if !result.ok || result.exit.code != 0 || #len(result.output) != 524288 || #len(result.errors) != 524288 { #panic("concurrent drain / exact fit") }
 for byte in result.output { if byte != 'o' { #panic("stdout bytes") } }
 for error_byte in result.errors { if error_byte != 'e' { #panic("stderr bytes") } }
 tiny: [1]u8 = [] small := mem.arena_from_buffer(tiny[..])
 failed := process.spawn(&small,"PYTHON",args[..],options)
 if failed.ok || failed.error != -28 || small.offset != 0 { #panic("arena capacity") }
 options.input = 4
 captured := process.capture(&allocated.arena,"PYTHON",args[..],options,output,errors,10000)
 if captured.ok || captured.error != -9 { #panic("capture reused closed stdin descriptor") }
 options.input = 2147483647
 invalid := process.spawn(&allocated.arena,"PYTHON",args[..],options)
 if invalid.ok || invalid.error != -9 { #panic("invalid redirect") }
}
'''.replace('CHILD',str(p/'child.py')).replace('PYTHON',__import__('sys').executable))
 for mode in ([],['--release']):
  subprocess.run([DYN,'build',str(p),'--quiet','--no-cache','--output',str(p/'run'),*mode],cwd=ROOT,check=True)
  subprocess.run([str(p/'run')],check=True,timeout=20)
print('PASS process concurrent 1MiB output, exact limits, environment, invalid handles, arena exhaustion, debug/release')
