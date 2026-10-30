/* Ordered declaration phases for complete compact source partitions. Semantic
   interning, name resolution, layout and diagnostics remain shared with ast.c. */
#define compact_report(n,s,e,m) _Generic((n), CompactNode: compact_diagnostic, DynSpan: diagnostic_span)((n),(s),(e),(m))
static bool compact_add_enum_names(const DynSource *s, DynAstProgram *a,
                           unsigned *errors) {
  for (uint32_t i = 0; i < a->compact_declaration_count && dyn_work_step(&s->context, 1); ++i) {
    CompactNode wrapper = compact_declaration(a, i);
    bool is_public = compact_flag(wrapper, EXP_PUBLIC);
    CompactNode d = compact_first(wrapper);
    if ((compact_kind(d) != SRC_ENUM))
      continue;
    CompactNode name = {0};
    for (CompactNode c = compact_child(d, 0); !compact_null(c); c = compact_next(c)) {
      if (!(compact_kind(c) != EXP_NAME)) {
        name = c;
        break;
      }
    }
    DynSpan ns = compact_span(name);
    if (find_enum(a, ns, s) != UINT32_MAX) {
      compact_report(name, s, errors, "duplicate enum declaration");
      continue;
    }
    if (a->enum_count >= DYN_TYPE_POINTER_BASE - DYN_TYPE_ENUM_BASE) {
      compact_report(d, s, errors, "enum type capacity exceeded");
      return false;
    }
    if (!reserve_enum(a)) {
      compact_report(d, s, errors, "out of memory");
      return false;
    }
    a->enums[a->enum_count++] =
        (DynAstEnum){.span = compact_span(d),
                     .name = ns,
                     .tag_type = DYN_TYPE_U32,
                     .alignment = 1,
                     .is_public = is_public,
                     .module_owner = declaration_owner(ns, s)};
  }
  return true;
}
static bool compact_add_struct_names(const DynSource *s, DynAstProgram *a,
                             unsigned *errors) {
  for (uint32_t i = 0; i < a->compact_declaration_count && dyn_work_step(&s->context, 1); ++i) {
    CompactNode wrapper = compact_declaration(a, i);
    bool is_public = compact_flag(wrapper, EXP_PUBLIC);
    CompactNode d = compact_first(wrapper);
    if ((compact_kind(d) != SRC_STRUCT))
      continue;
    CompactNode name = compact_child(d, 0);
    DynSpan ns = compact_span(name);
    if (find_struct(a, ns, s) != UINT32_MAX) {
      compact_report(name, s, errors, "duplicate struct declaration");
      continue;
    }
    if (a->struct_count >= DYN_TYPE_ENUM_BASE - DYN_TYPE_STRUCT_BASE) {
      compact_report(d, s, errors, "struct type capacity exceeded");
      return false;
    }
    if (!reserve_struct(a)) {
      compact_report(d, s, errors, "out of memory");
      return false;
    }
    bool packed = compact_flag(d, EXP_PACKED);
    a->structs[a->struct_count++] =
        (DynAstStruct){.span = compact_span(d),
                       .name = ns,
                       .packed = packed,
                       .alignment = 0,
                       .is_public = is_public,
                       .module_owner = declaration_owner(ns, s)};
  }
  return true;
}
static bool compact_add_alias_names(const DynSource *s, DynAstProgram *a,
                            unsigned *errors) {
  for (uint32_t i = 0; i < a->compact_declaration_count && dyn_work_step(&s->context, 1); ++i) {
    CompactNode wrapper = compact_declaration(a, i);
    bool is_public = compact_flag(wrapper, EXP_PUBLIC);
    CompactNode d = compact_first(wrapper);
    if ((compact_kind(d) != SRC_ALIAS))
      continue;
    CompactNode name = compact_child(d, 0), type = compact_child(d, 1);
    DynSpan ns = compact_span(name);
    if (find_alias(a, ns, s) != UINT32_MAX ||
        find_struct(a, ns, s) != UINT32_MAX) {
      compact_report(name, s, errors, "duplicate type declaration");
      continue;
    }
    if (a->alias_count >= DYN_TYPE_PARAM_BASE - DYN_TYPE_DISTINCT_BASE) {
      compact_report(d, s, errors, "alias type capacity exceeded");
      return false;
    }
    if (!reserve_alias(a)) {
      compact_report(d, s, errors, "out of memory");
      return false;
    }
    bool distinct = compact_flag(d, EXP_DISTINCT);
    a->aliases[a->alias_count++] =
        (DynAstAlias){.name = ns,
                      .target = DYN_TYPE_ERROR,
                      .compact_type = compact_reference(type),
                      .distinct = distinct,
                      .is_public = is_public,
                      .module_owner = declaration_owner(ns, s)};
  }
  for (uint32_t i = 0; i < a->alias_count; ++i)
    if (resolve_alias(a, i, s) == DYN_TYPE_ERROR)
      compact_report(a->aliases[i].name, s, errors, "invalid or cyclic type alias");
  return true;
}
static bool compact_add_struct_fields(const DynSource *s, DynAstProgram *a,
                              unsigned *errors) {
  uint32_t si = 0;
  for (uint32_t i = 0; i < a->compact_declaration_count && dyn_work_step(&s->context, 1); ++i) {
    CompactNode d = compact_first(compact_declaration(a, i));
    if ((compact_kind(d) != SRC_STRUCT))
      continue;
    if (si >= a->struct_count)
      break;
    DynAstStruct *st = &a->structs[si++];
    st->field_start = (uint32_t)a->field_count;
    for (CompactNode m = compact_child(d, 1); !compact_null(m); m = compact_next(m)) {
      if ((compact_kind(m) != SRC_STRUCT_MEMBER))
        continue;
      CompactNode tq = {0}, init = {0};
      for (CompactNode c = compact_first(m); !compact_null(c); c = compact_next(c)) {
        uint16_t ck = compact_kind(c);
        /* The initializer is the one operand that is not the name or type;
           a value identifier stays wrapped in primary. */
        if (ck == SRC_QUALIFIER)
          tq = c;
        else if ((ck != EXP_NAME || compact_flag(c, EXP_PRIMARY)))
          init = c;
      }
      DynType type = compact_null(tq)
                         ? DYN_TYPE_ERROR
                         : compact_type(compact_child(tq, 0), s, a);
      if (type == DYN_TYPE_ERROR)
        compact_report(tq, s, errors, "unknown or unsupported struct field type");
      for (CompactNode c = compact_first(m); !compact_null(c); c = compact_next(c)) {
        if (compact_kind(c) != EXP_NAME || compact_flag(c, EXP_PRIMARY))
          continue;
        DynSpan name = compact_span(c);
        bool duplicate = false;
        for (uint32_t q = 0; q < st->field_count; ++q)
          if (dyn_span_text_equal(name, a->fields[st->field_start + q].name, s))
            duplicate = true;
        if (duplicate) {
          compact_report(c, s, errors, "duplicate struct field");
          continue;
        }
        if (!reserve_field(a)) {
          compact_report(c, s, errors, "out of memory");
          return false;
        }
        DynExprId def = compact_null(init) ? DYN_NO_EXPR
                                              : compact_expr(init, s, a, errors);
        a->fields[a->field_count++] = (DynAstField){name, type, def, 0};
        ++st->field_count;
      }
    }
  }
  return true;
}
/* Integer, character or negated integer literal, as two's complement bits. */
static bool compact_enum_literal(CompactNode node, const DynSource *s, DynAstProgram *a,
                         unsigned *errors, uint64_t *bits, bool *negative) {
  DynExprId id = compact_expr(node, s, a, errors);
  if (id == DYN_NO_EXPR)
    return false;
  const DynAstExpr *e = &a->expressions[id];
  *negative = negative_literal(a, e);
  if (*negative)
    e = &a->expressions[e->left];
  if (e->kind != DYN_EXPR_INT && e->kind != DYN_EXPR_CHAR)
    return false;
  if (*negative && e->integer > UINT64_C(1) << 63)
    return false;
  *negative = *negative && e->integer != 0;
  *bits = *negative ? UINT64_C(0) - e->integer : e->integer;
  return true;
}
static bool compact_add_enum_variants(const DynSource *s, DynAstProgram *a,
                              unsigned *errors) {
  uint32_t ei = 0;
  for (uint32_t i = 0; i < a->compact_declaration_count && dyn_work_step(&s->context, 1); ++i) {
    CompactNode d = compact_first(compact_declaration(a, i));
    if ((compact_kind(d) != SRC_ENUM))
      continue;
    DynAstEnum *en = &a->enums[ei++];
    en->variant_start = (uint32_t)a->variant_count;
    bool saw_name = false, any_explicit = false;
    /* The next implicit value; exhausted once the previous was the maximum. */
    uint64_t next = 0;
    bool next_negative = false, exhausted = false;
    for (CompactNode c = compact_child(d, 0); !compact_null(c); c = compact_next(c)) {
      uint16_t k = compact_kind(c);
      if (!saw_name && !(k != EXP_PRIMITIVE)) {
        en->tag_type = compact_type(c, s, a);
        continue;
      }
      if (!saw_name && !(k != EXP_NAME)) {
        saw_name = true;
        continue;
      }
      if ((k != SRC_ENUM_MEMBER))
        continue;
      CompactNode name = compact_child(c, 0);
      bool duplicate = false;
      for (uint32_t q = 0; q < en->variant_count; ++q)
        if (dyn_span_text_equal(compact_span(name),
                                a->variants[en->variant_start + q].name, s))
          duplicate = true;
      if (duplicate) {
        compact_report(name, s, errors, "duplicate enum variant");
        continue;
      }
      DynType payload = DYN_TYPE_VOID;
      bool explicit_value = false, negative = next_negative;
      uint64_t value = next;
      for (CompactNode part = compact_child(c, 1); !compact_null(part); part = compact_next(part)) {
        if (!(compact_kind(part) != SRC_QUALIFIER)) {
          payload = compact_type(compact_child(part, 0), s, a);
          continue;
        }
        explicit_value = true;
        if (!compact_enum_literal(part, s, a, errors, &value, &negative))
          compact_report(part, s, errors, "enum value must be an integer literal");
      }
      if (explicit_value)
        any_explicit = true;
      if ((!explicit_value && exhausted) ||
          (en->tag_type >= DYN_TYPE_I8 && en->tag_type <= DYN_TYPE_USIZE &&
           !tag_fits(en->tag_type, value, negative))) {
        compact_report(c, s, errors, "enum value does not fit the tag type");
        continue;
      }
      if (!reserve_variant(a)) {
        compact_report(c, s, errors, "out of memory");
        return false;
      }
      for (uint32_t q = 0; q < en->variant_count; ++q)
        if (a->variants[en->variant_start + q].tag == value) {
          compact_report(c, s, errors, "duplicate enum value");
          break;
        }
      exhausted = !negative && value == UINT64_MAX;
      next = value + 1;
      next_negative = negative && next != 0;
      a->variants[a->variant_count++] = (DynAstVariant){compact_span(name), payload, value};
      ++en->variant_count;
      if (payload != DYN_TYPE_VOID)
        en->has_payload = true;
    }
    if (!en->variant_count)
      compact_report(d, s, errors, "enum requires at least one variant");
    /* Zeroed storage must hold a valid variant. */
    bool has_zero = false;
    for (uint32_t q = 0; q < en->variant_count; ++q)
      if (a->variants[en->variant_start + q].tag == 0)
        has_zero = true;
    if (en->variant_count && !has_zero)
      compact_report(en->name, s, errors,
                 "enum requires a variant with value 0 so zeroed storage is valid");
    unsigned width =
        en->tag_type == DYN_TYPE_I8 || en->tag_type == DYN_TYPE_U8     ? 8
        : en->tag_type == DYN_TYPE_I16 || en->tag_type == DYN_TYPE_U16 ? 16
        : en->tag_type == DYN_TYPE_I32 || en->tag_type == DYN_TYPE_U32 ? 32
                                                                       : 64;
    if (en->tag_type < DYN_TYPE_I8 || en->tag_type > DYN_TYPE_USIZE)
      compact_report(en->name, s, errors, "enum tag type must be integer");
    else if (width < 64 && en->variant_count > (UINT64_C(1) << width))
      compact_report(en->name, s, errors,
                 "enum has too many variants for tag type");
    else if (any_explicit && en->has_payload)
      compact_report(en->name, s, errors,
                 "enums with payloads cannot have explicit values");
  }
  return true;
}
static bool compact_add_globals(const DynSource *s, DynAstProgram *a,
                        unsigned *errors, DynNameIndex *globals) {
  for (uint32_t i = 0; i < a->compact_declaration_count && dyn_work_step(&s->context, 1); ++i) {
    CompactNode wrapper = compact_declaration(a, i);
    bool is_public = compact_flag(wrapper, EXP_PUBLIC);
    CompactNode d = compact_first(wrapper);
    bool foreign = !(compact_kind(d) != SRC_EXTERN_VARIABLE);
    bool is_const = !(compact_kind(d) != SRC_CONST);
    CompactNode v = is_const ? compact_child(d, 0) : d;
    if ((compact_kind(v) != SRC_VARIABLE) && !foreign)
      continue;
    CompactNode name = foreign ? compact_field(v, EXP_ROLE_NAME)
                          : compact_child(v, 0),
           tq = {0}, init = {0};
    DynSpan ns = compact_span(name);
    if (find_global(globals, a, ns, s) != UINT32_MAX ||
        find_struct(a, ns, s) != UINT32_MAX) {
      compact_report(name, s, errors, "duplicate declaration name");
      continue;
    }
    for (CompactNode c = compact_child(v, 1); !compact_null(c); c = compact_next(c)) {
      uint16_t ck = compact_kind(c);
      if (ck == SRC_QUALIFIER || ck == EXP_TYPE)
        tq = c;
      else if ((ck != EXP_NAME || compact_flag(c, EXP_PRIMARY)))
        init = c;
    }
    DynType type = compact_null(tq)
                       ? DYN_TYPE_INFER
                       : compact_type(!(compact_kind(tq) != SRC_QUALIFIER)
                                        ? compact_child(tq, 0)
                                        : tq,
                                    s, a);
    if (type == DYN_TYPE_ERROR)
      compact_report(!(compact_kind(tq) != SRC_QUALIFIER) ? compact_child(tq, 0) : tq, s, errors,
                     "unknown type in global declaration");
    if (!reserve_global(a)) {
      compact_report(v, s, errors, "out of memory");
      return false;
    }
    CompactNode link_name =
        foreign ? compact_field(v, EXP_ROLE_LINK_NAME) : (CompactNode){0};
    DynSpan link = compact_null(link_name)
                       ? ns
                       : (DynSpan){compact_span(link_name).start_byte + 1,
                                   compact_span(link_name).end_byte - 1};
    a->globals[a->global_count++] = (DynAstGlobal){
        .name = ns,
        .link_name = link,
        .type = type,
        .initializer = foreign || compact_null(init) ? DYN_NO_EXPR
                                             : compact_expr(init, s, a, errors),
        .is_const = is_const,
        .foreign = foreign,
        .is_public = is_public,
        .module_owner = declaration_owner(ns, s)};
  }
  return true;
}
static bool compact_add_asserts(const DynSource *s, DynAstProgram *a, unsigned *errors) {
  for (uint32_t i = 0; i < a->compact_declaration_count && dyn_work_step(&s->context, 1); ++i) {
    CompactNode d = compact_first(compact_declaration(a, i));
    if ((compact_kind(d) != SRC_ASSERT))
      continue;
    if (a->assert_count == a->assert_capacity) {
      size_t c = a->assert_capacity ? a->assert_capacity * 2 : 8;
      void *p = realloc(a->asserts, c * sizeof(*a->asserts));
      if (!p) {
        a->allocation_failed = true;
        compact_report(d, s, errors, "out of memory");
        return false;
      }
      a->asserts = p;
      a->assert_capacity = c;
    }
    CompactNode message = compact_child(d, 1);
    a->asserts[a->assert_count++] = (DynAstAssert){
        .span = compact_span(d),
        .message = compact_null(message)
                       ? (DynSpan){0}
                       : (DynSpan){compact_span(message).start_byte + 1,
                                   compact_span(message).end_byte - 1},
        .condition = compact_expr(compact_child(d, 0), s, a, errors)};
  }
  return true;
}
/* Only type parameters use `$`, and a signature ends at its body's `{`. */
static bool compact_has_type_parameter(CompactNode n, const DynSource *s) {
  for (uint32_t i = compact_span(n).start_byte; i < compact_span(n).end_byte; ++i) {
    if (!(i % 1024) && !dyn_work_step(&s->context, 1)) return false;
    if (s->text[i] == '{')
      return false;
    if (s->text[i] == '$')
      return true;
  }
  return false;
}
static bool compact_add_generic(const DynSource *s, DynAstProgram *a, unsigned *errors,
                        CompactNode d, DynSpan ns, bool is_public) {
  size_t parameter_capacity = 0;
  for (CompactNode c = compact_first(d); !compact_null(c); c = compact_next(c))
    if (compact_kind(c) == SRC_FN_PARAM) parameter_capacity += compact_count(c);
  if (!reserve_generic(a, parameter_capacity)) {
    compact_report(d, s, errors, "out of memory");
    return false;
  }
  DynAstGeneric g = {.compact_node = compact_reference(d), .function = (uint32_t)a->function_count,
                     .param_start = (uint32_t)a->generic_param_count,
                     .return_pattern = DYN_TYPE_VOID};
  a->scope_count = 0;
  a->declaring_generic = true;
  bool ok = true;
  for (CompactNode c = compact_child(d, 0); !compact_null(c); c = compact_next(c)) {
    uint16_t kind = compact_kind(c);
    if (!(kind != SRC_VARIADIC_PARAM)) {
      compact_report(c, s, errors, "generic functions cannot be variadic");
      ok = false;
    } else if (!(kind != SRC_FN_PARAM)) {
      CompactNode first = compact_child(c, 0);
      CompactNode qualifier = compact_last(c);
      if (!(compact_kind(first) != EXP_TYPE_PARAMETER)) {
        CompactNode type = compact_child(qualifier, 0);
        DynSpan text = compact_span(type);
        DynSpan name = compact_span(first);
        ++name.start_byte;
        DynType param = scope_type(a, name, s, true);
        if (text.end_byte - text.start_byte != 4 ||
            memcmp(s->text + text.start_byte, "type", 4)) {
          compact_report(type, s, errors, "a `$T` parameter must have type `type`");
          ok = false;
        } else if (param == DYN_TYPE_ERROR) {
          compact_report(first, s, errors, "duplicate or too many type parameters");
          ok = false;
        }
        a->generic_params[a->generic_param_count++] =
            (DynAstGenericParam){.name = name, .pattern = param, .is_type = true};
        ++g.param_count;
        continue;
      }
      DynType type = compact_type(compact_child(qualifier, 0), s, a);
      DynSpan written = compact_span(qualifier);
      if (type == DYN_TYPE_ERROR &&
          memchr(s->text + written.start_byte, '$', written.end_byte - written.start_byte)) {
        compact_report(qualifier, s, errors,
                       "type parameter declared more than once; write `T`, not `$T`, after its first use");
        ok = false;
      } else if (type == DYN_TYPE_ERROR) {
        /* The qualifier spans ": T"; point at the type itself. */
        compact_report(compact_child(qualifier, 0), s, errors, "unknown type in parameter");
        ok = false;
      }
      for (CompactNode q = compact_child(c, 0); !compact_null(q); q = compact_next(q)) {
        if ((compact_kind(q) != EXP_NAME))
          continue;
        a->generic_params[a->generic_param_count++] =
            (DynAstGenericParam){.name = compact_span(q), .pattern = type};
        ++g.param_count;
      }
    } else if (!(kind != EXP_TYPE)) {
      g.return_pattern = compact_type(c, s, a);
      if (g.return_pattern == DYN_TYPE_ERROR) {
        compact_report(c, s, errors, "unknown type in return signature");
        ok = false;
      }
    }
  }
  g.type_param_count = a->scope_count;
  memcpy(g.type_names, a->scope_names, sizeof(g.type_names));
  a->scope_count = 0;
  a->declaring_generic = false;
  if (!ok)
    g.param_count = 0;
  a->generics[a->generic_count] = g;
  a->functions[a->function_count++] = (DynAstFn){
      .span = compact_span(d), .name = ns, .link_name = ns,
      .return_type = DYN_TYPE_VOID, .param_start = (uint32_t)a->param_count,
      .is_public = is_public, .interface_only = true, .is_generic = true,
      .generic = (uint32_t)a->generic_count++,
      .module_owner = declaration_owner(ns, s)};
  return ok;
}
static bool compact_add_function_signatures(const DynSource *s,
                                    DynAstProgram *a, unsigned *errors, DynNameIndex *index,
                                    DynNameIndex *globals) {
  for (uint32_t i = 0; i < a->compact_declaration_count && dyn_work_step(&s->context, 1); ++i) {
    CompactNode wrapper = compact_declaration(a, i);
    bool is_public = compact_flag(wrapper, EXP_PUBLIC);
    CompactNode d = compact_first(wrapper);
    bool foreign = !(compact_kind(d) != SRC_EXTERN_FN);
    if ((compact_kind(d) != SRC_FN) && !foreign)
      continue;
    CompactNode name = compact_field(d, EXP_ROLE_NAME);
    DynSpan ns = compact_span(name);
    if (find_function(index, a, ns, s) != UINT32_MAX ||
        find_struct(a, ns, s) != UINT32_MAX ||
        find_global(globals, a, ns, s) != UINT32_MAX) {
      compact_report(name, s, errors, "duplicate declaration name");
      continue;
    }
    if (!reserve_function(a)) {
      compact_report(d, s, errors, "out of memory");
      return false;
    }
    if (!foreign && compact_has_type_parameter(d, s)) {
      if (!compact_add_generic(s, a, errors, d, ns, is_public))
        return false;
      continue;
    }
    DynAstFn fn = {.span = compact_span(d),
                   .name = ns,
                   .return_type = DYN_TYPE_VOID,
                   .param_start = (uint32_t)a->param_count,
                   .foreign = foreign,
                   .is_public = is_public,
                   .module_owner = declaration_owner(ns, s)};
    CompactNode link_name = compact_field(d, EXP_ROLE_LINK_NAME);
    fn.link_name = compact_null(link_name)
                       ? ns
                       : (DynSpan){compact_span(link_name).start_byte + 1,
                                   compact_span(link_name).end_byte - 1};
    fn.is_main = !foreign && ns.end_byte - ns.start_byte == 4 &&
                 !memcmp(s->text + ns.start_byte, "main", 4);
    for (CompactNode c = compact_child(d, 0); !compact_null(c); c = compact_next(c)) {
      if (!(compact_kind(c) != SRC_FN_PARAM)) {
        CompactNode tq = {0};
        for (CompactNode q = compact_child(c, 0); !compact_null(q); q = compact_next(q)) {
          if (!(compact_kind(q) != SRC_QUALIFIER))
            tq = q;
        }
        DynType type = compact_null(tq)
                           ? DYN_TYPE_ERROR
                           : compact_type(compact_child(tq, 0), s, a);
        if (type == DYN_TYPE_ERROR)
          compact_report(compact_null(tq) ? c : compact_child(tq, 0), s, errors,
                     "unknown type in parameter");
        else if (type == DYN_TYPE_VOID)
          compact_report(tq, s, errors, "parameter requires a non-void type");
        for (CompactNode q = compact_child(c, 0); !compact_null(q); q = compact_next(q)) {
          if ((compact_kind(q) != EXP_NAME))
            continue;
          if (!reserve_param(a)) {
            compact_report(q, s, errors, "out of memory");
            return false;
          }
          a->params[a->param_count++] = (DynAstParam){
              .name = compact_span(q), .type = type, .local_id = UINT32_MAX};
          ++fn.param_count;
        }
      } else if (!(compact_kind(c) != SRC_VARIADIC_PARAM)) {
        fn.variadic = true;
        fn.variadic_name = compact_span(compact_field(c, EXP_ROLE_NAME));
        fn.variadic_type = intern_slice(
            a, compact_type(compact_field(c, EXP_ROLE_TYPE), s, a),
            true);
      } else if (!(compact_kind(c) != SRC_VARIADIC))
        fn.variadic = true;
      else if (!(compact_kind(c) != EXP_TYPE)) {
        fn.return_type = compact_type(c, s, a);
        if (fn.return_type == DYN_TYPE_ERROR)
          compact_report(c, s, errors, "unknown type in return signature");
      }
    }
    a->functions[a->function_count++] = fn;
  }
  return true;
}
/* Function bodies lower independently: each appends only expressions, items,
   statements, children, patterns, case arms, strings, loop ids and interned
   types. Workers lower contiguous runs of bodies into private arrays that
   start at the shared counts. The runs merge in function order, shifting
   the appended ids and interning each new type in its creation order, which
   assigns exactly the ids a serial lowering assigns. */
