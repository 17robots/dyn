/* Preserve private constants needed by exported layouts without exporting
 * unrelated implementation constants. Names borrow the loaded source texts. */
typedef struct {
  const char *name;
  size_t length;
  const DynSource *source;
  TSNode initializer;
#ifdef DYN_EXPERIMENT_COMPACT_SOURCES
  const ExpSnapshotTree *compact;
  uint32_t compact_initializer;
#endif
  bool needed, scanned;
} InterfaceConstant;

static bool interface_constant_named(const InterfaceConstant *constant,
                                     TSNode name, const DynSource *source) {
  size_t length = ts_node_end_byte(name) - ts_node_start_byte(name);
  return length == constant->length &&
      !memcmp(source->text + ts_node_start_byte(name), constant->name, length);
}

static void interface_constant_refs(TSNode root, const DynSource *source,
                                    InterfaceConstant *constants, size_t count,
                                    bool types_only) {
  TSTreeCursor cursor = ts_tree_cursor_new(root);
  bool done = false;
  while (!done) {
    TSNode node = ts_tree_cursor_current_node(&cursor);
    const char *kind = ts_node_type(node);
    if (types_only && !strcmp(kind, "array_type")) {
      TSNode length = ts_node_child_by_field_name(node, "length", 6);
      if (!ts_node_is_null(length))
        interface_constant_refs(length, source, constants, count, false);
    } else if (!types_only && !strcmp(kind, "identifier")) {
      for (size_t i = 0; i < count; ++i)
        if (interface_constant_named(&constants[i], node, source)) constants[i].needed = true;
    }
    if ((!types_only || strcmp(kind, "block")) && ts_tree_cursor_goto_first_child(&cursor)) continue;
    while (!ts_tree_cursor_goto_next_sibling(&cursor))
      if (!ts_tree_cursor_goto_parent(&cursor)) { done = true; break; }
  }
  ts_tree_cursor_delete(&cursor);
}

#ifdef DYN_EXPERIMENT_COMPACT_SOURCES
static bool interface_compact_named(const InterfaceConstant *constant, const ExpSnapshotTree *tree,
                                     uint32_t name, const DynSource *source) {
  return name != UINT32_MAX && tree->nodes[name].end-tree->nodes[name].start == constant->length &&
    !memcmp(source->text+tree->nodes[name].start,constant->name,constant->length);
}
static bool interface_compact_refs(uint32_t root, const ExpSnapshotTree *tree, const DynSource *source,
                                   InterfaceConstant *constants, size_t count, bool types_only) {
  const ExpNode *nodes=tree->nodes;
  uint32_t node=root;
  while(node!=UINT32_MAX) {
    if(!dyn_work_step(&source->context,1)) return false;
    if(types_only && nodes[node].kind==EXP_ARRAY_TYPE) {
      uint32_t length=dyn_compact_field(tree,node,EXP_ROLE_LENGTH);
      if(length!=UINT32_MAX && !interface_compact_refs(length,tree,source,constants,count,false)) return false;
    } else if(!types_only && nodes[node].kind==EXP_NAME) {
      for(size_t i=0;i<count;++i) {
        if(!dyn_work_step(&source->context,1)) return false;
        if(interface_compact_named(&constants[i],tree,node,source)) constants[i].needed=true;
      }
    }
    if((!types_only || nodes[node].kind!=SRC_BLOCK) && nodes[node].first!=UINT32_MAX) {
      node=nodes[node].first; continue;
    }
    while(node!=root && nodes[node].next==UINT32_MAX) node=nodes[node].parent;
    if(node==root) break;
    node=nodes[node].next;
  }
  return true;
}
static bool interface_compact_constants(const DynSource *source,const ExpSnapshotTree *tree,
                                        InterfaceConstant **constants,size_t *used) {
  const ExpNode *nodes=tree->nodes;
  for(uint32_t wrapper=nodes[tree->root].first;wrapper!=UINT32_MAX;wrapper=nodes[wrapper].next) {
    if(!dyn_work_step(&source->context,1)) return false;
    if(nodes[wrapper].kind!=SRC_DECLARATION) continue;
    uint32_t node=nodes[wrapper].first;
    if(node==UINT32_MAX || nodes[node].kind!=SRC_CONST) continue;
    uint32_t name=dyn_compact_name(tree,wrapper),value=nodes[node].first;
    if(name==UINT32_MAX || value==UINT32_MAX) continue;
    uint32_t initializer=nodes[value].first;
    while(initializer!=UINT32_MAX && nodes[initializer].next!=UINT32_MAX) initializer=nodes[initializer].next;
    InterfaceConstant *grown=realloc(*constants,(*used+1)*sizeof(*grown));
    if(!grown) return false;
    *constants=grown;
    grown[(*used)++]=(InterfaceConstant){.name=source->text+nodes[name].start,
      .length=nodes[name].end-nodes[name].start,.source=source,.compact=tree,
      .compact_initializer=initializer,.needed=(nodes[wrapper].flags&EXP_PUBLIC)!=0};
  }
  return true;
}
static bool interface_compact_layout_refs(const DynSource *source,const ExpSnapshotTree *tree,
                                          InterfaceConstant *constants,size_t count) {
  const ExpNode *nodes=tree->nodes;
  for(uint32_t wrapper=nodes[tree->root].first;wrapper!=UINT32_MAX;wrapper=nodes[wrapper].next) {
    if(!dyn_work_step(&source->context,1)) return false;
    if(nodes[wrapper].kind!=SRC_DECLARATION) continue;
    uint32_t node=nodes[wrapper].first;
    if(node==UINT32_MAX) continue;
    unsigned kind=nodes[node].kind;
    if((nodes[wrapper].flags&EXP_PUBLIC) || kind==SRC_STRUCT || kind==SRC_ENUM || kind==SRC_ALIAS)
      if(!interface_compact_refs(node,tree,source,constants,count,true)) return false;
  }
  return true;
}
#endif

