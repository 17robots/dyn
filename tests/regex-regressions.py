#!/usr/bin/env python3
"""Counted repetition, capture priority, and bounded regex execution regressions."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT / 'build' / ('dyn-release.exe' if os.name == 'nt' else 'dyn-release'))).resolve()
SOURCE = r'''use "std/text/regex" regex
use "std/mem" memory
use "std/io" io
fn require(ok:bool,message:[]const u8){ if !ok { #panic(message) } }
fn compile(arena:*memory.Arena,pattern:[]const u8) regex.Program {
  result:=regex.compile(arena,pattern)
  require(result.ok,pattern)
  return result.value
}
fn check(pattern:[]const u8,text:[]const u8,expected:usize,matched:bool){
  arena:memory.Arena
  program:=compile(&arena,pattern)
  result:=regex.find(program,text)
  require(result.ok && result.value.ok==matched && (!matched || result.value.end==expected),pattern)
}
fn main(){
  check("^a{1,}$","aaaaaaaaaaaaaaaa",16,true)
  check("^a{0,}$","aaaaaaaaaaaaaaaa",16,true)
  check("a{4}","aaaaaaaa",4,true)
  check("^a{20,}$","aaaaaaaaaaaaaaaaaaaaaaaa",24,true)
  check("a{1,6}","aaaaaaaa",6,true)
  check("^a{0}$","",0,true)
  check("^a{0,2}$","aaa",0,false)
  check("(a|aa)","aa",1,true)
  check("(aa|a)","aa",2,true)
  check("(a?)*b","aaab",4,true)
  check("(a*)*b","aaab",4,true)
  check("a*ab","aaaab",5,true)
  check("^a|b","xb",2,true)
  arena:memory.Arena
  invalid:=regex.compile(&arena,"a{18446744073709551616}")
  require(!invalid.ok && invalid.detail==regex.CompileError.Syntax,"count overflow")
  invalid=regex.compile(&arena,"a{1,18446744073709551616}")
  require(!invalid.ok && invalid.detail==regex.CompileError.Syntax,"maximum overflow")
  program:=compile(&arena,"(a)*")
  input:=memory.push_array(u8,&arena,100000)
  for i in 0..#len(input){input[i]='a'}
  result:=regex.find(program,input)
  require(result.ok && result.value.ok && result.value.end==100000,"long repetition")
  require(result.captures[0].ok && result.captures[0].start==99999 && result.captures[0].end==100000,"last capture")
  program=compile(&arena,"(a*)a")
  result=regex.find(program,"aaaa")
  require(result.value.ok && result.value.end==4 && result.captures[0].end==3,"greedy backtracking capture")
  program=compile(&arena,"(a)b|(a)c")
  result=regex.find(program,"ac")
  require(result.value.ok && !result.captures[0].ok && result.captures[1].ok && result.captures[1].end==1,"failed branch capture rollback")
  program=compile(&arena,"(a){200}")
  long_input:[200]u8=[]
  for i in 0..200 {long_input[i]='a'}
  result=regex.find(program,long_input[..])
  require(result.ok && result.value.ok && result.value.end==200 && result.captures[0].start==199,"arena workspace")
  program=compile(&arena,"(a)*")
  result=regex.find(program,"aaa")
  require(result.ok && result.value.end==3 && result.captures[0].start==2,"reused workspace")
  _=io.println(io.stdout(),"regex passed")
}
'''

with tempfile.TemporaryDirectory(prefix='dyn-regex-') as temporary:
    work = Path(temporary)
    project = work / 'project'
    project.mkdir()
    (project / 'main.dyn').write_text(SOURCE, encoding='utf-8')
    for mode in ('--debug', '--release'):
        output = work / ('regex.exe' if os.name == 'nt' else 'regex')
        subprocess.run([str(DYN), 'build', str(project), '--no-cache', '--quiet', '--output', str(output), mode], cwd=work, check=True, timeout=120)
        result = subprocess.run([str(output)], cwd=work, capture_output=True, timeout=30)
        assert result.returncode == 0, (result.stdout, result.stderr)
        assert result.stdout == b'regex passed\n', result.stdout
print('PASS regex counts, captures, arena workspace and long repetition (debug/release)')