typedef struct {
  size_t expressions, items, statements, children, patterns, arms, strings;
  size_t pointers, arrays, slices, fn_types, fn_type_params;
  uint32_t loops;
} BodyBase;
typedef struct {
  uint32_t function;
  CompactNode block;
  uint32_t start, count; /* body in the run's id space */
} BodyJob;
typedef struct {
  DynAstProgram w;
  DynSource source;
  unsigned errors;
  BodyJob *jobs;
  size_t count;
} BodyRun;
static void body_silent(const char *severity, const char *path, unsigned line, unsigned column,
                        unsigned end_line, unsigned end_column, const char *message, void *data) {
  (void)severity; (void)path; (void)line; (void)column; (void)end_line; (void)end_column; (void)message;
  (void)data;
}
/* Interning compares against the shared types, so a run starts with a copy
   of them. Bodies never refer to earlier expressions, statements and the
   like, so a run numbers its own from zero. */
static bool body_array(void **array, size_t *capacity, size_t base, size_t element, const void *copy) {
  size_t n = base + 256;
  *array = malloc(n * element);
  if (!*array) return false;
  if (base) memcpy(*array, copy, base * element);
  *capacity = n;
  return true;
}
static bool body_run_open(BodyRun *r, const DynAstProgram *a, const DynSource *s) {
  r->w = *a;
  r->source = *s;
  r->source.context.diagnostic = body_silent;
  r->source.context.diagnostic_data = NULL;
  DynAstProgram *w = &r->w;
  w->expressions = NULL; w->items = NULL; w->statements = NULL; w->children = NULL;
  w->patterns = NULL; w->case_arms = NULL; w->strings = NULL; w->pointers = NULL;
  w->arrays = NULL; w->slices = NULL; w->fn_types = NULL; w->fn_type_params = NULL;
  w->expression_count = w->item_count = w->statement_count = w->child_count = 0;
  w->pattern_count = w->case_arm_count = w->string_count = 0;
  return body_array((void **)&w->expressions, &w->expression_capacity, 0, sizeof(*w->expressions), NULL) &&
         body_array((void **)&w->items, &w->item_capacity, 0, sizeof(*w->items), NULL) &&
         body_array((void **)&w->statements, &w->statement_capacity, 0, sizeof(*w->statements), NULL) &&
         body_array((void **)&w->children, &w->child_capacity, 0, sizeof(*w->children), NULL) &&
         body_array((void **)&w->patterns, &w->pattern_capacity, 0, sizeof(*w->patterns), NULL) &&
         body_array((void **)&w->case_arms, &w->case_arm_capacity, 0, sizeof(*w->case_arms), NULL) &&
         body_array((void **)&w->strings, &w->string_capacity, 0, sizeof(*w->strings), NULL) &&
         body_array((void **)&w->pointers, &w->pointer_capacity, a->pointer_count, sizeof(*w->pointers), a->pointers) &&
         body_array((void **)&w->arrays, &w->array_capacity, a->array_count, sizeof(*w->arrays), a->arrays) &&
         body_array((void **)&w->slices, &w->slice_capacity, a->slice_count, sizeof(*w->slices), a->slices) &&
         body_array((void **)&w->fn_types, &w->fn_type_capacity, a->fn_type_count, sizeof(*w->fn_types), a->fn_types) &&
         body_array((void **)&w->fn_type_params, &w->fn_type_param_capacity, a->fn_type_param_count,
                    sizeof(*w->fn_type_params), a->fn_type_params);
}
static void body_run_close(BodyRun *r, const BodyBase *base) {
  DynAstProgram *w = &r->w;
  if (w->strings)
    for (size_t i = base->strings; i < w->string_count; ++i) free(w->strings[i].data);
  free(w->expressions); free(w->items); free(w->statements); free(w->children);
  free(w->patterns); free(w->case_arms); free(w->strings); free(w->pointers);
  free(w->arrays); free(w->slices); free(w->fn_types); free(w->fn_type_params);
  free(r->jobs);
}
static void body_run(BodyRun *r) {
  for (size_t i = 0; i < r->count; ++i)
    compact_block(r->jobs[i].block, &r->source, &r->w, &r->errors, 0, &r->jobs[i].start, &r->jobs[i].count);
}
typedef struct {
  BodyRun *runs;
  bool *done;
  size_t count;
  atomic_size_t next;
#ifndef _WIN32
  pthread_mutex_t lock;
  pthread_cond_t finished;
#endif
} BodyPool;
static void *body_worker(void *raw) {
  BodyPool *pool = raw;
  for (size_t i; (i = atomic_fetch_add(&pool->next, 1)) < pool->count;) {
    body_run(&pool->runs[i]);
#ifndef _WIN32
    pthread_mutex_lock(&pool->lock);
    pool->done[i] = true;
    pthread_cond_broadcast(&pool->finished);
    pthread_mutex_unlock(&pool->lock);
#else
    pool->done[i] = true;
#endif
  }
  return NULL;
}
typedef struct {
  const BodyBase *base;
  const DynAstProgram *w;
  DynType *pointers, *arrays, *slices, *fn_types; /* new worker type -> shared type */
} BodyTypes;
/* Shared id of a worker type, or UINT32_MAX for a new one not merged yet. */
static DynType body_type(const BodyTypes *m, DynType t) {
  if (t >= DYN_TYPE_POINTER_BASE && t < DYN_TYPE_ARRAY_BASE && t - DYN_TYPE_POINTER_BASE >= m->base->pointers)
    return m->pointers[t - DYN_TYPE_POINTER_BASE - m->base->pointers];
  if (t >= DYN_TYPE_ARRAY_BASE && t < DYN_TYPE_SLICE_BASE && t - DYN_TYPE_ARRAY_BASE >= m->base->arrays)
    return m->arrays[t - DYN_TYPE_ARRAY_BASE - m->base->arrays];
  if (t >= DYN_TYPE_SLICE_BASE && t < DYN_TYPE_FN_BASE && t - DYN_TYPE_SLICE_BASE >= m->base->slices)
    return m->slices[t - DYN_TYPE_SLICE_BASE - m->base->slices];
  if (t >= DYN_TYPE_FN_BASE && t < DYN_TYPE_DISTINCT_BASE && t - DYN_TYPE_FN_BASE >= m->base->fn_types)
    return m->fn_types[t - DYN_TYPE_FN_BASE - m->base->fn_types];
  return t;
}
/* Interns the run's new types. Ids depend only on the order within each
   kind, and every type's parts precede it, so advancing each kind in order
   once its next type's parts are known reproduces the serial ids. */
