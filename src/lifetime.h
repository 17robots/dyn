#ifndef DYN_LIFETIME_H
#define DYN_LIFETIME_H
/* Conservative straight-line provenance. Branch/loop joins discard facts rather * than diagnosing a possible path as a proven error. This is not a borrow checker. */
typedef struct { bool stack, expired; uint32_t arena, address; } LifeValue;
typedef struct { uint32_t local, field; LifeValue value; } LifeField;
typedef struct {
  Sema *sema; DynAstProgram *a; const DynSource *source; unsigned *errors;
  uint32_t first, count; LifeValue *locals;
  LifeField *fields; size_t field_count, field_capacity;
} Life;
static LifeValue life_join(LifeValue a, LifeValue b) {
  a.stack |= b.stack; a.expired |= b.expired;
  if (!a.arena) a.arena = b.arena;
  else if (b.arena && a.arena != b.arena) a.arena = 0;
  if (!a.address) a.address = b.address;
  else if (b.address && a.address != b.address) a.address = 0;
  return a;
}
static LifeValue *life_local(Life *l, uint32_t id) {
  return id >= l->first && id-l->first < l->count ? &l->locals[id-l->first] : NULL;
}
static bool life_borrow_type(DynAstProgram *a, DynType t, unsigned depth) {
  if (depth > 64) return false;
  if (dyn_type_is_pointer(t) || dyn_type_is_slice(t) || t == DYN_TYPE_RAWPTR || t == DYN_TYPE_ANY) return true;
  if (dyn_type_is_array(t)) return life_borrow_type(a, a->arrays[t-DYN_TYPE_ARRAY_BASE].element,depth + 1);
  if (dyn_type_is_struct(t)) {
    DynAstStruct *st=&a->structs[t - DYN_TYPE_STRUCT_BASE];
    for (uint32_t i=0;i<st->field_count;++i) if (life_borrow_type(a,a->fields[st->field_start+i].type,depth+1)) return true;
  }
  return false;
}
static const char *const life_mem_names[] = {
  "arena_push_or_panic", "arena_push_uninit_or_panic", "arena_push", "arena_push_uninit",
  "arena_push_array", "push", "push_array", "push_bytes_uninit", "arena_rewind",
  "arena_from_buffer", "arena_reset"};
/* Which std/mem function a callee is. Mapping a span back to its file is a linear search, so each function is classified once and cached. */
static uint8_t life_mem_kind(Life *l, uint64_t function) {
  Sema *sema = l->sema;
  if (function >= sema->mem_kind_count) {
    size_t count = l->a->function_count;
    uint8_t *grown = realloc(sema->mem_kinds, count);
    if (!grown) { l->a->allocation_failed = true; return 1; }
    memset(grown + sema->mem_kind_count, 0, count - sema->mem_kind_count);
    sema->mem_kinds = grown; sema->mem_kind_count = count;
  }
  if (sema->mem_kinds[function]) return sema->mem_kinds[function];
  uint8_t kind = 1;
  DynSpan span=l->a->functions[function].name;
  const char *path,*text; size_t n,at;
  dyn_source_position(l->source,span.start_byte,&path,&text,&n,&at);
  if (path && (strstr(path,"/std/mem/") || strstr(path,"/share/dyn/mem/")))
    for (size_t i=0;i<sizeof(life_mem_names)/sizeof(*life_mem_names);++i) {
      size_t z=strlen(life_mem_names[i]);
      if (at+z<=n && !memcmp(text+at,life_mem_names[i],z) &&
          (at+z==n || !(isalnum((unsigned char)text[at+z]) || text[at+z]=='_'))) { kind = (uint8_t)(2+i); break; }
    }
  return sema->mem_kinds[function] = kind;
}
static bool life_mem_call(Life *l, DynAstExpr *e, const char *name) {
  if (e->kind != DYN_EXPR_CALL || e->integer >= l->a->function_count) return false;
  uint8_t kind = life_mem_kind(l, e->integer);
  return kind >= 2 && !strcmp(life_mem_names[kind-2], name);
}
/* Arena pushes; the first argument is the arena. */
static bool life_push_call(Life *l, DynAstExpr *e) {
  static const char *names[]={"arena_push_or_panic","arena_push_uninit_or_panic","arena_push", "arena_push_uninit","arena_push_array","push","push_array","push_bytes_uninit"};
  for (size_t i=0;i<sizeof(names)/sizeof(*names);++i) if (life_mem_call(l,e,names[i])) return true;
  return false;
}
static bool life_zero_rewind(Life *l, DynAstExpr *e) {
  if (!life_mem_call(l, e, "arena_rewind") || e->item_count != 2) return false;
  DynExprId id = l->a->items[e->item_start + 1].expression;
  if (id == DYN_NO_EXPR || id >= l->a->expression_count) return false;
  DynAstExpr *mark = &l->a->expressions[id];
  return mark->kind == DYN_EXPR_INT && mark->integer == 0;
}
static void life_invalidate(Life *l,uint32_t arena) {
  if (!arena) return;
  for (uint32_t i=0;i<l->count;++i) if (l->locals[i].arena==arena) l->locals[i].expired=true;
  for (size_t i=0;i<l->field_count;++i) if (l->fields[i].value.arena==arena) l->fields[i].value.expired=true;
}
static LifeValue life_expr(Life *,DynExprId,unsigned);
static void life_forget(Life *l);
/* Std types whose copies share one owned resource. Arenas own memory; the
   others hold OS handles that must be closed once. */
