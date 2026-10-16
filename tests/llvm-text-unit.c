/* Exercise every writer allocation boundary, including nested formatting.
 * Run under ASan/LSan to prove context cleanup after non-local OOM recovery. */
#include <assert.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
static size_t attempt, fail_at;
static void *test_malloc(size_t n) {
  if (++attempt == fail_at)
    return NULL;
  return malloc(n);
}
static void *test_calloc(size_t n, size_t size) {
  if (++attempt == fail_at)
    return NULL;
  return calloc(n, size);
}
static void *test_realloc(void *p, size_t n) {
  if (++attempt == fail_at)
    return NULL;
  return realloc(p, n);
}
#define malloc test_malloc
#define calloc test_calloc
#define realloc test_realloc
#include "../src/llvm_text.c"
#undef malloc
#undef calloc
#undef realloc

static size_t exercise(size_t failure) {
  attempt = 0;
  fail_at = failure;
  LLVMContextRef c = LLVMContextCreate();
  if (!c)
    return attempt;
  if (setjmp(*dyn_text_jump(c))) {
    LLVMContextDispose(c);
    return attempt;
  }
  LLVMModuleRef m = LLVMModuleCreateWithNameInContext("test", c);
  LLVMTypeRef i32 = LLVMInt32TypeInContext(c);
  LLVMTypeRef ft = LLVMFunctionType(i32, NULL, 0, 0);
  LLVMValueRef f = LLVMAddFunction(m, "function with escaped \"name", ft);
  LLVMBasicBlockRef entry = LLVMAppendBasicBlockInContext(c, f, "entry");
  LLVMBuilderRef b = LLVMCreateBuilderInContext(c);
  LLVMPositionBuilderAtEnd(b, entry);
  LLVMValueRef a = LLVMBuildAlloca(b, i32, "local");
  LLVMBuildStore(b, LLVMConstInt(i32, 42, 0), a);
  LLVMBuildRet(b, LLVMBuildLoad2(b, i32, a, "value"));
  char *error = NULL;
  if (!dyn_text_verify(m, &error)) {
    char *text = LLVMPrintModuleToString(m);
    if (text) {
      assert(!failure || attempt < failure);
      assert(strstr(text, "ret i32"));
      free(text);
    }
  }
  free(error);
  LLVMContextDispose(c);
  return attempt;
}
int main(void) {
  size_t count = exercise(0);
  assert(count > 30);
  for (size_t i = 1; i <= count; ++i)
    exercise(i);
  fail_at = 0;
  LLVMContextRef c = LLVMContextCreate();
  assert(c);
  if (setjmp(*dyn_text_jump(c)))
    abort();
  LLVMModuleRef m = LLVMModuleCreateWithNameInContext("invalid", c);
  LLVMTypeRef ft = LLVMFunctionType(LLVMVoidTypeInContext(c), NULL, 0, 0);
  LLVMValueRef f = LLVMAddFunction(m, "missing_terminator", ft);
  LLVMAppendBasicBlockInContext(c, f, "entry");
  char *error = NULL;
  assert(dyn_text_verify(m, &error));
  assert(error && strstr(error, "unterminated"));
  free(error);
  LLVMContextDispose(c);
  printf("PASS independent LLVM writer: %zu allocation failures and malformed "
         "CFG\n",
         count);
}
