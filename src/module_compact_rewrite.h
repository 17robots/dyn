#ifndef DYN_MODULE_COMPACT_REWRITE_H
#define DYN_MODULE_COMPACT_REWRITE_H
#include "dyn_location.h"
#include "dyn_name_text.h"
/* Edit selection is independent of parser-owned nodes. Points refer to current
   generated text, never the original-source diagnostic mapping. */
static char *compact_rewrite_text(DynNameText *t, const DynSource *source, const ExpSnapshotTree *tree, uint32_t id) {
  t->text = NULL;
  if (id == UINT32_MAX) return NULL;
  const ExpNode *node=&tree->nodes[id];
  return dyn_name_text(t, source->text+node->start, node->end-node->start);
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
static bool compact_rewrite_edit(Edits *edits,uint32_t start,uint32_t end,char *replacement) {
  return append_edit(edits,(Edit){start,end,replacement});
}
static bool compact_rewrite_name(Edits *edits,const DynSource *source,const ExpSnapshotTree *tree,
                                 uint32_t name,Module *module) {
  DynNameText text_buffer;
  char *text=compact_rewrite_text(&text_buffer,source,tree,name);
  if(!text) return false;
  char *replacement=symbol(edits,module,text); dyn_name_text_free(&text_buffer);
  return compact_rewrite_edit(edits,tree->nodes[name].start,tree->nodes[name].end,replacement);
}
/* The replacement for module.member: member qualified by target. */
static char *compact_rewrite_member(Edits *edits,const DynSource *source,const ExpSnapshotTree *tree,
                                    uint32_t member_id,const Module *target) {
  DynNameText member_buffer;
  char *member=compact_rewrite_text(&member_buffer,source,tree,member_id);
  char *replacement=member ? symbol(edits,target,member) : NULL;
  dyn_name_text_free(&member_buffer);
  return replacement;
}
static bool compact_rewrite_one(uint32_t id,const DynSource *source,const ExpSnapshotTree *tree,
                                Module *current,Module *modules,size_t module_count,Edits *edits,
                                const DynScopeIndex *locals,bool *skip) {
  const ExpNode *nodes=tree->nodes,*node=&nodes[id];
  uint32_t first=node->first;
  unsigned kind=node->kind;
  *skip=false;
  if(kind==SRC_FN || kind==SRC_EXTERN_FN || kind==SRC_STRUCT || kind==SRC_ENUM || kind==SRC_ALIAS) {
    uint32_t name=first;
    while(name!=UINT32_MAX && nodes[name].kind!=EXP_NAME) name=nodes[name].next;
    if(!current->root && name!=UINT32_MAX &&
       !compact_rewrite_name(edits,source,tree,name,current)) return false;
  }
  bool top=node->parent!=UINT32_MAX && nodes[node->parent].kind==SRC_DECLARATION;
  if(top && !current->root && (kind==SRC_VARIABLE || kind==SRC_CONST || kind==SRC_EXTERN_VARIABLE)) {
    uint32_t name=kind==SRC_CONST && first!=UINT32_MAX ? nodes[first].first : first;
    if(name!=UINT32_MAX && !compact_rewrite_name(edits,source,tree,name,current)) return false;
  }
  if(kind==EXP_FIELD_TYPE) {
    DynNameText name_buffer;
    char *name=compact_rewrite_text(&name_buffer,source,tree,first);
    if(first!=UINT32_MAX && !name) return false;
    if(name && compact_rewrite_value_type(tree,id) && dyn_scope_local_at(locals,node->start,name)) {
      dyn_name_text_free(&name_buffer); *skip=true; return true;
    }
    uint32_t second=first==UINT32_MAX ? UINT32_MAX : nodes[first].next;
    Module *target=second!=UINT32_MAX ? target_module(modules,module_count,current,name) : NULL;
    if(target) {
      dyn_name_text_free(&name_buffer); *skip=true;
      return compact_rewrite_edit(edits,node->start,node->end,compact_rewrite_member(edits,source,tree,second,target));
    }
    if(second==UINT32_MAX && name && has_decl(current,name)) {
      char *replacement=symbol(edits,current,name); dyn_name_text_free(&name_buffer); *skip=true;
      return compact_rewrite_edit(edits,node->start,node->end,replacement);
    }
    dyn_name_text_free(&name_buffer);
  }
  if(kind==EXP_STRUCT && first!=UINT32_MAX && nodes[first].kind==EXP_NAME) {
    uint32_t second=nodes[first].next;
    DynNameText name_buffer;
    char *name=compact_rewrite_text(&name_buffer,source,tree,first); if(!name) return false;
    if(second!=UINT32_MAX && nodes[second].kind==EXP_NAME) {
      Module *target=target_module(modules,module_count,current,name);
      if(target) {
        dyn_name_text_free(&name_buffer);
        return compact_rewrite_edit(edits,nodes[first].start,nodes[second].end,compact_rewrite_member(edits,source,tree,second,target));
      }
    } else if(has_decl(current,name)) {
      dyn_name_text_free(&name_buffer);
      return compact_rewrite_name(edits,source,tree,first,current);
    }
    dyn_name_text_free(&name_buffer);
  }
  if(kind==EXP_FIELD || kind==EXP_CALL) {
    uint32_t base=compact_rewrite_unwrap(tree,first);
    if(base!=UINT32_MAX && nodes[base].kind==EXP_NAME) {
      DynNameText name_buffer;
      char *name=compact_rewrite_text(&name_buffer,source,tree,base); if(!name) return false;
      bool local=dyn_scope_local_at(locals,kind==EXP_CALL ? node->start : nodes[base].start,name);
      Module *target=kind==EXP_FIELD ? target_module(modules,module_count,current,name) : NULL;
      if(target && !local) {
        dyn_name_text_free(&name_buffer); *skip=true;
        return compact_rewrite_edit(edits,node->start,node->end,compact_rewrite_member(edits,source,tree,nodes[first].next,target));
      }
      bool declared=has_decl(current,name); dyn_name_text_free(&name_buffer);
      if(declared && !local && !compact_rewrite_name(edits,source,tree,base,current)) return false;
    }
  }
  if(kind==EXP_NAME && (node->flags & EXP_PRIMARY)) {
    DynNameText name_buffer;
    char *name=compact_rewrite_text(&name_buffer,source,tree,id); if(!name) return false;
    bool rewrite=has_decl(current,name) && !dyn_scope_local_at(locals,node->start,name); dyn_name_text_free(&name_buffer);
    if(rewrite && !compact_rewrite_name(edits,source,tree,id,current)) return false;
  }
  return true;
}
static bool compact_rewrite_nodes(const DynSource *source,const ExpSnapshotTree *tree,
                                  Module *current,Module *modules,size_t module_count,
                                  Edits *edits,const DynScopeIndex *locals) {
  bool ok=true;
  uint32_t node=tree->root;
  while(node!=UINT32_MAX) {
    bool skip;
    if(!dyn_work_step(&source->context,1) ||
       !compact_rewrite_one(node,source,tree,current,modules,module_count,edits,locals,&skip)) {
      ok=false; break;
    }
    if(!skip && tree->nodes[node].first!=UINT32_MAX) { node=tree->nodes[node].first; continue; }
    while(node!=UINT32_MAX && tree->nodes[node].next==UINT32_MAX) node=tree->nodes[node].parent;
    if(node!=UINT32_MAX) node=tree->nodes[node].next;
  }
  return ok;
}
#endif
