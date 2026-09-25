#!/usr/bin/env python3
"""Generate target-specific raw vendor bindings from Clang's resolved C AST.

C adapters preserve aggregate calling conventions and expose opaque record fields.
A manifest records every selected public function and every unsupported declaration.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import platform
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

BUILTINS = {'void':'void','_Bool':'bool','bool':'bool','char':'c.char','signed char':'i8',
 'unsigned char':'u8','short':'i16','short int':'i16','unsigned short':'u16',
 'unsigned short int':'u16','int':'i32','unsigned int':'u32','unsigned':'u32',
 'long':'c.long','long int':'c.long','unsigned long':'c.unsigned_long',
 'long long':'i64','long long int':'i64','unsigned long long':'u64',
 'float':'f32','double':'f64','__int128':'i128','unsigned __int128':'u128'}
KEYWORDS=set('use type struct enum pub fn extern const var if else for return break continue defer match case default true false nil rawptr bool void i8 i16 i32 i64 u8 u16 u32 u64 f32 f64 usize isize'.split())
def ident(name):
 if name.startswith('dyn_helper_'):name=name[len('dyn_helper_'):]
 return 'c_'+name if name in KEYWORDS or name.startswith('__') else name

def const_qualified(value):
 return bool(re.search(r'\*\s*const$',value)) if '*' in value else bool(re.search(r'\bconst\b',value))

def children(node,kind):return [c for c in node.get('inner',[]) if c.get('kind')==kind]
def descend(node):
 yield node
 for child in node.get('inner',[]):yield from descend(child)
def split_types(value):
 result=[];start=0;depth=0
 for i,char in enumerate(value):
  if char in '([':depth+=1
  elif char in ')]':depth-=1
  elif char==',' and depth==0:result.append(value[start:i].strip());start=i+1
 tail=value[start:].strip()
 if tail:result.append(tail)
 return result

def return_type(node):
 value=node['type']['qualType']
 callback=re.fullmatch(r'([^()]+?)\s*\(\s*\*\s*\((.*)\)\s*\)\s*\((.*)\)',value)
 if callback:return callback[1]+' (*)('+callback[3]+')'
 return value.split('(',1)[0].strip()

def run(command,**kwargs):
 result=subprocess.run(command,text=True,capture_output=True,timeout=300,**kwargs)
 if result.returncode:raise RuntimeError(shlex.join(command)+'\n'+result.stderr)
 return result

def macro_constants(includes,cc,work,selector,owner=None):
 """Ask the C compiler to evaluate public object macros, never Python eval."""
 header=work/'macros.h';header.write_text(includes)
 definitions=run([*cc,'-dD','-E','-x','c',str(header)]).stdout
 current_file='' 
 macros={};function_macros=[]
 for line in definitions.splitlines():
  location=re.match(r'#\s+\d+\s+"([^"]+)"',line)
  if location:current_file=location[1];continue
  if owner and not owner.search(current_file):continue
  match=re.match(r'#define ([A-Za-z_]\w*)(.*)',line)
  if not match or not selector.match(match[1]):continue
  name,tail=match.groups()
  if tail.startswith('('):function_macros.append(name);continue
  value=tail.strip()
  if value and name.upper()==name:macros[name]=value
 def batch(names,body):
  if not names:return []
  source=includes+'\n#include <stdio.h>\n#include <stdint.h>\nint main(void) {\n'+''.join(body(n) for n in names)+'}\n'
  path=work/'macro-probe.c';path.write_text(source);binary=work/'macro-probe'
  compiled=subprocess.run([*cc,'-w',str(path),'-o',str(binary)],capture_output=True,text=True,timeout=60)
  if compiled.returncode:
   if len(names)==1:return []
   middle=len(names)//2;return batch(names[:middle],body)+batch(names[middle:],body)
  return run([str(binary)]).stdout.splitlines()
 metadata=batch(sorted(macros),lambda n:f'_Static_assert(__builtin_constant_p({n}), "not a constant"); printf("{n} %d %zu\\n",__builtin_classify_type({n}),sizeof({n}));\n')
 kinds={line.split()[0]:(int(line.split()[1]),int(line.split()[2])) for line in metadata}
 strings=[name for name in kinds if macros[name].startswith('"')]
 integers=[name for name,(kind,size) in kinds.items() if kind==1 and size<=8]
 floats=[name for name,(kind,size) in kinds.items() if kind==8 and size<=8]
 pointers=[name for name,(kind,size) in kinds.items() if kind==5 and name not in strings]
 result={}
 for line in batch(integers,lambda n:f'if (((__typeof__({n}))-1)<0) printf("{n} i64 %lld\\n",(long long)({n})); else printf("{n} u64 %llu\\n",(unsigned long long)({n}));\n'):
  name,kind,value=line.split();size=kinds[name][1];kind=('i' if kind=='i64' else 'u')+str(size*8);result[name]=(kind,value)
 for line in batch(floats,lambda n:f'printf("{n} %a\\n",(double)({n}));\n'):
  name,value=line.split();number=float.fromhex(value)
  if number==number and abs(number)!=float('inf'):result[name]=('f32' if kinds[name][1]==4 else 'f64',repr(number))
 for line in batch(strings,lambda n:f'printf("{n} "); for(size_t i=0;i<sizeof({n})-1;i++) printf("%02x",((const unsigned char*)({n}))[i]); puts("");\n'):
  name,_,value=line.partition(' ');result[name]=('string','"'+''.join('\\x'+value[i:i+2] for i in range(0,len(value),2))+'"')
 for line in batch(pointers,lambda n:f'_Static_assert(__builtin_constant_p((uintptr_t)({n})), "not an integer pointer constant"); printf("{n} %llu\\n",(unsigned long long)(uintptr_t)({n}));\n'):
  name,value=line.split();result[name]=('pointer',value)
 return result,sorted(function_macros),sorted(set(macros)-result.keys())

class Generator:
 def __init__(self,ast,prefix,library,includes,cc,work,dispatch=False,links=(),owner=None,procedures=()):
  self.dispatch=dispatch;self.procedures=set(procedures);self.links=links;self.owner=re.compile(owner) if owner else None
  current_file=''
  for node in ast.get('inner',[]):
   loc=node.get('loc',{});loc=loc.get('expansionLoc',loc)
   current_file=loc.get('file',current_file)
   for item in descend(node):item['_source_file']=current_file
  self.ast=ast;self.prefix=re.compile(prefix);self.library=library;self.includes=includes
  self.cc=cc;self.work=work;self.nodes=list(descend(ast));self.byid={n['id']:n for n in self.nodes if 'id' in n}
  self.typedefs={};self.records={};self.enums={};self.functions={};self.variables={};self.aliases={};self.needed=set();self.omissions=[]
  self.types={};self.enum_values={};self.layout={};self.opaque=set();self.incomplete=set();self.cnames={};self.record_ids={}
  for n in self.nodes:
   name=n.get('name','');kind=n.get('kind')
   if kind=='TypedefDecl' and name:self.typedefs[name]=n
   if kind=='RecordDecl' and name:
    if n.get('completeDefinition') or name not in self.records:self.records[name]=n;self.cnames[name]=n['tagUsed']+' '+name
    self.record_ids[n['id']]=name
   if kind=='EnumDecl' and name:self.enums[name]=n
   if kind=='FunctionDecl' and (name.startswith('dyn_helper_') or (self.prefix.match(name) and (not self.owner or self.owner.search(n.get('_source_file',''))))):self.functions[name]=n
  for n in ast.get('inner',[]):
   if n.get('kind')=='VarDecl' and self.prefix.match(n.get('name','')) and (not self.owner or self.owner.search(n.get('_source_file',''))):self.variables[n['name']]=n
  for name,n in self.typedefs.items():
   if not n['type']['qualType'].startswith(('struct ','union ','enum ')) or '*' in n['type']['qualType']:continue
   for item in descend(n):
    decl=item.get('decl',item.get('ownedTagDecl',{}));record=self.byid.get(decl.get('id'),{})
    if record.get('kind')=='RecordDecl' and not record.get('name'):
     self.records[name]=record;self.cnames[name]=name;self.record_ids[record['id']]=name;break
    if record.get('kind')=='EnumDecl' and not record.get('name'):
     self.enums[name]=record;break
  for name,n in self.enums.items():
   current=-1;values=[]
   for child in children(n,'EnumConstantDecl'):
    explicit=[item['value'] for item in descend(child) if item.get('kind')=='ConstantExpr' and 'value' in item]
    current=int(explicit[0]) if explicit else current+1;values.append((child['name'],current))
   self.enum_values[name]=values
  self.spellings={}
  pending=list(self.records)
  while pending:
   parent=pending.pop(0);anonymous=None
   for child in self.records[parent].get('inner',[]):
    if child.get('kind')=='RecordDecl' and not child.get('name'):anonymous=child
    elif child.get('kind')=='FieldDecl' and anonymous and child.get('name'):
     spelling=child['type']['qualType']
     if '(unnamed' in spelling or '(anonymous' in spelling:
      name=parent+'_'+child['name']+'_C'
      self.records[name]=anonymous;self.cnames[name]='__typeof__((('+self.cnames[parent]+'*)0)->'+child['name']+'[0]'*(len(re.findall(r'\[\d*\]',spelling))+spelling.count('*'))+')'
      self.spellings[re.sub(r'(?:\s*\[\d*\]|\s*\*\s*(?:const\s*)?)+$','',spelling)]=name
      if 'desugaredQualType' in child['type']:self.spellings[re.sub(r'(?:\s*\[\d*\]|\s*\*\s*(?:const\s*)?)+$','',child['type']['desugaredQualType'])]=name
      pending.append(name);anonymous=None
  self.root_names=sorted({name for name in self.typedefs|self.records|self.enums if self.prefix.match(name) and (not self.owner or self.owner.search((self.typedefs|self.records|self.enums)[name].get('_source_file','')))})

 def canonical(self,value,seen=None):
  if value in self.spellings:return 'struct '+self.spellings[value]
  value=re.sub(r'\b(const|volatile|restrict|__restrict|__restrict__)\b','',value).strip();value=re.sub(r'\s+',' ',value)
  seen=seen or set()
  if value in self.typedefs and value not in seen:
   n=self.typedefs[value];base=n['type'].get('desugaredQualType',n['type']['qualType'])
   if base!=value:return self.canonical(base,seen|{value})
  return value

 def record_name(self,value):
  plain=self.canonical(value)
  if plain.startswith(('struct ','union ')):
   name=plain.split(' ',1)[1]
   if name in self.records:return name
  if value in self.records:return value
  return None

 def type(self,value,seen=None):
  seen=seen or set();original=value
  value=self.spellings.get(value,value)
  value=re.sub(r'\s+__attribute__\s*\(\(.*?\)\)','',value).strip()
  value=re.sub(r'\b(volatile|restrict|__restrict|__restrict__)\b','',value).strip()
  value=re.sub(r'\s+',' ',value)
  nested=re.fullmatch(r'([^()]+?)\s*\(\s*\*\s*\(\s*\*\s*\)\s*\((.*)\)\s*\)\s*\((.*)\)',value)
  if nested:
   ret=self.type(nested[1]+' (*)('+nested[3]+')',seen)
   args=split_types(nested[2]);args=[] if args==['void'] else args
   return '*fn('+', '.join(self.type(arg,seen) for arg in args)+') '+ret
  # Function pointers and adjusted function parameters.
  match=re.fullmatch(r'([^()]+?)\s*\(\s*(\*+)\s*(?:const\s*)?\)\s*\((.*)\)',value)
  if match:
   for item in [match[1],*split_types(match[3])]:
    if self.record_name(item) in self.opaque:raise ValueError('opaque aggregate callback ABI requires a C trampoline')
   result=self.type(match[1],seen);params=split_types(match[3]);params=[] if params==['void'] else params
   mapped=[self.type(p,seen) if p!='...' else '...' for p in params]
   return '*'*(len(match[2])-1)+'*fn('+', '.join(mapped)+')'+(' '+result if result!='void' else '')
  match=re.fullmatch(r'(.+?)\s*\((.*)\)',value)
  if match and not match[2].lstrip().startswith('*') and not match[1].startswith(('struct ','union ')):
   for item in [match[1],*split_types(match[2])]:
    if self.record_name(item) in self.opaque:raise ValueError('opaque aggregate callback ABI requires a C trampoline')
   result=self.type(match[1],seen);params=split_types(match[2]);params=[] if params==['void'] else params
   mapped=[self.type(p,seen) if p!='...' else '...' for p in params]
   return '*fn('+', '.join(mapped)+')'+(' '+result if result!='void' else '')
  match=re.fullmatch(r'(.+?)\s*\(\s*\*\s*\)\s*\[(\d+)\]',value)
  if match:return '*['+match[2]+']'+self.type(match[1],seen)
  match=re.fullmatch(r'(.+?)((?:\s*\[\d*\])+)',value)
  if match:
   dimensions=re.findall(r'\[(\d*)\]',match[2]);return ''.join('['+(n or '0')+']' for n in dimensions)+self.type(match[1],seen)
  value=re.sub(r'(\*)\s*const$',r'\1',value).strip()
  if value.endswith('*'):
   base=value[:-1].strip()
   # const qualifies the immediate pointee, not every level of a pointer chain.
   pointer_const=re.search(r'\*\s*const$',base)
   readonly=bool(pointer_const) or ('*' not in base and (base.startswith('const ') or base.endswith(' const')))
   clean=re.sub(r'\bconst\s*$','',base).strip() if pointer_const else re.sub(r'\bconst\b','',base).strip() if readonly else base
   record=self.record_name(clean)
   canonical=self.canonical(clean)
   # Fn* is a function pointer when Fn typedefs a function, but Callback*
   # is a pointer-to-pointer when Callback already typedefs a function pointer.
   if re.fullmatch(r'[^()]+\(.*\)',canonical) and not canonical.startswith(('struct ','union ')) and not canonical.split('(',1)[1].lstrip().startswith('*'):return self.type(clean,seen)
   if self.canonical(clean)=='void' or clean=='struct __va_list_tag' or record in self.incomplete:return 'rawptr'
   return ('*const ' if readonly else '*')+self.type(clean,seen)
  value=re.sub(r'\bconst\b','',value).strip()
  if value in BUILTINS:
   if value in ('__int128','unsigned __int128'):raise ValueError('128-bit integer ABI requires adapter')
   return BUILTINS[value]
  if value.startswith(('struct ','union ','enum ')):value=value.split(' ',1)[1]
  if value in self.records:
   self.needed.add(value)
   if not self.records[value].get('completeDefinition'):self.incomplete.add(value)
   return ident(value)
  if value in self.enums:self.needed.add(value);return ident(value)
  if value in self.typedefs:
   if value in seen:raise ValueError('recursive typedef '+value)
   self.needed.add(value);node=self.typedefs[value];base=node['type']['qualType']
   if value in ('size_t','uintptr_t','ptrdiff_t','intptr_t'):
    self.types[value]='usize' if value in ('size_t','uintptr_t') else 'isize'
    return ident(value)
   if base in ('struct '+value,'union '+value,'enum '+value):return ident(value)
   self.types[value]=self.type(base,seen|{value});return ident(value)
  raise ValueError('unrepresentable C type '+original)

 def collect(self):
  # Preclassify incomplete tags before resolving pointer aliases.
  self.incomplete={name for name,n in self.records.items() if not n.get('completeDefinition')}
  for name in self.root_names:
   try:self.type(name)
   except ValueError as error:self.omissions.append({'kind':'type','name':name,'reason':str(error)})
  for name,n in self.functions.items():
   try:
    ret=return_type(n)
    self.type(ret)
    for p in children(n,'ParmVarDecl'):self.type(p['type']['qualType'])
   except ValueError as error:self.omissions.append({'kind':'function','name':name,'reason':str(error)})
  for name,n in self.variables.items():
   try:self.type(n['type']['qualType'])
   except ValueError as error:self.omissions.append({'kind':'variable','name':name,'reason':str(error)})
  done=set()
  while self.needed-done:
   name=sorted(self.needed-done)[0];done.add(name)
   if name in self.records:
    n=self.records[name]
    if n.get('tagUsed')=='union' or any(children(n,kind) for kind in ('PackedAttr','MaxFieldAlignmentAttr','AlignedAttr')):self.opaque.add(name)
    for f in children(n,'FieldDecl'):
     try:
      self.type(f['type']['qualType'])
      if not f.get('name') or f.get('isBitfield') or 'volatile' in f['type']['qualType'] or children(f,'AlignedAttr'):self.opaque.add(name)
     except ValueError:self.opaque.add(name)

 def layouts(self):
  names=[n for n in sorted(self.needed) if n in self.records and n not in self.incomplete]
  source=self.includes+'\n#include <stdio.h>\n#include <stddef.h>\nint main(void) {\n'
  for name in names:
   ctype=self.cnames[name]
   source+=f'printf("{name} %zu %zu\\n",sizeof({ctype}),_Alignof({ctype}));\n'
  for name in names:
   if name in self.opaque:continue
   for field in children(self.records[name],'FieldDecl'):
    source+=f'printf("@{name}.{field["name"]} %zu 0\\n",offsetof({self.cnames[name]},{field["name"]}));\n'
  source+='}\n';path=self.work/'layout.c';path.write_text(source);binary=self.work/'layout'
  run([*self.cc,str(path),'-o',str(binary)])
  for line in run([str(binary)]).stdout.splitlines():
   name,size,align=line.split();self.layout[name]=(int(size),int(align))

 def emit(self,out):
  self.collect()
  # Recheck callback types after all packed/union/aligned records are known.
  for name in sorted(self.needed):
   if name not in self.typedefs:continue
   try:self.type(name)
   except ValueError as error:self.omissions.append({'kind':'type','name':name,'reason':str(error)})
  self.layouts();constants,macro_functions,other_macros=macro_constants(self.includes,self.cc,self.work,self.prefix,self.owner)
  machine=platform.machine()
  if platform.system()!='Linux' or machine not in ('x86_64','aarch64'):
   raise ValueError('Native binding generation currently supports Linux x86_64/aarch64 only')
  lines=['// Generated from resolved C headers. Do not edit.',f'#target(kernel: linux, arch: {machine})', 'use "std/c"',f'#link("{self.library}")','']
  lines.extend('#link("'+library+'")' for library in self.links)
  glue=[self.includes,'#include <stddef.h>','#include <string.h>','']
  # Normal records retain fields; opaque records retain exact storage and alignment.
  for name in sorted(self.needed):
   target=ident(name)
   if name in self.records:
    if name in self.incomplete:
     lines.append(f'pub type {target} = rawptr');continue
    size,align=self.layout[name]
    glue.append(f'_Static_assert(sizeof({self.cnames[name]}) == {size} && _Alignof({self.cnames[name]}) == {align}, "regenerate {name} binding");')
    if align not in (1,2,4,8):
     self.omissions.append({'kind':'record','name':name,'reason':f'unsupported alignment {align}'});continue
    if name in self.opaque:
     scalar={1:'u8',2:'u16',4:'u32',8:'u64'}[align]
     lines.append(f'pub struct {target} {{ storage: [{size//align}]{scalar} }}')
    else:
     fields=[]
     for f in children(self.records[name],'FieldDecl'):
      fields.append(f'{ident(f["name"])}: {self.type(f["type"]["qualType"])}')
     lines.append(f'pub struct {target} {{ '+', '.join(fields)+' }')
    lines.append(f'pub const {target}_Size: usize = {size}')
    lines.append(f'pub const {target}_Alignment: usize = {align}')
   elif name in self.enums:
    vals=self.enum_values[name];lo=min([v for _,v in vals] or [0]);hi=max([v for _,v in vals] or [0]);base='i32' if lo<0 else 'u32'
    if hi>4294967295 or lo<-2147483648:base='i64' if lo<0 else 'u64'
    lines.append(f'pub type {target} = {base}')
    for item,value in vals:lines.append(f'pub const {ident(item)}: {target} = {value}')
   elif name in self.types:lines.append(f'pub type {target} = '+('rawptr' if self.types[name]=='void' else self.types[name]))
  declared={name for values in self.enum_values.values() for name,value in values}
  # C commonly exposes constants through anonymous, untypedef'd enums.
  for node in self.nodes:
   if node.get('kind')!='EnumDecl':continue
   current=-1
   for child in children(node,'EnumConstantDecl'):
    explicit=[item['value'] for item in descend(child) if item.get('kind')=='ConstantExpr' and 'value' in item]
    current=int(explicit[0]) if explicit else current+1
    name=child['name']
    if name in declared or not self.prefix.match(name) or (self.owner and not self.owner.search(node.get('_source_file',''))):continue
    kind='i32' if -2147483648<=current<=2147483647 else 'u32' if current<=4294967295 and current>=0 else 'i64' if current<0 else 'u64'
    lines.append(f'pub const {ident(name)}: {kind} = {current}');declared.add(name)
  for name,(kind,value) in sorted(constants.items()):
   if name in declared or name in self.needed or name in self.functions:continue
   if kind=='pointer':
    if value=='0':lines.append(f'pub const {ident(name)}: rawptr = nil')
    else:lines.append(f'pub fn {ident(name)}() rawptr {{ address: usize = {value} return #cast(rawptr) address }}')
   else:lines.append(f'pub const {ident(name)}: '+('[]const u8' if kind=='string' else kind)+' = '+value)
  checks=[]
  for name in sorted(self.needed):
   if name not in self.records or name in self.incomplete:continue
   size,align=self.layout[name]
   if align not in (1,2,4,8):continue
   target=ident(name);checks.append(f'  if #sizeof({target}) != {size} || #alignof({target}) != {align} {{ return false }}')
   if name not in self.opaque:
    checks.append(f'  v_{target} := {target}{{}}')
    for f in children(self.records[name],'FieldDecl'):
     field=f['name'];offset=self.layout['@'+name+'.'+field][0]
     glue.append(f'_Static_assert(offsetof({self.cnames[name]},{field}) == {offset}, "regenerate {name}.{field} binding");')
     checks.append(f'  if #cast(usize) &v_{target}.{ident(field)} - #cast(usize) &v_{target} != {offset} {{ return false }}')
   else:
    for field in children(self.records[name],'FieldDecl'):
     if not field.get('name'):continue
     f=field['name'];t=field['type']['qualType'];symbol='dyn_raw_'+name+'_'+f
     try:dt=self.type(t)
     except ValueError as error:
      self.omissions.append({'kind':'field','name':name+'.'+f,'reason':str(error)});continue
     aggregate=self.record_name(t) or '[' in self.canonical(t)
     if aggregate:
      # Copy aggregates: a packed parent may leave the field unaligned.
      glue.append(f'void {symbol}_get(const {self.cnames[name]} *v, void *out) {{ memcpy(out,&v->{f},sizeof(v->{f})); }}')
      lines.append(f'pub extern fn {target}_{ident(f)}_get "{symbol}_get"(value: *const {target}, out: *{dt})')
      if not const_qualified(t):
       glue.append(f'void {symbol}_set({self.cnames[name]} *v, const void *in) {{ memcpy(&v->{f},in,sizeof(v->{f})); }}')
       lines.append(f'pub extern fn {target}_{ident(f)}_set "{symbol}_set"(value: *{target}, field: *const {dt})')
     else:
      decl='__typeof__((('+self.cnames[name]+'*)0)->'+f+')' if not field.get('isBitfield') else t
      glue.append(f'{decl} {symbol}_get(const {self.cnames[name]} *v) {{ return v->{f}; }}')
      lines.append(f'pub extern fn {target}_{ident(f)}_get "{symbol}_get"(value: *const {target}) {dt}')
      if not const_qualified(t):
       glue.append(f'void {symbol}_set({self.cnames[name]} *v, {decl} value) {{ v->{f}=value; }}')
       lines.append(f'pub extern fn {target}_{ident(f)}_set "{symbol}_set"(value: *{target}, field: {dt})')
  lines.append('pub fn verify_layout() bool {\n'+'\n'.join(checks)+'\n  return true\n}')
  for name,node in sorted(self.variables.items()):
   if any(o['kind']=='variable' and o['name']==name for o in self.omissions):continue
   t=node['type']['qualType'];symbol='dyn_raw_variable_'+name
   glue.append(f'const void *{symbol}(void) {{ return &{name}; }}')
   lines.append(f'pub extern fn {ident(name)}_address "{symbol}"() '+('*const ' if const_qualified(t) else '*')+self.type(t))
  emitted=[]
  for name,node in sorted(self.functions.items()):
   if any(o['kind']=='function' and o['name']==name for o in self.omissions):continue
   try:
    ret=return_type(node);dr=self.type(ret);record=self.record_name(ret)
    params=children(node,'ParmVarDecl');dparams=[];cparams=[];args=[];dargs=[]
    for i,param in enumerate(params):
     t=param['type']['qualType'];dt=self.type(t);rec=self.record_name(t);arg='arg'+str(i)
     dparams.append(arg+': '+dt)
     if rec:
      cparams.append('const '+self.cnames[rec]+' *'+arg);args.append('*'+arg);dargs.append('&'+arg)
     else:
      # typeof handles function-pointer and pointer-to-array declarators.
      ct=t.replace('struct __va_list_tag *', '__typeof__(&((__builtin_va_list){0})[0])')
      cparams.append('void *'+arg if t=='struct __va_list_tag *' else ('__typeof__(('+ct+')0) '+arg if '(*' in t else ct+' '+arg));args.append(arg);dargs.append(arg)
    if (self.dispatch or name in self.procedures) and not name.startswith('dyn_helper_'):
     if record in self.opaque or any(self.record_name(p['type']['qualType']) in self.opaque for p in params):raise ValueError('opaque aggregate procedure ABI requires a C trampoline')
     signature='*fn('+', '.join(self.type(p['type']['qualType']) for p in params)+')'+(' '+dr if dr!='void' else '')
     lines.append(f'pub type Procedure_{ident(name)} = '+signature)
     lines.append(f'pub fn {ident(name)}(procedure: Procedure_{ident(name)}'+(', '+', '.join(dparams) if dparams else '')+')'+(' '+dr if dr!='void' else '')+' { '+('return ' if dr!='void' else '')+'procedure('+', '.join('arg'+str(i) for i in range(len(params)))+') }')
    elif node.get('variadic'):
     lines.append(f'pub extern fn {ident(name)} "{name}"('+', '.join(dparams+['...'])+')'+(' '+dr if dr!='void' else ''))
    else:
     symbol='dyn_raw_'+name
     if record:
      cparams.append(self.cnames[record]+' *result')
      glue.append('void '+symbol+'('+(', '.join(cparams) or 'void')+') { *result='+name+'('+', '.join(args)+'); }')
     else:
      c_return=ret
      if dr!='void':
       zeroes=[('*('+self.cnames[self.record_name(p['type']['qualType'])]+'*)0') if self.record_name(p['type']['qualType']) else '0' for p in params]
       c_return='dyn_return_'+name;glue.append('typedef __typeof__('+name+'('+', '.join(zeroes)+')) '+c_return+';')
      glue.append(c_return+' '+symbol+'('+(', '.join(cparams) or 'void')+') { '+('return ' if dr!='void' else '')+name+'('+', '.join(args)+'); }')
     native_params=[]
     for i,param in enumerate(params):
      t=param['type']['qualType'];native_params.append('arg'+str(i)+': '+('*const ' if self.record_name(t) else '')+self.type(t))
     if record:native_params.append('result: *'+dr)
     if record or any(self.record_name(p['type']['qualType']) for p in params):
      lines.append(f'extern fn native_{ident(name)} "{symbol}"('+', '.join(native_params)+')'+(' '+dr if dr!='void' and not record else ''))
      body=f'  result := {dr}{{}}\n  native_{ident(name)}('+', '.join(dargs+['&result'])+')\n  return result' if record else ('  '+('return ' if dr!='void' else '')+f'native_{ident(name)}('+', '.join(dargs)+')')
      lines.append(f'pub fn {ident(name)}('+', '.join(dparams)+')'+(' '+dr if dr!='void' else '')+' {\n'+body+'\n}')
     else:lines.append(f'pub extern fn {ident(name)} "{symbol}"('+', '.join(dparams)+')'+(' '+dr if dr!='void' else ''))
    emitted.append(name)
   except ValueError as error:self.omissions.append({'kind':'function','name':name,'reason':str(error)})
  fingerprint=hashlib.sha256(('\n'.join(lines)+'\n'.join(glue)).encode()).hexdigest()
  stamp=int(fingerprint[:16],16)
  lines.insert(0,f'// ABI fingerprint: {fingerprint}')
  lines.append(f'extern fn native_binding_fingerprint "{self.library}_fingerprint"() u64')
  lines=[line.replace('pub fn verify_layout() bool {\n',f'pub fn verify_layout() bool {{\n  if native_binding_fingerprint() != {stamp} {{ return false }}\n') for line in lines]
  glue.append(f'unsigned long long {self.library}_fingerprint(void) {{ return {stamp}ULL; }}')
  out.mkdir(parents=True,exist_ok=True)
  (out/'raw.dyn').write_text('\n'.join(lines)+'\n');(out/'bridge.c').write_text('\n'.join(glue)+'\n')
  report={'scope':'Active public header functions matching the provider selector; target-specific, not platform qualification.', 'functions':len(self.functions),'emitted_functions':len(emitted),'records':sum(not n.startswith('@') for n in self.layout),'omissions':self.omissions,'symbols':emitted,'procedure_symbols':[name for name in emitted if not name.startswith('dyn_helper_')] if self.dispatch else sorted(self.procedures & set(emitted)),'constants':len(constants),'function_macros':macro_functions,'non_value_macros':other_macros}
  report['macro_helpers']=[ident(name) for name in emitted if name.startswith('dyn_helper_')]
  report['untranslated_function_macros']=sorted(set(macro_functions)-set(report['macro_helpers']))
  report.update(target='linux-'+machine,abi_fingerprint=fingerprint,headers=[line for line in self.includes.splitlines() if line.startswith('#include ')],variables=sorted(self.variables),c_compiler=run([*self.cc,'--version']).stdout.splitlines()[0])
  (out/'coverage.json').write_text(json.dumps(report,indent=2)+'\n');return report

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--header',action='append',required=True);p.add_argument('--prefix',required=True);p.add_argument('--library',required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--cflags',default='');p.add_argument('--clang',default='clang');p.add_argument('--cc',default=os.environ.get('CC','cc'));p.add_argument('--allow-omissions',action='store_true');p.add_argument('--dispatch',action='store_true');p.add_argument('--owner');p.add_argument('--procedure',action='append',default=[]);p.add_argument('--link',action='append',default=[]);p.add_argument('--helper-header',type=Path);a=p.parse_args()
 includes='\n'.join('#include <'+h+'>' for h in a.header)+'\n';flags=shlex.split(a.cflags)
 if a.helper_header:includes+='\n'+a.helper_header.read_text()+'\n'
 with tempfile.TemporaryDirectory(prefix='dyn-raw-bindings-') as directory:
  work=Path(directory);header=work/'input.c';header.write_text(includes)
  command=[*shlex.split(a.clang),*flags,'-x','c','-fsyntax-only','-Xclang','-ast-dump=json',str(header)]
  ast=json.loads(run(command).stdout);report=Generator(ast,a.prefix,a.library,includes,[*shlex.split(a.cc),*flags],work,a.dispatch,a.link,a.owner,a.procedure).emit(a.output)
 print(json.dumps({k:v for k,v in report.items() if k not in ('symbols','omissions','function_macros','non_value_macros')},indent=2));print('Omissions:',len(report['omissions']))
 return 1 if report['omissions'] and not a.allow_omissions else 0
if __name__=='__main__':raise SystemExit(main())
