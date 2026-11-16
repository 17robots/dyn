#ifndef DYN_LIFETIME_H
#define DYN_LIFETIME_H
/* Conservative straight-line provenance of addresses into a function's own
   frame. Branch and loop joins discard facts rather than diagnosing a
   possible path as a proven error. This is not a borrow checker, and it knows
   no library function by name. */
typedef struct { bool stack; uint32_t address; } LifeValue;
typedef struct { uint32_t local, field; LifeValue value; } LifeField;
typedef struct {
  Sema *sema; DynAstProgram *a; const DynSource *source; unsigned *errors;
  uint32_t first, count, params; LifeValue *locals;
  LifeField *fields; size_t field_count, field_capacity;
} Life;
static LifeValue life_join(LifeValue a, LifeValue b) {
  a.stack |= b.stack;
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
static LifeValue life_expr(Life *,DynExprId,unsigned);
static void life_forget(Life *l);
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
  } else if(e->kind==DYN_EXPR_UNARY && e->op==DYN_OP_ADDRESS && a->expressions[e->left].kind==DYN_EXPR_STRUCT) {
    /* &T{...} lives in this function's frame, like a local. */
    v=life_expr(l,e->left,depth+1);v.stack=true;
  } else {
    LifeValue left=life_expr(l,e->left,depth+1), right=life_expr(l,e->right,depth+1);
    bool view=e->kind==DYN_EXPR_SLICE || e->kind==DYN_EXPR_CAST || e->kind==DYN_EXPR_CONVERT || e->kind==DYN_EXPR_BITCAST || e->kind==DYN_EXPR_FIELD || e->kind==DYN_EXPR_INDEX || e->kind==DYN_EXPR_UNARY;
    if(view && life_borrow_type(a,e->type,0)) v=left;
    (void)right;
    if(returns_local_borrow(l->sema,a,id)) v.stack=true;
    for(uint32_t i=0;i<e->item_count;++i) {
      LifeValue item=life_expr(l,a->items[e->item_start+i].expression,depth+1);
      if(e->kind==DYN_EXPR_STRUCT || e->kind==DYN_EXPR_ARRAY || e->kind==DYN_EXPR_ENUM) v=life_join(v,item);
    }
    /* A callee may change any address-exposed local or alias. */
    if(e->kind==DYN_EXPR_CALL) life_forget(l);
  }
  if (!life_borrow_type(a,e->type,0)) { v.stack=false; v.address=0; }
  return v;
}
static void life_forget(Life *l) { memset(l->locals,0,l->count*sizeof(*l->locals)); l->field_count=0; }
/* Whether a pointer comes from outside this call: a parameter, a global, or
   a pointer read through one of them. Pointers made in the function are
   unknown here, so they never count. */
static bool life_outside_pointer(Life *l,DynExprId id,unsigned depth) {
  DynAstProgram *a=l->a;
  if(id==DYN_NO_EXPR || id>=a->expression_count || depth>64) return false;
  DynAstExpr *e=&a->expressions[id];
  if(e->kind==DYN_EXPR_NAME) return e->integer>=l->first && e->integer<(uint64_t)l->first+l->params;
  if(e->kind==DYN_EXPR_GLOBAL) return true;
  if(e->kind==DYN_EXPR_FIELD || e->kind==DYN_EXPR_INDEX || e->kind==DYN_EXPR_CONVERT || e->kind==DYN_EXPR_CAST ||
     (e->kind==DYN_EXPR_UNARY && e->op==DYN_OP_DEREF))
    return life_outside_pointer(l,e->left,depth+1);
  return false;
}
/* Whether a write to target lands where the caller or a global can see it. */
static bool life_target_escapes(Life *l,DynExprId id,unsigned depth) {
  DynAstProgram *a=l->a;
  if(id==DYN_NO_EXPR || id>=a->expression_count || depth>64) return false;
  DynAstExpr *e=&a->expressions[id];
  if(e->kind==DYN_EXPR_GLOBAL) return true;
  if(e->kind==DYN_EXPR_UNARY && e->op==DYN_OP_DEREF) return life_outside_pointer(l,e->left,depth+1);
  if(e->kind==DYN_EXPR_FIELD) {
    if(dyn_type_is_pointer(a->expressions[e->left].type)) return life_outside_pointer(l,e->left,depth+1);
    return life_target_escapes(l,e->left,depth+1);
  }
  if(e->kind==DYN_EXPR_INDEX) {
    if(dyn_type_is_array(a->expressions[e->left].type)) return life_target_escapes(l,e->left,depth+1);
    return life_outside_pointer(l,e->left,depth+1);
  }
  return false;
}
static void life_block(Life *l,uint32_t start,uint32_t count,unsigned depth) {
  if(depth>128) { life_forget(l); return; }
  for(uint32_t i=0;i<count && dyn_work_step(&l->source->context,1);++i) {
    DynAstStmt *st=&l->a->statements[l->a->children[start+i]];
    if(st->kind==DYN_STMT_DEFER) { life_forget(l); continue; }
    LifeValue value=life_expr(l,st->expression,0);
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
      (void)life_expr(l,st->target,0);
      bool direct_field= target->kind == DYN_EXPR_FIELD && !target->boolean && l->a->expressions[target->left].kind == DYN_EXPR_NAME;
      if(direct_field) life_set_field(l,(uint32_t)l->a->expressions[target->left].integer,(uint32_t)target->integer,value);
      else {
        if(value.stack && life_target_escapes(l,st->target,0))
          error_span(st->span,l->source,l->errors,"stores the address of function-local storage where it outlives the function");
        life_forget(l); /* An indirect write may replace tracked provenance. */
      }
    }
  }
}
static void life_check_function(Sema *sema,DynAstProgram *a,const DynSource *s,unsigned *errors,DynAstFn *fn) {
  if(*errors || !fn->local_count) return;
  Life l = {.sema=sema,.a=a,.source=s,.errors=errors,.first=fn->local_start,.count=fn->local_count,.params=fn->param_count};
  l.locals = calloc(l.count,sizeof(*l.locals));
  if(!l.locals) {
    a->allocation_failed = true;
    return;
  }
  life_block(&l,fn->body_start,fn->body_count,0);
  free(l.locals);free(l.fields);
}
#endif