typedef enum { LIFE_NOT_OWNER, LIFE_ARENA_OWNER, LIFE_HANDLE_OWNER } LifeOwner;
static LifeOwner life_owner(Life *l, DynType type) {
  static const struct { const char *module, *name; LifeOwner kind; } owners[] = {
    {"mem/", "Arena", LIFE_ARENA_OWNER}, {"mem/", "GrowingArena", LIFE_ARENA_OWNER},
    {"fs/", "File", LIFE_HANDLE_OWNER}, {"fs/watch/", "Watcher", LIFE_HANDLE_OWNER},
    {"process/", "Child", LIFE_HANDLE_OWNER}, {"thread/", "Thread", LIFE_HANDLE_OWNER},
    {"net/", "Listener", LIFE_HANDLE_OWNER}, {"net/", "Connection", LIFE_HANDLE_OWNER},
  };
  if (!dyn_type_is_struct(type)) return LIFE_NOT_OWNER;
  DynSpan name = l->a->structs[type - DYN_TYPE_STRUCT_BASE].name;
  const char *path, *text; size_t length, at;
  dyn_source_position(l->source, name.start_byte, &path, &text, &length, &at);
  if (!path) return LIFE_NOT_OWNER;
  for (size_t i = 0; i < sizeof(owners) / sizeof(*owners); ++i) {
    char std_dir[64], share_dir[64];
    snprintf(std_dir, sizeof(std_dir), "/std/%s", owners[i].module);
    snprintf(share_dir, sizeof(share_dir), "/share/dyn/%s", owners[i].module);
    const char *found = strstr(path, std_dir);
    size_t prefix = strlen(std_dir);
    if (!found) { found = strstr(path, share_dir); prefix = strlen(share_dir); }
    /* The struct must be declared directly in that module directory. */
    if (!found || strchr(found + prefix, '/')) continue;
    size_t n = strlen(owners[i].name);
    if (at + n <= length && !memcmp(text + at, owners[i].name, n) &&
        (at + n == length || !(isalnum((unsigned char)text[at+n]) || text[at+n] == '_')))
      return owners[i].kind;
  }
  return LIFE_NOT_OWNER;
}
static void life_warn_copy(Life *l, DynAstStmt *statement) {
  if (!l->source->context.vet || statement->expression == DYN_NO_EXPR) return;
  if (statement->kind != DYN_STMT_LOCAL && statement->kind != DYN_STMT_ASSIGN) return;
  DynAstExpr *value = &l->a->expressions[statement->expression];
  if (value->kind != DYN_EXPR_NAME && value->kind != DYN_EXPR_FIELD) return;
  LifeOwner owner = life_owner(l, value->type);
  if (owner == LIFE_NOT_OWNER) return;
  // Only assignment destinations copy a value; `_ = arena` does not create an owner.
  if (statement->kind == DYN_STMT_ASSIGN && statement->target == DYN_NO_EXPR &&
      discard_name(statement->name, l->source)) return;
  const char *path, *text; size_t length, at;
  dyn_source_position(l->source, statement->span.start_byte, &path, &text, &length, &at);
  // The standard library implements these types and transfers them deliberately.
  if (path && (strstr(path, "/std/") || strstr(path, "/share/dyn/"))) return;
  dyn_diagnostic_source("warning", l->source,
      statement->span.start_byte, statement->span.end_byte,
      owner == LIFE_ARENA_OWNER
        ? "copying an arena descriptor duplicates mutable allocation state; borrow its address or transfer ownership explicitly"
        : "copying a handle duplicates an OS resource that must be closed once; borrow its address or transfer it with take");
  if (l->source->context.vet_findings) ++*l->source->context.vet_findings;
}
static LifeValue life_field(Life *l,uint32_t local,uint32_t field) {
  for (size_t i=l->field_count;i;--i) if(l->fields[i-1].local==local && l->fields[i-1].field==field) return l->fields[i-1].value;
  LifeValue *v=life_local(l,local); return v ? *v : (LifeValue){0};
}
static void life_set_field(Life *l,uint32_t local,uint32_t field,LifeValue value) {
  for(size_t i=0;i<l->field_count;++i) if(l->fields[i].local==local && l->fields[i].field==field) { l->fields[i].value=value; return; }
  if(l->field_count==l->field_capacity) {
    size_t capacity=l->field_capacity ? l->field_capacity*2 : 16;
    LifeField *fields=realloc(l->fields,capacity*sizeof(*fields));
    if(!fields) { l->a->allocation_failed=true; return; }
    l->fields=fields;l->field_capacity=capacity;
  }
  l->fields[l->field_count++]=(LifeField){local,field,value};
}
static LifeValue life_expr(Life *l,DynExprId id,unsigned depth) {
  LifeValue v={0}; DynAstProgram *a=l->a;
  if(id==DYN_NO_EXPR || id>=a->expression_count || depth>128 || !dyn_work_step(&l->source->context,1)) return v;
  DynAstExpr *e=&a->expressions[id];
  if(e->kind==DYN_EXPR_NAME) {
    LifeValue *p=life_local(l,(uint32_t)e->integer); if(p) v=*p;
    for(size_t i=0;i<l->field_count;++i) if(l->fields[i].local==e->integer) v=life_join(v,l->fields[i].value);
  } else if(e->kind==DYN_EXPR_FIELD && a->expressions[e->left].kind==DYN_EXPR_NAME && !e->boolean) {
    v=life_field(l,(uint32_t)a->expressions[e->left].integer,(uint32_t)e->integer);
  } else if(e->kind==DYN_EXPR_UNARY && e->op==DYN_OP_ADDRESS && a->expressions[e->left].kind==DYN_EXPR_NAME) {
    uint32_t local=(uint32_t)a->expressions[e->left].integer;
    v.stack=life_local(l,local)!=NULL;v.address=local+1;
  } else {
    LifeValue left=life_expr(l,e->left,depth+1), right=life_expr(l,e->right,depth+1);
    bool view=e->kind==DYN_EXPR_SLICE || e->kind==DYN_EXPR_CAST || e->kind==DYN_EXPR_CONVERT || e->kind==DYN_EXPR_BITCAST || e->kind==DYN_EXPR_FIELD || e->kind==DYN_EXPR_INDEX || e->kind==DYN_EXPR_UNARY;
    if(view && life_borrow_type(a,e->type,0)) v=left;
    if(returns_local_borrow(l->sema,a,id)) v.stack=true;
    if(left.expired || right.expired) v.expired=true;
    for(uint32_t i=0;i<e->item_count;++i) {
      LifeValue item=life_expr(l,a->items[e->item_start+i].expression,depth+1);
      if(e->kind==DYN_EXPR_STRUCT || e->kind==DYN_EXPR_ARRAY || e->kind==DYN_EXPR_ENUM) v=life_join(v,item);
      else if(item.expired) v.expired=true;
    }
    if(e->kind==DYN_EXPR_CALL && e->item_count) {
      LifeValue first=life_expr(l,a->items[e->item_start].expression,depth+1);
      bool push=life_push_call(l,e);
      if(push) {
        v.arena=first.address;v.stack=false;
        LifeValue *backing=first.address ? life_local(l,first.address-1) : NULL;
        if(backing) v.stack=backing->stack;
      }
      if(life_mem_call(l,e,"arena_from_buffer")) v.stack=first.stack;
      if(life_mem_call(l,e,"arena_reset") || life_zero_rewind(l,e)) life_invalidate(l,first.address);
      /* Unknown callees may mutate any address-exposed local or alias. */
      if (!push &&
          !life_mem_call(l,e,"arena_from_buffer") && !life_mem_call(l,e,"arena_reset") && !life_zero_rewind(l,e)) life_forget(l);
      /* Rewind invalidates only a suffix; without allocation offsets it is
       * unsound to mark every arena pointer expired. Release may fail. */
    }
  }
  if (e->kind==DYN_EXPR_LEN) v.expired=false; /* Descriptor length does not read backing storage. */
  if (!life_borrow_type(a,e->type,0)) { v.stack=false; v.arena=0; v.address=0; }
  if (e->kind==DYN_EXPR_CALL && !e->item_count) life_forget(l);
  return v;
}
static void life_forget(Life *l) { memset(l->locals,0,l->count*sizeof(*l->locals)); l->field_count=0; }
static void life_block(Life *l,uint32_t start,uint32_t count,unsigned depth) {
  if(depth>128) { life_forget(l); return; }
  for(uint32_t i=0;i<count && dyn_work_step(&l->source->context,1);++i) {
    DynAstStmt *st=&l->a->statements[l->a->children[start+i]];
    life_warn_copy(l, st);
    if(st->kind==DYN_STMT_DEFER) { life_forget(l); continue; }
    LifeValue value=life_expr(l,st->expression,0);
    if(value.expired) error_span(st->span,l->source,l->errors,"use of storage after arena_reset or arena_rewind to zero");
    if(st->kind==DYN_STMT_RETURN) {
      if(value.stack && !returns_local_borrow(l->sema,l->a,st->expression))
        error_span(st->span,l->source,l->errors,"returned value borrows function-local storage through an alias");
      break;
    }
    if(st->kind==DYN_STMT_IF || st->kind==DYN_STMT_FOR || st->kind==DYN_STMT_CASE || st->kind==DYN_STMT_DEFER) {
      /* Defers execute later; never simulate their invalidations immediately. */
      life_forget(l);
      if(st->kind!=DYN_STMT_DEFER) {
        life_block(l,st->body_start,st->body_count,depth+1);life_forget(l);
        life_block(l,st->else_start,st->else_count,depth+1);life_forget(l);
        for(uint32_t j=0;j<st->case_arm_count;++j) {
          DynAstCaseArm *arm=&l->a->case_arms[st->case_arm_start+j];
          life_block(l,arm->body_start,arm->body_count,depth+1);life_forget(l);
        }
      }
      continue;
    }
    if(st->kind==DYN_STMT_LOCAL || (st->kind==DYN_STMT_ASSIGN && st->target==DYN_NO_EXPR && st->assignment_op==DYN_OP_NONE && !discard_name(st->name,l->source))) {
      LifeValue *p=life_local(l,st->local_id);
      if(!p) continue;
      for(size_t j=0;j<l->field_count;) {
        if(l->fields[j].local==st->local_id) l->fields[j]=l->fields[--l->field_count]; else ++j;
      }
      *p=value;
      if (st->expression!=DYN_NO_EXPR) {
        DynAstExpr *source=&l->a->expressions[st->expression];
        if (source->kind==DYN_EXPR_NAME && dyn_type_is_struct(source->type) && source->integer!=st->local_id) {
          LifeValue *original=life_local(l,(uint32_t)source->integer);
          *p=original ? *original : (LifeValue){0};
          size_t fields=l->field_count;
          for (size_t j=0;j<fields;++j) if (l->fields[j].local==source->integer) {
            LifeField field=l->fields[j];
            life_set_field(l,st->local_id,field.field,field.value);
          }
        }
      }
      if(st->expression!=DYN_NO_EXPR) {
        DynAstExpr *e = &l->a->expressions[st->expression];
        if(e->kind == DYN_EXPR_STRUCT) {
          *p=(LifeValue){0};
          for(uint32_t j=0;j<e->item_count;++j) {
            DynAstItem *item = &l->a->items[e->item_start+j];
            life_set_field(l,st->local_id,item->field_index,life_expr(l,item->expression,0));
          }
        }
      }
    } else if(st->kind == DYN_STMT_ASSIGN && st->target != DYN_NO_EXPR) {
      DynAstExpr *target = &l->a->expressions[st->target];
      LifeValue dest=life_expr(l,st->target,0);
      bool direct_field= target->kind == DYN_EXPR_FIELD && !target->boolean && l->a->expressions[target->left].kind == DYN_EXPR_NAME;
      if(dest.expired && !direct_field) error_span(st->span,l->source,l->errors,"write to storage after arena_reset or arena_rewind to zero");
      if(direct_field) life_set_field(l,(uint32_t)l->a->expressions[target->left].integer,(uint32_t)target->integer,value);
      else life_forget(l); /* An indirect write may replace tracked provenance. */
    }
  }
}
static void life_check_function(Sema *sema,DynAstProgram *a,const DynSource *s,unsigned *errors,DynAstFn *fn) {
  if(*errors || !fn->local_count) return;
  Life l = {.sema=sema,.a=a,.source=s,.errors=errors,.first=fn->local_start,.count=fn->local_count};
  l.locals = calloc(l.count,sizeof(*l.locals));
  if(!l.locals) {
    a->allocation_failed = true;
    return;
  }
  life_block(&l,fn->body_start,fn->body_count,0);
  free(l.locals);free(l.fields);
}
#endif
