#!/usr/bin/env python3
"""Independent C IEEE oracle versus the actual integer-only Dyn helper module.

Builds a generated Dyn dispatcher and a host C oracle, runs both debug/release.
No Python float oracle, helper reimplementation, or expected-result stubs.
DYN / CC override the compiler paths; SOFTFLOAT_RANDOM (default 30000) controls
random pairs per width. SOFTFLOAT_SEED overrides the reproducible seed (integer
with optional 0x prefix). Failures print the exact operation and raw operands.
"""
import os
from pathlib import Path
import shlex
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
COUNT = int(os.environ.get('SOFTFLOAT_RANDOM', '30000'))
SEED = int(os.environ.get('SOFTFLOAT_SEED', '0x6a09e667f3bcc909'), 0)
assert COUNT >= 0 and 0 < SEED < 2**64
HELPERS = (ROOT / 'runtime/support/softfloat.dyn').read_text()
# Guard the freestanding integer-only boundary as well as numerical results.
code = re.sub(r'//[^\n]*', '', HELPERS)
assert not re.search(r'\b(f32|f64|use|extern|defer)\b', code)
assert not re.search(r'\b[0-9]+\.[0-9]', code)
C = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <fenv.h>
#include <float.h>
#pragma STDC FENV_ACCESS ON
typedef uint64_t (*dispatch)(uint64_t,uint64_t,uint64_t);
static uint64_t state=UINT64_C(0x6a09e667f3bcc909), checks;
static uint64_t random_bits(void) {
 state ^= state << 13; state ^= state >> 7; state ^= state << 17; return state;
}
static uint64_t oracle(unsigned wide, unsigned op, uint64_t a, uint64_t b) {
 float af,bf,rf; double ad,bd,rd; uint32_t aa=(uint32_t)a,bb=(uint32_t)b,out;
 memcpy(&af,&aa,4); memcpy(&bf,&bb,4); memcpy(&ad,&a,8); memcpy(&bd,&b,8);
 long double x=wide?(long double)ad:(long double)af;
 long double y=wide?(long double)bd:(long double)bf;
 if(op>=5 && op<=11) {
  switch(op) {
   case 5:return x==y; case 6:return x!=y; case 7:return x<y;
   case 8:return x<=y; case 9:return x>y; case 10:return x>=y;
   case 11:return isnan(x)||isnan(y);
  }
 }
 if(op==12 || op==13) {
  long double t=truncl(x);
  if(!isfinite(x)) return UINT64_C(0x8000000000000000);
  if(op==12) {
   if(t < -0x1p63L || t >= 0x1p63L) return UINT64_C(0x8000000000000000);
   return (uint64_t)(int64_t)t;
  }
  if(t < 0 || t >= 0x1p64L) return UINT64_C(0x8000000000000000);
  return (uint64_t)t;
 }
 int64_t signed_a; memcpy(&signed_a,&a,8);
 if(wide) {
  volatile double av=ad,bv=bd,r=0;
  switch(op) {
   case 0:r=av+bv;break; case 1:r=av-bv;break; case 2:r=av*bv;break;
   case 3:r=av/bv;break; case 4:r=fmod(av,bv);break;
   case 14:r=(double)signed_a;break;case 15:r=(double)a;break;
   case 16:rf=(float)av;memcpy(&out,&rf,4);
    return isnan(rf)?UINT32_C(0x7fc00000):out;
  }
  rd=r;memcpy(&a,&rd,8);
  return isnan(rd)?UINT64_C(0x7ff8000000000000):a;
 }
 volatile float av=af,bv=bf,r=0;
 switch(op) {
  case 0:r=av+bv;break;case 1:r=av-bv;break;case 2:r=av*bv;break;
  case 3:r=av/bv;break;case 4:r=fmodf(av,bv);break;
  case 14:r=(float)signed_a;break;case 15:r=(float)a;break;
  case 16:rd=(double)av;memcpy(&a,&rd,8);
   return isnan(rd)?UINT64_C(0x7ff8000000000000):a;
 }
 rf=r;memcpy(&out,&rf,4);
 return isnan(rf)?UINT32_C(0x7fc00000):out;
}
static void check(dispatch fn,unsigned wide,unsigned op,uint64_t a,uint64_t b) {
 uint64_t expected=oracle(wide,op,a,b), actual=fn(wide*17+op,a,b);
 checks++;
 if(actual!=expected) {
  fprintf(stderr,"f%u op=%u a=%016llx b=%016llx expected=%016llx actual=%016llx check=%llu\n",
   wide?64:32,op,(unsigned long long)a,(unsigned long long)b,
   (unsigned long long)expected,(unsigned long long)actual,(unsigned long long)checks);
  exit(1);
 }
}
static void pair(dispatch fn,unsigned wide,uint64_t a,uint64_t b) {
 for(unsigned op=0;op<17;op++) check(fn,wide,op,a,b);
}
int run_oracle(dispatch fn,uint64_t count,uint64_t seed) {
 state=seed;
 if(FLT_RADIX!=2 || FLT_MANT_DIG!=24 || DBL_MANT_DIG!=53 || LDBL_MANT_DIG<64 ||
    sizeof(float)!=4 || sizeof(double)!=8 || fesetround(FE_TONEAREST)) return 2;
 for(unsigned wide=0;wide<2;wide++) {
  unsigned p=wide?52:23, bias=wide?1023:127;
  uint64_t sign=wide?UINT64_C(0x8000000000000000):UINT64_C(0x80000000);
  uint64_t inf=wide?UINT64_C(0x7ff0000000000000):UINT64_C(0x7f800000);
  uint64_t frac=(UINT64_C(1)<<p)-1, values[1024];unsigned n=0;
  uint64_t basics[]={0,1,2,3,frac-1,frac,frac+1,frac+2,inf-2,inf-1,inf,inf+1,inf+(UINT64_C(1)<<(p-1)),inf+frac};
  for(unsigned i=0;i<sizeof(basics)/sizeof(*basics);i++) {
   values[n++]=basics[i]; values[n++]=basics[i]|sign;
  }
  // Binade edges, conversion limits, epsilon, and halfway/subnormal boundaries.
  int exponents[]={-54,-53,-52,-25,-24,-23,-2,-1,0,1,2,23,24,31,32,52,53,62,63,64,65};
  for(unsigned i=0;i<sizeof(exponents)/sizeof(*exponents);i++) {
   uint64_t center=(uint64_t)(bias+exponents[i])<<p;
   for(int delta=-3;delta<=3;delta++) {
    values[n++]=center+delta; values[n++]=(center+delta)|sign;
   }
  }
  for(unsigned i=0;i<n;i++) for(unsigned j=0;j<n;j++) pair(fn,wide,values[i],values[j]);
  // Every exponent field with near-zero, midpoint, and maximal fraction.
  for(unsigned e=0;e<(wide?2048:256);e++) {
   uint64_t a=(uint64_t)e<<p;
   uint64_t fs[]={0,1,frac>>1,(frac>>1)+1,frac-1,frac};
   for(unsigned k=0;k<6;k++) {
    uint64_t v=a|fs[k];
    pair(fn,wide,v,values[(e+k)%n]);
    pair(fn,wide,v|sign,(v+1)&(sign-1));
    pair(fn,wide,v,v^sign); // exact cancellation and opposite signs
   }
  }
  for(uint64_t i=0;i<count;i++) {
   uint64_t a=random_bits(),b=random_bits();
   pair(fn,wide,a,b);
   // Close magnitudes exercise cancellation; exponent gaps exercise sticky bits.
   uint64_t mask=sign-1, mag=a&mask;
   pair(fn,wide,mag,(mag^(random_bits()&255))|sign);
   pair(fn,wide,mag,((mag>>p)>p+4)?mag-((uint64_t)(p+4)<<p):b);
  }
  // Explicit ties and sticky-bit neighborhoods: exponent gaps around precision,
  // both signs and both even/odd retained significands.
  uint64_t one=(uint64_t)bias<<p;
  for(unsigned odd=0;odd<4;odd++) for(unsigned gap=p;gap<=p+5;gap++) {
   uint64_t small=(uint64_t)(bias-gap)<<p;
   for(int d=-3;d<=3;d++) {
    pair(fn,wide,one+odd,small+d);
    pair(fn,wide,one+odd,(small+d)|sign);
    pair(fn,wide,(one+odd)|sign,small+d);
   }
  }
  if(wide) {
   // f64 -> f32 rounding: half-ulp +/- 3 source ulps around every f32
   // normal binade and the overflow threshold.
   for(int e=-126;e<=128;e++) for(unsigned odd=0;odd<4;odd++) {
    uint64_t center=(uint64_t)(1023+e)<<52;
    uint64_t halfway=center+((uint64_t)(2*odd+1)<<28);
    for(int d=-3;d<=3;d++) {
     pair(fn,wide,halfway+d,center);
     pair(fn,wide,(halfway+d)|sign,center);
    }
   }
   // Subnormals have fixed spacing 2^-149, independent of binade.
   // Midpoints are (k + 1/2) * 2^-149, exactly representable in f64.
   // Sample both retained parities throughout the subnormal exponent range.
   for(unsigned bit=0;bit<23;bit++) for(unsigned offset=0;offset<4;offset++) {
    uint32_t k=(UINT32_C(1)<<bit)+offset;
    double midpoint=ldexp((double)(2*k+1),-150);
    uint64_t halfway; memcpy(&halfway,&midpoint,8);
    for(int d=-3;d<=3;d++) {
     pair(fn,wide,halfway+d,one);
     pair(fn,wide,(halfway+d)|sign,one);
    }
   }
   uint64_t edges[]={UINT64_C(0x3690000000000000), // half minimum f32 subnormal
    UINT64_C(0x380fffffe0000000), // halfway maximum subnormal/minimum normal
    UINT64_C(0x47effffff0000000)}; // halfway maximum finite/infinity
   for(unsigned i=0;i<3;i++) for(int d=-8;d<=8;d++) {
    pair(fn,wide,edges[i]+d,one);
    pair(fn,wide,(edges[i]+d)|sign,one);
   }
  }
  // All integer powers of two and neighbors, signed MIN/MAX and UINT64_MAX.
  for(unsigned bit=0;bit<64;bit++) for(int d=-3;d<=3;d++) {
   uint64_t a=(UINT64_C(1)<<bit)+d;
   check(fn,wide,14,a,0);check(fn,wide,15,a,0);
   check(fn,wide,14,~a,0);check(fn,wide,15,~a,0);
  }
 }
 printf("PASS %llu oracle comparisons; random pairs/width=%llu seed=%016llx\n",
  (unsigned long long)checks,(unsigned long long)count,(unsigned long long)seed);
 fflush(stdout);
 return 0;
}
'''

with tempfile.TemporaryDirectory(prefix='dyn-softfloat-bits-') as tmp:
    work = Path(tmp)
    source = work / 'source'
    source.mkdir()
    # Runtime symbols are reserved in ordinary application builds. Rename
    # only those symbols in this isolated copy; helper bodies stay identical.
    (source / 'softfloat.dyn').write_text(HELPERS.replace('dyn_soft_', 'test_soft_'))
    driver = ['extern fn run_oracle(f:*fn(u64,u64,u64) u64, count:u64, seed:u64) i32',
              'fn dispatch(op:u64,a:u64,b:u64) u64 {', 'case op {']
    for wide in (False, True):
        width = 64 if wide else 32
        aa = 'a' if wide else '#cast(u32, a & 0xffffffff)'
        bb = 'b' if wide else '#cast(u32, b & 0xffffffff)'
        expressions = []
        for op in ('add', 'sub', 'mul', 'div', 'rem', 'eq', 'ne', 'lt', 'le', 'gt', 'ge', 'unordered'):
            expressions.append(f'dyn_soft_f{width}_{op}({aa}, {bb})')
        expressions += [f'#bitcast(u64, dyn_soft_f{width}_to_i64({aa}))',
                        f'dyn_soft_f{width}_to_u64({aa})',
                        f'dyn_soft_i64_to_f{width}(#bitcast(i64, a))',
                        f'dyn_soft_u64_to_f{width}(a)',
                        f'dyn_soft_f{width}_to_f{32 if wide else 64}({aa})']
        for op, expr in enumerate(expressions):
            if 5 <= op <= 11:
                body = f'if {expr} {{ return 1 }} return 0'
            else:
                body = f'return #cast(u64, {expr})'
            driver.append(f'{17*wide+op} => {{ {body} }},')
    driver += ['_ => { return 0 },', '}', '}',
               f'fn main() {{ if run_oracle(&dispatch, {COUNT}, {SEED}) != 0 {{ #panic("host IEEE oracle unsupported") }} }}']
    (source / 'main.dyn').write_text('\n'.join(driver).replace('dyn_soft_', 'test_soft_'))
    (work / 'oracle.c').write_text(C)
    subprocess.run([*shlex.split(os.environ.get('CC', 'cc')), '-std=c11', '-O2',
                    '-fno-fast-math', '-frounding-math', '-ffp-contract=off',
                    '-shared', '-fPIC', str(work / 'oracle.c'), '-lm', '-o', str(work / 'oracle.so')], check=True)
    for mode in ('debug', 'release'):
        print(f'[{mode}]', flush=True)
        subprocess.run([DYN, 'build', str(source), '--no-cache', '--jobs', '1',
                        f'--{mode}', '--link', str(work / 'oracle.so'),
                        '--output', str(work / 'test')], check=True)
        subprocess.run([str(work / 'test')], check=True, timeout=240)