static bool body_merge_types(DynAstProgram *a, BodyTypes *m) {
  const DynAstProgram *w = m->w;
  const BodyBase *b = m->base;
  size_t np = w->pointer_count - b->pointers, na = w->array_count - b->arrays;
  size_t ns = w->slice_count - b->slices, nf = w->fn_type_count - b->fn_types;
  size_t ip = 0, ia = 0, is = 0, in = 0;
  while (ip < np || ia < na || is < ns || in < nf) {
    bool progress = false;
    while (ip < np) {
      DynType pointee = body_type(m, w->pointers[b->pointers + ip].pointee);
      if (pointee == UINT32_MAX) break;
      m->pointers[ip] = intern_pointer(a, pointee, w->pointers[b->pointers + ip].is_const);
      ++ip;
      progress = true;
    }
    while (ia < na) {
      DynType element = body_type(m, w->arrays[b->arrays + ia].element);
      if (element == UINT32_MAX) break;
      m->arrays[ia] = intern_array(a, element, w->arrays[b->arrays + ia].length);
      ++ia;
      progress = true;
    }
    while (is < ns) {
      DynType element = body_type(m, w->slices[b->slices + is].element);
      if (element == UINT32_MAX) break;
      m->slices[is] = intern_slice(a, element, w->slices[b->slices + is].is_const);
      ++is;
      progress = true;
    }
    while (in < nf) {
      const DynAstFnType *f = &w->fn_types[b->fn_types + in];
      DynType params[64], result = body_type(m, f->return_type);
      bool ready = result != UINT32_MAX && f->param_count <= 64 && !f->variadic;
      for (uint32_t j = 0; ready && j < f->param_count; ++j)
        ready = (params[j] = body_type(m, w->fn_type_params[f->param_start + j])) != UINT32_MAX;
      if (!ready) break;
      m->fn_types[in++] = intern_fn_type(a, params, f->param_count, result);
      progress = true;
    }
    if (!progress) return false;
  }
  return !a->allocation_failed && !a->type_capacity_exceeded;
}
static bool body_grow(void **array, size_t *capacity, size_t need, size_t element) {
  if (need <= *capacity) return true;
  size_t n = *capacity ? *capacity : 32;
  while (n < need) n *= 2;
  void *p = realloc(*array, n * element);
  if (!p) return false;
  *array = p;
  *capacity = n;
  return true;
}
/* Best effort: a failed shrink keeps the larger block. */
static void body_shrink(void **array, size_t *capacity, size_t count, size_t element) {
  if (!count || count >= *capacity) return;
  void *p = realloc(*array, count * element);
  if (!p) return;
  *array = p;
  *capacity = count;
}
#define BODY_SHIFT(id, from, by) ((id) != UINT32_MAX && (id) >= (from) ? (id) + (by) : (id))
static bool body_merge(DynAstProgram *a, BodyRun *r, const BodyBase *b) {
  DynAstProgram *w = &r->w;
  BodyTypes m = {b, w, NULL, NULL, NULL, NULL};
  size_t np = w->pointer_count - b->pointers, na = w->array_count - b->arrays;
  size_t ns = w->slice_count - b->slices, nf = w->fn_type_count - b->fn_types;
  m.pointers = malloc((np + 1) * sizeof(DynType));
  m.arrays = malloc((na + 1) * sizeof(DynType));
  m.slices = malloc((ns + 1) * sizeof(DynType));
  m.fn_types = malloc((nf + 1) * sizeof(DynType));
  bool ok = m.pointers && m.arrays && m.slices && m.fn_types;
  if (ok) {
    memset(m.pointers, 0xff, (np + 1) * sizeof(DynType));
    memset(m.arrays, 0xff, (na + 1) * sizeof(DynType));
    memset(m.slices, 0xff, (ns + 1) * sizeof(DynType));
    memset(m.fn_types, 0xff, (nf + 1) * sizeof(DynType));
  }
  ok = ok && body_merge_types(a, &m);
  size_t ne = w->expression_count - b->expressions, ni = w->item_count - b->items;
  size_t nst = w->statement_count - b->statements, nc = w->child_count - b->children;
  size_t npt = w->pattern_count - b->patterns, nar = w->case_arm_count - b->arms;
  size_t nstr = w->string_count - b->strings;
  ok = ok &&
       body_grow((void **)&a->expressions, &a->expression_capacity, a->expression_count + ne, sizeof(*a->expressions)) &&
       body_grow((void **)&a->items, &a->item_capacity, a->item_count + ni, sizeof(*a->items)) &&
       body_grow((void **)&a->statements, &a->statement_capacity, a->statement_count + nst, sizeof(*a->statements)) &&
       body_grow((void **)&a->children, &a->child_capacity, a->child_count + nc, sizeof(*a->children)) &&
       body_grow((void **)&a->patterns, &a->pattern_capacity, a->pattern_count + npt, sizeof(*a->patterns)) &&
       body_grow((void **)&a->case_arms, &a->case_arm_capacity, a->case_arm_count + nar, sizeof(*a->case_arms)) &&
       body_grow((void **)&a->strings, &a->string_capacity, a->string_count + nstr, sizeof(*a->strings));
  if (!ok) {
    a->allocation_failed = true;
    goto done;
  }
  /* Shifts from the run's ids to the shared ones. */
  uint32_t de = (uint32_t)(a->expression_count - b->expressions), di = (uint32_t)(a->item_count - b->items);
  uint32_t ds = (uint32_t)(a->statement_count - b->statements), dc = (uint32_t)(a->child_count - b->children);
  uint32_t dp = (uint32_t)(a->pattern_count - b->patterns), da = (uint32_t)(a->case_arm_count - b->arms);
  uint32_t dstr = (uint32_t)(a->string_count - b->strings), dl = a->loop_count - b->loops;
  uint32_t be = (uint32_t)b->expressions, bi = (uint32_t)b->items, bs = (uint32_t)b->statements;
  uint32_t bc = (uint32_t)b->children, bp = (uint32_t)b->patterns, ba = (uint32_t)b->arms;
  for (size_t k = 0; k < ne; ++k) {
    DynAstExpr e = w->expressions[b->expressions + k];
    e.type = body_type(&m, e.type);
    e.left = BODY_SHIFT(e.left, be, de);
    e.right = BODY_SHIFT(e.right, be, de);
    if (e.kind != DYN_EXPR_OFFSET) e.item_start = BODY_SHIFT(e.item_start, bi, di);
    if (e.kind == DYN_EXPR_SLICE) e.integer = BODY_SHIFT((uint32_t)e.integer, be, de);
    else if (e.kind == DYN_EXPR_STRING) e.integer = (uint32_t)e.integer + dstr;
    else if (e.kind == DYN_EXPR_CAST || e.kind == DYN_EXPR_BITCAST || e.kind == DYN_EXPR_OFFSET ||
             ((e.kind == DYN_EXPR_SIZE || e.kind == DYN_EXPR_ALIGN || e.kind == DYN_EXPR_TYPEOF) && e.boolean))
      e.integer = body_type(&m, (DynType)e.integer);
    a->expressions[a->expression_count++] = e;
  }
  for (size_t k = 0; k < ni; ++k) {
    DynAstItem item = w->items[b->items + k];
    item.expression = BODY_SHIFT(item.expression, be, de);
    a->items[a->item_count++] = item;
  }
  for (size_t k = 0; k < nst; ++k) {
    DynAstStmt st = w->statements[b->statements + k];
    st.expression = BODY_SHIFT(st.expression, be, de);
    st.target = BODY_SHIFT(st.target, be, de);
    st.declared_type = body_type(&m, st.declared_type);
    st.body_start = BODY_SHIFT(st.body_start, bc, dc);
    st.else_start = BODY_SHIFT(st.else_start, bc, dc);
    st.case_arm_start = BODY_SHIFT(st.case_arm_start, ba, da);
    if (st.kind == DYN_STMT_FOR) st.loop_id += dl;
    a->statements[a->statement_count++] = st;
  }
  for (size_t k = 0; k < nc; ++k)
    a->children[a->child_count++] = BODY_SHIFT(w->children[b->children + k], bs, ds);
  for (size_t k = 0; k < npt; ++k) {
    DynAstPattern pattern = w->patterns[b->patterns + k];
    pattern.first = BODY_SHIFT(pattern.first, be, de);
    pattern.last = BODY_SHIFT(pattern.last, be, de);
    pattern.type = body_type(&m, pattern.type);
    a->patterns[a->pattern_count++] = pattern;
  }
  for (size_t k = 0; k < nar; ++k) {
    DynAstCaseArm arm = w->case_arms[b->arms + k];
    arm.pattern_start = BODY_SHIFT(arm.pattern_start, bp, dp);
    arm.body_start = BODY_SHIFT(arm.body_start, bc, dc);
    a->case_arms[a->case_arm_count++] = arm;
  }
  for (size_t k = 0; k < nstr; ++k) a->strings[a->string_count++] = w->strings[b->strings + k];
  w->string_count = b->strings; /* ownership moved */
  a->loop_count += w->loop_count - b->loops;
  for (size_t k = 0; k < r->count; ++k) {
    DynAstFn *fn = &a->functions[r->jobs[k].function];
    fn->body_start = BODY_SHIFT(r->jobs[k].start, bc, dc);
    fn->body_count = r->jobs[k].count;
  }
done:
  free(m.pointers); free(m.arrays); free(m.slices); free(m.fn_types);
  return ok;
}
static unsigned body_workers(const DynSource *s, size_t jobs) {
#ifdef _WIN32
  (void)s; (void)jobs;
  return 1;
#else
  /* Budgeted analysis charges work in order on one context. */
  if (s->context.work || jobs < 64) return 1;
  long online = sysconf(_SC_NPROCESSORS_ONLN);
  return online < 2 ? 1 : online > 4 ? 4 : (unsigned)online;
#endif
}
/* Lowers jobs on worker threads into the program; false leaves it unchanged
   so the caller lowers serially, which also reports diagnostics in order. */
