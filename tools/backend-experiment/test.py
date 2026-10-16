#!/usr/bin/env python3
"""Inspect ELF and compare normal and panic execution with the production compiler."""
import ctypes
import itertools
import math
import os
import operator
from pathlib import Path
import random
import shlex
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
BUILD = Path(os.environ.get('BUILD', ROOT / 'build')).resolve()
DYN = Path(os.environ.get('DYN', BUILD / 'dyn-release')).resolve()
BACKEND = BUILD / 'scalar-backend'
CC = shlex.split(os.environ.get('CC', 'cc'))
SOURCE = '''
pub fn constant() u64 { return 18446744073709551615 }
pub fn minimum() i64 { return -9223372036854775808 }
pub fn identity(a: u64) u64 { return a }
pub fn mix(a: u64, b: u64, c: u64, d: u64, e: u64, f: u64) u64 {
  return #wrap((a + b) * (c - d)) ^ (e | f)
}
pub fn bits(a: u64, b: u64) u64 { return (a & b) ^ (a | b) }
pub fn subtract(a: i64, b: i64) i64 { return #wrap(a - b) }
pub fn negate(a: i64) i64 { return #wrap(-a) }
pub fn complement(a: u64) u64 { return ~a }
pub fn invert(a: bool) bool { return !a }
pub fn truth() bool { return true }
pub fn size(a: usize, b: usize) usize { return #wrap(a + b) }
pub fn literal_shift(a: u64) u64 { return #wrap(a << 63) }
pub fn literal_right(a: i64) i64 { return a >> 63 }
pub fn nested(a: u64, b: u64, c: u64) u64 { return a + (b * c) }
pub fn nested_twice(a: i64, b: i64, c: i64, d: i64) i64 { return a + (b + (c * d)) }
'''
OPERATORS = {'add': '+', 'sub': '-', 'mul': '*', 'neg': '-'}
for ty in ('i64', 'u64', 'isize', 'usize'):
    for operation, symbol in OPERATORS.items():
        params = f'a: {ty}' + (f', b: {ty}' if operation != 'neg' else '')
        expr = f'a {symbol} b' if operation != 'neg' else '-a'
        SOURCE += f'pub fn checked_{ty}_{operation}({params}) {ty} {{ return {expr} }}\n'


SAFETY_OPERATORS = {'div': '/', 'rem': '%', 'shl': '<<', 'shr': '>>'}
for ty in ('i64', 'u64', 'isize', 'usize'):
    for operation, symbol in SAFETY_OPERATORS.items():
        for wrap in (False, True):
            expr = f'a {symbol} b'
            if wrap: expr = f'#wrap({expr})' if operation == 'shl' else f'#wrap(({expr}) + 0)'
            right_type = 'u64' if operation in ('shl', 'shr') else ty
            name = f'{"wrap" if wrap else "checked"}_{ty}_{operation}'
            SOURCE += f'pub fn {name}(a: {ty}, b: {right_type}) {ty} {{ return {expr} }}\n'
SOURCE += 'pub fn nested_div(a:u64,b:u64,c:u64) u64 { return a + (b / c) }\n'
SOURCE += 'pub fn nested_shift(a:i64,b:i64,c:u64) i64 { return a + (b << c) }\n'

COMPARISONS = {'eq': ('==', operator.eq), 'ne': ('!=', operator.ne),
               'lt': ('<', operator.lt), 'le': ('<=', operator.le),
               'gt': ('>', operator.gt), 'ge': ('>=', operator.ge)}
for ty in ('i64', 'u64', 'isize', 'usize', 'bool'):
    for operation, (symbol, _) in COMPARISONS.items():
        if ty == 'bool' and operation not in ('eq', 'ne'): continue
        SOURCE += f'pub fn compare_{ty}_{operation}(a: {ty}, b: {ty}) bool {{ return a {symbol} b }}\n'
SOURCE += """
pub fn logical_and(a: bool, b: bool) bool { return a && b }
pub fn logical_or(a: bool, b: bool) bool { return a || b }
pub fn and_div(a: u64, b: u64) bool { return a != 0 && (1 / b) > 0 }
pub fn or_div(a: u64, b: u64) bool { return a == 0 || (1 / b) > 0 }
pub fn order_and(a: u64, b: u64, c: u64) bool { return (a + b) > 0 && (1 / c) > 0 }
pub fn nested_chain(a: u64, b: u64, c: u64) bool { return a == 0 || b != 0 && (1 / c) > 0 }
pub fn choose(a: u64, b: u64) u64 { if a > b { return a } else { return b } }
pub fn early(a: i64, b: i64) i64 { if a < 0 { return a } if b < 0 { return b } return a + b }
pub fn nested_branch(a: u64, b: u64, c: u64) u64 {
  if a == 0 { if b == 0 { return c } return b } else if b == 0 { return a }
  return a + b
}
pub fn bool_branch(a: bool, b: bool) bool { if a { return b } else { return !b } }
pub fn branch_div(a: u64, b: u64) u64 { if a == 0 { return 7 } else { return a / b } }
pub fn branch_overflow(a: u64, b: u64) u64 { if a == 0 { return b } if b == 0 { return a } return a + b }
pub fn condition_div(a: u64, b: u64) u64 { if (a / b) > 0 { return a } else { return b } }
pub fn branch_shift(a: u64, b: u64) u64 { if a == 0 { return 0 } return a << b }
"""

SOURCE += """
pub fn call_zero() u64 { return 0 }
pub fn call_identity(a: u64) u64 { return a }
pub fn call_pair(a: u64, b: u64) u64 { return #wrap(a * 131 + b) }
pub fn call_six(a: u64,b: u64,c: u64,d: u64,e: u64,f: u64) u64 {
  return #wrap(a * 100000 + b * 10000 + c * 1000 + d * 100 + e * 10 + f)
}
pub fn call_nested(a: u64,b: u64,c: u64) u64 {
  return #wrap(a + call_pair(call_identity(b), call_pair(call_zero(), c)))
}
pub fn call_args6(a: u64,b: u64,c: u64,d: u64,e: u64,f: u64) u64 {
  return call_six(call_identity(a),call_identity(b),call_identity(c),call_identity(d),call_identity(e),call_identity(f))
}
pub fn call_six_nested(a: u64,b: u64,c: u64,d: u64,e: u64,f: u64) u64 {
  return #wrap(a + call_six(call_identity(a),b+call_zero(),call_identity(c),d+call_identity(e),call_zero(),f))
}
pub fn call_bool(a: bool, b: bool) bool { return logical_or(logical_and(a,b),invert(a)) }
pub fn call_forward(a: u64) u64 { return forward_leaf(a) }
pub fn forward_leaf(a: u64) u64 { return #wrap(a + 1) }
pub fn factorial(n: u64) u64 { if n <= 1 { return 1 } return n * factorial(n - 1) }
pub fn rec_panic(n: u64, denominator: u64) u64 { if n == 0 { return 1 / denominator } return rec_panic(n - 1, denominator) }
pub fn rec_entry(n: u64, denominator: u64) u64 { return #wrap(call_identity(n) + rec_panic(n, denominator)) }
pub fn mutual_even(n: u64) bool { if n == 0 { return true } return mutual_odd(n - 1) }
pub fn mutual_odd(n: u64) bool { if n == 0 { return false } return mutual_even(n - 1) }
pub fn div_leaf(a: u64, b: u64) u64 { return a / b }
pub fn add_leaf(a: u64, b: u64) u64 { return a + b }
pub fn call_order(a: u64,b: u64,c: u64) u64 { return call_pair(div_leaf(a,b),add_leaf(a,c)) }
pub fn call_after(a: u64,b: u64,c: u64) u64 { return #wrap(call_identity(a) + div_leaf(b,c)) }
pub fn call_short(a: u64,b: u64) bool { return a == 0 || div_leaf(1,b) > 0 }
pub fn call_branch(a: u64,b: u64) u64 { if a == 0 { return call_identity(b) } else { return div_leaf(a,b) } }
"""

SOURCE += """
pub fn loop_sum(n:u64) u64 {
  i:u64 = 0 total:u64 = 0
  for i < n { i += 1 if i == 2 { continue } if i > 20 { break } total += call_identity(i) }
  return total
}
pub fn loop_nested(n:u64) u64 {
  i:u64 = 0 total:u64 = 0
  for i < n { i += 1 j:u64 = 0 for j < 4 { j += 1 if j == 2 { continue } if j == 4 { break } total += i + j } }
  return total
}
pub fn loop_early(n:u64) u64 { i:u64 = 0 for i < n { if i == 5 { return i } i += 1 } return i }
pub fn loop_forever(n:u64) u64 { i:u64 = 0 for { if i == n { break } i += 1 } return i }
pub fn loop_label(n:u64) u64 {
  i:u64 = 0 total:u64 = 0 outer: for i < n { i += 1
    for { if i == 2 { continue:outer } if i > 5 { break:outer } total += i break }
  } return total
}
pub fn loop_call_div(a:u64,b:u64) u64 { x := a for x > 0 { x = div_leaf(x,b) return x } return x }
pub fn local_bool(a:bool) bool { b:bool = false b = a if b { b = !b } return b }
pub fn local_zero() u64 { x:u64 return x }
pub fn local_scope(a:u64) u64 { x := a if true { y := call_identity(99) y += 1 } return x }
pub fn local_overflow(a:u64,b:u64) u64 { x := a for b > 0 { x += b break } return x }
pub fn loop_div(a:u64,b:u64) u64 { x := a for x > 0 { x /= b return x } return x }
pub fn loop_condition_div(a:u64,b:u64) u64 { x := a for x / b > 1 { x -= 1 } return x }
pub fn local_signed(a:i64,b:i64) i64 { x := a x += b return x }
pub fn local_wrap(a:u64,b:u64) u64 { x := a x = #wrap(x + b) return x }
"""
SOURCE += 'pub fn large_frame_panic(a:u64,b:u64) u64 {' + ''.join(f'x{i} := call_identity(a) ' for i in range(24)) + 'x23 += b return x23 }\n'
SOURCE += 'pub fn large_frame(a:u64) u64 {' + ''.join(f'x{i} := call_identity(a) ' for i in range(24)) + 'return #wrap(' + '+'.join(f'x{i}' for i in range(24)) + ') }\n'

UPDATE_OPERATORS = dict(add='+',sub='-',mul='*',div='/',rem='%',shl='<<',shr='>>',band='&',bor='|',bxor='^')
for ty in ('i64','u64'):
    for op,symbol in UPDATE_OPERATORS.items():
        right = 'u64' if op in ('shl','shr') else ty
        SOURCE += f'pub fn update_{ty}_{op}(a:{ty},b:{right}) {ty} {{ x := a x {symbol}= b return x }}\n'

for arity in (3,4,5):
    names = ['a','b','c','d','e'][:arity]
    params = ','.join(f'{name}:u64' for name in names)
    expr = '+'.join(f'{name}*{10 ** (arity-index-1)}' for index,name in enumerate(names))
    SOURCE += f'pub fn arity{arity}({params}) u64 {{ return #wrap({expr}) }}\n'
    SOURCE += f'pub fn call_arity{arity}({params}) u64 {{ return arity{arity}({",".join(names)}) }}\n'


def safety_result(operation, args, signed, wrap, bits=64):
    a, b = args
    low, high = (-(1 << (bits-1)), (1 << (bits-1)) - 1) if signed else (0, (1 << bits) - 1)
    if operation in ('div', 'rem'):
        if b == 0: return None, 'divide.ok'
        if signed and a == low and b == -1: return None, 'division.overflow.ok'
        quotient = abs(a) // abs(b)
        if (a < 0) != (b < 0): quotient = -quotient
        return (quotient if operation == 'div' else a - quotient * b), None
    if not 0 <= b < bits: return None, 'shift.count.ok'
    if operation == 'shr': return a >> b, None
    result = a << b
    if wrap:
        result &= (1 << bits) - 1
        if signed and result >= 1 << (bits-1): result -= 1 << bits
    elif not low <= result <= high:
        return None, 'overflow.ok'
    return result, None


def clean_stderr(result):
    assert not any(marker in result.stderr for marker in
                   ('AddressSanitizer', 'UndefinedBehaviorSanitizer', 'runtime error:', 'LeakSanitizer')), result.stderr


STACK_ARITIES = (7, 8, 9, 16, 32, 256)
for arity in STACK_ARITIES:
    names = [f'a{i}' for i in range(arity)]
    params = ','.join(f'{name}:u64' for name in names)
    selected = range(arity) if arity <= 32 else (0, 5, 6, 127, 255)
    expr = '+'.join(f'a{i}*{i+1}' for i in selected)
    SOURCE += f'pub fn stack{arity}({params}) u64 {{return #wrap({expr})}}\n'
    arguments = ','.join(f'call_identity({name})' for name in names)
    SOURCE += f'pub fn stack_call{arity}({params}) u64 {{return #wrap(a0+stack{arity}({arguments}))}}\n'

