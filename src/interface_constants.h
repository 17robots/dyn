/* Preserve private constants needed by exported layouts without exporting
 * unrelated implementation constants. Names borrow the loaded source texts. */
typedef struct {
  const char *name;
  size_t length;
  const DynSource *source;
  const ExpSnapshotTree *compact;
  uint32_t compact_initializer;
  bool needed, scanned;
} InterfaceConstant;



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

static bool interface_constants(const DynSources *sources,
                                InterfaceConstant **result, size_t *count) {
  InterfaceConstant *constants = NULL;
  size_t used = 0;
  for (size_t si = 0; si < sources->count; ++si) {
    const DynSource *source = &sources->items[si];
    if (dyn_source_target_enabled(source) == 0) continue;
    const ExpSnapshotTree *compact = dyn_compact_tree(source);
    if (!compact || !interface_compact_constants(source, compact, &constants, &used)) goto fail;
  }
  for (size_t si = 0; si < sources->count; ++si) {
    const DynSource *source = &sources->items[si];
    if (dyn_source_target_enabled(source) == 0) continue;
    if (!interface_compact_layout_refs(source, dyn_compact_tree(source), constants, used)) goto fail;
  }
  bool progress = true;
  while (progress) {
    progress = false;
    for (size_t i = 0; i < used; ++i) {
      if (!constants[i].needed || constants[i].scanned) continue;
      constants[i].scanned = true;
      if (!interface_compact_refs(constants[i].compact_initializer, constants[i].compact,
                                  constants[i].source, constants, used, false)) goto fail;
      progress = true;
    }
  }
  *result = constants; *count = used;
  return true;
fail:
  free(constants);
  return false;
}
