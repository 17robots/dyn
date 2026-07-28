#include <stdio.h>

// process folder
// if in cache (or cache file exists), grab and go, if not then
// grab files
// lex/parse files
// typecheck
// store in module cache
// call process module on main
// create config options to use for how theyre compiled
// once all is typechecked and gathered, then
// convert to ir
// optimize with given passes
// convert to asm with given arch settings
// create binary with given name if supplied one
int main(int argc, char** argv) {
  for(int i = 0; i < argc; i++) {
    printf("%s\n", argv[i]);
  }
  return 0;
}