for ty, expression in (('i64', '#wrap(a6-a7+a0)'), ('bool', '(a6 && !a7) || a0')):
    params = ','.join(f'a{i}:{ty}' for i in range(8))
    SOURCE += f'pub fn stack_{ty}({params}) {ty} {{return {expression}}}\n'
    SOURCE += f'pub fn stack_call_{ty}({params}) {ty} {{return stack_{ty}('+','.join(f'a{i}' for i in range(8))+')}\n'
SOURCE += """
pub fn stack_order(a:u64,b:u64) u64 {
 return stack8(0,0,0,0,0,0,1/b,a+1)
}
pub fn stack_div(a:u64,b:u64,c:u64,d:u64,e:u64,f:u64,g:u64,h:u64) u64 {return g/h}
pub fn stack_panic(a:u64,b:u64) u64 {return stack_div(0,0,0,0,0,0,a,b)}
"""

SOURCE += """
extern fn abs(a:i32) i32
pub fn foreign_abs32(a:i32) i32 { return abs(a) }
extern fn llabs(a:i64) i64
pub fn indirect_apply(f:*fn(u64) u64,a:u64) u64 { return f(a) }
pub fn indirect_use(a:u64) u64 { f := &call_identity return #wrap(a + indirect_apply(f,a)) }
pub fn indirect_six(a:u64) u64 { f := &call_six return f(a,2,3,4,5,6) }
pub fn indirect_stack(a:u64) u64 { f := &stack_div return f(0,0,0,0,0,0,a,1) }
pub fn indirect_void(a:u64) { f := &void_work f(a,1) }
pub fn indirect_foreign(a:i64) i64 { f := &llabs return f(a) }
pub fn indirect_nil(a:u64) u64 { f:*fn(u64) u64 = nil if a == 0 { return 0 } return f(a/(a-a)) }
pub fn indirect_panic(a:u64,b:u64) u64 { f := &div_leaf return f(a,b) }
pub fn foreign_abs(a:i64) i64 { return llabs(a) }
pub fn void_empty() {}
pub fn void_work(a:u64,b:u64) { _ = a / b return }
pub fn void_caller(a:u64,b:u64) u64 { void_empty() void_work(a,b) return a }
pub fn scalar_case(a:i64) i64 { case a { -5..=-1 => { return -1 }, 0,2,4 => { return 10 }, _ => { return 99 } } }
pub fn case_update(a:u64) u64 { x:u64 = 0 case a { 0..=2 => { x = 10 }, _ => { x = 20 } } return x }
pub fn case_panic(a:u64,b:u64) u64 { case a { 0 => { return 1 }, _ => { return a/b } } }
pub fn range_controls(a:u64,b:u64) u64 { total:u64 = 0 for i in a..b { if i == 2 { continue } if i == 5 { break } total += i i = 99 } return total }
pub fn range_nested(a:u64,b:u64) u64 { total:u64 = 0 lo:u64 = 0 hi:u64 = 3 outer: for i in a..b { for j in lo..hi { if i == 2 { continue:outer } if i == 5 { break:outer } total += i+j } } return total }
pub fn range_bound_panic(a:u64,b:u64) u64 { total:u64 = 0 for i in (a/b)..(a+1) { total += i } return total }
"""
for ty in ('i64','u64'):
    for reverse in (False,True):
        for inclusive in (False,True):
            name = f'range_{ty}_{int(reverse)}_{int(inclusive)}'
            interval = 'a' + ('..=' if inclusive else '..') + 'b'
            if reverse: interval = f'#reverse({interval})'
            SOURCE += f'pub fn {name}(a:{ty},b:{ty}) {ty} {{ total:{ty} = 0 for i in {interval} {{ total = #wrap(total*17+i) }} return total }}\n'

NARROW_TYPES = {f'{sign}{bits}': (bits,sign=='i',getattr(ctypes,f'c_{"int" if sign=="i" else "uint"}{bits}')) for sign in ('i','u') for bits in (8,16,32)}
for ty,(bits,sign,ctype) in NARROW_TYPES.items():
    for op,symbol in {**OPERATORS,**SAFETY_OPERATORS}.items():
        right='u64' if op in ('shl','shr') else ty
        for wrap in (False,True):
            expr=f'a {symbol} b' if op!='neg' else '-a'
            if wrap: expr=f'#wrap(({expr}) + 0)' if op in ('div','rem','shr') else f'#wrap({expr})'
            params=f'a:{ty}' + (f',b:{right}' if op!='neg' else '')
            SOURCE+=f'pub fn narrow_{ty}_{op}_{int(wrap)}({params}) {ty} {{ return {expr} }}\n'
    SOURCE+=f'pub fn narrow_{ty}_cast(a:u64) {ty} {{ return #cast({ty}) a }}\n'
    SOURCE+=f'pub fn narrow_{ty}_ptr(a:{ty}) u64 {{ return #cast(u64) #cast(rawptr) a }}\n'
    SOURCE+=f'pub fn narrow_{ty}_bits(a:{ty},b:{ty}) {ty} {{ return (~a & b) | (a ^ b) }}\n'
    SOURCE+=f'pub fn narrow_{ty}_apply(f:*fn({ty}) {ty},a:{ty}) {ty} {{ return f(a) }}\n'
    SOURCE+=f'pub fn narrow_{ty}_stack(' + ','.join(f'a{i}:{ty}' for i in range(8)) + f') {ty} {{ return #wrap(a0+a6+a7) }}\n'
    SOURCE+=f'pub fn narrow_{ty}_identity(a:{ty}) {ty} {{ return a }}\n'
    SOURCE+=f'pub fn narrow_{ty}_call(a:{ty}) {ty} {{ f:=&narrow_{ty}_identity return f(a) }}\n'

SOURCE += 'extern fn difftime(a:i64,b:i64) f64\npub fn foreign_time(a:i64,b:i64) f64 { return difftime(a,b) }\n'
for ty in ('f32','f64'):
    for op,symbol in dict(add='+',sub='-',mul='*',div='/',rem='%').items():
        SOURCE+=f'pub fn float_{ty}_{op}(a:{ty},b:{ty}) {ty} {{ return a {symbol} b }}\n'
    SOURCE+=f'pub fn float_{ty}_neg(a:{ty}) {ty} {{ return -a }}\n'
    SOURCE+=f'pub fn float_{ty}_constant() {ty} {{ return 1.25 }}\n'
    SOURCE+=f'pub fn float_{ty}_apply(f:*fn({ty},{ty}) {ty},a:{ty},b:{ty}) {ty} {{ return f(a,b) }}\n'
    SOURCE+=f'pub fn float_{ty}_call(a:{ty},b:{ty}) {ty} {{ f:=&float_{ty}_add return f(a,b) }}\n'
    SOURCE+=f'pub fn float_{ty}_local(a:{ty},b:{ty}) {ty} {{ x:=a x+=b if x>0.0 {{ return x }} return -x }}\n'
    for op,(symbol,_) in COMPARISONS.items():
        SOURCE+=f'pub fn float_{ty}_{op}(a:{ty},b:{ty}) bool {{ return a {symbol} b }}\n'
    params=','.join(f'a{i}:{ty}' for i in range(10));expr='+'.join(f'a{i}' for i in range(10))
    SOURCE+=f'pub fn float_{ty}_stack({params}) {ty} {{ return {expr} }}\n'
    SOURCE+=f'pub fn float_{ty}_stack_call({params}) {ty} {{ return float_{ty}_stack('+','.join(f'a{i}' for i in range(10))+') }\n'
SOURCE+='pub fn float_widen(a:f32) f64 { return a }\npub fn float_narrow(a:f64) f32 { return #cast(f32) a }\n'
params=','.join(f'f{i}:f64,i{i}:u64' for i in range(10));checks=' || '.join(f'i{i} != {i}' for i in range(10))
SOURCE+=f'pub fn float_mixed({params}) f64 {{ if {checks} {{ return -1.0 }} return '+ '+'.join(f'f{i}' for i in range(10))+' }\n'
args=','.join(f'{i}.25,{i}' for i in range(10))
SOURCE+=f'pub fn float_mixed_call() f64 {{ return float_mixed({args}) }}\n'
SOURCE+=f'pub fn float_mixed_indirect() f64 {{ f:=&float_mixed return f({args}) }}\n'
SOURCE+='pub fn float_panic(a:f64,b:u64,c:u64) f64 { _ = b/c return a }\n'
SOURCE+='pub fn float_panic_call(a:u64,b:u64) f64 { return float_panic(1.25,a,b) }\n'

SOURCE+='pub fn float_max('+','.join(f'a{i}:f64' for i in range(256))+') f64 { return a0+a7+a8+a127+a255 }\n'
SOURCE+='pub fn float_max_call() f64 { return float_max('+','.join(f'{i}.0' for i in range(256))+') }\n'

SOURCE += """
pub fn generic_min(a,b:$T) T { if a < b { return a } return b }
pub fn generic_count(n:$T) T { if n == 0 { return 0 } return generic_count(n-1)+1 }
pub fn generic_add(a,b:$T) T { return a+b }
pub fn generic_i8(a:i8,b:i8) i8 { return generic_min(a,b) }
pub fn generic_i64(a:i64,b:i64) i64 { return generic_min(a,b) }
pub fn generic_f64(a:f64,b:f64) f64 { return generic_min(a,b) }
pub fn generic_recursion(a:u64) u64 { return generic_count(a) }
pub fn generic_panic(a:u64,b:u64) u64 { return generic_add(a,b) }
"""

GLOBAL_COUNT=10
SOURCE += """
pub global_counter:u64 = 7
pub global_small:i8 = -128
pub global_float:f64 = -1.25
pub global_f32:f32 = 1.25
pub global_i32:i32
pub global_u16:u16
pub global_flag:bool
const global_constant:u64 = 99
pub global_copy:u64 = global_constant
pub global_callback:*fn(u64) u64
pub fn globals_f32(a:f32) f32 { global_f32=a return global_f32 }
pub fn globals_i32(a:i32) i32 { global_i32=a return global_i32 }
pub fn globals_u16(a:u16) u16 { global_u16=a return global_u16 }
pub fn globals_read() u64 { return global_counter+global_copy }
pub fn globals_update(a:u64) u64 { global_counter += a return global_counter }
pub fn globals_reset(a:u64) { global_counter=a }
pub fn globals_small(a:i8) i8 { global_small=a global_small+=1 return global_small }
pub fn globals_float(a:f64) f64 { global_float+=a return global_float }
pub fn globals_bool(a:bool) bool { global_flag=a return global_flag }
pub fn globals_callback(a:u64) u64 { global_callback=&call_identity return global_callback(a) }
pub fn globals_order(a:u64) u64 { global_counter=1 global_counter += globals_update(a) return global_counter }
"""

SOURCE += """
extern fn malloc(n:usize) rawptr
extern fn free(p:rawptr)
pub fn pointer_local(a:u64) u64 { x:=a p:=&x p.*+=call_identity(1) return x }
pub fn pointer_global(a:u64) u64 { p:=&global_counter p.*=a return global_counter }
pub fn pointer_retarget(p:**u64,q:*u64) u64 { p.*=q return 7 }
pub fn pointer_alias(a:u64) u64 { x:=a y:u64=99 p:=&x p.*=pointer_retarget(&p,&y) return x*100+y }
pub fn pointer_alias_add(a:u64) u64 { x:=a y:u64=99 p:=&x p.*+=pointer_retarget(&p,&y) return x*100+y }
pub fn pointer_null(a:u64) u64 { if a==0 { return 0 } p:*u64=nil return p.* }
pub fn pointer_unaligned(a:u64) u64 { if a==0 { return 0 } p:=#cast(*u64) a return p.* }
pub fn pointer_store_panic(a:u64,b:u64) u64 {
  if a==0 && b==0 { return 0 } x:u64=0 p:=#cast(*u64) a
  if a==2 { p=&x } p.*=1/(b-b) return x
}
pub fn pointer_heap(a:u64) u64 { p:=#cast(*u64) malloc(8) p.*=a value:=p.* free(p) return value }
pub fn float_bits(a:f32) u32 { return #bitcast(u32) a }
pub fn bits_float(a:u32) f32 { return #bitcast(f32) a }
"""
for ty in ('i8','u16','i32','u64','bool','f32','f64'):
    SOURCE+=f'pub fn pointer_{ty}(p:*{ty},a:{ty}) {ty} {{ p.*=a return p.* }}\n'

