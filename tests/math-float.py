#!/usr/bin/env python3
"""Host libm callback oracle for the portable std/math implementation.

Exact primitives use format-specific C functions; transcendentals use host
long-double libm rounded to the target format (requires >=64-bit mantissa).
Native float/double-libm disagreements >1 ulp are reported separately. This
avoids treating known host double-log10 errors as Dyn regressions, while
retaining their raw inputs. Host libm is still an oracle, not a formal proof.
DYN/CC select compilers; MATH_FLOAT_RANDOM (default 2000) and
MATH_FLOAT_SEED control bounded reproducible testing. Both debug and release
run even on numerical failure. Exact operations require bit equality (NaNs
ignore payload); transcendentals allow 1 ulp. These are acceptance
budgets, not a claim that finite sampling proves a global error bound.

Measured 2026-10-23, x86_64 Linux, system cc/libm, FE_TONEAREST:
- Width-specific boundary/neighbor default run: 1153931 comparisons in EACH
  of debug/release, zero failures;
  exact primitives (including sqrt/FMA): zero ulp; transcendentals: <=1 ulp.
- Width-specific larger sweep: 30000 random samples/width, alternate seed
  0x9e3779b97f4a7c15: 11793931 comparisons/mode, zero failures; exact
  primitives zero ulp, transcendentals <=1 ulp. Native double log10 had
  8 disagreements >1 ulp against extended libm in each mode.
- Generator controls assert distinct neighbor bits and bracket underflow/
  overflow results. A temporary check reproduced the old f32 collapse:
  all 17 narrowed double neighbors had one bit pattern for representative
  exp, exp2, pow, and trig inputs.
- Earlier development sweep: 30000 random samples/width, seed 0x243f6a8885a308d3,
  9273591 comparisons/mode, zero failures. This preceded the final pow
  half-minimum-subnormal guard and 340 additional pow-boundary comparisons.
- Additional seed 0x9e3779b97f4a7c15, 2000 samples/width: 985591/mode, zero
  failures, before those final boundary additions. Boundary-only final run:
  393931/mode, zero failures.
- The large sweep found 16 native-double log10 disagreements >1 ulp versus
  extended libm. Retained examples 0x3fe89056f1249974 and 0x3fef6ff9fe32c89c
  were also checked with Python Decimal at precision 85: correctly rounded
  bits 0xbfbd67119bd98bc4 / 0xbf7f8d6f52aa9a14, agreeing with Dyn and log10l;
  native log10 returned 0xbfbd67119bd98bc2 / 0xbf7f8d6f52aa9a12.

Limitations: finite sampling cannot prove global bounds; host long-double libm
is not an arbitrary-precision oracle; other targets/backends are not exercised.
f32 transcendental wrappers round an f64 approximation, without a general
correct-rounding guarantee. NaN payloads/exception flags are not tested.
The library uses no external dependency or runtime libm; only this test does.
"""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
COUNT = int(os.environ.get('MATH_FLOAT_RANDOM', '2000'))
SEED = int(os.environ.get('MATH_FLOAT_SEED', '0x243f6a8885a308d3'), 0)
assert 0 <= COUNT <= 1000000 and 0 < SEED < 2**64
OPS = 'sqrt floor ceil trunc round copysign fma sin cos tan asin acos atan atan2 exp exp2 log log2 log10 pow hypot'.split()
C = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <float.h>
#include <fenv.h>
typedef uint64_t (*dispatch)(uint64_t,uint64_t,uint64_t,uint64_t);
static uint64_t state, checks, failures, worst[2][21], bad[2][21], native_bad[2][21];
static const char *names[]={NAMES};
static uint64_t rng(void) {state^=state<<13;state^=state>>7;state^=state<<17;return state;}
static uint64_t bits(double x) {uint64_t r;memcpy(&r,&x,8);return r;}
static uint64_t bitsf(float x) {uint32_t r;memcpy(&r,&x,4);return r;}
static double value(uint64_t x) {double r;memcpy(&r,&x,8);return r;}
static float valuef(uint64_t x) {uint32_t u=x;float r;memcpy(&r,&u,4);return r;}
static uint64_t native_oracle(unsigned w,unsigned op,uint64_t a,uint64_t b,uint64_t c) {
#define CASES(S) switch(op) {case 0:r=sqrt##S(x);break;case 1:r=floor##S(x);break;case 2:r=ceil##S(x);break;case 3:r=trunc##S(x);break;case 4:r=round##S(x);break;case 5:r=copysign##S(x,y);break;case 6:r=fma##S(x,y,z);break;case 7:r=sin##S(x);break;case 8:r=cos##S(x);break;case 9:r=tan##S(x);break;case 10:r=asin##S(x);break;case 11:r=acos##S(x);break;case 12:r=atan##S(x);break;case 13:r=atan2##S(x,y);break;case 14:r=exp##S(x);break;case 15:r=exp2##S(x);break;case 16:r=log##S(x);break;case 17:r=log2##S(x);break;case 18:r=log10##S(x);break;case 19:r=pow##S(x,y);break;case 20:r=hypot##S(x,y);break;}
 if(w) {volatile double x=value(a),y=value(b),z=value(c),r=0;CASES();return bits(r);}
 volatile float x=valuef(a),y=valuef(b),z=valuef(c),r=0;CASES(f);return bitsf(r);
}
// Use the host's extended-precision libm for transcendental references:
// some double libm implementations (notably log10 near 1) err by >1 ulp.
// Exact primitives still use the format-specific functions, including fmaf.
static uint64_t oracle(unsigned w,unsigned op,uint64_t a,uint64_t b,uint64_t c) {
 if(op<7 || isnan(w?value(a):valuef(a)) || isnan(w?value(b):valuef(b))) return native_oracle(w,op,a,b,c);
 volatile long double x=w?value(a):valuef(a),y=w?value(b):valuef(b),z=w?value(c):valuef(c),r=0;
 CASES(l);
 return w?bits((double)r):bitsf((float)r);
}
static uint64_t ordered(uint64_t a,uint64_t sign) {return a&sign?~a&((sign-1)|sign):a|sign;}
static void check(dispatch f,unsigned w,unsigned op,uint64_t a,uint64_t b,uint64_t c) {
 if(!w) {a&=0xffffffff;b&=0xffffffff;c&=0xffffffff;}
 uint64_t expected=oracle(w,op,a,b,c),actual=f(w*21+op,a,b,c),sign=w?UINT64_C(1)<<63:UINT64_C(1)<<31;
 double e=w?value(expected):valuef(expected),r=w?value(actual):valuef(actual);
 uint64_t eo=ordered(expected,sign),ao=ordered(actual,sign),distance=eo>ao?eo-ao:ao-eo;
 int ok=isnan(e)?isnan(r):expected==actual;
 if(!ok && op>=7 && isfinite(e) && isfinite(r) && e!=0 && r!=0) ok=distance<=1;
 if(op>=7) {
  uint64_t native=native_oracle(w,op,a,b,c),no=ordered(native,sign);
  uint64_t nd=no>eo?no-eo:eo-no;
  double nv=w?value(native):valuef(native);
  if(isfinite(e)&&isfinite(nv)&&nd>1) native_bad[w][op]++;
 }
 checks++;
 if(isfinite(e)&&isfinite(r)&&distance>worst[w][op])worst[w][op]=distance;
 if(!ok) {
  if(bad[w][op]++<3) fprintf(stderr,"FAIL f%u %s a=%016llx b=%016llx c=%016llx expected=%016llx actual=%016llx ulp=%llu\n",w?64:32,names[op],(unsigned long long)a,(unsigned long long)b,(unsigned long long)c,(unsigned long long)expected,(unsigned long long)actual,(unsigned long long)distance);
  failures++;
 }
}
static void sample(dispatch f,unsigned w,uint64_t a,uint64_t b,uint64_t c) {for(unsigned op=0;op<21;op++)check(f,w,op,a,b,c);}
static void domain(dispatch f,unsigned w,double x,double y,double z) {sample(f,w,w?bits(x):bitsf(x),w?bits(y):bitsf(y),w?bits(z):bitsf(z));}
// Step in the input format: narrowing double neighbors collapses f32 sweeps.
static double neighbor(unsigned w,double center,int steps) {
 double x=w?center:(double)(float)center;
 for(int k=0;k<abs(steps);k++)
  x=w?nextafter(x,steps<0?-INFINITY:INFINITY):nextafterf((float)x,steps<0?-INFINITY:INFINITY);
 return x;
}
static uint64_t input_bits(unsigned w,double x) {return w?bits(x):bitsf((float)x);}
static void distinct_neighbors(unsigned w,double center) {
 for(int d=-8;d<8;d++)assert(input_bits(w,neighbor(w,center,d))!=input_bits(w,neighbor(w,center,d+1)));
}
// Control the generator with the oracle itself: each threshold must straddle
// zero/min-subnormal or finite/infinity, independently of Dyn's result.
static void bracket(unsigned w,unsigned op,double base,double center,int overflow) {
 distinct_neighbors(w,center);
 uint64_t a=input_bits(w,neighbor(w,center,-8)),b=input_bits(w,neighbor(w,center,8));
 uint64_t lo=oracle(w,op,op==19?input_bits(w,base):a,op==19?a:0,0);
 uint64_t hi=oracle(w,op,op==19?input_bits(w,base):b,op==19?b:0,0);
 double x=w?value(lo):valuef(lo),y=w?value(hi):valuef(hi);
 if(overflow)assert((isinf(x)&&isfinite(y)&&y>0)||(isinf(y)&&isfinite(x)&&x>0));
 else assert((x==0&&y>0&&isfinite(y))||(y==0&&x>0&&isfinite(x)));
}
int run_oracle(dispatch f,uint64_t count,uint64_t seed) {
 state=seed;
 if(FLT_RADIX!=2||FLT_MANT_DIG!=24||DBL_MANT_DIG!=53||LDBL_MANT_DIG<64||fesetround(FE_TONEAREST))return 2;
 for(unsigned w=0;w<2;w++) {
  unsigned p=w?52:23,bias=w?1023:127;uint64_t sign=UINT64_C(1)<<(w?63:31),inf=(uint64_t)(2*bias+1)<<p,frac=(UINT64_C(1)<<p)-1;
  uint64_t v[]={0,sign,1,sign|1,frac,frac+1,inf-1,sign|(inf-1),inf,inf|sign,inf+1,inf+(UINT64_C(1)<<(p-1)),(uint64_t)bias<<p,sign|((uint64_t)bias<<p)};
  unsigned n=sizeof(v)/sizeof(*v);
  for(unsigned i=0;i<n;i++)for(unsigned j=0;j<n;j++)for(unsigned k=0;k<n;k++)sample(f,w,v[i],v[j],v[k]);
  for(unsigned e=0;e<2*bias+1;e++)for(int d=-2;d<=2;d++) {
   uint64_t a=((uint64_t)e<<p)+d;
   sample(f,w,a,a^sign,((uint64_t)bias<<p)+d);
   check(f,w,6,a,((uint64_t)bias<<p)+1,a^sign);
  }
  if(w) {
   uint64_t regressions[]={UINT64_C(0x3fe89056f1249974),UINT64_C(0x3fef6ff9fe32c89c),UINT64_C(0x3fe83bb65de2b6b4)};
   for(unsigned i=0;i<3;i++)check(f,w,18,regressions[i],0,0);
  }
  // Cancellation, midpoint perturbations, overflow rescue, subnormal rounding.
  domain(f,w,0x1.fffffffffffffp1023,2,-0x1.fffffffffffffp1023);
  domain(f,w,0x1.000002p0,0x1.8p0,0x1p-80);
  domain(f,w,0x1.000002p0,0x1.8p0,-0x1p-80);
  domain(f,w,-0.0,1,0);
  // Runtime inputs near exp/exp2 and pow overflow/underflow thresholds.
  long double low=w?-1075.L:-150.L,high=w?1024.L:128.L;
  long double maximum=w?(long double)DBL_MAX:(long double)FLT_MAX;
  // Half the minimum subnormal is the round-to-even zero boundary. The
  // maximum finite value locates overflow within one target input ulp.
  double exp_low=(double)logl(ldexpl(1.L,(int)low));
  double exp_high=(double)logl(maximum);
  bracket(w,14,0,exp_low,0);bracket(w,14,0,exp_high,1);
  bracket(w,15,0,(double)low,0);bracket(w,15,0,(double)high,1);
  double edges[]={(double)low,(double)(low+1),w?-1022:-126,w?1023:127,(double)high,exp_low,exp_high,0,1,-1};
  for(unsigned i=0;i<sizeof(edges)/sizeof(*edges);i++) {
   distinct_neighbors(w,edges[i]);
   for(int d=-8;d<=8;d++) {
    double x=neighbor(w,edges[i],d);
    domain(f,w,x,0.5,x);
    check(f,w,19,input_bits(w,2),input_bits(w,x),0);
   }
  }
  double bases[]={0.5,1.5,3,10,1+0x1p-20};
  for(unsigned i=0;i<5;i++)for(int boundary=0;boundary<2;boundary++) {
   double x=w?bases[i]:(double)(float)bases[i];
   double y=(double)((boundary?logl(maximum):logl(ldexpl(1.L,(int)low)))/logl((long double)x));
   bracket(w,19,x,y,boundary);
   for(int d=-8;d<=8;d++)
    check(f,w,19,input_bits(w,x),input_bits(w,neighbor(w,y,d)),0);
  }
  // Products exactly at a target midpoint, then perturbed far below f64
  // precision: these specifically reject f64-then-f32 double rounding.
  for(unsigned k=0;k<16;k++)for(int e=-149;e<=127;e+=23)for(int neg=0;neg<2;neg++) {
   double a=ldexp(1.0+ldexp((double)(2*k+1),-23),e),b=1.5,c=ldexp(neg?-1.0:1.0,e-90);
   domain(f,w,a,b,c);
  }
  for(uint64_t i=0;i<count;i++) {
   uint64_t a=rng(),b=rng(),c=rng();sample(f,w,a,b,c);
   double u=(double)(rng()>>11)*0x1p-53,t=2*u-1;
   domain(f,w,t,(double)(rng()%2001)-1000,t);
   domain(f,w,t*1.6e6,t*1000,t);
   domain(f,w,exp2(t*1000),t*1000,t);
   domain(f,w,1+t*0x1p-20,t*0x1p30,t);
   domain(f,w,t*750,1+t,t);
   // Adjacent representable arguments around pi/2 multiples.
   double q=(double)(rng()%1000000)*1.57079632679489661923;
   distinct_neighbors(w,q);
   for(int d=-1;d<=1;d++)domain(f,w,neighbor(w,q,d),t,t);
   if(w)check(f,w,6,a,b,bits(-value(a)*value(b)));
   else check(f,w,6,a,b,bitsf(-valuef(a)*valuef(b)));
  }
  for(unsigned op=0;op<21;op++)printf("f%u %-8s max_ulp=%llu failures=%llu native_vs_extended_gt1=%llu\n",w?64:32,names[op],(unsigned long long)worst[w][op],(unsigned long long)bad[w][op],(unsigned long long)native_bad[w][op]);
 }
 printf("%s %llu comparisons failures=%llu random/width=%llu seed=%016llx\n",failures?"FAIL":"PASS",(unsigned long long)checks,(unsigned long long)failures,(unsigned long long)count,(unsigned long long)seed);fflush(stdout);return failures?1:0;
}
'''.replace('NAMES', ','.join('"'+op+'"' for op in OPS))

with tempfile.TemporaryDirectory(prefix='dyn-math-float-') as tmp:
    work = Path(tmp)
    source = work / 'source'
    source.mkdir()
    # Copy only the owned implementation; use the existing std integer helper.
    (source / 'float.dyn').write_text((ROOT / 'std/math/float.dyn').read_text())
    driver = ['use "std/math" integer', 'fn leading_zeros(x:u64) u32 { return integer.leading_zeros(x) }',
              'extern fn run_oracle(f:fn(u64,u64,u64,u64) u64,count:u64,seed:u64) i32',
              'fn dispatch(op:u64,a:u64,b:u64,c:u64) u64 { case op {']
    for wide in (False, True):
        width = 64 if wide else 32
        def operand(name):
            raw = name if wide else f'#cast(u32,{name} & 0xffffffff)'
            return f'#bitcast(f{width},{raw})'
        for op, name in enumerate(OPS):
            arity = 3 if name == 'fma' else 2 if name in ('copysign','atan2','pow','hypot') else 1
            expr = f'{name}({",".join(operand(v) for v in "abc"[:arity])})'
            driver.append(f'{21*wide+op} => {{ return #cast(u64,#bitcast(u{width},{expr})) }},')
    driver += ['_ => { return 0 },','} }',f'fn main() {{ if run_oracle(&dispatch,{COUNT},{SEED}) != 0 {{ #panic("math float oracle failed") }} }}']
    (source / 'main.dyn').write_text('\n'.join(driver))
    (work / 'oracle.c').write_text(C)
    subprocess.run([*shlex.split(os.environ.get('CC','cc')),'-std=c11','-O2','-fno-fast-math','-frounding-math','-ffp-contract=off','-fno-builtin','-shared','-fPIC',str(work/'oracle.c'),'-lm','-o',str(work/'oracle.so')],check=True)
    failed = False
    for mode in ('debug','release'):
        print(f'[{mode}]',flush=True)
        subprocess.run([DYN,'build',str(source),'--no-cache','--jobs','1',f'--{mode}','--link',str(work/'oracle.so'),'--output',str(work/'test')],check=True)
        failed |= subprocess.run([str(work/'test')],timeout=180).returncode != 0
    raise SystemExit(1 if failed else 0)
