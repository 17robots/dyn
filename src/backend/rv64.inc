/* RV64IMAFD instruction lowering. No compressed encodings or relaxation are
   required. The integer model uses caller-saved registers only; gp/tp stay
   untouched. x28-x31 retain synthesized arithmetic/comparison flags. */
static void bare_stack_check(BackendContext *, uint32_t);
static const unsigned char rv_reg[] = {10,5,11,12,13,14,15,16};
static void rv_r(BackendContext *c,unsigned op,unsigned rd,unsigned rs,unsigned rt,unsigned f3,unsigned f7) {
  word(c,op|rd<<7|f3<<12|rs<<15|rt<<20|f7<<25);
}
static void rv_i(BackendContext *c,unsigned op,unsigned rd,unsigned rs,int64_t imm,unsigned f3) {
  word(c,op|rd<<7|f3<<12|rs<<15|((uint32_t)imm&4095)<<20);
}
static void rv_move(BackendContext *c,unsigned d,unsigned s) { rv_i(c,0x13,d,s,0,0); }
static void rv_imm(BackendContext *c,unsigned d,uint64_t value) {
  int64_t n=(int64_t)value;
  if(n>=-2048&&n<=2047) { rv_i(c,0x13,d,0,n,0); return; }
  int64_t lo=(int64_t)(value<<52)>>52;
  rv_imm(c,d,(value-(uint64_t)lo)>>12);
  rv_i(c,0x13,d,d,12,1);
  if(lo) rv_i(c,0x13,d,d,lo,0);
}
static void rv_address(BackendContext *c,unsigned d,unsigned base,int64_t offset) {
  if(offset>=-2048&&offset<=2047) rv_i(c,0x13,d,base,offset,0);
  else { rv_imm(c,7,(uint64_t)offset); rv_r(c,0x33,d,base,7,0,0); }
}
static void rv_memory(BackendContext *c,bool store,unsigned reg,unsigned base,int64_t offset,unsigned f3,bool floating) {
  if(offset < -2048 || offset>2047) { rv_address(c,7,base,offset); base=7; offset=0; }
  if(store) { uint32_t imm=(uint32_t)offset&4095; word(c,(floating?0x27:0x23)|(imm&31)<<7|f3<<12|base<<15|reg<<20|(imm>>5)<<25); }
  else rv_i(c,floating?7:3,reg,base,offset,f3);
}
static void rv_compare(BackendContext *c,unsigned a,unsigned b) { rv_move(c,30,a); rv_move(c,31,b); }
static void rv_condition(BackendContext *c,int cond,unsigned *a,unsigned *b,unsigned *f3) {
  *a=30; *b=31;
  switch(cond) {
  case CC_E:*f3=0;break;case CC_NE:*f3=1;break;case CC_B:*f3=6;break;case CC_AE:*f3=7;break;
  case CC_BE:*a=31;*b=30;*f3=7;break;case CC_A:*a=31;*b=30;*f3=6;break;
  case CC_L:*f3=4;break;case CC_GE:*f3=5;break;case CC_LE:*a=31;*b=30;*f3=5;break;case CC_G:*a=31;*b=30;*f3=4;break;
  case CC_NO:*a=28;*b=0;*f3=0;break;case CC_NO_CARRY:*a=29;*b=0;*f3=0;break;
  default:c->text.failed=true;*f3=0;
  }
}
static void rv_b(BackendContext *c,unsigned a,unsigned b,unsigned f3,int offset) {
  uint32_t u=(uint32_t)offset; word(c,0x63|((u>>11)&1)<<7|((u>>1)&15)<<8|f3<<12|a<<15|b<<20|((u>>5)&63)<<25|((u>>12)&1)<<31);
}
static size_t rv_branch(BackendContext *c,int cond) {
  if(cond>=0) { unsigned a,b,f3;rv_condition(c,cond,&a,&b,&f3);rv_b(c,a,b,f3^1,12); }
  size_t at=c->text.n; word(c,0x00000317); rv_i(c,0x67,0,6,0,0); return at;
}
static void rv_patch(BackendContext *c,size_t at,size_t destination) {
  int64_t delta=(int64_t)destination-(int64_t)at;
  if(delta<INT32_MIN||delta>INT32_MAX) { c->text.failed=true;return; }
  uint32_t hi=(uint32_t)((delta+2048)>>12),lo=(uint32_t)delta&4095;
  patch_word(c,at,hi<<12|6<<7|0x17);patch_word(c,at+4,lo<<20|6<<15|0x67);
}
static void rv_set(BackendContext *c,Cond cond) {
  size_t yes=rv_branch(c,cond);rv_imm(c,10,0);size_t end=rv_branch(c,-1);
  rv_patch(c,yes,c->text.n);rv_imm(c,10,1);rv_patch(c,end,c->text.n);
}
static void rv_push(BackendContext *c,Reg r) { bare_stack_check(c,16); ++c->stack_slots;rv_i(c,0x13,2,2,-16,0);rv_memory(c,true,rv_reg[r],2,0,3,false); }
static void rv_pop(BackendContext *c,Reg r) { --c->stack_slots;rv_memory(c,false,rv_reg[r],2,0,3,false);rv_i(c,0x13,2,2,16,0); }
static void rv_fp_bits(BackendContext *c,bool to_float,bool f32,unsigned d,unsigned s) {
  rv_r(c,0x53,d,s,0,0,(to_float?0x78:0x70)|(f32?0:1));
}
static void rv_call(BackendContext *c,unsigned symbol) {
  relocate(c,symbol,19,0);word(c,0x00000097);rv_i(c,0x67,1,1,0,0);
}
static void rv_symbol(BackendContext *c,unsigned d,unsigned symbol,int64_t addend,bool got) {
  size_t at=c->text.n;
  if(c->rv_anchor_count>=MAX_NODES) { c->text.failed=true;return; }
  unsigned anchor=c->rv_anchor_count++;c->rv_anchors[anchor]=(uint32_t)at;
  relocate(c,symbol,got?20:23,addend);word(c,d<<7|0x17);
  relocate(c,0x80000000u|anchor,24,0);rv_i(c,got?3:0x13,d,d,0,got?(c->rv32?2:3):0);
}
static void rv_extend(BackendContext *c,unsigned bits,bool sign) {
  if(bits>=64)return;
  if(bits==1) {rv_i(c,0x13,10,10,1,7);return;}
  rv_i(c,0x13,10,10,64-bits,1);rv_i(c,0x13,10,10,(sign?0x400:0)+64-bits,5);
}
static void rv_alu(BackendContext *c,int op,Reg dest,Reg source) {
  unsigned a=rv_reg[dest],b=rv_reg[source];rv_compare(c,a,b);
  unsigned f3=op==2?7:op==3?6:op==4?4:0;
  rv_r(c,0x33,a,a,b,f3,op==1?32:0);
  if(op<=1) {
    rv_r(c,0x33,6,30,a,4,0);rv_r(c,0x33,7,op?30:31,op?31:a,4,0);
    rv_r(c,0x33,28,6,7,7,0);rv_i(c,0x13,28,28,63,5);
    rv_r(c,0x33,29,op?30:a,op?31:30,3,0);
  }
}
static void rv_load_chunk(BackendContext *c,unsigned offset,unsigned size) {
  rv_address(c,6,16,offset);rv_imm(c,15,0);
  for(unsigned i=0;i<size;++i) {rv_memory(c,false,7,6,i,4,false);if(i)rv_i(c,0x13,7,7,i*8,1);rv_r(c,0x33,15,15,7,6,0);}
}
static void rv_store_chunk(BackendContext *c,unsigned offset,unsigned size) {
  rv_address(c,6,13,offset);
  for(unsigned i=0;i<size;++i) {rv_memory(c,true,15,6,i,0,false);if(i+1<size)rv_i(c,0x13,15,15,8,5);}
}
static void rv_float_compare(BackendContext *c,bool f32,unsigned op) {
  unsigned left=10,right=11;if(op>=4){left=11;right=10;}
  rv_r(c,0x53,10,left,right,op<2?2:(op==2||op==4)?1:0,f32?0x50:0x51);
  if(op==1)rv_i(c,0x13,10,10,1,4);
}
static void rv_multiply(BackendContext *c,bool checked,bool sign) {
  if(checked)rv_r(c,0x33,6,10,5,sign?1:3,1);
  rv_r(c,0x33,10,10,5,0,1);
  if(checked) {if(sign)rv_i(c,0x13,7,10,0x43f,5);else rv_imm(c,7,0);rv_compare(c,6,7);}
}
static void rv_enter(BackendContext *c) {
  rv_i(c,0x13,2,2,-16,0);rv_memory(c,true,8,2,0,3,false);rv_memory(c,true,1,2,8,3,false);
  rv_move(c,8,2);rv_address(c,2,2,-(int64_t)c->frame_bytes);
  /* Preserve incoming banks before aggregate copies use caller-saved scratch. */
  rv_i(c,0x13,2,2,-128,0);
  for(unsigned i=0;i<8;++i) {rv_memory(c,true,10+i,2,i*8,3,false);rv_memory(c,true,10+i,2,64+i*8,3,true); }
}
static void rv_return(BackendContext *c) {
  if(c->dwarf&&!backend_dwarf_epilogue(c->dwarf,c->text.n))c->text.failed=true;
  rv_move(c,2,8);rv_memory(c,false,8,2,0,3,false);rv_memory(c,false,1,2,8,3,false);
  rv_i(c,0x13,2,2,16,0);rv_i(c,0x67,0,1,0,0);
}
static void rv_copy(BackendContext *c,uint32_t size) {
  rv_move(c,12,10);rv_pop(c,R_DI);rv_imm(c,17,size);rv_compare(c,13,12);size_t forward=rv_branch(c,CC_BE);
  size_t back=c->text.n;rv_compare(c,17,0);size_t done_back=rv_branch(c,CC_E);
  rv_i(c,0x13,17,17,-1,0);rv_r(c,0x33,6,12,17,0,0);rv_memory(c,false,7,6,0,4,false);
  rv_r(c,0x33,6,13,17,0,0);rv_memory(c,true,7,6,0,0,false);size_t repeat=rv_branch(c,-1);rv_patch(c,repeat,back);
  rv_patch(c,forward,c->text.n);size_t next=c->text.n;rv_compare(c,17,0);size_t done=rv_branch(c,CC_E);
  rv_memory(c,false,7,12,0,4,false);rv_memory(c,true,7,13,0,0,false);rv_i(c,0x13,12,12,1,0);rv_i(c,0x13,13,13,1,0);rv_i(c,0x13,17,17,-1,0);
  repeat=rv_branch(c,-1);rv_patch(c,repeat,next);rv_patch(c,done,c->text.n);rv_patch(c,done_back,c->text.n);
}
