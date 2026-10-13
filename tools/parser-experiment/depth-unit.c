#define _POSIX_C_SOURCE 200809L
#include "depth.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <tree_sitter/api.h>
extern const TSLanguage *tree_sitter_dyn(void);
static unsigned checked, fallback;
static unsigned raw_depth(TSNode root) {
  TSTreeCursor cursor=ts_tree_cursor_new(root);
  unsigned depth=0,maximum=0;
  for (;;) {
    if (ts_tree_cursor_goto_first_child(&cursor)) {
      if (++depth>maximum) maximum=depth;
      continue;
    }
    while (!ts_tree_cursor_goto_next_sibling(&cursor)) {
      if (!ts_tree_cursor_goto_parent(&cursor)) { ts_tree_cursor_delete(&cursor); return maximum; }
      --depth;
    }
  }
}
static void check(const char *text,size_t length) {
  TSParser *parser=ts_parser_new(); assert(parser && ts_parser_set_language(parser,tree_sitter_dyn()));
  TSTree *tree=ts_parser_parse_string(parser,NULL,text,(uint32_t)length); assert(tree);
  TSNode root=ts_tree_root_node(tree);
  ExpSnapshotError error;
  ExpSnapshot *snapshot=exp_snapshot_create(text,length,NULL,&error);
  if (!snapshot) {
    assert(ts_node_has_error(root) || error.kind==EXP_LIMIT_ERROR);
    ++fallback;
  } else {
    if (ts_node_has_error(root)) { fprintf(stderr,"compact accepted invalid source: %.*s\n",(int)length,text); abort(); }
    const ExpSnapshotTree *compact=exp_snapshot_tree(snapshot);
    unsigned actual=raw_depth(root),bound=1;
    while (!exp_depth_certified(compact,bound)) { assert(bound<10000); ++bound; }
    assert(actual<=bound);
    assert(!exp_depth_certified(compact,1024) || actual<=1024);
    ++checked;
  }
  exp_snapshot_release(snapshot);ts_tree_delete(tree);ts_parser_delete(parser);
}
int main(int argc,char **argv) {
  unsigned sizes[]={1,10,120,250,300,500,1018,1022,1023,1024,1100};
  char text[40000];
  for(unsigned i=0;i<sizeof(sizes)/sizeof(*sizes);++i) {
    size_t n=sizes[i],at=0;
    at+=(size_t)sprintf(text+at,"const x:=1");
    for(size_t j=0;j<n;++j) at+=(size_t)sprintf(text+at,"+1");
    check(text,at);
    at=(size_t)sprintf(text,"fn f(){_=x");
    for(size_t j=0;j<n;++j) at+=(size_t)sprintf(text+at,".x");
    at+=(size_t)sprintf(text+at,"}");check(text,at);
    at=(size_t)sprintf(text,"const x:=");
    for(size_t j=0;j<n;++j) text[at++]='(';
    text[at++]='1';for(size_t j=0;j<n;++j) text[at++]=')';check(text,at);
    at=(size_t)sprintf(text,"type T=");
    for(size_t j=0;j<n;++j) text[at++]='*';
    at+=(size_t)sprintf(text+at,"u8");check(text,at);
  }
  const char *trivia[]={"/*root*/", "fn f(){_=x /*last*/}","const s:=\"a\\u{123}\\x41\"", "fn f(){_=a[ /*lo*/ .. /*hi*/ ]}", "fn f(){_=(( /*nested*/ x ))}"};
  for(unsigned i=0;i<sizeof(trivia)/sizeof(*trivia);++i) check(trivia[i],strlen(trivia[i]));
  for(int i=1;i<argc;++i) {
    FILE *f=fopen(argv[i],"rb");assert(f);assert(!fseek(f,0,SEEK_END));long n=ftell(f);assert(n>=0);rewind(f);
    char *data=malloc((size_t)n+1);assert(data && fread(data,1,(size_t)n,f)==(size_t)n);fclose(f);
    check(data,(size_t)n);free(data);
  }
  printf("PASS pinned depth upper bound: %u valid sources, %u syntax/capacity fallbacks\n",checked,fallback);
}
