#!/usr/bin/env python3
"""DNS answer ownership and CNAME chains through the public parser."""
import os, struct, subprocess, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn')).resolve())
def name(s): return b''.join(bytes([len(x)])+x.encode() for x in s.split('.'))+b'\0'
def rr(owner,kind,data): return name(owner)+struct.pack('!HHIH',kind,1,60,len(data))+data
def packet(records): return struct.pack('!6H',7,0x8180,1,len(records),0,0)+name('example.test')+struct.pack('!HH',1,1)+b''.join(records)
a=lambda owner:rr(owner,1,b'\1\2\3\4')
c=lambda owner,target:rr(owner,5,name(target))
cases=[('unrelated',[a('other.test')],0,True),('direct',[a('EXAMPLE.test')],1,True),('chain',[c('example.test','alias.test'),a('alias.test')],1,True),('unordered',[a('final.test'),c('alias.test','final.test'),c('example.test','alias.test')],1,True),('injection',[c('other.test','alias.test'),a('alias.test')],0,True),('cycle',[c('example.test','alias.test'),c('alias.test','example.test')],0,False),('conflict',[c('example.test','one.test'),c('example.test','two.test')],0,False),('compressed',[b'\xc0\x0c'+struct.pack('!HHIH',1,1,60,4)+b'\1\2\3\4'],1,True),('label_boundary',[bytes([12])+b'example.test'+b'\0'+struct.pack('!HHIH',1,1,60,4)+b'\1\2\3\4'],0,True),('malformed_alias',[rr('example.test',5,name('alias.test')+b'x')],0,False)]
with tempfile.TemporaryDirectory() as tmp:
 p=Path(tmp)
 source='use "std/net/dns" dns\n'
 for label,records,count,ok in cases:
  data=packet(records)
  source+='fn case_'+label.replace('-','_')+'() { data: ['+str(len(data))+']u8 = ['+','.join(map(str,data))+'] addresses: [4]dns.Ipv4 = [] result := dns.parse_ipv4(data[..],7,"example.test",addresses[..])\n'
  source+=f'if result.ok != {str(ok).lower()} || result.count != {count} {{ #panic("{label}") }} }}\n'
 source+='fn main() { '+ ' '.join('case_'+x[0].replace('-','_')+'()' for x in cases)+' }\n';(p/'main.dyn').write_text(source)
 for mode in ([],['--release']):
  subprocess.run([DYN,'build',str(p),'--quiet','--no-cache','--output',str(p/'run'),*mode],cwd=ROOT,check=True)
  subprocess.run([str(p/'run')],check=True)
print('PASS DNS owner and CNAME contracts, debug/release')
