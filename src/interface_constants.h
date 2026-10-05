/* Preserve private constants needed by exported layouts without exporting
 * unrelated implementation constants. Names borrow the loaded source texts. */
typedef struct {
  const char *name;
  size_t length;
  const DynSource *source;
  TSNode initializer;
  bool needed, scanned;
} InterfaceConstant;

static bool interface_constant_named(const InterfaceConstant *constant,
                                     TSNode name, const DynSource *source) {
  size_t length = ts_node_end_byte(name) - ts_node_start_byte(name);
  return length == constant->length &&
      !memcmp(source->text + ts_node_start_byte(name), constant->name, length);
}

static void interface_constant_refs(TSNode root, const DynSource *source,
                                    InterfaceConstant *constants, size_t count,
                                    bool types_only) {
  TSTreeCursor cursor = ts_tree_cursor_new(root);
  bool done = false;
  while (!done) {
    TSNode node = ts_tree_cursor_current_node(&cursor);
    const char *kind = ts_node_type(node);
    if (types_only && !strcmp(kind, "array_type")) {
      TSNode length = ts_node_child_by_field_name(node, "length", 6);
      if (!ts_node_is_null(length))
        interface_constant_refs(length, source, constants, count, false);
    } else if (!types_only && !strcmp(kind, "identifier")) {
      for (size_t i = 0; i < count; ++i)
        if (interface_constant_named(&constants[i], node, source)) constants[i].needed = true;
    }
    if ((!types_only || strcmp(kind, "block")) && ts_tree_cursor_goto_first_child(&cursor)) continue;
    while (!ts_tree_cursor_goto_next_sibling(&cursor))
      if (!ts_tree_cursor_goto_parent(&cursor)) { done = true; break; }
  }
  ts_tree_cursor_delete(&cursor);
}

static bool interface_constants(const DynSources *sources,
                                InterfaceConstant **result, size_t *count) {
  TSTree **trees = calloc(sources->count, sizeof(*trees));
  if (!trees && sources->count) return false;
  InterfaceConstant *constants = NULL;
  size_t used = 0;
  bool ok = false;
  for (size_t si = 0; si < sources->count; ++si) {
    const DynSource *source = &sources->items[si];
    if (dyn_source_target_enabled(source) == 0) continue;
    trees[si] = dyn_source_tree(source);
    if (!trees[si] || ts_node_has_error(ts_tree_root_node(trees[si]))) goto cleanup;
    TSNode root = ts_tree_root_node(trees[si]);
    for (uint32_t i = 0; i < ts_node_named_child_count(root); ++i) {
      DynDeclaration declaration;
      if (!dyn_syntax_declaration(ts_node_named_child(root, i), &declaration) ||
          declaration.kind != DYN_DECL_CONSTANT) continue;
      InterfaceConstant *grown = realloc(constants, (used + 1) * sizeof(*grown));
      if (!grown) goto cleanup;
      constants = grown;
      constants[used++] = (InterfaceConstant){
          .name = source->text + ts_node_start_byte(declaration.name),
          .length = ts_node_end_byte(declaration.name) - ts_node_start_byte(declaration.name),
          .source = source,
          .initializer = dyn_syntax_last_child(dyn_syntax_child(declaration.node, 0)),
          .needed = declaration.is_public};
    }
  }
  for (size_t si = 0; si < sources->count; ++si) {
    if (!trees[si]) continue;
    TSNode root = ts_tree_root_node(trees[si]);
    for (uint32_t i = 0; i < ts_node_named_child_count(root); ++i) {
      DynDeclaration declaration;
      if (!dyn_syntax_declaration(ts_node_named_child(root, i), &declaration)) continue;
      if (declaration.is_public || declaration.kind == DYN_DECL_STRUCT ||
          declaration.kind == DYN_DECL_ENUM || declaration.kind == DYN_DECL_ALIAS)
        interface_constant_refs(declaration.node, &sources->items[si], constants, used, true);
    }
  }
  bool progress = true;
  while (progress) {
    progress = false;
    for (size_t i = 0; i < used; ++i) {
      if (!constants[i].needed || constants[i].scanned) continue;
      constants[i].scanned = true;
      interface_constant_refs(constants[i].initializer, constants[i].source, constants, used, false);
      progress = true;
    }
  }
  *result = constants; *count = used; ok = true;
cleanup:
  for (size_t i = 0; i < sources->count; ++i) if (trees[i]) ts_tree_delete(trees[i]);
  free(trees);
  if (!ok) free(constants);
  return ok;
}

static bool interface_constant_needed(InterfaceConstant *constants, size_t count,
                                      TSNode declaration, const DynSource *source) {
  DynDeclaration parsed;
  if (!dyn_syntax_declaration(declaration, &parsed)) return false;
  for (size_t i = 0; i < count; ++i)
    if (constants[i].needed && interface_constant_named(&constants[i], parsed.name, source)) return true;
  return false;
}
