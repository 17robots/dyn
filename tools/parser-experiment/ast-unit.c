#define _POSIX_C_SOURCE 200809L
#include <stdlib.h>
#include <stdint.h>
static unsigned allocations, fail_at;
static void *ast_malloc(size_t n) { return n && ++allocations == fail_at ? NULL : malloc(n); }
static void *ast_calloc(size_t n, size_t z) { return n && z && ++allocations == fail_at ? NULL : calloc(n,z); }
static void *ast_realloc(void *p, size_t n) { return n && ++allocations == fail_at ? NULL : realloc(p,n); }
#define malloc ast_malloc
#define calloc ast_calloc
#define realloc ast_realloc
#include "../../src/ast.c"
#undef malloc
#undef calloc
#undef realloc
#include <assert.h>
static unsigned compared, skipped, complete, declaration_fallbacks;
typedef struct { char bytes[65536]; size_t length; } Diagnostics;
static void collect(const char *severity, const char *path, unsigned line, unsigned column,
                    unsigned end_line, unsigned end_column, const char *message, void *data) {
  Diagnostics *d = data;
  int n = snprintf(d->bytes + d->length, sizeof(d->bytes) - d->length,
    "%s|%s|%u:%u-%u:%u|%s\n", severity, path, line, column, end_line, end_column, message);
  assert(n >= 0 && (size_t)n < sizeof(d->bytes) - d->length); d->length += (size_t)n;
}
#define SAME(field) do { if (a->field != b->field) { fprintf(stderr, "%s mismatch: %s\n", label, #field); abort(); } } while (0)
static void same(const DynAstProgram *a, const DynAstProgram *b, const char *label) {
  SAME(expression_count); SAME(statement_count); SAME(item_count); SAME(child_count);
  SAME(struct_count); SAME(field_count); SAME(enum_count); SAME(variant_count); SAME(alias_count); SAME(param_count); SAME(global_count); SAME(assert_count); SAME(generic_count); SAME(generic_param_count);
  SAME(function_count); SAME(string_count); SAME(pattern_count); SAME(case_arm_count);
  SAME(pointer_count); SAME(array_count); SAME(slice_count); SAME(fn_type_count); SAME(fn_type_param_count);
#define FIELD(f) do { if (x->f != y->f) { fprintf(stderr,"%s mismatch %s[%zu].%s: %llu != %llu\n",label, section,i,#f,(unsigned long long)x->f,(unsigned long long)y->f); abort(); } } while (0)
  for (size_t i=0;i<a->expression_count;++i) {
    const DynAstExpr *x=&a->expressions[i], *y=&b->expressions[i]; const char *section="expressions";
    FIELD(kind); FIELD(span.start_byte); FIELD(span.end_byte); FIELD(type); FIELD(op);
    FIELD(left); FIELD(right); FIELD(integer); FIELD(floating); FIELD(boolean); FIELD(item_start); FIELD(item_count); FIELD(wrap);
  }
  for (size_t i=0;i<a->statement_count;++i) {
    const DynAstStmt *x=&a->statements[i], *y=&b->statements[i]; const char *section="statements";
    FIELD(kind); FIELD(span.start_byte); FIELD(span.end_byte); FIELD(name.start_byte); FIELD(name.end_byte);
    FIELD(label.start_byte); FIELD(label.end_byte); FIELD(control_label.start_byte); FIELD(control_label.end_byte);
    FIELD(declared_type); FIELD(expression); FIELD(target); FIELD(assignment_op); FIELD(local_id);
    FIELD(body_start); FIELD(body_count); FIELD(else_start); FIELD(else_count); FIELD(loop_depth); FIELD(loop_id); FIELD(target_loop_id);
    FIELD(case_arm_start); FIELD(case_arm_count); FIELD(defer_block); FIELD(for_pointer); FIELD(for_const); FIELD(is_const); FIELD(for_range); FIELD(for_inclusive); FIELD(for_reverse);
  }
  for (size_t i=0;i<a->item_count;++i) {
    const DynAstItem *x=&a->items[i], *y=&b->items[i]; const char *section="items";
    FIELD(name.start_byte); FIELD(name.end_byte); FIELD(expression); FIELD(field_index);
  }
  for (size_t i=0;i<a->function_count;++i) {
    const DynAstFn *x=&a->functions[i], *y=&b->functions[i]; const char *section="functions";
    FIELD(body_start); FIELD(body_count); FIELD(span.start_byte); FIELD(span.end_byte);
    FIELD(name.start_byte); FIELD(name.end_byte); FIELD(link_name.start_byte); FIELD(link_name.end_byte);
    FIELD(return_type); FIELD(param_start); FIELD(param_count); FIELD(is_main); FIELD(foreign); FIELD(variadic); FIELD(is_public); FIELD(interface_only);
    FIELD(is_generic); FIELD(is_instance); FIELD(body_pending); FIELD(generic); FIELD(instance); FIELD(module_owner);
    FIELD(variadic_type); FIELD(variadic_name.start_byte); FIELD(variadic_name.end_byte);
  }
  for (size_t i=0;i<a->pattern_count;++i) {
    const DynAstPattern *x=&a->patterns[i], *y=&b->patterns[i]; const char *section="patterns";
    FIELD(span.start_byte); FIELD(span.end_byte); FIELD(first); FIELD(last); FIELD(type); FIELD(range); FIELD(inclusive); FIELD(is_type);
  }
  for (size_t i=0;i<a->case_arm_count;++i) {
    const DynAstCaseArm *x=&a->case_arms[i], *y=&b->case_arms[i]; const char *section="case_arms";
    FIELD(span.start_byte); FIELD(span.end_byte); FIELD(binding.start_byte); FIELD(binding.end_byte);
    FIELD(pattern_start); FIELD(pattern_count); FIELD(body_start); FIELD(body_count); FIELD(local_id); FIELD(wildcard); FIELD(pointer_binding);
  }
  for(size_t i=0;i<a->struct_count;++i) { const DynAstStruct *x=&a->structs[i],*y=&b->structs[i]; const char *section="structs"; FIELD(span.start_byte); FIELD(span.end_byte); FIELD(name.start_byte); FIELD(name.end_byte); FIELD(packed); FIELD(is_public); FIELD(module_owner); FIELD(field_start); FIELD(field_count); FIELD(size); FIELD(alignment); }
  for(size_t i=0;i<a->field_count;++i) { const DynAstField *x=&a->fields[i],*y=&b->fields[i]; const char *section="fields"; FIELD(name.start_byte); FIELD(name.end_byte); FIELD(type); FIELD(default_expression); FIELD(offset); }
  for(size_t i=0;i<a->enum_count;++i) { const DynAstEnum *x=&a->enums[i],*y=&b->enums[i]; const char *section="enums"; FIELD(span.start_byte); FIELD(span.end_byte); FIELD(name.start_byte); FIELD(name.end_byte); FIELD(tag_type); FIELD(variant_start); FIELD(variant_count); FIELD(size); FIELD(alignment); FIELD(payload_size); FIELD(payload_alignment); FIELD(has_payload); FIELD(is_public); FIELD(module_owner); }
  for(size_t i=0;i<a->variant_count;++i) { const DynAstVariant *x=&a->variants[i],*y=&b->variants[i]; const char *section="variants"; FIELD(name.start_byte); FIELD(name.end_byte); FIELD(payload_type); FIELD(tag); }
  for(size_t i=0;i<a->alias_count;++i) { const DynAstAlias *x=&a->aliases[i],*y=&b->aliases[i]; const char *section="aliases"; FIELD(name.start_byte); FIELD(name.end_byte); FIELD(target); FIELD(distinct); FIELD(is_public); FIELD(module_owner); FIELD(state); }
  for(size_t i=0;i<a->param_count;++i) { const DynAstParam *x=&a->params[i],*y=&b->params[i]; const char *section="params"; FIELD(name.start_byte); FIELD(name.end_byte); FIELD(type); FIELD(local_id); }
  for(size_t i=0;i<a->global_count;++i) { const DynAstGlobal *x=&a->globals[i],*y=&b->globals[i]; const char *section="globals"; FIELD(name.start_byte); FIELD(name.end_byte); FIELD(link_name.start_byte); FIELD(link_name.end_byte); FIELD(type); FIELD(initializer); FIELD(is_const); FIELD(foreign); FIELD(is_public); FIELD(module_owner); }
  for(size_t i=0;i<a->assert_count;++i) { const DynAstAssert *x=&a->asserts[i],*y=&b->asserts[i]; const char *section="asserts"; FIELD(span.start_byte); FIELD(span.end_byte); FIELD(message.start_byte); FIELD(message.end_byte); FIELD(condition); }
  for(size_t i=0;i<a->generic_count;++i) { const DynAstGeneric *x=&a->generics[i],*y=&b->generics[i]; const char *section="generics"; FIELD(function); FIELD(param_start); FIELD(param_count); FIELD(type_param_count); FIELD(return_pattern); }
  for(size_t i=0;i<a->generic_param_count;++i) { const DynAstGenericParam *x=&a->generic_params[i],*y=&b->generic_params[i]; const char *section="generic_params"; FIELD(name.start_byte); FIELD(name.end_byte); FIELD(pattern); FIELD(is_type); }
  for(size_t i=0;i<a->pointer_count;++i) { const DynAstPointer *x=&a->pointers[i],*y=&b->pointers[i]; const char *section="pointers"; FIELD(pointee); FIELD(is_const); }
  for(size_t i=0;i<a->slice_count;++i) { const DynAstSlice *x=&a->slices[i],*y=&b->slices[i]; const char *section="slices"; FIELD(element); FIELD(is_const); }
  for(size_t i=0;i<a->array_count;++i) { const DynAstArray *x=&a->arrays[i],*y=&b->arrays[i]; const char *section="arrays"; FIELD(element); FIELD(length); }
  for(size_t i=0;i<a->fn_type_count;++i) { const DynAstFnType *x=&a->fn_types[i],*y=&b->fn_types[i]; const char *section="fn_types"; FIELD(return_type); FIELD(param_start); FIELD(param_count); }
  for(size_t i=0;i<a->fn_type_param_count;++i) assert(a->fn_type_params[i]==b->fn_type_params[i]);
  for(size_t i=0;i<a->child_count;++i) assert(a->children[i]==b->children[i]);
  for(size_t i=0;i<a->string_count;++i) assert(a->strings[i].length==b->strings[i].length && !memcmp(a->strings[i].data,b->strings[i].data,a->strings[i].length));
#undef FIELD
}
static void compare(const char *text, const char *label, bool required) {
  DynSource source = {.path=strdup(label), .text=strdup(text), .length=strlen(text)};
  assert(source.path && source.text && dyn_source_prepare(&source));
  if (!source.compact) { if(required) fprintf(stderr,"no compact: %s\n", label); assert(!required); ++skipped; dyn_source_free(&source); return; }
  DynAstProgram expected={0}, actual={0}; unsigned ea=0, eb=0;
  Diagnostics da={0}, db={0}; source.context.diagnostic=collect;
  source.context.diagnostic_data=&da;
  ExpSnapshot *snapshot=source.compact; source.compact=NULL;
  bool fa=dyn_ast_lower_source(ts_tree_root_node(source.syntax),&source,&expected,&ea,NULL);
  source.compact=snapshot; source.context.diagnostic_data=&db;
  allocations=0;
  bool fb=dyn_ast_lower_source(ts_tree_root_node(source.syntax),&source,&actual,&eb,NULL);
  unsigned total=allocations;
  if(fa!=fb || ea!=eb || strcmp(da.bytes,db.bytes)) { fprintf(stderr,"%s diagnostics mismatch\n%s\n%s",label,da.bytes,db.bytes); abort(); }
  if(required) assert(actual.compact_complete && actual.compact_declaration_count);
  same(&expected,&actual,label); ++compared;
  if(actual.compact_complete) ++complete; else ++declaration_fallbacks;
  dyn_ast_program_free(&actual);
  if(required) {
    for(unsigned failure=1;failure<=total;++failure) {
      allocations=0; fail_at=failure; eb=0; db=(Diagnostics){0};
      dyn_ast_lower_source(ts_tree_root_node(source.syntax),&source,&actual,&eb,NULL);
      if(!actual.allocation_failed && !eb) fprintf(stderr,"nonterminal allocation %u/%u: %s\n",failure,total,label);
      assert(actual.allocation_failed || eb);
      fail_at=0; dyn_ast_program_free(&actual);
    }
    DynWork work={.remaining=UINT64_MAX}; source.context.work=&work; eb=0; db=(Diagnostics){0};
    dyn_ast_lower_source(ts_tree_root_node(source.syntax),&source,&actual,&eb,NULL);
    uint64_t used=UINT64_MAX-work.remaining; dyn_ast_program_free(&actual);
    for(uint64_t budget=0;budget<used;++budget) {
      work=(DynWork){.remaining=budget}; eb=0; db=(Diagnostics){0};
      dyn_ast_lower_source(ts_tree_root_node(source.syntax),&source,&actual,&eb,NULL);
      assert(work.status==DYN_WORK_LIMIT); dyn_ast_program_free(&actual);
    }
    source.context.work=NULL;
  }
  DynSources project={.items=&source,.count=1};
  bool was_complete=source.compact && compact_shape_supported((CompactNode){exp_snapshot_tree(source.compact),exp_snapshot_tree(source.compact)->root,0,source.compact},&source);
  bool eligible=dyn_source_target_enabled(&source)==1;
  if (eligible) assert(dyn_ast_release_project_trees(&project)==was_complete);
  if (eligible && was_complete) {
    assert(source.compact_only && !source.syntax);
    eb=0; db=(Diagnostics){0}; allocations=0;
    bool fc=dyn_ast_lower_compact(&source,&actual,&eb,NULL);
    unsigned compact_allocations=allocations;
    assert(fc==fa && ea==eb && !strcmp(da.bytes,db.bytes));
    same(&expected,&actual,label); dyn_ast_program_free(&actual);
    if(required) for(unsigned failure=1;failure<=compact_allocations;++failure) {
      allocations=0; fail_at=failure; eb=0; db=(Diagnostics){0};
      dyn_ast_lower_compact(&source,&actual,&eb,NULL);
      assert(actual.allocation_failed || eb);
      fail_at=0; dyn_ast_program_free(&actual);
    }
  } else assert(source.syntax && !source.compact_only);
  dyn_ast_program_free(&expected);
  dyn_source_free(&source);
}
static void generic_lifetime(void) {
  const char *text="fn identity(value:$T) T {x:T=value return x} fn main(){}";
  DynSource source={.path=strdup("generic.dyn"),.text=strdup(text),.length=strlen(text)};
  assert(dyn_source_prepare(&source));
  DynAstProgram a={0},b={0}; unsigned ea=0,eb=0;
  ExpSnapshot *snapshot=source.compact; source.compact=NULL;
  dyn_ast_lower_source(ts_tree_root_node(source.syntax),&source,&a,&ea,NULL);
  source.compact=snapshot;
  dyn_ast_lower_source(ts_tree_root_node(source.syntax),&source,&b,&eb,NULL);
  assert(!ea && !eb && b.compact_body_count==2);
  exp_snapshot_release(source.compact); source.compact=NULL;
  DynType types[DYN_MAX_TYPE_PARAMS]={DYN_TYPE_I64};
  uint32_t fa=dyn_ast_instantiate(&a,&source,0,types,0,(DynSpan){0},0);
  uint32_t fb=dyn_ast_instantiate(&b,&source,0,types,0,(DynSpan){0},0);
  assert(fa!=UINT32_MAX && fa==fb);
  assert(dyn_ast_lower_instance(&a,&source,fa,&ea));
  assert(ts_node_is_null(b.generics[0].node) && b.generics[0].compact_node.snapshot);
  dyn_source_release_batch_trees(&source); assert(!source.syntax);
  assert(dyn_ast_lower_instance(&b,&source,fb,&eb));
  assert(!ea && !eb); same(&a,&b,"retained generic");
  dyn_ast_program_free(&a); dyn_ast_program_free(&b); dyn_source_free(&source);
}
static void merged_lifetime(void) {
  const char *texts[]={"const Size:u64=3 type Bytes=[Size]u8", "fn main(){a:Bytes _=#typeof(a)}"};
  DynSource inputs[2]={0};
  for(unsigned i=0;i<2;++i) {
    inputs[i]=(DynSource){.path=strdup(i?"main.dyn":"types.dyn"),.text=strdup(texts[i]),.length=strlen(texts[i])};
    assert(dyn_source_prepare(&inputs[i]));
  }
  DynSources list={.items=inputs,.count=2}; DynSource merged;
  assert(!dyn_sources_merge(&list,"merged",&merged));
  assert(merged.syntax_part_count==3 && merged.compact_parts[0]);
  TSTree *survivor=ts_tree_copy(inputs[0].syntax);
  for(unsigned i=0;i<2;++i) {
    ExpSnapshot *snapshot=inputs[i].compact;
    dyn_source_release_batch_trees(&inputs[i]);
    assert(!inputs[i].syntax && inputs[i].compact==snapshot);
  }
  assert(!ts_node_has_error(ts_tree_root_node(survivor)));
  ts_tree_delete(survivor);
  TSNode roots[3]; for(unsigned i=0;i<3;++i) roots[i]=ts_tree_root_node(merged.syntax_parts[i]);
  DynAstProgram a={0},b={0}; unsigned ea=0,eb=0;
  ExpSnapshot **parts=merged.compact_parts; merged.compact_parts=NULL;
  dyn_ast_lower_roots(roots,3,&merged,&a,&ea,NULL);
  merged.compact_parts=parts;
  dyn_ast_lower_roots(roots,3,&merged,&b,&eb,NULL);
  assert(!ea && !eb && b.compact_complete && b.alias_count==1);
  same(&a,&b,"merged reflection partitions");
  for(unsigned i=0;i<2;++i) dyn_source_free(&inputs[i]);
  dyn_source_release_batch_trees(&merged);
  assert(merged.syntax_part_count==3 && merged.compact_parts==parts);
  for(unsigned i=0;i<3;++i) { assert(!merged.syntax_parts[i]); exp_snapshot_release(parts[i]); parts[i]=NULL; }
  dyn_source_release_batch_trees(&merged); /* Idempotent terminal release. */
  assert(ts_node_is_null(b.aliases[0].type_node) && b.aliases[0].compact_type.snapshot);
  DynType target=b.aliases[0].target; b.aliases[0].state=0;
  assert(resolve_alias(&b,0,&merged)==target);
  dyn_ast_program_free(&a); dyn_ast_program_free(&b); dyn_source_free(&merged);
}
int main(int argc, char **argv) {
  generic_lifetime();
  merged_lifetime();
  char grouped[2048]="fn group(";
  for(unsigned i=0;i<64;++i) { char name[20]; snprintf(name,sizeof(name),"%sa%u",i?",":"",i); strcat(grouped,name); }
  strcat(grouped,":$T){} fn main(){}"); compare(grouped,"grouped generic parameters",true);
  const char *cases[]={
    "fn main(){x:=1+2*3 _=x}",
    "fn f(){(1)=2}",
    "fn f(x:i64){case x {0=>{case x {0=>{},1=>{},2=>{},3=>{},4=>{},5=>{},6=>{},7=>{},8=>{}}},_=>{}}}",
    "const N:u64=3 type Table=[N+1]u8 fn f(){const M:=2 x:[M+N]u8 _=x}",
    "const N:=3 fn f(N:i64){x:[N]u8} fn g(){N:=2 x:[N]u8} fn h(){for N in 0..2 {x:[N]u8}}",
    "const A:=B const B:=A fn f(){x:[A]u8}",
    "type Word=u64 distinct type Other=i32 packed struct Pair{x,y:Word=3} enum(u8) Tag{A=1,B=2} pub const G:Word=7 extern fn foreign(x:i32) i32 fn identity(x:$T) T{return x} fn main(){x:Pair _=G}",
    "fn f(a:any){case a {is i64 x=>{_=x},_ other=>{_=other}}}",
    "fn f(a:i64){case a {0,1 x=>{_=x},2..=4 y=>{_=y},_=>{}}}",
    "fn f(a:i64){for i in #reverse(0..=a){_=i} outer:for *const p in a {_=p} if a>0 {return} else if a<0 {return} else {a=1}}",
    "struct S{x:i64} fn main(){s:=S{x:1} a:=[1,2,3] _=a[1..] _=a[..2] _=s.x _=f(*u8) _=#bitcast(i32)1 _=#wrap(1+2)}",
    "fn f(){x: [1+2]u8 y: []const u8 z: *fn(i32) i64 _=#sizeof(*u8) _=#alignof(i32) _=#typeof(x) _=#offsetof(S,x)}",
    "fn f(){defer {g()} defer g() #panic(\"bad\") _='é' _=\"x\\x00\\n\" _=0xff _=1.2e3 _=nil _=!true}"
  };
  for(size_t i=0;i<sizeof(cases)/sizeof(*cases);++i) compare(cases[i],cases[i],true);
  for(int i=1;i<argc;++i) {
    FILE *file=fopen(argv[i],"rb"); assert(file); assert(!fseek(file,0,SEEK_END)); long length=ftell(file); assert(length>=0);
    rewind(file); char *text=calloc((size_t)length+1,1); assert(text); assert(fread(text,1,(size_t)length,file)==(size_t)length); fclose(file);
    compare(text,argv[i],false); free(text);
  }
  printf("PASS compact AST: %u compared, %u complete, %u declaration fallbacks, %u parser fallbacks\n",compared,complete,declaration_fallbacks,skipped);
}