static bool interface_constants(const DynSources *sources,
                                InterfaceConstant **result, size_t *count) {
  TSTree **trees = calloc(sources->count, sizeof(*trees));
  if (!trees && sources->count) return false;
  InterfaceConstant *constants = NULL;
  size_t used = 0;
  bool ok = false;
  for (size_t si = 0; si < sources->count; ++si) {
    const DynSource *source = &sources->items[si];
    if (dyn_source_target_enabled(source) == 0) continue;
#ifdef DYN_EXPERIMENT_COMPACT_SOURCES
    const ExpSnapshotTree *compact=dyn_compact_tree(source);
    if(compact) {
      if(!interface_compact_constants(source,compact,&constants,&used)) goto cleanup;
      continue;
    }
#endif
    trees[si] = dyn_source_tree(source);
    if (!trees[si] || ts_node_has_error(ts_tree_root_node(trees[si]))) goto cleanup;
    TSNode root = ts_tree_root_node(trees[si]);
    for (uint32_t i = 0; i < ts_node_named_child_count(root); ++i) {
      DynDeclaration declaration;
      if (!dyn_syntax_declaration(ts_node_named_child(root, i), &declaration) ||
          declaration.kind != DYN_DECL_CONSTANT) continue;
      InterfaceConstant *grown = realloc(constants, (used + 1) * sizeof(*grown));
      if (!grown) goto cleanup;
      constants = grown;
      constants[used++] = (InterfaceConstant){
          .name = source->text + ts_node_start_byte(declaration.name),
          .length = ts_node_end_byte(declaration.name) - ts_node_start_byte(declaration.name),
          .source = source,
          .initializer = dyn_syntax_last_child(dyn_syntax_child(declaration.node, 0)),
          .needed = declaration.is_public};
    }
  }
  for (size_t si = 0; si < sources->count; ++si) {
#ifdef DYN_EXPERIMENT_COMPACT_SOURCES
    const DynSource *source=&sources->items[si];
    if(dyn_source_target_enabled(source)==0) continue;
    const ExpSnapshotTree *compact=dyn_compact_tree(source);
    if(compact) {
      if(!interface_compact_layout_refs(source,compact,constants,used)) goto cleanup;
      continue;
    }
#endif
    if (!trees[si]) continue;
    TSNode root = ts_tree_root_node(trees[si]);
    for (uint32_t i = 0; i < ts_node_named_child_count(root); ++i) {
      DynDeclaration declaration;
      if (!dyn_syntax_declaration(ts_node_named_child(root, i), &declaration)) continue;
      if (declaration.is_public || declaration.kind == DYN_DECL_STRUCT ||
          declaration.kind == DYN_DECL_ENUM || declaration.kind == DYN_DECL_ALIAS)
        interface_constant_refs(declaration.node, &sources->items[si], constants, used, true);
    }
  }
  bool progress = true;
  while (progress) {
    progress = false;
    for (size_t i = 0; i < used; ++i) {
      if (!constants[i].needed || constants[i].scanned) continue;
      constants[i].scanned = true;
#ifdef DYN_EXPERIMENT_COMPACT_SOURCES
      if(constants[i].compact) {
        if(!interface_compact_refs(constants[i].compact_initializer,constants[i].compact,
                                  constants[i].source,constants,used,false)) goto cleanup;
      } else
#endif
        interface_constant_refs(constants[i].initializer, constants[i].source, constants, used, false);
      progress = true;
    }
  }
  *result = constants; *count = used; ok = true;
cleanup:
  for (size_t i = 0; i < sources->count; ++i) if (trees[i]) ts_tree_delete(trees[i]);
  free(trees);
  if (!ok) free(constants);
  return ok;
}

static bool interface_constant_needed(InterfaceConstant *constants, size_t count,
                                      TSNode declaration, const DynSource *source) {
  DynDeclaration parsed;
  if (!dyn_syntax_declaration(declaration, &parsed)) return false;
  for (size_t i = 0; i < count; ++i)
    if (constants[i].needed && interface_constant_named(&constants[i], parsed.name, source)) return true;
  return false;
}