def run(args, **kwargs):
    result = subprocess.run([str(x) for x in args], check=False,
                            capture_output=True, text=True, timeout=120, **kwargs)
    clean_stderr(result)
    assert result.returncode == 0, (args, result.returncode, result.stdout, result.stderr)
    return result


def reject(source, obj, diagnostic):
    result = subprocess.run([BACKEND, source, obj], capture_output=True, text=True, timeout=10)
    clean_stderr(result)
    assert result.returncode == 1 and diagnostic in result.stderr, result
    return result


def inspect(path, debug):
    data = path.read_bytes()
    assert data[:6] == b'\x7fELF\x02\x01'
    assert struct.unpack_from('<HH', data, 16) == (1, 62)
    start = struct.unpack_from('<Q', data, 40)[0]
    stride, count, names = struct.unpack_from('<HHH', data, 58)
    headers = [struct.unpack_from('<IIQQQQIIQQ', data, start + i * stride)
               for i in range(count)]
    strings = data[headers[names][4]:headers[names][4] + headers[names][5]]
    sections = {strings[h[0]:].split(b'\0')[0]: h for h in headers}
    assert sections[b'.text'][2] == 6
    assert sections[b'.rodata'][2] == 2 and sections[b'.rodata'][8] == 8
    assert sections[b'.data'][2] == 3 and sections[b'.data'][8] == 8
    assert sections[b'.note.GNU-stack'][2] == 0
    table = sections[b'.symtab']
    symbols = [struct.unpack_from('<IBBHQQ', data, offset)
               for offset in range(table[4], table[4] + table[5], table[9])]
    assert all(s[1] >> 4 == 0 for s in symbols[:table[7]])
    assert all(s[1] >> 4 == 1 for s in symbols[table[7]:])
    assert len(symbols) == SOURCE.count('pub fn ') + SOURCE.count('extern fn ') + GLOBAL_COUNT + 12 + (3 if debug else 1)
    names = headers[table[6]]
    names = data[names[4]:names[4] + names[5]]
    undefined = {names[s[0]:].split(b'\0')[0] for s in symbols[2:] if s[3] == 0}
    assert undefined == {b'llabs',b'abs',b'difftime',b'malloc',b'free',b'write',b'dyn_unwind_set',b'dyn_unwind_link',b'dyn_unwind_unlink',b'dyn_unwind_continue',b'fmod',b'fmodf'} | ({b'dyn_panic', b'dyn_trace_push', b'dyn_trace_pop'} if debug else {b'dyn_panic'})
    constructors = sections[b'.init_array']
    assert constructors[1] == 14 and constructors[2] == 3 and constructors[5] == 8
    init_reloc = sections[b'.rela.init_array']
    assert init_reloc[5] == 24 and init_reloc[6] == 4
    offset, info, addend = struct.unpack_from('<QQq', data, init_reloc[4])
    target = symbols[info >> 32]
    assert (offset, info & 0xffffffff, addend) == (0, 1, 0)
    assert target[1] >> 4 == 0 and names[target[0]:].split(b'\0')[0] == b'__dyn_backend_initialize'
    rel = sections[b'.rela.text']
    assert rel[6] == 4 and rel[7] == 1 and rel[9] == 24
    relocations = [struct.unpack_from('<QQq', data, offset)
                   for offset in range(rel[4], rel[4] + rel[5], rel[9])]
    assert relocations
    function_relocations = 0
    for offset, info, addend in relocations:
        assert offset + 4 <= sections[b'.text'][5]
        symbol, kind = info >> 32, info & 0xffffffff
        assert kind in (2, 4, 9)  # R_X86_64_PC32 and R_X86_64_PLT32 only
        if kind == 2:
            assert symbol == 1 and 0 <= addend + 4 < sections[b'.rodata'][5]
        else:
            assert addend == -4
            if symbols[symbol][3] == 1:
                assert symbols[symbol][1] & 15 == 2 and symbols[symbol][4] < sections[b'.text'][5]
                function_relocations += 1
            else: assert symbols[symbol][3] in (0,2,8,11)
    assert function_relocations > 0
    run(['readelf', '-h', '-S', '-s', '-r', path])



SOURCE += """
pub fn defer_digit(a:u64) { global_counter = global_counter*10+a }
pub fn defer_capture(a:u64) u64 { global_counter=0 x:=a defer defer_digit(x) x=9 defer { defer_digit(x) } return x+1 }
pub fn defer_scope(a:u64) u64 { global_counter=0 if a>0 { defer defer_digit(1) defer defer_digit(2) } return global_counter }
pub fn defer_loop(a:u64) u64 { global_counter=0 for i in 0..a { defer defer_digit(i+1) if i==0 { continue } if i==2 { break } } return global_counter }
pub fn defer_early(a:u64) u64 { global_counter=0 defer defer_digit(1) if a>0 { defer defer_digit(2) return a } return a+1 }
pub fn defer_call(a:u64) u64 { global_counter=0 defer defer_digit(3) return a+call_identity(a) }
pub fn defer_indirect(a:u64) u64 { global_counter=0 f:=&defer_digit defer f(a) f=nil a=9 return a }
pub fn defer_float(a:f64) f64 { defer defer_digit(1) return float_mixed_call()+a }
pub fn defer_read() u64 { return global_counter }
extern fn write(fd:i32,data:rawptr,length:usize) isize
pub fn defer_emit(a:u64) { c:=#cast(u8) (a+48) _=write(1,#cast(rawptr) &c,1) }
pub fn defer_panic_leaf(a:u64) u64 { return 1/a }
pub fn defer_panic_call(a:u64) u64 { defer defer_emit(1) defer defer_emit(2) return 4+defer_panic_leaf(a) }
pub fn defer_panic_guard(a:u64) u64 { defer defer_emit(1) defer defer_emit(2) return 1/a }
pub fn defer_panic_capture(a:u64) u64 { defer defer_emit(1) defer defer_emit(1/a) return 7 }
pub fn defer_panic_cleanup(a:u64) u64 { defer defer_emit(1) defer { _=1/a } return 4 }
pub fn defer_panic_recursive(a:u64) u64 { defer defer_emit(a) if a>0 { return defer_panic_recursive(a-1) } return defer_panic_leaf(a) }
pub fn defer_panic_parent(a:u64) u64 { defer defer_emit(8) return defer_panic_call(a) }
"""

SOURCE += """
struct Storage { tag:u8=3, wide:u64=7, small:i16=-2, values:[3]u64 }
struct NestedStorage { first:u8, item:Storage, last:u16 }
pub fn array_local(a:u64,i:usize) u64 { x:[3]u64=[a,2] x[2]=4 x[1]+=3 return x[i]+#cast(u64) #len(x) }
pub fn array_zero(i:usize) u64 { x:[8]u64 return x[i] }
pub fn array_nested(a:u64) u64 { x:[2][3]u64=[[a,2,3],[4,5,6]] y:=x x[0][0]=8 return y[0][0]+x[1][2] }
pub fn array_assign(a:u64) u64 { x:[3]u64=[a,2,3] y:[3]u64 y=x y=y return y[0]+y[1]+y[2] }
pub fn array_pointer(p:*[3]u16,i:usize,a:u16) u16 { p.*[i]=a return p.*[i] }
pub fn array_copy(dst:*[3]u16,src:*[3]u16) { dst.*=src.* }
pub fn struct_local(a:u64) u64 { x:=Storage{wide:a,values:[1,2,3]} y:=x x.wide+=2 y.values[1]=9 return x.wide+y.wide+#cast(u64) x.tag+y.values[1] }
pub fn struct_nested(a:u64) u64 { x:=NestedStorage{first:1,item:Storage{wide:a},last:2} x.item.wide+=3 return x.item.wide+#cast(u64) x.last }
pub fn struct_zero() u64 { x:Storage return x.wide+#cast(u64) x.tag }
pub fn struct_pointer(p:*Storage,a:u64) u64 { p.wide=a p.tag=8 p.small=-3 p.values[1]=a+1 return p.wide+p.values[1] }
pub fn aggregate_defer(a:u64) u64 { global_counter=0 x:[2]u64=[a,2] defer { defer_digit(x[0]) } x[0]=3 return x[1] }
pub fn array_panic(i:usize) u64 { x:[3]u64=[1,2,3] defer defer_emit(4) return x[i] }
"""

SOURCE += """
pub fn slice_local(a:u64,i:usize) u64 { x:[4]u64=[a,2,3,4] s:=x[1..] s[0]+=5 t:=s[..2] return t[i]+#cast(u64) #len(s) }
pub fn slice_read(s:[]const u64,i:usize) u64 { return s[i]+#cast(u64) #len(s) }
pub fn slice_identity(s:[]u64) []u64 { return s }
pub fn slice_raw(p:*u64,n:usize) []u64 { return p[0..n] }
pub fn slice_call(a:u64) u64 { x:[4]u64=[a,2,3,4] return slice_read(slice_identity(x[..]),0) }
pub fn slice_stack(a:u64,b:u64,c:u64,d:u64,e:u64,s:[]u64,t:[]u64) u64 { return a+b+c+d+e+s[0]+t[1] }
pub fn slice_stack_call(a:u64) u64 { x:[3]u64=[a,2,3] f:=&slice_stack return f(1,2,3,4,5,x[..],x[1..]) }
pub fn slice_capture(s:[]u64) u64 { global_counter=0 defer slice_observe(s) s=s[0..0] return 9 }
pub fn slice_observe(s:[]u64) { global_counter=s[0]+#cast(u64) #len(s) }
pub fn slice_defer_return(s:[]u64) []u64 { defer defer_digit(1) return slice_identity(s) }
pub fn slice_string(i:usize) u8 { s:[]const u8="abc" return s[i] }
pub fn slice_bounds(a:usize,b:usize) u64 { x:[4]u64=[1,2,3,4] s:=x[a..b] return #cast(u64) #len(s) }
pub fn panic_replace(a:u64) u64 { defer { #panic("cleanup") } #panic("original") }
pub fn panic_owned(a:u64) u64 { message:[2]u8=[111,107] defer { message[0]=120 defer_emit(5) } #panic(message[..]) }
pub fn slice_nested_bounds(a:usize,b:usize) u64 { x:[5]u64=[1,2,3,4,5] s:=x[1..4] t:=s[a..b] return #cast(u64) #len(t) }
"""

ABI_STRUCTS = [
    ('Three',[('a',ctypes.c_uint64),('b',ctypes.c_uint64),('value',ctypes.c_uint64)],'a:u64,b:u64,value:u64','value',9),
    ('FourDoubles',[('a',ctypes.c_double),('b',ctypes.c_double),('c',ctypes.c_double),('value',ctypes.c_double)],'a:f64,b:f64,c:f64,value:f64','value',2.5),
    ('Byte',[('value',ctypes.c_uint8)],'value:u8','value',9),
    ('Bytes',[('data',ctypes.c_uint8*3)],'data:[3]u8','data[2]',9),
    ('Pair',[('value',ctypes.c_int64),('real',ctypes.c_double)],'value:i64,real:f64','value',9),
    ('Reverse',[('real',ctypes.c_double),('value',ctypes.c_int64)],'real:f64,value:i64','value',9),
    ('Two',[('other',ctypes.c_uint64),('value',ctypes.c_uint64)],'other:u64,value:u64','value',9),
    ('Float',[('value',ctypes.c_float)],'value:f32','value',2.5),
    ('Floats',[('a',ctypes.c_float),('value',ctypes.c_float)],'a:f32,value:f32','value',2.5),
    ('ThreeFloats',[('a',ctypes.c_float),('b',ctypes.c_float),('value',ctypes.c_float)],'a:f32,b:f32,value:f32','value',2.5),
    ('Doubles',[('a',ctypes.c_double),('value',ctypes.c_double)],'a:f64,value:f64','value',2.5),
    ('Padding',[('tag',ctypes.c_uint8),('value',ctypes.c_double)],'tag:u8,value:f64','value',2.5),
    ('Boolean',[('flag',ctypes.c_bool),('value',ctypes.c_int8)],'flag:bool,value:i8','value',-9),
]
for name,fields,decl,field,value in ABI_STRUCTS:
    SOURCE+=f'struct Abi{name} {{ {decl} }}\n'
    increment='1.0' if isinstance(value,float) else '1'
    SOURCE+=f'pub fn abi_{name}(x:Abi{name}) Abi{name} {{ x.{field}+={increment} return x }}\n'
    SOURCE+=f'pub fn abi_{name}_call(x:Abi{name}) Abi{name} {{ return abi_{name}(x) }}\n'
    SOURCE+=f'pub fn abi_{name}_apply(f:*fn(Abi{name}) Abi{name},x:Abi{name}) Abi{name} {{ return f(x) }}\n'
    SOURCE+=f'pub fn abi_{name}_defer(x:Abi{name}) Abi{name} {{ defer {{ x.{field}+={increment} }} return x }}\n'
