#ifndef DYN_INTERFACE_COMPACT_H
#define DYN_INTERFACE_COMPACT_H
/* Serialize the same canonical declaration fragments without retaining syntax
   handles. Constant reachability has already been computed across all files. */
static int interface_compact_declarations(const DynSource *source,const ExpSnapshotTree *tree,
                                          InterfaceConstant *constants,size_t constant_count,
                                          char ***decls,size_t *count) {
  const ExpNode *nodes=tree->nodes;
  for(uint32_t wrapper=nodes[tree->root].first;wrapper!=UINT32_MAX;wrapper=nodes[wrapper].next) {
    if(!dyn_work_step(&source->context,1)) return 1;
    if(nodes[wrapper].kind!=SRC_DECLARATION) continue;
    uint32_t node=nodes[wrapper].first;
    if(node==UINT32_MAX) continue;
    unsigned kind=nodes[node].kind;
    bool representation=kind==SRC_STRUCT || kind==SRC_ENUM || kind==SRC_ALIAS;
    if(kind==SRC_CONST) {
      uint32_t name=dyn_compact_name(tree,wrapper);
      for(size_t i=0;i<constant_count;++i) {
        if(!dyn_work_step(&source->context,1)) return 1;
        if(constants[i].needed && interface_compact_named(&constants[i],tree,name,source)) representation=true;
      }
    }
    if(!(nodes[wrapper].flags&EXP_PUBLIC) && !representation) continue;
    uint32_t start=nodes[wrapper].start,end=nodes[wrapper].end;
    char *raw=NULL,*text=NULL;
    size_t length=0;
    if(kind==SRC_FN) {
      for(uint32_t child=nodes[node].first;child!=UINT32_MAX;child=nodes[child].next) {
        if(!dyn_work_step(&source->context,1)) return 1;
        if(nodes[child].kind==SRC_BLOCK) { end=nodes[child].start; break; }
      }
      size_t size=(size_t)(end-start)+4;
      raw=malloc(size);
      if(!raw) return 1;
      int written=snprintf(raw,size,"%.*s{}",(int)(end-start),source->text+start);
      if(written>0) text=canonical(raw,(size_t)written,&length);
    } else if(kind==SRC_VARIABLE) {
      uint32_t name=dyn_compact_name(tree,wrapper),type=nodes[node].first;
      while(type!=UINT32_MAX && nodes[type].kind!=SRC_QUALIFIER && nodes[type].kind!=EXP_TYPE) type=nodes[type].next;
      if(type==UINT32_MAX) return 3;
      if(nodes[type].kind==SRC_QUALIFIER) type=nodes[type].first;
      if(name==UINT32_MAX || type==UINT32_MAX) return 1;
      uint32_t na=nodes[name].start,nb=nodes[name].end,ta=nodes[type].start,tb=nodes[type].end;
      size_t size=(size_t)(nb-na)*2+(tb-ta)+21;
      raw=malloc(size);
      if(!raw) return 1;
      int written=snprintf(raw,size,"pub extern %.*s \"%.*s\":%.*s",
                            (int)(nb-na),source->text+na,(int)(nb-na),source->text+na,
                            (int)(tb-ta),source->text+ta);
      if(written>0) text=canonical(raw,(size_t)written,&length);
    } else text=canonical(source->text+start,end-start,&length);
    free(raw);
    if(!text) return 1;
    char **next=realloc(*decls,(*count+1)*sizeof(*next));
    if(!next) { free(text); return 1; }
    *decls=next;
    next[(*count)++]=text;
  }
  return 0;
}
#endif
