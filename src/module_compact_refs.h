#ifndef DYN_MODULE_COMPACT_REFS_H
#define DYN_MODULE_COMPACT_REFS_H
#ifdef DYN_EXPERIMENT_COMPACT_SOURCES
/* Concrete source-reference checks over immutable compact nodes. Module lookup
   and diagnostics share the production policy; recovery keeps its TS walker. */
static uint32_t compact_ref_unwrap(const ExpSnapshotTree *tree, uint32_t node) {
  while (node != UINT32_MAX && tree->nodes[node].first != UINT32_MAX &&
         tree->nodes[tree->nodes[node].first].next == UINT32_MAX)
    node = tree->nodes[node].first;
  return node;
}
static char *compact_ref_text(const DynSource *s, const ExpSnapshotTree *tree, uint32_t id) {
  if (id == UINT32_MAX) return NULL;
  const ExpNode *node = &tree->nodes[id];
  return dyn_import_copy(s->text + node->start, node->end - node->start);
}
static bool compact_ref_value_type(const ExpSnapshotTree *tree, uint32_t id) {
  uint32_t parent = tree->nodes[id].parent;
  while (parent != UINT32_MAX && tree->nodes[parent].kind == EXP_TYPE)
    parent = tree->nodes[parent].parent;
  return parent != UINT32_MAX && (tree->nodes[parent].kind == EXP_TYPEOF ||
    tree->nodes[parent].kind == EXP_SIZE || tree->nodes[parent].kind == EXP_ALIGN);
}
static int validate_compact_ref(Resolver *r, const DynSource *s, const ExpSnapshotTree *tree,
                                uint32_t id, const char *directory, char **aliases,
                                char **targets, size_t count, const DynScopeIndex *locals) {
  const ExpNode *nodes = tree->nodes, *node = &nodes[id];
  uint32_t first = node->first;
  if (first == UINT32_MAX) return 0;
  int errors = 0;
  if (node->kind == EXP_FIELD) {
    if (nodes[first].kind == EXP_FIELD) return 0;
    uint32_t base = compact_ref_unwrap(tree, first);
    if (base == UINT32_MAX || nodes[base].kind != EXP_NAME) return 0;
    char *qualifier = compact_ref_text(s, tree, base),
         *member = compact_ref_text(s, tree, nodes[first].next);
    if (!qualifier || !member) { free(qualifier); free(member); return 1; }
    if (alias_index(aliases, count, qualifier) < count &&
        !dyn_scope_local_at(locals, nodes[base].start, qualifier))
      errors = validate_member_at(r,node->start,node->end,s,aliases,targets,count,qualifier,member);
    free(qualifier); free(member);
  } else if (node->kind == EXP_FIELD_TYPE || node->kind == EXP_STRUCT) {
    uint32_t names = nodes[first].kind == EXP_NAME ? 1 : 0;
    if (names && nodes[first].next != UINT32_MAX && nodes[nodes[first].next].kind == EXP_NAME) names = 2;
    bool value = node->kind == EXP_FIELD_TYPE && compact_ref_value_type(tree,id);
    if (names > 1) {
      char *qualifier=compact_ref_text(s,tree,first), *member=compact_ref_text(s,tree,nodes[first].next);
      if (!qualifier || !member) { free(qualifier); free(member); return 1; }
      if (!(value && dyn_scope_local_at(locals,node->start,qualifier)))
        errors = validate_member_at(r,node->start,node->end,s,aliases,targets,count,qualifier,member);
      free(qualifier); free(member);
    } else if (names == 1) {
      char *name=compact_ref_text(s,tree,first);
      if (!name) return 1;
      bool pub=false;
      if (!decl_named(r,directory,name,&pub) &&
          !(value && dyn_scope_local_at(locals,node->start,name)) && imported_decl(r,targets,count,name)) {
        char message[512];
        snprintf(message,sizeof(message),"imported type '%s' must be module-qualified",name);
        dyn_diagnostic_source("error",s,node->start,node->end,message); ++errors;
      }
      free(name);
    }
  } else if (node->kind == EXP_CALL) {
    uint32_t callee=compact_ref_unwrap(tree,first);
    if (callee==UINT32_MAX || nodes[callee].kind!=EXP_NAME) return 0;
    char *name=compact_ref_text(s,tree,callee);
    if (!name) return 1;
    bool pub=false;
    if (!decl_named(r,directory,name,&pub) &&
        !dyn_scope_local_at(locals,nodes[callee].start,name) && imported_decl(r,targets,count,name)) {
      char message[512];
      snprintf(message,sizeof(message),"imported function '%s' must be module-qualified",name);
      dyn_diagnostic_source("error",s,nodes[callee].start,nodes[callee].end,message); ++errors;
    }
    free(name);
  }
  return errors;
}
static int validate_compact_refs(Resolver *r, const DynSource *s, const ExpSnapshotTree *tree,
                                 const char *directory, char **aliases, char **targets,
                                 size_t count, const DynScopeIndex *locals) {
  int errors=0;
  uint32_t node=tree->root;
  while (node!=UINT32_MAX) {
    if (!dyn_work_step(&s->context,1)) return errors+1;
    errors += validate_compact_ref(r,s,tree,node,directory,aliases,targets,count,locals);
    if (tree->nodes[node].first!=UINT32_MAX) { node=tree->nodes[node].first; continue; }
    while (node!=UINT32_MAX && tree->nodes[node].next==UINT32_MAX) node=tree->nodes[node].parent;
    if (node!=UINT32_MAX) node=tree->nodes[node].next;
  }
  return errors;
}
#endif
#endif
