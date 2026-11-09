#include "../ir_reachability.inc"

static bool reachable_functions(BackendContext *ctx, const DynSource *source, const DynIrProgram *ir) {
  memset(ctx->global_live, 0, sizeof(ctx->global_live));
  Reachability p = {.ir = ir, .live = ctx->function_live, .globals = ctx->global_live};
  p.expressions = calloc(ir->expression_count ? ir->expression_count : 1, 1);
  p.statements = calloc(ir->statement_count ? ir->statement_count : 1, 1);
  p.queue = calloc(ir->function_count ? ir->function_count : 1, sizeof(*p.queue));
  bool ok = reachable_collect(&p, !ir->live.functions, source->context.runtime_support);
  if (ok && source->context.optimization && source->context.optimization->remarks) {
    size_t removed = 0;
    for (size_t i = 0; i < ir->function_count; ++i) removed += !ir->functions[i].generic && !p.live[i];
    size_t globals = 0;
    for (size_t i = 0; i < ir->global_count; ++i) globals += !ctx->global_live[i];
    fprintf(stderr, "remark: removed %zu unreachable functions and %zu unused globals\n", removed, globals);
  }
  free(ctx->expression_live);
  ctx->expression_live = ok ? p.expressions : NULL;
  if (!ok) free(p.expressions);
  free(p.statements); free(p.queue);
  return ok;
}