static bool body_parallel(const DynSource *s, DynAstProgram *a, BodyJob *jobs, size_t count, unsigned workers) {
  BodyBase base = {0, 0, 0, 0, 0, 0, 0, a->pointer_count, a->array_count, a->slice_count,
                   a->fn_type_count, a->fn_type_param_count, a->loop_count};
  /* Runs of about equal source size, a few per worker for balance. */
  size_t run_count = 8 * (size_t)workers, total = 0;
  for (size_t i = 0; i < count; ++i) total += compact_span(jobs[i].block).end_byte - compact_span(jobs[i].block).start_byte;
  BodyRun *runs = calloc(run_count, sizeof(*runs));
  if (!runs) return false;
  size_t used = 0, at = 0;
  bool ok = true;
  for (size_t r = 0; r < run_count && at < count && ok; ++r) {
    size_t first = at, size = 0, goal = total / run_count + 1;
    while (at < count && (size < goal || r + 1 == run_count)) {
      size += compact_span(jobs[at].block).end_byte - compact_span(jobs[at].block).start_byte;
      ++at;
    }
    runs[r].jobs = malloc((at - first) * sizeof(*runs[r].jobs));
    ok = runs[r].jobs && body_run_open(&runs[r], a, s);
    if (runs[r].jobs) memcpy(runs[r].jobs, jobs + first, (at - first) * sizeof(*jobs));
    runs[r].count = at - first;
    used = r + 1;
  }
  /* Runs merge in order as soon as they finish, so at most the unmerged
     runs exist beside the program. Merging only appends; a run reporting a
     diagnostic truncates the program back to these counts. */
  size_t before[12] = {a->expression_count, a->item_count, a->statement_count, a->child_count,
                       a->pattern_count, a->case_arm_count, a->string_count, a->pointer_count,
                       a->array_count, a->slice_count, a->fn_type_count, a->fn_type_param_count};
  uint32_t loops = a->loop_count;
  BodyPool pool = {.runs = runs, .count = used, .done = calloc(used ? used : 1, sizeof(bool))};
  atomic_init(&pool.next, 0);
  bool merged = ok && pool.done;
  bool clean = merged;
#ifndef _WIN32
  pthread_t threads[4];
  unsigned started = 0;
  if (merged) {
    pthread_mutex_init(&pool.lock, NULL);
    pthread_cond_init(&pool.finished, NULL);
    for (; started < workers; ++started)
      if (pthread_create(&threads[started], NULL, body_worker, &pool)) break;
    if (!started) body_worker(&pool);
  }
#else
  if (merged) body_worker(&pool);
#endif
  for (size_t r = 0; r < used && merged; ++r) {
#ifndef _WIN32
    pthread_mutex_lock(&pool.lock);
    while (!pool.done[r]) pthread_cond_wait(&pool.finished, &pool.lock);
    pthread_mutex_unlock(&pool.lock);
#endif
    clean = !runs[r].errors && !runs[r].w.allocation_failed && !runs[r].w.type_capacity_exceeded &&
            !runs[r].w.invalid_array_extent.end_byte;
    merged = clean && body_merge(a, &runs[r], &base);
    body_run_close(&runs[r], &base);
    runs[r] = (BodyRun){0};
  }
#ifndef _WIN32
  if (pool.done) {
    /* Unmerged runs still finish; the pool hands out no new ones. */
    atomic_store(&pool.next, used);
    for (unsigned i = 0; i < started; ++i) pthread_join(threads[i], NULL);
    if (ok) {
      pthread_mutex_destroy(&pool.lock);
      pthread_cond_destroy(&pool.finished);
    }
  }
#endif
  for (size_t r = 0; r < used; ++r) body_run_close(&runs[r], &base);
  free(runs);
  free(pool.done);
  if (!merged && !a->allocation_failed) {
    for (size_t i = before[6]; i < a->string_count; ++i) free(a->strings[i].data);
    a->expression_count = before[0]; a->item_count = before[1]; a->statement_count = before[2];
    a->child_count = before[3]; a->pattern_count = before[4]; a->case_arm_count = before[5];
    a->string_count = before[6]; a->pointer_count = before[7]; a->array_count = before[8];
    a->slice_count = before[9]; a->fn_type_count = before[10]; a->fn_type_param_count = before[11];
    a->loop_count = loops;
  }
  /* Doubling while merging leaves slack the program would keep. */
  if (merged) {
    body_shrink((void **)&a->expressions, &a->expression_capacity, a->expression_count, sizeof(*a->expressions));
    body_shrink((void **)&a->items, &a->item_capacity, a->item_count, sizeof(*a->items));
    body_shrink((void **)&a->statements, &a->statement_capacity, a->statement_count, sizeof(*a->statements));
    body_shrink((void **)&a->children, &a->child_capacity, a->child_count, sizeof(*a->children));
  }
#ifdef __GLIBC__
  /* The runs grew in the workers' heap arenas, which later allocations on
     this thread never reuse; return those pages instead of holding them. */
  malloc_trim(0);
#endif
  /* A failed merge already changed the program; it reports out of memory. */
  return merged || a->allocation_failed;
}
static void compact_lower_function_bodies(const DynSource *s,
                                  DynAstProgram *a, unsigned *errors,
                                  const char *owner_key, DynNameIndex *index) {
  uint64_t wanted = owner_key_value(owner_key);
  BodyJob *jobs = calloc(a->compact_declaration_count ? a->compact_declaration_count : 1, sizeof(*jobs));
  if (!jobs) {
    a->allocation_failed = true;
    return;
  }
  size_t count = 0;
  for (uint32_t i = 0; i < a->compact_declaration_count && dyn_work_step(&s->context, 1); ++i) {
    CompactNode d = compact_first(compact_declaration(a, i));
    if ((compact_kind(d) != SRC_FN) && (compact_kind(d) != SRC_EXTERN_FN))
      continue;
    CompactNode name = compact_field(d, EXP_ROLE_NAME);
    uint32_t id = find_function(index, a, compact_span(name), s);
    if (id == UINT32_MAX)
      continue;
    if (a->functions[id].foreign || a->functions[id].is_generic)
      continue;
    if (owner_key && a->functions[id].module_owner != wanted) {
      a->functions[id].interface_only = true;
      continue;
    }
    CompactNode block = {0};
    for (CompactNode c = compact_child(d, 0); !compact_null(c); c = compact_next(c)) {
      if (!(compact_kind(c) != SRC_BLOCK)) {
        block = c;
        break;
      }
    }
    jobs[count++] = (BodyJob){id, block, 0, 0};
  }
  unsigned workers = body_workers(s, count);
  if (workers < 2 || !body_parallel(s, a, jobs, count, workers))
    for (size_t i = 0; i < count; ++i)
      compact_block(jobs[i].block, s, a, errors, 0, &a->functions[jobs[i].function].body_start,
                    &a->functions[jobs[i].function].body_count);
  for (size_t i = 0; i < count; ++i) {
    const DynAstFn *fn = &a->functions[jobs[i].function];
    if (fn->is_main) {
      a->span = fn->span;
      a->name = fn->name;
      a->parameter_count = fn->param_count;
      a->has_return_type = fn->return_type != DYN_TYPE_VOID;
      a->body_start = fn->body_start;
      a->body_count = fn->body_count;
    }
  }
  free(jobs);
}

#undef compact_report
