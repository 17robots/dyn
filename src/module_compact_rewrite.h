#ifndef DYN_MODULE_COMPACT_REWRITE_H
#define DYN_MODULE_COMPACT_REWRITE_H
#ifdef DYN_EXPERIMENT_COMPACT_SOURCES
#include "dyn_location.h"
/* Edit selection is independent of parser-owned nodes. Points refer to current
   generated text, never the original-source diagnostic mapping. */
static char *compact_rewrite_text(const DynSource *source, const ExpSnapshotTree *tree, uint32_t id) {
  if (id == UINT32_MAX) return NULL;
  const ExpNode *node=&tree->nodes[id];
  size_t length=node->end-node->start;
  char *text=malloc(length+1);
  if (text) { memcpy(text,source->text+node->start,length); text[length]=0; }
  return text;
}
static uint32_t compact_rewrite_unwrap(const ExpSnapshotTree *tree,uint32_t node) {
  while(node!=UINT32_MAX && tree->nodes[node].first!=UINT32_MAX &&
        tree->nodes[tree->nodes[node].first].next==UINT32_MAX) node=tree->nodes[node].first;
  return node;
}
static bool compact_rewrite_value_type(const ExpSnapshotTree *tree,uint32_t id) {
  uint32_t parent=tree->nodes[id].parent;
  while(parent!=UINT32_MAX && tree->nodes[parent].kind==EXP_TYPE) parent=tree->nodes[parent].parent;
  return parent!=UINT32_MAX && (tree->nodes[parent].kind==EXP_TYPEOF ||
    tree->nodes[parent].kind==EXP_SIZE || tree->nodes[parent].kind==EXP_ALIGN);
}
static bool compact_rewrite_edit(Edits *edits,const DynLocationIndex *lines,const DynSource *coordinates,
                                 uint32_t start,uint32_t end,char *replacement) {
  unsigned line,column; const char *path;
  dyn_location_get(lines,coordinates,start,&path,&line,&column);
  TSPoint a={line-1,column-1};
  dyn_location_get(lines,coordinates,end,&path,&line,&column);
  TSPoint b={line-1,column-1};
  return append_edit(edits,(Edit){start,end,replacement,a,b});
}
static bool compact_rewrite_name(Edits *edits,const DynSource *source,const ExpSnapshotTree *tree,
                                 uint32_t name,Module *module,const DynLocationIndex *lines,
                                 const DynSource *coordinates) {
  char *text=compact_rewrite_text(source,tree,name);
  if(!text) return false;
  char *replacement=symbol(module,text); free(text);
  return compact_rewrite_edit(edits,lines,coordinates,tree->nodes[name].start,tree->nodes[name].end,replacement);
}
static bool compact_rewrite_one(uint32_t id,const DynSource *source,const ExpSnapshotTree *tree,
                                Module *current,Module *modules,size_t module_count,Edits *edits,
                                const DynScopeIndex *locals,const DynLocationIndex *lines,
                                const DynSource *coordinates,bool *skip) {
  const ExpNode *nodes=tree->nodes,*node=&nodes[id];
  uint32_t first=node->first;
  unsigned kind=node->kind;
  *skip=false;
  if(kind==SRC_FN || kind==SRC_EXTERN_FN || kind==SRC_STRUCT || kind==SRC_ENUM || kind==SRC_ALIAS) {
    uint32_t name=first;
    while(name!=UINT32_MAX && nodes[name].kind!=EXP_NAME) name=nodes[name].next;
    if(!current->root && name!=UINT32_MAX &&
       !compact_rewrite_name(edits,source,tree,name,current,lines,coordinates)) return false;
  }
  bool top=node->parent!=UINT32_MAX && nodes[node->parent].kind==SRC_DECLARATION;
  if(top && !current->root && (kind==SRC_VARIABLE || kind==SRC_CONST || kind==SRC_EXTERN_VARIABLE)) {
    uint32_t name=kind==SRC_CONST && first!=UINT32_MAX ? nodes[first].first : first;
    if(name!=UINT32_MAX && !compact_rewrite_name(edits,source,tree,name,current,lines,coordinates)) return false;
  }
  if(kind==EXP_FIELD_TYPE) {
    char *name=compact_rewrite_text(source,tree,first);
    if(first!=UINT32_MAX && !name) return false;
    if(name && compact_rewrite_value_type(tree,id) && dyn_scope_local_at(locals,node->start,name)) {
      free(name); *skip=true; return true;
    }
    uint32_t second=first==UINT32_MAX ? UINT32_MAX : nodes[first].next;
    Module *target=second!=UINT32_MAX ? target_module(modules,module_count,current,name) : NULL;
    if(target) {
      char *member=compact_rewrite_text(source,tree,second), *replacement=member ? symbol(target,member) : NULL;
      free(member); free(name); *skip=true;
      return compact_rewrite_edit(edits,lines,coordinates,node->start,node->end,replacement);
    }
    if(second==UINT32_MAX && name && has_decl(current,name)) {
      char *replacement=symbol(current,name); free(name); *skip=true;
      return compact_rewrite_edit(edits,lines,coordinates,node->start,node->end,replacement);
    }
    free(name);
  }
  if(kind==EXP_STRUCT && first!=UINT32_MAX && nodes[first].kind==EXP_NAME) {
    uint32_t second=nodes[first].next;
    char *name=compact_rewrite_text(source,tree,first); if(!name) return false;
    if(second!=UINT32_MAX && nodes[second].kind==EXP_NAME) {
      Module *target=target_module(modules,module_count,current,name);
      if(target) {
        char *member=compact_rewrite_text(source,tree,second), *replacement=member ? symbol(target,member) : NULL;
        free(member); free(name);
        return compact_rewrite_edit(edits,lines,coordinates,nodes[first].start,nodes[second].end,replacement);
      }
    } else if(has_decl(current,name)) {
      free(name);
      return compact_rewrite_name(edits,source,tree,first,current,lines,coordinates);
    }
    free(name);
  }
  if(kind==EXP_FIELD || kind==EXP_CALL) {
    uint32_t base=compact_rewrite_unwrap(tree,first);
    if(base!=UINT32_MAX && nodes[base].kind==EXP_NAME) {
      char *name=compact_rewrite_text(source,tree,base); if(!name) return false;
      bool local=dyn_scope_local_at(locals,kind==EXP_CALL ? node->start : nodes[base].start,name);
      Module *target=kind==EXP_FIELD ? target_module(modules,module_count,current,name) : NULL;
      if(target && !local) {
        uint32_t member_id=nodes[first].next;
        char *member=compact_rewrite_text(source,tree,member_id), *replacement=member ? symbol(target,member) : NULL;
        free(member); free(name); *skip=true;
        return compact_rewrite_edit(edits,lines,coordinates,node->start,node->end,replacement);
      }
      bool declared=has_decl(current,name); free(name);
      if(declared && !local && !compact_rewrite_name(edits,source,tree,base,current,lines,coordinates)) return false;
    }
  }
  if(kind==EXP_NAME && (node->flags & EXP_PRIMARY)) {
    char *name=compact_rewrite_text(source,tree,id); if(!name) return false;
    bool rewrite=has_decl(current,name) && !dyn_scope_local_at(locals,node->start,name); free(name);
    if(rewrite && !compact_rewrite_name(edits,source,tree,id,current,lines,coordinates)) return false;
  }
  return true;
}
static bool compact_rewrite_nodes(const DynSource *source,const ExpSnapshotTree *tree,
                                  Module *current,Module *modules,size_t module_count,
                                  Edits *edits,const DynScopeIndex *locals) {
  DynSource coordinates={.path=source->path,.text=source->text,.length=source->length};
  DynLocationIndex lines={0};
  if(!dyn_work_step(&source->context,source->length) || !dyn_location_build(&lines,&coordinates)) return false;
  bool ok=true;
  uint32_t node=tree->root;
  while(node!=UINT32_MAX) {
    bool skip;
    if(!dyn_work_step(&source->context,1) ||
       !compact_rewrite_one(node,source,tree,current,modules,module_count,edits,locals,&lines,&coordinates,&skip)) {
      ok=false; break;
    }
    if(!skip && tree->nodes[node].first!=UINT32_MAX) { node=tree->nodes[node].first; continue; }
    while(node!=UINT32_MAX && tree->nodes[node].next==UINT32_MAX) node=tree->nodes[node].parent;
    if(node!=UINT32_MAX) node=tree->nodes[node].next;
  }
  dyn_location_free(&lines); return ok;
}
#endif
#endif
