#include "ir_dump.h"
#include <inttypes.h>
#include <stdlib.h>
#include <string.h>

/* The dry run and output run share the exact same traversal. No IR graph
   recursion is needed: every edge is an explicitly tagged table index. */
typedef struct {
  FILE *out;
  const DynIrProgram *p;
  uint64_t *owners;
  size_t owner_count;
  bool valid;
} Dump;

static void text(Dump *d, const char *s) {
  if (d->out) fputs(s, d->out);
}
static void number(Dump *d, uint64_t n) {
  if (d->out) fprintf(d->out, "%" PRIu64, n);
}
static void key(Dump *d, const char *s) {
  text(d, " "); text(d, s); text(d, "=");
}
static void num(Dump *d, const char *s, uint64_t n) {
  key(d, s); number(d, n);
}
static void flag(Dump *d, const char *s, bool b) {
  key(d, s); text(d, b ? "true" : "false");
}
static void hex(Dump *d, uint64_t n) {
  static const char digits[] = "0123456789abcdef";
  if (d->out) for (unsigned i = 16; i; --i)
    fputc(digits[(n >> ((i - 1) * 4)) & 15], d->out);
}
static void raw(Dump *d, const char *s, uint64_t n) {
  key(d, s); hex(d, n);
}
static void bytes(Dump *d, const void *data, size_t n) {
  static const char digits[] = "0123456789abcdef";
  if (n && !data) { d->valid = false; return; }
  number(d, n); text(d, ":");
  if (d->out) for (size_t i = 0; i < n; ++i) {
    unsigned c = ((const unsigned char *)data)[i];
    fputc(digits[c >> 4], d->out); fputc(digits[c & 15], d->out);
  }
}
static void name(Dump *d, const char *s, const char *value, bool optional) {
  key(d, s);
  if (!value) { if (!optional) d->valid = false; text(d, "none"); }
  else bytes(d, value, strlen(value));
}
static void ref(Dump *d, const char *s, const char *table, uint64_t id,
                size_t count, bool optional) {
  key(d, s);
  if (optional && id == UINT32_MAX) text(d, "none");
  else {
    if (id >= count) d->valid = false;
    text(d, table); text(d, ":"); number(d, id);
  }
}
static void range(Dump *d, const char *s, const char *table,
                  uint32_t start, uint32_t count, size_t total) {
  if (start > total || count > total - start) d->valid = false;
  key(d, s); text(d, table); text(d, ":"); number(d, start);
  text(d, "+"); number(d, count);
}
static const char *builtin(DynType t) {
  switch (t) {
#define B(x, s) case DYN_TYPE_##x: return s
    B(INFER,"infer"); B(ERROR,"error"); B(VOID,"void"); B(BOOL,"bool");
    B(I8,"i8"); B(I16,"i16"); B(I32,"i32"); B(I64,"i64");
    B(U8,"u8"); B(U16,"u16"); B(U32,"u32"); B(U64,"u64");
    B(ISIZE,"isize"); B(USIZE,"usize"); B(F32,"f32"); B(F64,"f64");
    B(STRING,"string"); B(RAWPTR,"rawptr"); B(ANY,"any");
#undef B
    default: return NULL;
  }
}
static void type(Dump *d, const char *s, DynType t) {
  const char *b = builtin(t);
  if (b) { key(d,s); text(d,b); return; }
#define T(base, end, table, count) \
  if (t >= DYN_TYPE_##base && t < DYN_TYPE_##end) { \
    ref(d,s,table,t-DYN_TYPE_##base,d->p->count,false); return; }
  T(STRUCT_BASE, ENUM_BASE, "struct", struct_count)
  T(ENUM_BASE, POINTER_BASE, "enum", enum_count)
  T(POINTER_BASE, ARRAY_BASE, "pointer", pointer_count)
  T(ARRAY_BASE, SLICE_BASE, "array", array_count)
  T(SLICE_BASE, FN_BASE, "slice", slice_count)
  T(FN_BASE, DISTINCT_BASE, "fn_type", fn_type_count)
#undef T
  if (dyn_type_is_param(t)) {
    key(d,s); text(d,"type_param:"); number(d,t-DYN_TYPE_PARAM_BASE); return;
  }
  d->valid = false;
}
static const char *operator_name(DynOperator op) {
  switch(op) {
#define O(x,s) case DYN_OP_##x: return s
    O(NONE,"none"); O(NEG,"neg"); O(NOT,"not"); O(BIT_NOT,"bit_not");
    O(ADDRESS,"address"); O(DEREF,"deref"); O(ADD,"add"); O(SUB,"sub");
    O(MUL,"mul"); O(DIV,"div"); O(REM,"rem"); O(EQ,"eq"); O(NE,"ne");
    O(LT,"lt"); O(LE,"le"); O(GT,"gt"); O(GE,"ge");
    O(LOGICAL_AND,"logical_and"); O(LOGICAL_OR,"logical_or");
    O(BIT_AND,"bit_and"); O(BIT_OR,"bit_or"); O(BIT_XOR,"bit_xor");
    O(SHL,"shl"); O(SHR,"shr");
#undef O
    default: return NULL;
  }
}
static void op(Dump *d, const char *s, DynOperator value) {
  const char *n = operator_name(value);
  if (!n) { d->valid = false; return; }
  key(d,s); text(d,n);
}
static size_t owner(Dump *d, uint64_t value) {
  size_t i = 0;
  while (i < d->owner_count && d->owners[i] != value) ++i;
  if (i == d->owner_count) d->owners[d->owner_count++] = value;
  return i;
}
static void declaration(Dump *d, const char *value, uint64_t module,
                        bool instance, size_t index) {
  size_t ordinal = owner(d,module);
  num(d,"owner",ordinal);
  key(d,"name");
  if (instance) {
    char buffer[64];
    int n = snprintf(buffer,sizeof(buffer),"instance.%zu",index);
    bytes(d,buffer,(size_t)n); return;
  }
  if (!value) { d->valid = false; return; }
  size_t n = strlen(value);
  bool generated = n >= 22 && !memcmp(value,"dyn_m",5) && value[21] == '_';
  for (size_t i = 5; generated && i < 21; ++i)
    if (!((value[i] >= '0' && value[i] <= '9') ||
          (value[i] >= 'a' && value[i] <= 'f') ||
          (value[i] >= 'A' && value[i] <= 'F'))) generated = false;
  if (generated) {
    char prefix[64];
    int k = snprintf(prefix,sizeof(prefix),"module.%zu.",ordinal);
    number(d,(size_t)k+n-22); text(d,":");
    if (d->out) {
      static const char digits[]="0123456789abcdef";
      for (size_t i=0;i<(size_t)k;++i) {
        unsigned c=(unsigned char)prefix[i];
        fputc(digits[c>>4],d->out); fputc(digits[c&15],d->out);
      }
      for (size_t i=22;i<n;++i) {
        unsigned c=(unsigned char)value[i];
        fputc(digits[c>>4],d->out); fputc(digits[c&15],d->out);
      }
    }
  } else bytes(d,value,n);
}
static void row(Dump *d,const char *s,size_t i) {
  text(d,s); text(d," "); number(d,i);
}
static void section(Dump *d,const char *s,size_t n) {
  text(d,"section "); text(d,s); text(d," "); number(d,n); text(d,"\n");
}
#define EX(s,x) ref(d,s,"expression",x,p->expression_count,true)
#define LOCAL(s,x) ref(d,s,"local",x,p->local_count,true)
#define CHECK(x) ref(d,"check_origin","function",(x)?(uint64_t)(x)-1:UINT32_MAX,p->function_count,true)
#define ITEMS(x) range(d,"items","item",(x)->item_start,(x)->item_count,p->item_count)
#define BODY(s,x,y) range(d,s,"child",x,y,p->child_count)

static void expression(Dump *d, const DynIrExpr *e) {
  const DynIrProgram *p=d->p;
  const char *kind=NULL;
  switch(e->kind) {
#define K(x,s) case DYN_EXPR_##x: kind=s; break
    K(INT,"int"); K(FLOAT,"float"); K(BOOL,"bool"); K(CHAR,"char");
    K(STRING,"string"); K(NAME,"name"); K(UNARY,"unary"); K(BINARY,"binary");
    K(CONVERT,"convert"); K(STRUCT,"struct"); K(FIELD,"field"); K(CALL,"call");
    K(NIL,"nil"); K(ARRAY,"array"); K(INDEX,"index"); K(SLICE,"slice");
    K(LEN,"len"); K(ENUM,"enum"); K(GLOBAL,"global"); K(FUNCTION,"function");
    K(INDIRECT_CALL,"indirect_call"); K(SIZE,"size"); K(ALIGN,"align");
    K(TYPEOF,"typeof"); K(CAST,"cast"); K(BITCAST,"bitcast");
    K(SYSCALL,"syscall"); K(TYPE,"type"); K(OFFSET,"offset");
#undef K
    default: d->valid=false; return;
  }
  key(d,"kind"); text(d,kind); type(d,"type",e->type); CHECK(e->check_origin);
  switch(e->kind) {
    case DYN_EXPR_INT: case DYN_EXPR_CHAR: raw(d,"bits",e->integer); break;
    case DYN_EXPR_FLOAT: {
      uint64_t bits; memcpy(&bits,&e->floating,sizeof(bits)); raw(d,"bits",bits); break;
    }
    case DYN_EXPR_BOOL: flag(d,"value",e->boolean); break;
    case DYN_EXPR_STRING: ref(d,"string","string",e->integer,p->string_count,false); break;
    case DYN_EXPR_NAME: LOCAL("local",e->integer); break;
    case DYN_EXPR_GLOBAL: ref(d,"global","global",e->integer,p->global_count,false); break;
    case DYN_EXPR_FUNCTION: ref(d,"function","function",e->integer,p->function_count,false); break;
    case DYN_EXPR_CALL:
      ref(d,"function","function",e->integer,p->function_count,false); ITEMS(e); break;
    case DYN_EXPR_INDIRECT_CALL:
      ref(d,"signature","fn_type",e->integer,p->fn_type_count,false);
      EX("callee",e->left); ITEMS(e); break;
    case DYN_EXPR_STRUCT:
      ref(d,"struct","struct",e->integer,p->struct_count,false); ITEMS(e);
      if(e->integer<p->struct_count && e->item_start<=p->item_count &&
         e->item_count<=p->item_count-e->item_start)
        for(uint32_t i=0;i<e->item_count;++i)
          if(p->items[e->item_start+i].field_index>=p->structs[e->integer].field_count)
            d->valid=false;
      break;
    case DYN_EXPR_ENUM:
      ref(d,"variant","variant",e->integer,p->variant_count,false); ITEMS(e); break;
    case DYN_EXPR_ARRAY: case DYN_EXPR_SYSCALL: ITEMS(e); break;
    case DYN_EXPR_FIELD:
      EX("base",e->left); num(d,"field",e->integer);
      if(e->left<p->expression_count) {
        DynType base=p->expressions[e->left].type;
        if(base>=DYN_TYPE_POINTER_BASE && base<DYN_TYPE_ARRAY_BASE &&
           base-DYN_TYPE_POINTER_BASE<p->pointer_count)
          base=p->pointers[base-DYN_TYPE_POINTER_BASE].pointee;
        if(base<DYN_TYPE_STRUCT_BASE || base>=DYN_TYPE_ENUM_BASE ||
           base-DYN_TYPE_STRUCT_BASE>=p->struct_count ||
           e->integer>=p->structs[base-DYN_TYPE_STRUCT_BASE].field_count)
          d->valid=false;
      }
      break;
    case DYN_EXPR_SLICE:
      EX("base",e->left); EX("start",e->right); EX("stop",e->integer); break;
    case DYN_EXPR_BINARY:
      op(d,"op",e->op); EX("left",e->left); EX("right",e->right);
      flag(d,"wrap",e->wrap); break;
    case DYN_EXPR_UNARY:
      op(d,"op",e->op); EX("operand",e->left); flag(d,"wrap",e->wrap);
      if(e->op==DYN_OP_NEG) flag(d,"signed_literal",e->boolean);
      break;
    case DYN_EXPR_INDEX: EX("base",e->left); EX("index",e->right); break;
    case DYN_EXPR_CONVERT: case DYN_EXPR_CAST: case DYN_EXPR_BITCAST:
    case DYN_EXPR_LEN: EX("operand",e->left); break;
    case DYN_EXPR_SIZE: case DYN_EXPR_ALIGN: case DYN_EXPR_TYPEOF:
      flag(d,"type_operand",e->boolean);
      if(e->boolean) {
        if(e->integer>UINT32_MAX) d->valid=false;
        type(d,"operand_type",(DynType)e->integer);
      } else EX("operand",e->left);
      break;
    case DYN_EXPR_OFFSET:
      /* Source-byte field selectors cannot be represented by lowered IR.
         Sema must have folded this node before a semantic snapshot. */
      d->valid=false; break;
    case DYN_EXPR_NIL: case DYN_EXPR_TYPE: break;
  }
}
static void statement(Dump *d,const DynIrStmt *s) {
  const DynIrProgram *p=d->p;
  const char *kind=NULL;
  switch(s->kind) {
#define K(x,n) case DYN_STMT_##x: kind=n; break
    K(INVALID,"invalid"); K(LOCAL,"local"); K(ASSIGN,"assign"); K(RETURN,"return");
    K(EXPR,"expr"); K(IF,"if"); K(FOR,"for"); K(BREAK,"break");
    K(CONTINUE,"continue"); K(CASE,"case"); K(DEFER,"defer"); K(PANIC,"panic");
#undef K
    default: d->valid=false; return;
  }
  key(d,"kind"); text(d,kind); CHECK(s->check_origin);
  switch(s->kind) {
    case DYN_STMT_INVALID: break;
    case DYN_STMT_LOCAL: LOCAL("local",s->local_id); EX("initializer",s->expression); break;
    case DYN_STMT_ASSIGN:
      EX("value",s->expression); EX("target",s->target);
      if (s->target==DYN_NO_EXPR) LOCAL("local",s->local_id);
      op(d,"op",s->assignment_op); break;
    case DYN_STMT_RETURN: case DYN_STMT_EXPR: case DYN_STMT_PANIC:
      EX("expression",s->expression); break;
    case DYN_STMT_IF:
      EX("condition",s->expression); BODY("body",s->body_start,s->body_count);
      BODY("else",s->else_start,s->else_count); break;
    case DYN_STMT_FOR:
      EX("expression",s->expression); EX("target",s->target);
      LOCAL("local",s->local_id); BODY("body",s->body_start,s->body_count);
      ref(d,"loop","loop",s->loop_id,p->statement_count,false);
      flag(d,"pointer",s->for_pointer); flag(d,"const",s->for_const);
      flag(d,"range",s->for_range); flag(d,"inclusive",s->for_inclusive);
      flag(d,"reverse",s->for_reverse); break;
    case DYN_STMT_BREAK: case DYN_STMT_CONTINUE:
      ref(d,"target_loop","loop",s->target_loop_id,p->statement_count,false); break;
    case DYN_STMT_CASE:
      EX("expression",s->expression);
      range(d,"arms","case_arm",s->case_arm_start,s->case_arm_count,p->case_arm_count); break;
    case DYN_STMT_DEFER:
      flag(d,"block",s->defer_block);
      BODY("body",s->body_start,s->body_count);
      break;
  }
}

static bool storage(const DynIrProgram *p) {
#define S(field,count) if (p->count > UINT32_MAX || (p->count && !p->field)) return false
  S(expressions,expression_count); S(items,item_count); S(fields,field_count);
  S(structs,struct_count); S(enums,enum_count); S(variants,variant_count);
  S(params,param_count); S(functions,function_count); S(globals,global_count);
  S(global_init_order,global_init_count); S(pointers,pointer_count);
  S(arrays,array_count); S(slices,slice_count); S(fn_types,fn_type_count);
  S(fn_type_params,fn_type_param_count); S(strings,string_count);
  S(statements,statement_count); S(patterns,pattern_count);
  S(case_arms,case_arm_count); S(children,child_count); S(locals,local_count);
#undef S
  /* Type tags have disjoint reserved index spaces. */
  return p->struct_count <= DYN_TYPE_ENUM_BASE-DYN_TYPE_STRUCT_BASE &&
    p->enum_count <= DYN_TYPE_POINTER_BASE-DYN_TYPE_ENUM_BASE &&
    p->pointer_count <= DYN_TYPE_ARRAY_BASE-DYN_TYPE_POINTER_BASE &&
    p->array_count <= DYN_TYPE_SLICE_BASE-DYN_TYPE_ARRAY_BASE &&
    p->slice_count <= DYN_TYPE_FN_BASE-DYN_TYPE_SLICE_BASE &&
    p->fn_type_count <= DYN_TYPE_DISTINCT_BASE-DYN_TYPE_FN_BASE;
}
static void walk(Dump *d,const DynTarget *t) {
  const DynIrProgram *p=d->p;
  text(d,"dyn-ir1\n"); text(d,"target");
  name(d,"name",t->name,false); name(d,"triple",t->triple,false);
  name(d,"arch",t->arch,false); name(d,"kernel",t->kernel,false);
  name(d,"abi",t->abi,false); name(d,"libc",t->libc,false);
  name(d,"endian",t->endian,false); name(d,"pointer_bits",t->pointer_bits,false);
  flag(d,"executable_link",t->executable_link); text(d,"\n");
#define SECTION(table,count) section(d,#table,p->count); \
  for(size_t i=0;i<p->count;++i)
#define END text(d,"\n")
  SECTION(structs,struct_count) {
    const DynIrStruct *s=&p->structs[i]; row(d,"struct",i);
    declaration(d,s->name,s->module_owner,false,i);
    flag(d,"packed",s->packed); flag(d,"public",s->is_public);
    range(d,"fields","field",s->field_start,s->field_count,p->field_count); END;
  }
  SECTION(enums,enum_count) {
    const DynIrEnum *e=&p->enums[i]; row(d,"enum",i);
    declaration(d,e->name,e->module_owner,false,i);
    type(d,"tag_type",e->tag_type); flag(d,"public",e->is_public);
    range(d,"variants","variant",e->variant_start,e->variant_count,p->variant_count); END;
  }
  SECTION(fields,field_count) {
    const DynIrField *f=&p->fields[i]; row(d,"field",i);
    name(d,"name",f->name,false); type(d,"type",f->type);
    EX("default",f->default_expression); END;
  }
  SECTION(variants,variant_count) {
    const DynIrVariant *v=&p->variants[i]; row(d,"variant",i);
    name(d,"name",v->name,false); type(d,"payload_type",v->payload_type);
    raw(d,"tag",v->tag); END;
  }
  SECTION(globals,global_count) {
    const DynIrGlobal *g=&p->globals[i]; row(d,"global",i);
    declaration(d,g->name,g->module_owner,false,i);
    /* Only foreign link names carry independent semantic bytes. */
    if(g->foreign) name(d,"link_name",g->link_name,true);
    type(d,"type",g->type); EX("initializer",g->initializer);
    flag(d,"const",g->is_const); flag(d,"foreign",g->foreign);
    flag(d,"public",g->is_public); END;
  }
  SECTION(global_init_order,global_init_count) {
    row(d,"global_init",i); ref(d,"global","global",p->global_init_order[i],p->global_count,false); END;
  }
  SECTION(functions,function_count) {
    const DynIrFunction *f=&p->functions[i]; row(d,"function",i);
    declaration(d,f->name,f->module_owner,f->instance,i);
    if(f->foreign) name(d,"link_name",f->link_name,true);
    type(d,"return_type",f->return_type);
    range(d,"params","param",f->param_start,f->param_count,p->param_count);
    BODY("body",f->body_start,f->body_count);
    range(d,"locals","local",f->local_start,f->local_count,p->local_count);
    flag(d,"main",f->is_main); flag(d,"foreign",f->foreign);
    flag(d,"variadic",f->variadic); flag(d,"public",f->is_public);
    flag(d,"generic",f->generic); flag(d,"instance",f->instance);
    if(f->variadic) {
      type(d,"variadic_type",f->variadic_type); LOCAL("variadic_local",f->variadic_local_id);
    }
    END;
  }
  SECTION(params,param_count) {
    const DynIrParam *v=&p->params[i]; row(d,"param",i);
    name(d,"name",v->name,false); type(d,"type",v->type); LOCAL("local",v->local_id); END;
  }
  SECTION(pointers,pointer_count) {
    row(d,"pointer",i); type(d,"pointee",p->pointers[i].pointee);
    flag(d,"const",p->pointers[i].is_const); END;
  }
  SECTION(arrays,array_count) {
    row(d,"array",i); type(d,"element",p->arrays[i].element);
    raw(d,"length",p->arrays[i].length); END;
  }
  SECTION(slices,slice_count) {
    row(d,"slice",i); type(d,"element",p->slices[i].element);
    flag(d,"const",p->slices[i].is_const); END;
  }
  SECTION(fn_types,fn_type_count) {
    const DynIrFnType *f=&p->fn_types[i]; row(d,"fn_type",i);
    type(d,"return_type",f->return_type);
    range(d,"params","fn_type_param",f->param_start,f->param_count,p->fn_type_param_count);
    flag(d,"variadic",f->variadic); END;
  }
  SECTION(fn_type_params,fn_type_param_count) {
    row(d,"fn_type_param",i); type(d,"type",p->fn_type_params[i]); END;
  }
  SECTION(strings,string_count) {
    row(d,"string",i); key(d,"bytes"); bytes(d,p->strings[i].data,p->strings[i].length); END;
  }
  SECTION(locals,local_count) {
    row(d,"local",i); name(d,"name",p->locals[i].name,false);
    type(d,"type",p->locals[i].type); END;
  }
  SECTION(expressions,expression_count) {
    row(d,"expression",i); expression(d,&p->expressions[i]); END;
  }
  SECTION(items,item_count) {
    row(d,"item",i); EX("expression",p->items[i].expression);
    key(d,"field");
    if(p->items[i].field_index==UINT32_MAX) text(d,"none");
    else { text(d,"field_index:"); number(d,p->items[i].field_index); }
    END;
  }
  SECTION(statements,statement_count) {
    row(d,"statement",i); statement(d,&p->statements[i]); END;
  }
  SECTION(patterns,pattern_count) {
    const DynIrPattern *v=&p->patterns[i]; row(d,"pattern",i);
    flag(d,"enum",v->is_enum); flag(d,"signed",v->is_signed); flag(d,"is_type",v->is_type);
    if(v->is_type) type(d,"type",v->type);
    else if(v->is_enum) {
      ref(d,"variant","variant",v->variant,p->variant_count,false);
    } else { raw(d,"first",v->first); raw(d,"last",v->last); }
    END;
  }
  SECTION(case_arms,case_arm_count) {
    const DynIrCaseArm *a=&p->case_arms[i]; row(d,"case_arm",i);
    range(d,"patterns","pattern",a->pattern_start,a->pattern_count,p->pattern_count);
    BODY("body",a->body_start,a->body_count); LOCAL("local",a->local_id);
    flag(d,"wildcard",a->wildcard); flag(d,"pointer_binding",a->pointer_binding); END;
  }
  SECTION(children,child_count) {
    row(d,"child",i); ref(d,"statement","statement",p->children[i],p->statement_count,false); END;
  }
#undef SECTION
#undef END
  text(d,"end\n");
}

int dyn_ir_dump(FILE *out,const DynIrProgram *p,const DynTarget *target) {
  if(!out || !p || !target || !storage(p) || sizeof(double)!=sizeof(uint64_t)) return 2;
  size_t n=p->struct_count;
  if(p->enum_count>SIZE_MAX-n) return 2;
  n+=p->enum_count;
  if(p->global_count>SIZE_MAX-n) return 2;
  n+=p->global_count;
  if(p->function_count>SIZE_MAX-n) return 2;
  n+=p->function_count;
  if(n>SIZE_MAX/sizeof(uint64_t)) return 2;
  uint64_t *owners=n?malloc(n*sizeof(*owners)):NULL;
  if(n && !owners) return 2;
  Dump d={NULL,p,owners,0,true};
  walk(&d,target);
  if(!d.valid) { free(owners); return 2; }
  d.out=out; d.owner_count=0;
  walk(&d,target);
  free(owners);
  return ferror(out)?2:0;
}