SOURCE+="""
packed struct AbiPacked { tag:u8,value:i64 }
pub fn abi_Packed(x:AbiPacked) AbiPacked { x.value+=1 return x }
pub fn abi_Packed_call(x:AbiPacked) AbiPacked { return abi_Packed(x) }
pub fn abi_Packed_defer(x:AbiPacked) AbiPacked { defer { x.value+=1 } return x }
pub fn abi_bytes_ptr(p:*AbiBytes) AbiBytes { return abi_Bytes(p.*) }
pub fn abi_big_panic(a:u64) u64 { return abi_Three(AbiThree{a:1,b:2,value:a}).value }
pub fn abi_pressure(a:u64,b:u64,c:u64,d:u64,e:u64,x:AbiTwo,f:u64) u64 { return a+b+c+d+e+x.other+x.value+f }
pub fn abi_pressure_call() u64 { return abi_pressure(1,2,3,4,5,AbiTwo{other:7,value:9},11) }
pub fn abi_fp_pressure(a:f64,b:f64,c:f64,d:f64,e:f64,f:f64,g:f64,x:AbiDoubles,h:f64) f64 { return a+b+c+d+e+f+g+x.a+x.value+h }
pub fn abi_fp_pressure_call() f64 { return abi_fp_pressure(1.0,2.0,3.0,4.0,5.0,6.0,7.0,AbiDoubles{a:8.0,value:9.0},10.0) }
pub fn abi_no_local() AbiTwo { return AbiTwo{other:11,value:22} }
pub fn abi_literal(a:u64) u64 { return abi_Two(AbiTwo{other:1,value:a}).value }
pub fn abi_observe(x:AbiTwo) { global_counter=x.other+x.value }
pub fn abi_capture(a:u64) u64 { global_counter=0 x:=AbiTwo{other:1,value:a} defer abi_observe(x) x.value=99 return x.value }
"""

CAST_TYPES=[('i8',ctypes.c_int8,8,True),('u8',ctypes.c_uint8,8,False),('i16',ctypes.c_int16,16,True),('u16',ctypes.c_uint16,16,False),('i32',ctypes.c_int32,32,True),('u32',ctypes.c_uint32,32,False),('i64',ctypes.c_int64,64,True),('u64',ctypes.c_uint64,64,False)]
for integer,ty,bits,signed in CAST_TYPES:
    for floating in ('f32','f64'):
        SOURCE+=f'pub fn cast_{integer}_{floating}(a:{integer}) {floating} {{ return #cast({floating}) a }}\n'
        SOURCE+=f'pub fn cast_{floating}_{integer}(a:{floating}) {integer} {{ return #cast({integer}) a }}\n'
ARRAY_ABI_TYPES=[('u8',ctypes.c_uint8),('i16',ctypes.c_int16),('u64',ctypes.c_uint64),('f32',ctypes.c_float),('f64',ctypes.c_double)]
for name,ty in ARRAY_ABI_TYPES:
    for n in range(1,7):
        increment='1.0' if name.startswith('f') else '1'
        literal=','.join(f'{i}.0' if name.startswith('f') else str(i) for i in range(n))
        SOURCE+=f'pub fn arrayabi_{name}_{n}(x:[{n}]{name}) [{n}]{name} {{ x[{n-1}]+={increment} return x }}\n'
        SOURCE+=f'pub fn arrayabi_{name}_{n}_call(a:{name}) {name} {{ x:[{n}]{name}=[{literal}] x[{n-1}]=a return arrayabi_{name}_{n}(x)[{n-1}] }}\n'
        SOURCE+=f'pub fn arrayabi_{name}_{n}_apply(f:*fn([{n}]{name}) [{n}]{name},a:{name}) {name} {{ x:[{n}]{name}=[{literal}] x[{n-1}]=a return f(x)[{n-1}] }}\n'
SOURCE+="""
pub fn arrayabi_gp(a:u64,b:u64,c:u64,d:u64,e:u64,x:[3]u8) [3]u8 { return x }
pub fn arrayabi_gp_call() u64 { x:=arrayabi_gp(1,2,3,4,5,[7,8,9]) return #cast(u64)x[0]*100+#cast(u64)x[1]*10+#cast(u64)x[2] }
pub fn arrayabi_fp(a:f64,b:f64,c:f64,d:f64,e:f64,f:f64,g:f64,x:[3]f32) [3]f32 { return x }
pub fn arrayabi_fp_call() f32 { x:=arrayabi_fp(1.0,2.0,3.0,4.0,5.0,6.0,7.0,[8.0,9.0,10.0]) return x[0]+x[1]+x[2] }
struct ArrayMixed { a:u64,b:u64,c:u64,d:f32,e:f64,f:f32,g:f64 }
pub fn arrayabi_mixed(x:[1]ArrayMixed) [1]ArrayMixed { return x }
pub fn arrayabi_mixed_call() f64 { x:=arrayabi_mixed([ArrayMixed{a:1,b:2,c:3,d:4.0,e:5.0,f:6.0,g:7.0}]) return #cast(f64)(x[0].a+x[0].b+x[0].c)+#cast(f64)x[0].d+x[0].e+#cast(f64)x[0].f+x[0].g }
pub fn arrayabi_nested(x:[2][2]u64) [2][2]u64 { return x }
pub fn arrayabi_nested_call() u64 { x:=arrayabi_nested([[1,2],[3,4]]) return x[0][0]+x[0][1]*10+x[1][0]*100+x[1][1]*1000 }
pub fn each_array(a:u64) u64 { x:[3]u64=[1,2,3] total:u64=0 for item in x { x[1]=9 total=total*10+item } return total }
pub fn each_slice(a:u64) u64 { x:[3]u64=[1,2,3] total:u64=0 for item in x[..] { x[1]=9 total=total*10+item } return total }
pub fn each_pointer(a:u64) u64 { x:[3]u64=[1,2,3] for *item in x { item.*+=a } return x[0]+x[1]+x[2] }
pub fn each_reverse(a:u64) u64 { total:u64=0 for item in #reverse([1,2,3]) { total=total*10+#cast(u64)item } return total }
pub fn each_nested(a:u64) u64 { x:[2][2]u64=[[1,2],[3,4]] total:u64=0 for row in x { for item in row { total=total*10+item } } return total }
pub fn each_defer(a:u64) u64 { global_counter=0 for item in [1,2,3,4] { defer defer_digit(#cast(u64)item) if item==1 { continue } if item==3 { break } } return global_counter }
pub fn each_early(a:u64) u64 { global_counter=0 for item in [1,2,3] { defer defer_digit(#cast(u64)item) if #cast(u64)item==a { return #cast(u64)item } } return 0 }
"""

def configure(library, name, ty, argc):
    fn = getattr(library, name)
    fn.argtypes = [ty] * argc
    if name.endswith(('_shl', '_shr')) or name == 'nested_shift':
        fn.argtypes = [ty] * (argc - 1) + [ctypes.c_uint64]
    fn.restype = ty
    return fn


def math_result(operation, args):
    a = args[0]
    if operation == 'neg': return -a
    b = args[1]
    return a + b if operation == 'add' else a - b if operation == 'sub' else a * b


