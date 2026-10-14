#define _POSIX_C_SOURCE 200809L
#include "../../src/module.c"
#include <assert.h>
typedef struct { char text[65536]; size_t length; } Diagnostics;
static void diagnostic(const char *severity,const char *path,unsigned line,unsigned column,
                       unsigned end_line,unsigned end_column,const char *message,void *data) {
  Diagnostics *d=data;
  int n=snprintf(d->text+d->length,sizeof(d->text)-d->length,"%s|%s|%u:%u-%u:%u|%s\n",
                 severity,path,line,column,end_line,end_column,message);
  assert(n>=0 && (size_t)n<sizeof(d->text)-d->length); d->length+=(size_t)n;
}
static void compare(Resolver *resolver, const char *text) {
  Diagnostics expected={0}, actual={0};
  DynSource source={.path=strdup("refs.dyn"),.text=strdup(text),.length=strlen(text),
    .context={.diagnostic=diagnostic,.diagnostic_data=&expected}};
  if (!dyn_source_prepare(&source) || !source.compact) { fprintf(stderr,"invalid fixture: %s\n",text); abort(); }
  TSNode root=ts_tree_root_node(source.syntax);
  assert(!ts_node_has_error(root));
  DynScopeIndex scopes={0};
  assert(dyn_scope_build(&scopes,root,&source));
  char *aliases[]={"mod"}, *targets[]={"/dependency"};
  int old=validate_refs(resolver,root,&source,"/root",aliases,targets,1,&scopes);
  source.context.diagnostic_data=&actual;
  int current=validate_source_refs(resolver,(TSNode){0},&source,"/root",aliases,targets,1,&scopes);
  if(old!=current || strcmp(expected.text,actual.text)) {
    fprintf(stderr,"SOURCE %s\nOLD %sNEW %s",text,expected.text,actual.text); abort();
  }
  dyn_scope_free(&scopes); dyn_source_free(&source);
}
int main(int argc, char **argv) {
  InterfaceDecl declarations[]={{.name="Record",.is_public=true},{.name="call",.is_public=true},
                               {.name="hidden",.is_public=false}};
  ModuleInterface interface={.directory="/dependency",.decls=declarations,.decl_count=3};
  Resolver resolver={.interfaces=&interface,.interface_count=1}; assert(index_interfaces(&resolver));
  const char *expressions[]={"mod.call()","mod.hidden()","call()","(call)()","(mod.call)()",
    "mod.Record{}","Record{}","wrong.Record{}","#sizeof(Record)","#sizeof(mod.Record)",
    "#alignof(mod.hidden)","#typeof(mod.hidden)","mod.hidden.x","(mod).hidden", "(&mod).hidden",
    "mod.call(mod.hidden())","[mod.hidden,call()]","#cast(mod.Record) 0",
    "#sizeof(*mod.hidden)","#typeof(mod.Record.x)","#cast(*fn(mod.hidden) Record) nil"};
  const char *prefixes[]={"", "mod:=1 ", "Record:=1 ", "call:=1 ", "const mod:=1 ",
    "for mod in 0..1 {", "if true {mod:=1 ", "case 1 {_ mod=>{"};
  const char *suffixes[]={"", "", "", "", "", "}","}","}}"};
  unsigned cases=0;
  for(size_t i=0;i<sizeof(expressions)/sizeof(*expressions);++i)
    for(size_t j=0;j<sizeof(prefixes)/sizeof(*prefixes);++j) {
      char text[2048];
      snprintf(text,sizeof(text),"fn main(){%s _ = %s %s}",prefixes[j],expressions[i],suffixes[j]);
      compare(&resolver,text); ++cases;
    }
  compare(&resolver,"fn f(x:mod.hidden) Record {a:Record b:mod.hidden return mod.Record{}} ");
  compare(&resolver,"fn f(mod,call:Record) {call() _=mod.hidden} ");
  for (int i=1;i<argc;++i) {
    FILE *file=fopen(argv[i],"rb"); assert(file);
    assert(!fseek(file,0,SEEK_END)); long size=ftell(file); assert(size>=0);
    rewind(file); char *text=calloc((size_t)size+1,1); assert(text);
    assert(fread(text,1,(size_t)size,file)==(size_t)size); fclose(file);
    compare(&resolver,text); free(text); ++cases;
  }
  free(resolver.interface_buckets);
  printf("PASS %u compact reference diagnostic comparisons\n",cases+2);
}
