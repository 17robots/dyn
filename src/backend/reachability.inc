#include "../ir_reachability.inc"

static bool reachable_functions(BackendContext *ctx, const DynSource *source, const DynIrProgram *ir) {
  Reachability p = {.ir = ir, .live = ctx->function_live};
  p.expressions = calloc(ir->expression_count ? ir->expression_count : 1, 1);
  p.statements = calloc(ir->statement_count ? ir->statement_count : 1, 1);
  p.queue = calloc(ir->function_count ? ir->function_count : 1, sizeof(*p.queue));
  bool ok = reachable_collect(&p, !ir->live.functions, source->context.runtime_support);
  if (ok && source->context.optimization && source->context.optimization->remarks) {
    size_t removed = 0;
    for (size_t i = 0; i < ir->function_count; ++i) removed += !ir->functions[i].generic && !p.live[i];
    fprintf(stderr, "remark: removed %zu unreachable functions\n", removed);
  }
  free(p.expressions); free(p.statements); free(p.queue);
  return ok;
}