with tempfile.TemporaryDirectory(prefix='dyn-scalar-backend-') as directory:
    root = Path(directory)
    source = root / 'main.dyn'
    source.write_text(SOURCE)
    support = root / 'support.o'
    run([*CC, '-O2', '-fPIC', '-ffreestanding', '-fno-builtin', '-fno-stack-protector',
         '-c', ROOT / 'runtime/reference_support.c', '-o', support])
    rng = random.Random(1776)
    count = panic_count = 0
    u64, i64, boolean = ctypes.c_uint64, ctypes.c_int64, ctypes.c_bool
    specs = [('constant', u64, 0), ('minimum', i64, 0), ('identity', u64, 1), ('mix', u64, 6),
             ('bits', u64, 2), ('subtract', i64, 2), ('negate', i64, 1),
             ('complement', u64, 1), ('invert', boolean, 1), ('truth', boolean, 0), ('size', u64, 2),
             ('literal_shift', u64, 1), ('literal_right', i64, 1)]
    for mode in ('debug', 'release'):
        obj = root / ('scalar-' + mode + '.o')
        native = root / ('scalar-' + mode + '.so')
        run([BACKEND, *(['--debug'] if mode == 'debug' else []), source, obj])
        inspect(obj, mode == 'debug')
        runtime = root / ('runtime-' + mode + '.o')
        # Production shared builds use dynrt_shared.o in both modes. Debug
        # emission adds function traces; release retains only the runtime header.
        run([*CC, '-fPIC', '-DDYN_SHARED', '-c', ROOT / 'runtime/linux_x86_64_start.S', '-o', runtime])
        run([*CC, '-shared', '-Wl,--no-undefined', obj, runtime, support, '-lm', '-o', native])
        if mode == 'debug':
            alignment_source = root / 'alignment.S'
            alignment_source.write_text("""
.text
.global dyn_trace_push
.type dyn_trace_push,@function
dyn_trace_push:
    mov %rsp, %rax
    and $15, %eax
    cmp $8, %eax
    jne .Lbad
    incq .Lcalls(%rip)
    ret
.Lbad:
    mov $122, %edi
    mov $231, %eax
    syscall
    ud2
.global alignment_seen
.type alignment_seen,@function
alignment_seen:
    mov .Lcalls(%rip), %rax
    ret
.bss
.p2align 3
.Lcalls: .quad 0
.section .note.GNU-stack,"",@progbits
""")
            alignment_library = root / 'alignment.so'
            run([*CC, '-shared', '-fPIC', alignment_source, '-o', alignment_library])
            alignment_code = """import ctypes as c,sys
lib=c.CDLL(sys.argv[1]); probe=c.CDLL(sys.argv[2]); probe.alignment_seen.restype=c.c_uint64
for name,args,expected in [('call_nested',(1,2,3),266),('call_args6',(1,2,3,4,5,6),123456),
                           ('call_six_nested',(1,2,3,4,5,6),123907),('call_arity3',(1,2,3),123),
                           ('float_mixed_call',(),47.5),('float_mixed_indirect',(),47.5),('float_max_call',(),397.0),('indirect_use',(7,),14),('indirect_six',(1,),123456),('indirect_stack',(7,),7),('large_frame',(7,),168),('loop_nested',(5,),50),('call_arity4',(1,2,3,4),1234),('call_arity5',(1,2,3,4,5),12345),
                           ('factorial',(10,),3628800),('rec_entry',(3,1),4)]:
 fn=getattr(lib,name);fn.argtypes=[c.c_uint64]*len(args);fn.restype=c.c_double if name.startswith('float_') else c.c_uint64
 for _ in range(5): assert fn(*args)==expected
for n in (7,8,9,16,32,256):
 fn=getattr(lib,f'stack_call{n}'); fn.argtypes=[c.c_uint64]*n; fn.restype=c.c_uint64
 selected=range(n) if n<=32 else (0,5,6,127,255)
 assert fn(*range(n))==sum(i*(i+1) for i in selected)
assert probe.alignment_seen()>100, 'alignment interposer did not run'
"""
            # Only this ABI probe replaces the trace hook. Ordinary execution
            # and all panic comparisons use the unmodified Dyn runtime.
            run([sys.executable, '-c', alignment_code, native, alignment_library],
                env=dict(os.environ, LD_PRELOAD=str(alignment_library)))
        production_path = root / ('production-' + mode + '.so')
        run([DYN, 'build', root, '--shared', '--' + mode, '--no-cache',
             '--jobs', '1', '--output', production_path])
        # An executable's smaller overriding symbol has no experiment-owned padding.
        override_asm=root/'override.S';override_c=root/'override.c'
        text='.data\n'
        for name,size in [('global_small',1),('global_u16',2),('global_i32',4),('global_f32',4)]:
            text+=f'.global {name}\n.type {name},@object\n.size {name},{size}\n{name}: .zero {size}\n'
            text+=f'.global {name}_canary\n{name}_canary: .byte 1,2,3,4,5,6,7\n'
        override_asm.write_text(text+'.section .note.GNU-stack,"",@progbits\n')
        override_c.write_text('#include <stdint.h>\nextern int8_t globals_small(int8_t);\nextern uint16_t globals_u16(uint16_t);\nextern int32_t globals_i32(int32_t);\nextern float globals_f32(float);\nextern unsigned char global_small_canary[],global_u16_canary[],global_i32_canary[],global_f32_canary[];\nint main(void) {\n if(globals_small(-2)!=-1 || globals_u16(65535)!=65535 || globals_i32(-12345)!=-12345 || globals_f32(1.25f)!=1.25f) return 1;\n unsigned char *p[]={global_small_canary,global_u16_canary,global_i32_canary,global_f32_canary};\n for(unsigned j=0;j<4;j++) for(unsigned i=0;i<7;i++) if(p[j][i]!=i+1) return 2;\n return 0;\n}\n')
        for library in (native,production_path):
            override_exe=root/'override'
            run([*CC,override_c,override_asm,library,'-lm','-Wl,-rpath,'+str(root),'-o',override_exe])
            run([override_exe])
        fast, production = ctypes.CDLL(str(native)), ctypes.CDLL(str(production_path))
        generic_symbol=next(line.split()[-1] for line in run(['nm','-D',native]).stdout.splitlines() if ' generic_add__g' in line)
        for name, ty, argc in specs:
            ours, reference = [configure(lib, name, ty, argc) for lib in (fast, production)]
            edges = [0, 1, 2, (1 << 63) - 1, 1 << 63, (1 << 64) - 1]
            vectors = [[n] * argc for n in edges]
            vectors += [[rng.getrandbits(64) for _ in range(argc)] for _ in range(100)]
            for args in vectors:
                assert ours(*args) == reference(*args), (mode, name, args)
                count += 1
        for type_name in ('i64', 'u64', 'isize', 'usize', 'bool'):
            signed = type_name.startswith('i')
            ty = boolean if type_name == 'bool' else i64 if signed else u64
            values = [0, 1] if ty == boolean else [ty(n).value for n in (0, 1, 2, (1 << 63) - 1, 1 << 63, (1 << 64) - 1)]
            vectors = list(itertools.product(values, repeat=2))
            if ty != boolean: vectors += [(ty(rng.getrandbits(64)).value, ty(rng.getrandbits(64)).value) for _ in range(100)]
            for operation, (_, compare) in COMPARISONS.items():
                if ty == boolean and operation not in ('eq', 'ne'): continue
                name = f'compare_{type_name}_{operation}'
                ours, reference = [configure(lib, name, ty, 2) for lib in (fast, production)]
                ours.restype = reference.restype = boolean
                for args in vectors:
                    assert ours(*args) == reference(*args) == compare(*args), (mode, name, args)
                    count += 1
        branch_cases = [
            ('logical_and', boolean, (False, False), False), ('logical_and', boolean, (False, True), False),
            ('logical_and', boolean, (True, False), False), ('logical_and', boolean, (True, True), True),
            ('logical_or', boolean, (False, False), False), ('logical_or', boolean, (False, True), True),
            ('logical_or', boolean, (True, False), True), ('logical_or', boolean, (True, True), True),
            ('and_div', u64, (0, 0), False), ('and_div', u64, (1, 1), True), ('and_div', u64, (1, 2), False),
            ('or_div', u64, (0, 0), True), ('or_div', u64, (1, 1), True), ('or_div', u64, (1, 2), False),
            ('order_and', u64, (0, 0, 0), False), ('order_and', u64, (1, 1, 1), True),
            ('nested_chain', u64, (0, 0, 0), True), ('nested_chain', u64, (1, 0, 0), False),
            ('nested_chain', u64, (1, 1, 1), True), ('nested_chain', u64, (1, 1, 2), False),
            ('choose', u64, (0, (1 << 64) - 1), (1 << 64) - 1), ('choose', u64, ((1 << 64) - 1, 0), (1 << 64) - 1),
            ('early', i64, (-(1 << 63), (1 << 63) - 1), -(1 << 63)), ('early', i64, (1, -2), -2), ('early', i64, (3, 4), 7),
            ('nested_branch', u64, (0, 0, 9), 9), ('nested_branch', u64, (0, 2, 9), 2),
            ('nested_branch', u64, (3, 0, 9), 3), ('nested_branch', u64, (3, 2, 9), 5),
            ('bool_branch', boolean, (False, False), True), ('bool_branch', boolean, (False, True), False),
            ('bool_branch', boolean, (True, False), False), ('bool_branch', boolean, (True, True), True),
            ('branch_div', u64, (0, 0), 7), ('branch_div', u64, (9, 2), 4),
            ('branch_overflow', u64, (0, (1 << 64) - 1), (1 << 64) - 1),
            ('branch_overflow', u64, ((1 << 64) - 1, 0), (1 << 64) - 1),
            ('condition_div', u64, (0, 1), 1), ('condition_div', u64, (9, 2), 9),
            ('branch_shift', u64, (0, 64), 0), ('branch_shift', u64, (1, 63), 1 << 63),
        ]
        for _ in range(100):
            a, b, c = [rng.randrange(10000) for _ in range(3)]
            branch_cases += [('choose', u64, (a, b), max(a, b)), ('early', i64, (a, b), a + b),
                             ('nested_branch', u64, (a, b, c), c if a == b == 0 else b if a == 0 else a if b == 0 else a + b)]
        for name, ty, args, expected in branch_cases:
            ours, reference = [configure(lib, name, ty, len(args)) for lib in (fast, production)]
            if isinstance(expected, bool): ours.restype = reference.restype = boolean
            assert ours(*args) == reference(*args) == expected, (mode, name, args)
            count += 1
        mask = (1 << 64) - 1
        for _ in range(100):
            args = [rng.getrandbits(64) for _ in range(6)]
            a,b,c,d,e,f = args
            cases = [('call_zero', [], 0), ('call_nested', args[:3], (a + b * 131 + c) & mask),
                     ('call_args6', args, (a * 100000 + b * 10000 + c * 1000 + d * 100 + e * 10 + f) & mask),
                     ('call_six_nested', args, (a + a * 100000 + b * 10000 + c * 1000 + ((d + e) & mask) * 100 + f) & mask),
                     ('call_forward', [a], (a + 1) & mask), ('call_after', [a,b,c or 1], (a + b // (c or 1)) & mask),
                     ('call_branch', [0,b], b), ('call_branch', [a,b or 1], a // (b or 1) if a else b or 1),
                     ('call_short', [0,0], True)]
            cases += [(f'call_arity{n}', args[:n], sum(args[i] * 10 ** (n-i-1) for i in range(n)) & mask) for n in (3,4,5)]
            for name, values, expected in cases:
                ours, reference = [configure(lib, name, u64, len(values)) for lib in (fast, production)]
                if isinstance(expected, bool): ours.restype = reference.restype = boolean
                assert ours(*values) == reference(*values) == expected, (mode,name,values)
                count += 1
        for arity in STACK_ARITIES:
            selected = range(arity) if arity <= 32 else (0, 5, 6, 127, 255)
            for values in ([0]*arity, [mask]*arity, list(range(arity)),
                           *([rng.getrandbits(64) for _ in range(arity)] for _ in range(20))):
                expected = sum(values[i]*(i+1) for i in selected) & mask
                for name, result in ((f'stack{arity}', expected),
                                     (f'stack_call{arity}', (expected+values[0]) & mask)):
                    ours, reference = [configure(lib, name, u64, arity) for lib in (fast,production)]
                    assert ours(*values) == reference(*values) == result, (mode,name,values)
                    count += 1
        for a,b in itertools.product((False,True),repeat=2):
            for lib in (fast,production): assert configure(lib,'call_bool',boolean,2)(a,b) == ((a and b) or not a)
            count += 1
        for values in itertools.product((False,True), repeat=8):
            expected = (values[6] and not values[7]) or values[0]
            for name in ('stack_bool','stack_call_bool'):
                for lib in (fast,production): assert configure(lib,name,boolean,8)(*values) == expected
                count += 1
        for _ in range(100):
            values = [rng.randrange(-(1<<63),1<<63) for _ in range(8)]
            expected = (values[6]-values[7]+values[0]) & mask
            if expected >= 1<<63: expected -= 1<<64
            for name in ('stack_i64','stack_call_i64'):
                for lib in (fast,production): assert configure(lib,name,i64,8)(*values) == expected
                count += 1
        factorial_value = 1
        for n in range(21):
            if n: factorial_value *= n
            for lib in (fast,production):
                assert configure(lib,'factorial',u64,1)(n) == factorial_value
                for name, expected in [('mutual_even', n % 2 == 0), ('mutual_odd', n % 2 == 1)]:
                    fn=configure(lib,name,u64,1); fn.restype=boolean
                    assert fn(n) == expected
                assert configure(lib,'rec_entry',u64,2)(n,1) == n+1
            count += 4
        for n in range(32):
            for name, args, expected in [
                ('loop_sum',[n],sum(i for i in range(1,min(n,20)+1) if i != 2)),
                ('loop_nested',[n],n*(n+1)+4*n), ('loop_early',[n],min(n,5)),
                ('loop_forever',[n],n), ('loop_label',[n],sum(i for i in range(1,min(n,5)+1) if i != 2)), ('local_zero',[],0), ('local_scope',[n],n),
                ('large_frame',[n],24*n), ('local_wrap',[(1<<64)-1,n],(n-1)&((1<<64)-1))]:
                for lib in (fast,production): assert configure(lib,name,u64,len(args))(*args) == expected, (name,args)
                count += 1
        for a in (False, True):
            for lib in (fast,production): assert configure(lib,'local_bool',boolean,1)(a) == False
            count += 1
        for a,b in [(-(1<<63),0),((1<<63)-1,0),(-100,99),(100,-99)]:
            for lib in (fast,production): assert configure(lib,'local_signed',i64,2)(a,b) == a+b
            count += 1
        callback_type = ctypes.CFUNCTYPE(u64,u64)
        seen=[]
        callback=callback_type(lambda value: seen.append(value) or ((value*7)&((1<<64)-1)))
        for lib in (fast,production):
            fn=lib.indirect_apply;fn.argtypes=[callback_type,u64];fn.restype=u64
            assert fn(callback,123)==861
            count+=1
        assert seen==[123,123]
        for tyname in ('i64','u64'):
            ty=i64 if tyname == 'i64' else u64
            lo,hi=(-(1<<63),(1<<63)-1) if tyname == 'i64' else (0,(1<<64)-1)
            for a,b in [(0,0),(0,5),(5,0),(lo,lo+3),(hi-3,hi)]:
                for reverse,inclusive in itertools.product((False,True),repeat=2):
                    values=list(range(a,b+int(inclusive)))
                    if reverse: values.reverse()
                    expected=0
                    for value in values: expected=(expected*17+value)&((1<<64)-1)
                    if tyname=='i64' and expected>=1<<63: expected-=1<<64
                    name=f'range_{tyname}_{int(reverse)}_{int(inclusive)}'
                    for lib in (fast,production): assert configure(lib,name,ty,2)(a,b)==expected,(name,a,b,expected)
                    count+=1
        for a in range(-10,11):
            for lib in (fast,production):
                assert configure(lib,'scalar_case',i64,1)(a)==(-1 if -5<=a<=-1 else 10 if a in (0,2,4) else 99)
                assert configure(lib,'foreign_abs32',ctypes.c_int32,1)(a)==abs(a)
                assert configure(lib,'foreign_abs',i64,1)(a)==abs(a)
                assert configure(lib,'indirect_foreign',i64,1)(a)==abs(a)
            count+=4
        for a,b in [(0,0),(0,8),(3,8),(6,9)]:
            values=[]
            for i in range(a,b):
                if i==2: continue
                if i==5: break
                values.append(i)
            for lib in (fast,production):
                assert configure(lib,'range_controls',u64,2)(a,b)==sum(values)
                assert configure(lib,'range_nested',u64,2)(a,b)==sum(3*i+3 for i in values)
                assert configure(lib,'void_caller',u64,2)(a,b or 1)==a
                assert configure(lib,'indirect_use',u64,1)(a)==a*2
                assert configure(lib,'indirect_six',u64,1)(a)==a*100000+23456
                assert configure(lib,'indirect_stack',u64,1)(a)==a
                configure(lib,'indirect_void',u64,1)(a)
                assert configure(lib,'case_update',u64,1)(a)==(10 if a<=2 else 20)
            count+=8
        def same_float(a,b,ty):
            return (math.isnan(a) and math.isnan(b)) or bytes(ty(a))==bytes(ty(b))
        for tyname,ty in [('f32',ctypes.c_float),('f64',ctypes.c_double)]:
            values=[0.0,-0.0,1.0,-1.0,0.25,1e-30,1e30,float('inf'),-float('inf'),float('nan')]
            values+=[rng.uniform(-1e6,1e6) for _ in range(8)]
            for op in ('add','sub','mul','div','rem',*COMPARISONS):
                name=f'float_{tyname}_{op}'
                ours,ref=[configure(lib,name,ty,2) for lib in (fast,production)]
                if op in COMPARISONS: ours.restype=ref.restype=boolean
                for a,b in itertools.product(values,repeat=2):
                    actual,expected=ours(a,b),ref(a,b)
                    assert actual==expected if op in COMPARISONS else same_float(actual,expected,ty),(name,a,b,actual,expected)
                    count+=1
            for a in values:
                for suffix in ('neg',):
                    name=f'float_{tyname}_{suffix}'
                    actual,expected=[configure(lib,name,ty,1)(a) for lib in (fast,production)]
                    assert same_float(actual,expected,ty),(name,a,actual,expected);count+=1
            for lib in (fast,production):
                assert configure(lib,f'float_{tyname}_constant',ty,0)()==1.25
                assert configure(lib,f'float_{tyname}_call',ty,2)(1.25,2.5)==3.75
                assert configure(lib,f'float_{tyname}_local',ty,2)(-1.25,-2.5)==3.75
                for suffix in ('stack','stack_call'):
                    assert configure(lib,f'float_{tyname}_{suffix}',ty,10)(*range(10))==45.0
                cb_type=ctypes.CFUNCTYPE(ty,ty,ty);callback=cb_type(lambda a,b:a+b)
                fn=getattr(lib,f'float_{tyname}_apply');fn.argtypes=[cb_type,ty,ty];fn.restype=ty
                assert fn(callback,1.25,2.5)==3.75
                count+=6
        for lib in (fast,production):
            for name in ('float_mixed_call','float_mixed_indirect'):
                assert configure(lib,name,ctypes.c_double,0)()==47.5;count+=1
            assert configure(lib,'float_max',ctypes.c_double,256)(*range(256))==397.0;count+=1
            assert configure(lib,'float_max_call',ctypes.c_double,0)()==397.0;count+=1
            fn=lib.float_mixed;fn.argtypes=[ctypes.c_double,u64]*10;fn.restype=ctypes.c_double
            assert fn(*sum(([i+0.25,i] for i in range(10)),[]))==47.5;count+=1
            fn=configure(lib,'foreign_time',i64,2);fn.restype=ctypes.c_double;assert fn(20,3)==17.0;count+=1
            fn=configure(lib,'float_widen',ctypes.c_float,1);fn.restype=ctypes.c_double;assert fn(1.25)==1.25;count+=1
            fn=configure(lib,'float_narrow',ctypes.c_double,1);fn.restype=ctypes.c_float;assert fn(1.25)==1.25;count+=1
        for lib in (fast,production):
            for name,ty,a,b in [('generic_i8',ctypes.c_int8,-128,127),('generic_i64',i64,-(1<<63),(1<<63)-1),('generic_f64',ctypes.c_double,-1.25,2.5)]:
                assert configure(lib,name,ty,2)(a,b)==min(a,b);count+=1
            assert configure(lib,'generic_recursion',u64,1)(10)==10;count+=1
        for lib in (fast,production):
            assert configure(lib,'globals_read',u64,0)()==106
            assert ctypes.c_int8.in_dll(lib,'global_small').value==-128
            assert ctypes.c_double.in_dll(lib,'global_float').value==-1.25
            assert ctypes.c_bool.in_dll(lib,'global_flag').value==False
            for value in (0,1,100):
                assert configure(lib,'globals_order',u64,1)(value)==value+2
                configure(lib,'globals_reset',u64,1)(7)
                assert configure(lib,'globals_update',u64,1)(value)==7+value
                assert configure(lib,'globals_callback',u64,1)(value)==value
                count+=3
            assert configure(lib,'globals_small',ctypes.c_int8,1)(-128)==-127
            assert configure(lib,'globals_float',ctypes.c_double,1)(0.25)==-1.0
            assert configure(lib,'globals_bool',boolean,1)(True)==True
            configure(lib,'globals_reset',u64,1)(7)
            count+=7
        for integer,ity,bits,signed in CAST_TYPES:
            low=-(1<<(bits-1)) if signed else 0;high=(1<<(bits-1))-1 if signed else (1<<bits)-1
            integers=[low,low+1,0,1,2,high-1,high]+([-(1<<31)+1] if signed and bits==64 else [])
            if bits==64 and not signed: integers += [(1<<63)-1,1<<63,(1<<63)+1,(1<<63)+(1<<39)+1]
            for floating,fty in [('f32',ctypes.c_float),('f64',ctypes.c_double)]:
                ours,ref=[getattr(lib,f'cast_{integer}_{floating}') for lib in (fast,production)]
                for fn in (ours,ref):fn.argtypes=[ity];fn.restype=fty
                for value in integers: assert same_float(ours(value),ref(value),fty),(integer,floating,value,ours(value),ref(value));count+=1
                ours,ref=[getattr(lib,f'cast_{floating}_{integer}') for lib in (fast,production)]
                for fn in (ours,ref):fn.argtypes=[fty];fn.restype=ity
                values=[fty(x).value for x in [low,low+1,high,high-1,0.0,-0.0,0.75,-0.75,1.9,127.9,-127.9,65535.5,2**31+0.5,2**63,2**63+2**40]]
                for value in values:
                    if math.isfinite(value) and low<=math.trunc(value)<=high:
                        assert ours(value)==ref(value)==math.trunc(value),(floating,integer,value,ours(value),ref(value));count+=1
        for name,ty in ARRAY_ABI_TYPES:
            for n in range(1,7):
                for lib,other in ((fast,production),(production,fast)):
                    direct=configure(lib,f'arrayabi_{name}_{n}_call',ty,1)
                    indirect=getattr(lib,f'arrayabi_{name}_{n}_apply');indirect.argtypes=[ctypes.c_void_p,ty];indirect.restype=ty
                    for value in (0,2,7):
                        assert direct(value)==value+1,(mode,name,n,'direct',direct(value))
                        assert indirect(ctypes.cast(getattr(other,f'arrayabi_{name}_{n}'),ctypes.c_void_p),value)==value+1,(mode,name,n,'cross')
                        count+=2
        for lib in (fast,production):
            for name,ty,want in [('arrayabi_gp_call',u64,789),('arrayabi_fp_call',ctypes.c_float,27.0),('arrayabi_mixed_call',ctypes.c_double,28.0),('arrayabi_nested_call',u64,4321)]:
                assert configure(lib,name,ty,0)()==want,(mode,name);count+=1
            for name,arg,want in [('each_array',0,123),('each_slice',0,193),('each_pointer',7,27),('each_reverse',0,321),('each_nested',0,1234),('each_defer',0,123),('each_early',2,2)]:
                assert configure(lib,name,u64,1)(arg)==want,(mode,name);count+=1
        foreign_root=root/'foreign-abi';foreign_root.mkdir(exist_ok=True)
        foreign_source=foreign_root/'main.dyn'
        foreign_source.write_text("""
struct Pair { value:i64,real:f64 }
struct Big { a:u64,b:u64,c:u64 }
packed struct Packed { tag:u8,value:i64 }
extern fn c_pair(x:Pair) Pair
extern fn c_big(x:Big) Big
extern fn c_packed(x:Packed) Packed
pub fn foreign_pair(a:i64) f64 { return c_pair(Pair{value:a,real:2.5}).real }
pub fn foreign_big(a:u64) u64 { return c_big(Big{a:1,b:2,c:a}).c }
pub fn foreign_packed(a:i64) i64 { return c_packed(Packed{tag:7,value:a}).value }
""")
        provider=root/'foreign-provider.c';provider_obj=root/'foreign-provider.o'
        provider.write_text("""
#include <stdint.h>
typedef struct { int64_t value;double real; } Pair;
typedef struct { uint64_t a,b,c; } Big;
typedef struct __attribute__((packed)) { uint8_t tag;int64_t value; } Packed;
Pair c_pair(Pair x) { x.real+=x.value;return x; }
Big c_big(Big x) { x.c+=x.a+x.b;return x; }
Packed c_packed(Packed x) { x.value+=x.tag;return x; }
""")
        run([*CC,'-O2','-fPIC','-c',provider,'-o',provider_obj])
        foreign_obj=root/('foreign-'+mode+'.o');foreign_native=root/('foreign-native-'+mode+'.so');foreign_llvm=root/('foreign-production-'+mode+'.so')
        run([BACKEND,*(['--debug'] if mode=='debug' else []),foreign_source,foreign_obj])
        run([*CC,'-shared','-Wl,--no-undefined',foreign_obj,runtime,support,provider_obj,'-o',foreign_native])
        run([DYN,'build',foreign_root,'--shared','--'+mode,'--no-cache','--jobs','1','--link',provider_obj,'--output',foreign_llvm])
        for library in (foreign_native,foreign_llvm):
            lib=ctypes.CDLL(str(library))
            fn=lib.foreign_pair;fn.argtypes=[i64];fn.restype=ctypes.c_double;assert fn(9)==11.5
            assert configure(lib,'foreign_big',u64,1)(9)==12
            assert configure(lib,'foreign_packed',i64,1)(9)==16
            count+=3
        packed_source=root/'packed-abi.c'
        packed_source.write_text("""
#include <stdint.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
typedef struct __attribute__((packed)) { uint8_t tag; int64_t value; } Packed;
typedef struct { uint8_t data[3]; } Bytes;
extern Packed abi_Packed(Packed);
extern Packed abi_Packed_call(Packed);
extern Packed abi_Packed_defer(Packed);
extern Bytes abi_bytes_ptr(Bytes *);
extern void packed_boundary(void *,uint64_t,uint64_t);
__asm__(".text\\n.global packed_boundary\\npacked_boundary:\\nsub $24,%rsp\\nmov %rsi,(%rsp)\\nmov %rdx,8(%rsp)\\ncall abi_Packed\\nadd $24,%rsp\\nret\\n");
int main(void) { Packed x={7,9},a=abi_Packed(x),b=abi_Packed_call(x),c=abi_Packed_defer(x);
if (a.tag!=7 || a.value!=10 || b.tag!=7 || b.value!=10 || c.tag!=7 || c.value!=9) return 1;
long page=sysconf(_SC_PAGESIZE); unsigned char *area=mmap(0,(size_t)page*2,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
if (area==MAP_FAILED || mprotect(area+page,(size_t)page,PROT_NONE)) return 2;
Bytes *bytes=(Bytes*)(area+page-3); bytes->data[0]=1;bytes->data[1]=2;bytes->data[2]=9;
Bytes result=abi_bytes_ptr(bytes); if (result.data[0]!=1 || result.data[1]!=2 || result.data[2]!=10) return 3;
unsigned char *dest=area+page-9; packed_boundary(dest,0x907,0); int64_t value; memcpy(&value,dest+1,8);
if (dest[0]!=7 || value!=10) return 4;
return munmap(area,(size_t)page*2)!=0; }
""")
        for library in (native,production_path):
            host=root/(library.stem+'-packed')
            run([*CC,packed_source,str(library),'-lm','-Wl,-rpath,'+str(root),'-o',host]);run([host]);count+=1
        for name,fields,decl,field,value in ABI_STRUCTS:
            Ty=type(name,(ctypes.Structure,),{'_fields_':fields})
            item=Ty()
            for fname,fty in fields:
                if issubclass(fty,ctypes.Array):
                    setattr(item,fname,fty(1,2,9))
                else: setattr(item,fname,True if fty==ctypes.c_bool else 2.5 if fty in (ctypes.c_float,ctypes.c_double) else 7)
            if '[' not in field: setattr(item,field,value)
            def components(x):
                return [list(getattr(x,n)) if issubclass(t,ctypes.Array) else getattr(x,n) for n,t in fields]
            expected=components(item)
            target=field.split('[')[0]; index=[n for n,_ in fields].index(target)
            if '[' in field: expected[index][2]+=1
            else: expected[index]+=1
            for lib,other in ((fast,production),(production,fast)):
                for suffix in ('','_call','_apply','_defer'):
                    fn=getattr(lib,'abi_'+name+suffix);fn.restype=Ty
                    if suffix=='_apply':
                        fn.argtypes=[ctypes.c_void_p,Ty]
                        actual=fn(ctypes.cast(getattr(other,'abi_'+name),ctypes.c_void_p),item)
                    else:
                        fn.argtypes=[Ty];actual=fn(item)
                    assert components(actual)==(components(item) if suffix=='_defer' else expected),(mode,name,suffix,components(actual),expected)
                    count+=1
        for lib in (fast,production):
            class NoLocal(ctypes.Structure):
                _fields_=[('other',u64),('value',u64)]
            actual=configure(lib,'abi_no_local',NoLocal,0)()
            assert (actual.other,actual.value)==(11,22)
            count+=1
            assert configure(lib,'abi_pressure_call',u64,0)()==42
            assert configure(lib,'abi_fp_pressure_call',ctypes.c_double,0)()==55.0
            for a in (0,1,9,100):
                assert configure(lib,'abi_literal',u64,1)(a)==a+1
                assert configure(lib,'abi_capture',u64,1)(a)==99
                assert configure(lib,'defer_read',u64,0)()==a+1
                count+=2
            count+=2
        class Slice(ctypes.Structure):
            _fields_=[('data',ctypes.c_void_p),('length',ctypes.c_size_t)]
        for lib in (fast,production):
            for a in (0,1,7,1000):
                assert configure(lib,'slice_call',u64,1)(a)==a+4
                assert configure(lib,'slice_stack_call',u64,1)(a)==a+18
                for i,want in enumerate((10,6)): assert configure(lib,'slice_local',u64,2)(a,i)==want
                count+=4
            buf=(u64*4)(7,8,9,10); descriptor=Slice(ctypes.addressof(buf),4)
            fn=lib.slice_read;fn.argtypes=[Slice,ctypes.c_size_t];fn.restype=u64
            for i in range(4): assert fn(descriptor,i)==buf[i]+4; count+=1
            for name in ('slice_identity','slice_defer_return'):
                fn=getattr(lib,name);fn.argtypes=[Slice];fn.restype=Slice
                actual=fn(descriptor);assert (actual.data,actual.length)==(descriptor.data,4);count+=1
            fn=lib.slice_raw;fn.argtypes=[ctypes.c_void_p,ctypes.c_size_t];fn.restype=Slice
            actual=fn(ctypes.addressof(buf),4);assert (actual.data,actual.length)==(ctypes.addressof(buf),4);count+=1
            fn=lib.slice_capture;fn.argtypes=[Slice];fn.restype=u64
            assert fn(descriptor)==9 and configure(lib,'defer_read',u64,0)()==11;count+=1
            for i in range(3): assert configure(lib,'slice_string',ctypes.c_uint8,1)(i)==ord('abc'[i]);count+=1
            for name,length in [('slice_bounds',4),('slice_nested_bounds',3)]:
                fn=configure(lib,name,u64,2)
                for a in range(length+1):
                    for b in range(a,length+1): assert fn(a,b)==b-a;count+=1
        class Storage(ctypes.Structure):
            _fields_=[('tag',ctypes.c_uint8),('wide',u64),('small',ctypes.c_int16),('values',u64*3)]
        for lib in (fast,production):
            for a in (0,1,7,1000):
                for name,want in [('array_nested',a+6),('array_assign',a+5),('struct_local',2*a+14),('struct_nested',a+5)]:
                    assert configure(lib,name,u64,1)(a)==want,(mode,name)
                    count+=1
                for i,want in enumerate((a+3,8,7)):
                    assert configure(lib,'array_local',u64,2)(a,i)==want
                    count+=1
                st=Storage(); fn=lib.struct_pointer;fn.argtypes=[ctypes.POINTER(Storage),u64];fn.restype=u64
                assert fn(ctypes.byref(st),a)==2*a+1
                assert (st.tag,st.wide,st.small,list(st.values))==(8,a,-3,[0,a+1,0])
                count+=1
            for i in range(8): assert configure(lib,'array_zero',u64,1)(i)==0; count+=1
            assert configure(lib,'struct_zero',u64,0)()==0
            assert configure(lib,'aggregate_defer',u64,1)(7)==2 and configure(lib,'defer_read',u64,0)()==3
            count+=2
            fn=lib.array_pointer;fn.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_uint16];fn.restype=ctypes.c_uint16
            for i in range(3):
                buf=(ctypes.c_uint16*5)(91,0,0,0,92)
                assert fn(ctypes.byref(buf,2),i,65530)==65530
                assert list(buf)==[91]+[65530 if j==i else 0 for j in range(3)]+[92]
                count+=1
            fn=lib.array_copy;fn.argtypes=[ctypes.c_void_p,ctypes.c_void_p];fn.restype=None
            for dst,src,want in [(1,0,[1,1,2,3,5]),(0,1,[2,3,4,4,5]),(0,0,[1,2,3,4,5])]:
                buf=(ctypes.c_uint16*5)(1,2,3,4,5)
                fn(ctypes.byref(buf,dst*2),ctypes.byref(buf,src*2))
                assert list(buf)==want,(mode,dst,src,list(buf))
                count+=1
        for lib in (fast,production):
            read=configure(lib,'defer_read',u64,0)
            for name,args,want,side in [
                ('defer_capture',(3,),10,93), ('defer_scope',(1,),21,21),
                ('defer_scope',(0,),0,0), ('defer_loop',(5,),123,123),
                ('defer_loop',(0,),0,0), ('defer_early',(2,),2,21),
                ('defer_early',(0,),1,1), ('defer_call',(7,),14,3),
                ('defer_indirect',(4,),9,4)]:
                assert configure(lib,name,u64,len(args))(*args)==want,(mode,name)
                assert read()==side,(mode,name,read(),side)
                count+=1
            assert configure(lib,'defer_float',ctypes.c_double,1)(0.25)==47.75
            count+=1
        for name,args,output in [
            ('panic_owned',(0,),'5'), ('panic_replace',(0,),''),
            ('array_panic',(3,),'4'), ('array_panic',((1<<64)-1,),'4'),
            ('defer_panic_call',(0,),'21'), ('defer_panic_guard',(0,),'21'),
            ('defer_panic_capture',(0,),'1'), ('defer_panic_cleanup',(0,),''),
            ('defer_panic_recursive',(3,),'0123'), ('defer_panic_parent',(0,),'218')]:
            results=[]
            code="import ctypes,sys; l=ctypes.CDLL(sys.argv[1]); f=getattr(l,sys.argv[2]); f.argtypes=[ctypes.c_uint64]; f.restype=ctypes.c_uint64; f(int(sys.argv[3]))"
            for library in (native,production_path):
                result=subprocess.run([sys.executable,'-c',code,str(library),name,str(args[0])],capture_output=True,text=True,timeout=10)
                clean_stderr(result)
                assert result.returncode==101 and result.stdout==output,(mode,name,result)
                results.append(result.stderr)
            assert results[0]==results[1],(mode,name,results)
            panic_count+=1
        for lib in (fast,production):
            for a in (0,1,10,1000):
                assert configure(lib,'pointer_local',u64,1)(a)==a+1
                assert configure(lib,'pointer_global',u64,1)(a)==a
                assert configure(lib,'pointer_alias',u64,1)(a)==799
                assert configure(lib,'pointer_alias_add',u64,1)(a)==(a+7)*100+99
                assert configure(lib,'pointer_heap',u64,1)(a)==a
                count+=5
            for name,ty,value in [('i8',ctypes.c_int8,-12),('u16',ctypes.c_uint16,65530),('i32',ctypes.c_int32,-123456),('u64',u64,(1<<64)-1),('bool',boolean,True),('f32',ctypes.c_float,1.25),('f64',ctypes.c_double,-1.25)]:
                storage=ctypes.create_string_buffer(bytes(range(32)))
                fn=getattr(lib,f'pointer_{name}');fn.argtypes=[ctypes.c_void_p,ty];fn.restype=ty
                assert fn(ctypes.addressof(storage),value)==value
                width=ctypes.sizeof(ty);assert storage.raw[width:32]==bytes(range(width,32))
                count+=1
            for value in (0.0,-0.0,1.25,-12.5,float('inf')):
                raw=struct.unpack('<I',struct.pack('<f',value))[0]
                fn=configure(lib,'float_bits',ctypes.c_float,1);fn.restype=ctypes.c_uint32;assert fn(value)==raw
                fn=configure(lib,'bits_float',ctypes.c_uint32,1);fn.restype=ctypes.c_float
                assert struct.pack('<f',fn(raw))==struct.pack('<f',value)
                count+=2
            configure(lib,'globals_reset',u64,1)(7)
        panics = []
        for tyname,(bits,signed,ty) in NARROW_TYPES.items():
            low,high=(-(1<<(bits-1)),(1<<(bits-1))-1) if signed else (0,(1<<bits)-1)
            values=[low,low+1,0,1,2,high-1,high]+([-1,-2] if signed else [])
            for op in {**OPERATORS,**SAFETY_OPERATORS}:
                for wrap in (False,True):
                    name=f'narrow_{tyname}_{op}_{int(wrap)}'; failures={}
                    vectors=[(a,) for a in values] if op=='neg' else itertools.product(values,[0,1,bits-1,bits,bits+1] if op in ('shl','shr') else values)
                    for args in vectors:
                        error=None
                        if op in SAFETY_OPERATORS: expected,error=safety_result(op,args,signed,wrap,bits)
                        else:
                            expected=math_result(op,args)
                            if wrap: expected=ty(expected).value
                            elif not low<=expected<=high: error='overflow.ok'
                        if error: failures.setdefault(error,args);continue
                        for lib in (fast,production):
                            fn=configure(lib,name,ty,len(args))
                            if op in ('shl','shr'): fn.argtypes=[ty,u64]
                            assert fn(*args)==expected,(mode,name,args,expected)
                        count+=1
                    panics.extend((name,signed,args,error) for error,args in failures.items())
            for a,b in itertools.product(values,repeat=2):
                for lib in (fast,production):
                    assert configure(lib,f'narrow_{tyname}_bits',ty,2)(a,b)==ty((~a&b)|(a^b)).value
                    assert configure(lib,f'narrow_{tyname}_stack',ty,8)(a,0,0,0,0,0,b,1)==ty(a+b+1).value
                count+=2
            cb_type=ctypes.CFUNCTYPE(ty,ty)
            callback=cb_type(lambda value: ty(value+1).value)
            for lib in (fast,production):
                fn=getattr(lib,f'narrow_{tyname}_apply');fn.argtypes=[cb_type,ty];fn.restype=ty
                assert fn(callback,high)==ty(high+1).value
                count+=1
            for a in values:
                for lib in (fast,production):
                    fn=configure(lib,f'narrow_{tyname}_ptr',ty,1);fn.restype=u64
                    assert fn(a)==(a&((1<<bits)-1))
                count+=1
                for lib in (fast,production): assert configure(lib,f'narrow_{tyname}_call',ty,1)(a)==a
                count+=1
            for a in (0,1,255,256,65535,65536,(1<<32)-1,(1<<64)-1):
                for lib in (fast,production):
                    fn=configure(lib,f'narrow_{tyname}_cast',u64,1);fn.restype=ty
                    assert fn(a)==ty(a).value
                count+=1

        for tyname in ('i64','u64'):
            signed = tyname == 'i64'; ty = i64 if signed else u64
            low,high = (-(1<<63),(1<<63)-1) if signed else (0,(1<<64)-1)
            for op in UPDATE_OPERATORS:
                name = f'update_{tyname}_{op}'; failures = {}
                values = [low,low+1,0,1,2,high-1,high] + ([-1,-2] if signed else [])
                for a,b in itertools.product(values, [0,1,63,64] if op in ('shl','shr') else values):
                    error = None
                    if op in SAFETY_OPERATORS: expected,error = safety_result(op,(a,b),signed,False)
                    elif op in ('band','bor','bxor'): expected = {'band':operator.and_,'bor':operator.or_,'bxor':operator.xor}[op](a,b)
                    else:
                        expected = math_result(op,(a,b))
                        if not low <= expected <= high: error = 'overflow.ok'
                    if error:
                        failures.setdefault(error,(a,b)); continue
                    for lib in (fast,production): assert configure(lib,name,ty,2)(a,b) == expected, (name,a,b)
                    count += 1
                panics.extend((name,signed,args,error) for error,args in failures.items())
        for type_name in ('i64', 'u64', 'isize', 'usize'):
            signed = type_name.startswith('i')
            ty = i64 if signed else u64
            low, high = (-(1 << 63), (1 << 63) - 1) if signed else (0, (1 << 64) - 1)
            edges = [low, low + 1, -1, 0, 1, high - 1, high] if signed else [0, 1, 2, 1 << 32, high - 1, high]
            for operation in OPERATORS:
                name = f'checked_{type_name}_{operation}'
                argc = 1 if operation == 'neg' else 2
                ours, reference = [configure(lib, name, ty, argc) for lib in (fast, production)]
                vectors = list(itertools.product(edges, repeat=argc))
                vectors += [tuple(rng.randint(low, high) for _ in range(argc)) for _ in range(100)]
                vectors += [tuple(rng.randint(-1000000 if signed else 0, 1000000) for _ in range(argc)) for _ in range(100)]
                failures = []
                for args in vectors:
                    expected = math_result(operation, args)
                    if not low <= expected <= high:
                        if len(failures) < 3: failures.append(args)
                        continue
                    assert ours(*args) == reference(*args) == expected, (mode, name, args)
                    count += 1
                assert failures, (name, 'missing overflow probes')
                panics.extend((name, signed, args, 'overflow.ok') for args in failures)
        for type_name in ('i64', 'u64', 'isize', 'usize'):
            signed = type_name.startswith('i')
            ty = i64 if signed else u64
            low, high = (-(1 << 63), (1 << 63) - 1) if signed else (0, (1 << 64) - 1)
            values = [low, low + 1, 0, 1, 2, high - 1, high]
            if signed: values += [-1, -2]
            for operation in SAFETY_OPERATORS:
                right_values = values if operation in ('div', 'rem') else [0, 1, 2, 31, 32, 62, 63, 64, 65, 1 << 63, (1 << 64) - 1]
                for wrap in (False, True):
                    name = f'{"wrap" if wrap else "checked"}_{type_name}_{operation}'
                    ours, reference = [configure(lib, name, ty, 2) for lib in (fast, production)]
                    vectors = list(itertools.product(values, right_values))
                    vectors += [(rng.randint(low, high), rng.randint(low, high) if operation in ('div', 'rem') else rng.randrange(64)) for _ in range(100)]
                    failures = {}
                    for args in vectors:
                        expected, diagnostic = safety_result(operation, args, signed, wrap)
                        if diagnostic:
                            failures.setdefault(diagnostic, args)
                            continue
                        assert ours(*args) == reference(*args) == expected, (mode, name, args, expected)
                        count += 1
                    assert failures, (name, 'missing safety probes')
                    panics.extend((name, signed, args, diagnostic) for diagnostic, args in failures.items())
        for name, signed, args, expected in [('nested', False, (1, 2, 3), 7),
                                             ('nested_twice', True, (1, 2, 3, 4), 15),
                                             ('nested_div', False, (1, 8, 2), 5),
                                             ('nested_shift', True, (1, -1, 3), -7)]:
            ty = i64 if signed else u64
            for lib in (fast, production): assert configure(lib, name, ty, len(args))(*args) == expected
            count += 1
        panics += [('stack_order',False,((1<<64)-1,0),'divide.ok'),
                   ('stack_order',False,((1<<64)-1,1),'overflow.ok'),
                   ('stack_panic',False,(1,0),'divide.ok'),
                   ('nested', False, (1, (1 << 64) - 1, 2), 'overflow.ok'),
                   ('nested', False, ((1 << 64) - 1, 1, 1), 'overflow.ok'),
                   ('nested_twice', True, (1, 2, (1 << 63) - 1, 2), 'overflow.ok'),
                   ('nested_twice', True, ((1 << 63) - 1, 1, 0, 0), 'overflow.ok'),
                   ('nested_div', False, (1, 1, 0), 'divide.ok'),
                   ('nested_shift', True, (1, 1, 64), 'shift.count.ok'),
                   ('nested_shift', True, (1, 1, 63), 'overflow.ok'),
                   ('and_div', False, (1, 0), 'divide.ok'), ('or_div', False, (1, 0), 'divide.ok'),
                   ('order_and', False, ((1 << 64) - 1, 1, 0), 'overflow.ok'),
                   ('order_and', False, (1, 1, 0), 'divide.ok'),
                   ('nested_chain', False, (1, 1, 0), 'divide.ok'),
                   ('branch_div', False, (1, 0), 'divide.ok'), ('condition_div', False, (1, 0), 'divide.ok'),
                   ('branch_overflow', False, ((1 << 64) - 1, 1), 'overflow.ok'),
                   ('early', True, ((1 << 63) - 1, 1), 'overflow.ok'),
                   ('nested_branch', False, ((1 << 64) - 1, 1, 0), 'overflow.ok'),
                   ('branch_shift', False, (1, 64), 'shift.count.ok'),
                   ('factorial', False, (21,), 'overflow.ok'),
                   ('case_panic', False, (1,0), 'divide.ok'),
                   ('slice_bounds', False, (3,2), 'slice.order.ok'),
                   ('slice_bounds', False, (0,5), 'slice.bounds.ok'),
                   ('slice_nested_bounds', False, (0,4), 'slice.bounds.ok'),
                   ('pointer_null', False, (1,), 'pointer.nonnull.ok'),
                   ('pointer_unaligned', False, (1,), 'pointer.aligned.ok'),
                   ('pointer_store_panic', False, (0,1), 'pointer.nonnull.ok'),
                   ('pointer_store_panic', False, (1,1), 'pointer.aligned.ok'),
                   ('pointer_store_panic', False, (2,1), 'divide.ok'),
                   ('abi_big_panic', False, ((1<<64)-1,), 'overflow.ok'),
                   ('generic_panic', False, ((1<<64)-1,1), 'overflow.ok'),
                   ('globals_update', False, ((1<<64)-1,), 'overflow.ok'),
                   ('globals_small', True, (127,), 'overflow.ok'),
                   ('float_panic_call', False, (1,0), 'divide.ok'),
                   ('indirect_nil', False, (1,), 'function.nonnull.ok'),
                   ('indirect_panic', False, (1,0), 'divide.ok'),
                   ('void_caller', False, (1,0), 'divide.ok'),
                   ('range_bound_panic', False, (1,0), 'divide.ok'),
                   ('local_overflow', False, ((1<<64)-1,1), 'overflow.ok'),
                   ('local_signed', True, ((1<<63)-1,1), 'overflow.ok'),
                   ('loop_div', False, (1,0), 'divide.ok'),
                   ('loop_call_div', False, (1,0), 'divide.ok'),
                   ('large_frame_panic', False, ((1<<64)-1,1), 'overflow.ok'),
                   ('loop_condition_div', False, (1,0), 'divide.ok'),
                   ('rec_panic', False, (4,0), 'divide.ok'), ('rec_entry', False, (3,0), 'divide.ok'),
                   ('call_order', False, ((1 << 64) - 1,0,1), 'divide.ok'),
                   ('call_order', False, ((1 << 64) - 1,1,1), 'overflow.ok'),
                   ('call_after', False, (7,1,0), 'divide.ok'),
                   ('call_short', False, (1,0), 'divide.ok'), ('call_branch', False, (1,0), 'divide.ok')]
        for name, signed, args, diagnostic in panics:
            code = '''import ctypes as c, json, sys
library = c.CDLL(sys.argv[1]); function = getattr(library, sys.argv[2])
args = json.loads(sys.argv[4]); ty = c.c_int64 if sys.argv[3] == 'signed' else c.c_uint64
function.argtypes = [ty] * len(args); function.restype = ty
if sys.argv[2].endswith(('_shl', '_shr')) or sys.argv[2] == 'nested_shift':
 function.argtypes = [ty] * (len(args) - 1) + [c.c_uint64]
# Exercise every early/nested return path before the panic. Leaked trace frames
# would change stderr even when the failing function itself has balanced traces.
for name, values in [('choose', (1, 2)), ('choose', (2, 1)),
                     ('early', (-1, 0)), ('early', (1, -1)), ('early', (1, 1)),
                     ('nested_branch', (0, 0, 1)), ('nested_branch', (0, 1, 2)),
                     ('nested_branch', (1, 0, 2)), ('nested_branch', (1, 1, 2)),
                     ('bool_branch', (False, False)), ('bool_branch', (False, True)),
                     ('bool_branch', (True, False)), ('bool_branch', (True, True)),
                     ('branch_div', (0, 0)), ('branch_div', (4, 2)),
                     ('condition_div', (0, 1)), ('condition_div', (4, 2)),
                     ('branch_overflow', (0, 1)), ('branch_overflow', (1, 0)),
                     ('branch_overflow', (1, 1)), ('branch_shift', (0, 64)),
                     ('loop_early', (10,)), ('loop_sum', (25,)), ('loop_nested', (4,)),
                     ('loop_label', (10,)), ('loop_forever', (3,)), ('branch_shift', (1, 1)), ('call_nested', (1,2,3)),
                     ('call_args6', (1,2,3,4,5,6)), ('call_six_nested', (1,2,3,4,5,6)),
                     ('factorial', (5,)), ('rec_panic', (3,1)), ('rec_entry', (3,1)),
                     ('mutual_even', (4,)), ('mutual_odd', (5,))]:
 warm = getattr(library, name)
 wt = c.c_bool if name == 'bool_branch' else c.c_int64 if name == 'early' else c.c_uint64
 warm.argtypes = [wt] * len(values); warm.restype = wt
 warm(*values)
# Repeated successful calls must pop traces; a later panic shows one frame.
safe = [0] * len(args)
if 'div' in sys.argv[2] or 'rem' in sys.argv[2]: safe[-1] = 1
if sys.argv[2] in ('rec_panic','rec_entry','call_after','stack_order','stack_panic'): safe[-1] = 1
if sys.argv[2] in ('void_caller','range_bound_panic','indirect_panic','float_panic_call'): safe[-1] = 1
if sys.argv[2] == 'call_order': safe = [0,1,0]
for _ in range(3): function(*safe)
function(*args)
raise AssertionError('overflow returned normally')
'''
            import json
            results = []
            for library in (native, production_path):
                result = subprocess.run([sys.executable, '-c', code, str(library), name,
                                         'signed' if signed else 'unsigned', json.dumps(args)],
                                        capture_output=True, text=True, timeout=10)
                clean_stderr(result)
                assert result.returncode == 101 and result.stdout == '', (mode, name, args, result)
                results.append(result.stderr)
            assert results[0] == results[1], (mode, name, args, results)
            origin = ('abi_Three' if name == 'abi_big_panic' else generic_symbol if name == 'generic_panic' else 'stack_div' if name == 'stack_panic' else 'rec_panic' if name == 'rec_entry' else
                      ('div_leaf' if diagnostic == 'divide.ok' else 'add_leaf') if name == 'call_order' else
                      'float_panic' if name == 'float_panic_call' else
                      'void_work' if name == 'void_caller' else
                      'div_leaf' if name in ('call_after','call_short','call_branch','loop_call_div','indirect_panic') else name)
            assert results[0].splitlines()[0] == f'runtime check failed ({diagnostic}) in {origin}', (mode,name,origin,results[0])
            panic_count += 1
    rejected = {
        'aggregate-deref-limit': 'enum E { A:[2097153]u64,B } pub fn fail(a:*E) E { return a.* }',
        'unreachable-aggregate': 'pub fn fail(a:u64) u64 { if false { x:[2097153]u64 _=x } return a }',
        'main-frame-limit': 'fn main() { x:[2097153]u64 _=x }',
        'aggregate-local': 'pub fn fail(a: u64) u64 { b: [2097153]u64 return a }',
        'frame-limit': 'pub fn fail() u64 {' + ''.join(f'x{i}:[1048576]u64 ' for i in range(3)) + 'return 0}',
        'enum-storage-limit': 'enum E { A:[2097153]u64,B } pub fn fail(a:E) E { return a }',
        'indirect-aggregate-limit': 'pub fn fail(f:*fn([513]u8) u64,x:[513]u8) u64 { return f(x) }',
        'global-aggregate-limit': 'stored:[536870912]u64 pub fn fail() u64 { return 0 }',
        'global-symbol-collision': 'stored:u64 extern fn alias "stored"() u64 pub fn fail() u64 { return alias() }',
        'parameter-limit': 'pub fn fail('+','.join(f'a{i}:u64' for i in range(513))+') u64 { return a512 }',
        'reserved-runtime': 'pub fn dyn_panic(a: u64) u64 { return a }',
        'wrap-div-plain': 'pub fn fail(a: u64, b: u64) u64 { return #wrap(a / b) }',
        'signed-count': 'pub fn fail(a: i64, b: i64) i64 { return a << b }',
        'syntax': 'pub fn broken(',
    }
    for name, content in rejected.items():
        source.write_text(content)
        obj.unlink(missing_ok=True)
        diagnostic = 'error' if name in ('syntax', 'wrap-div-plain', 'signed-count') else 'unsupported by native backend'
        result = reject(source, obj, diagnostic)
        assert not obj.exists(), (name, result)
        obj.write_bytes(b'KEEP EXISTING OUTPUT')
        reject(source, obj, diagnostic)
        assert obj.read_bytes() == b'KEEP EXISTING OUTPUT', name
    source.write_bytes(b' ' * (16 * 1024 * 1024 + 1))
    reject(source, obj, 'exceeds 16 MiB')
    assert obj.read_bytes() == b'KEEP EXISTING OUTPUT'
    print(f'PASS ELF relocations; {count} production value comparisons; {panic_count} exact panic comparisons; '
          f'{len(rejected)} rejection cases, new/existing outputs')
