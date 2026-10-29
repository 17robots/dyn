#!/usr/bin/env python3
"""Generate pinned Unicode 17 tables. Input: official UCD.zip, checksum enforced."""
import hashlib, sys, zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
raw=Path(sys.argv[1]).read_bytes()
assert hashlib.sha256(raw).hexdigest()=='2066d1909b2ea93916ce092da1c0ee4808ea3ef8407c94b4f14f5b7eb263d28e'
import io
z=zipfile.ZipFile(io.BytesIO(raw))
def text(name): return z.read(name).decode('utf-8')
def records(name):
 for line in text(name).splitlines():
  line=line.split('#')[0].strip()
  if line: yield [x.strip() for x in line.split(';')]
def span(s):
 a,_,b=s.partition('..');return range(int(a,16),int(b or a,16)+1)
categories='Cn Lu Ll Lt Lm Lo Mn Mc Me Nd Nl No Pc Pd Ps Pe Pi Pf Po Sm Sc Sk So Zs Zl Zp Cc Cf Cs Co'.split()
graphemes='Other CR LF Control Extend ZWJ Regional_Indicator Prepend SpacingMark L V T LV LVT'.split()
props=[0]*0x110000; decomposition={};ccc={};pending=None
for fields in records('UnicodeData.txt'):
 cp=int(fields[0],16);v=categories.index(fields[2])|(int(fields[3])<<5)
 if fields[1].endswith(', First>'): pending=cp
 elif fields[1].endswith(', Last>'):
  for c in range(pending,cp+1): props[c]=v
  pending=None
 else: props[cp]=v
 ccc[cp]=int(fields[3])
 if fields[5]:
  parts=fields[5].split();compat=parts[0].startswith('<')
  decomposition[cp]=(compat,[int(x,16) for x in parts[compat:]])
for f in records('auxiliary/GraphemeBreakProperty.txt'):
 for cp in span(f[0]): props[cp]|=graphemes.index(f[1])<<13
for f in records('emoji/emoji-data.txt'):
 if f[1]=='Extended_Pictographic':
  for cp in span(f[0]): props[cp]|=1<<17
for f in records('DerivedCoreProperties.txt'):
 flag={'XID_Start':1<<20,'XID_Continue':1<<21}.get(f[1],0)
 if f[1]=='InCB': flag={'Linker':1,'Consonant':2,'Extend':3}[f[2]]<<18
 if flag:
  for cp in span(f[0]): props[cp]|=flag
for f in records('PropList.txt'):
 if f[1]=='White_Space':
  for cp in span(f[0]): props[cp]|=1<<22
ranges=[];start=0
for cp in range(1,len(props)+1):
 if cp==len(props) or props[cp]!=props[start]:
  if props[start]: ranges.extend((start,cp-1,props[start]))
  start=cp
excluded=set()
for f in records('DerivedNormalizationProps.txt'):
 if f[1]=='Full_Composition_Exclusion': excluded.update(span(f[0]))
composition=sorted((parts[0],parts[1],cp) for cp,(compat,parts) in decomposition.items() if not compat and len(parts)==2 and cp not in excluded)
def expand(cp,compat):
 if cp in decomposition and (compat or not decomposition[cp][0]):
  return sum((expand(x,compat) for x in decomposition[cp][1]),[])
 return [cp]
values=[];maps={}
for key,compat in [('Canonical',False),('Compatibility',True)]:
 entries=[]
 for cp in sorted(decomposition):
  result=expand(cp,compat)
  if result!=[cp]: entries.extend((cp,len(values),len(result)));values+=result
 maps[key]=entries
fold={}
for f in records('CaseFolding.txt'):
 if f[1] in ('C','F'): fold[int(f[0],16)]=[int(x,16) for x in f[2].split()]
entries=[]
for cp,result in sorted(fold.items()): entries.extend((cp,len(values),len(result)));values+=result
maps['Folding']=entries
# Word and line segmentation (UAX #29 words, UAX #14 lines): one value per
# code point. Bits 0-4 word class, 5-10 line class (after the LB1 defaults),
# 11 East Asian width F/W/H, 12 Extended_Pictographic, 13 gc=Pi, 14 gc=Pf,
# 15 gc=Cn.
words='Other CR LF Newline Extend ZWJ Regional_Indicator Format Katakana Hebrew_Letter ALetter Single_Quote Double_Quote MidNumLet MidLetter MidNum Numeric ExtendNumLet WSegSpace'.split()
lines='AL BK CR LF NL SP ZW ZWJ CM WJ GL BA HY HH BB B2 CB CL CP EX IN NS OP QU IS NU PO PR SY HL ID EB EM H2 H3 JL JV JT RI AK AP AS VF VI'.split()
segment=[0]*0x110000
for f in records('auxiliary/WordBreakProperty.txt'):
 for cp in span(f[0]): segment[cp]|=words.index(f[1])
def missing(name):
 for line in text(name).splitlines():
  if line.startswith('# @missing:'):
   r,v=[x.strip() for x in line[11:].split(';')]
   yield r,v
long_line={'Unknown':'XX','Ideographic':'ID','Prefix_Numeric':'PR'}
line_value=[None]*0x110000
for r,v in missing('extracted/DerivedLineBreak.txt'):
 for cp in span(r): line_value[cp]=long_line[v]
for f in records('extracted/DerivedLineBreak.txt'):
 for cp in span(f[0]): line_value[cp]=f[1]
east=[False]*0x110000
for r,v in missing('extracted/DerivedEastAsianWidth.txt'):
 for cp in span(r): east[cp]=v in ('Fullwidth','Wide','Halfwidth')
for f in records('extracted/DerivedEastAsianWidth.txt'):
 for cp in span(f[0]): east[cp]=f[1] in ('F','W','H')
pictographic=set()
for f in records('emoji/emoji-data.txt'):
 if f[1]=='Extended_Pictographic': pictographic.update(span(f[0]))
for cp in range(0x110000):
 value=line_value[cp]; category=categories[props[cp]&31]
 if value in ('AI','SG','XX'): value='AL'
 elif value=='SA': value='CM' if category in ('Mn','Mc') else 'AL'
 elif value=='CJ': value='NS'
 segment[cp]|=lines.index(value)<<5
 if east[cp]: segment[cp]|=1<<11
 if cp in pictographic: segment[cp]|=1<<12
 if category=='Pi': segment[cp]|=1<<13
 if category=='Pf': segment[cp]|=1<<14
 if category=='Cn': segment[cp]|=1<<15
segments=[];start=0
for cp in range(1,0x110001):
 if cp==0x110000 or segment[cp]!=segment[start]:
  if segment[start]: segments.extend((start,cp-1,segment[start]))
  start=cp
out=['// Generated by tools/unicode/generate.py; Unicode 17.0.0. Do not edit.\n// Unicode data licensed under Unicode-3.0; see LICENSE-UNICODE.txt.\n']
for name,items in [('Properties',ranges),*maps.items(),('MappingValues',values),('Composition',sum((list(x) for x in composition),[])),('Segments',segments)]:
 out.append(f'const {name}: [{len(items)}]u32 = [\n')
 for at in range(0,len(items),24): out.append('  '+', '.join(map(str,items[at:at+24]))+',\n')
 out.append(']\n')
dest=ROOT/'std/unicode/text';dest.mkdir(exist_ok=True)
(dest/'tables_generated.dyn').write_text(''.join(out))
print(f'generated {len(ranges)//3} property ranges; {len(values)} mapping scalars; {len(segments)//3} segment ranges')
