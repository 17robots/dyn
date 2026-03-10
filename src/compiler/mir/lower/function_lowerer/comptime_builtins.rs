impl FunctionLowerer {
    pub(super) fn emit_comptime_value(
        &mut self,
        block: MirBlockId,
        value: ComptimeValue,
    ) -> MirValueId {
        let (value, ty) = match value {
            ComptimeValue::Literal(lit) => {
                let ty = literal_type(&lit);
                (MirValue::Literal(lit), ty)
            }
            ComptimeValue::Type(name) => (MirValue::TypeLiteral(name), MirValueType::Type),
            ComptimeValue::Function(name) => (MirValue::Ident(name), MirValueType::FunctionPointer),
        };
        self.push_eval(block, value, ty)
    }

    pub(super) fn refresh_comptime_local_from_expr(&mut self, name: &str, expr: &HirExpr) {
        self.comptime_local_function_exprs.remove(name);
        let mut locals = self.current_comptime_locals();
        locals.remove(name);

        let local_function_expr = match &expr.kind {
            HirExprKind::Function { .. } => Some(expr.clone()),
            HirExprKind::Inline { expr } if matches!(expr.kind, HirExprKind::Function { .. }) => {
                Some((**expr).clone())
            }
            _ => None,
        };

        if let Some(function_expr) = local_function_expr {
            self.comptime_known_locals
                .insert(name.to_string(), ComptimeValue::Function(name.to_string()));
            self.comptime_local_function_exprs
                .insert(name.to_string(), function_expr);
            return;
        }

        if let Some(value) = self.try_eval_comptime_expr_with_locals(expr, 0, &mut locals) {
            self.comptime_known_locals.insert(name.to_string(), value);
        } else {
            self.comptime_known_locals.remove(name);
        }
    }

    pub(super) fn current_comptime_locals(&self) -> BTreeMap<String, ComptimeValue> {
        let mut locals = self.comptime_known_locals.clone();
        locals.retain(|name, _| self.locals.contains_key(name));

        let mut cache = BTreeMap::new();
        let mut visiting = BTreeSet::new();
        for (name, value_id) in &self.locals {
            if let Some(value) =
                self.try_eval_comptime_value_id(*value_id, 0, &mut cache, &mut visiting)
            {
                locals.insert(name.clone(), value);
            } else if !self.comptime_known_locals.contains_key(name) {
                locals.remove(name);
            }
        }
        locals
    }

    pub(super) fn try_eval_comptime_value_id(
        &self,
        value_id: MirValueId,
        depth: usize,
        cache: &mut BTreeMap<MirValueId, Option<ComptimeValue>>,
        visiting: &mut BTreeSet<MirValueId>,
    ) -> Option<ComptimeValue> {
        if depth > 64 {
            return None;
        }
        if let Some(cached) = cache.get(&value_id) {
            return cached.clone();
        }
        if !visiting.insert(value_id) {
            return None;
        }

        let evaluated = match self.value_defs.get(&value_id) {
            Some(MirValue::Literal(lit)) => Some(ComptimeValue::Literal(lit.clone())),
            Some(MirValue::TypeLiteral(name)) => Some(ComptimeValue::Type(name.clone())),
            Some(MirValue::Ident(name)) => {
                if self.function_return_types.contains_key(name)
                    || self
                        .function_exprs
                        .get(name)
                        .is_some_and(|expr| matches!(&expr.kind, HirExprKind::Function { .. }))
                {
                    Some(ComptimeValue::Function(name.clone()))
                } else {
                    None
                }
            }
            Some(MirValue::Unary { op, operand }) => {
                let operand =
                    self.try_eval_comptime_value_id(*operand, depth + 1, cache, visiting)?;
                match (op, operand) {
                    (UnaryOp::Neg, ComptimeValue::Literal(HirLiteral::Integer(v))) => {
                        let parsed = parse_i64_literal(&v)?;
                        Some(ComptimeValue::Literal(HirLiteral::Integer(
                            (-parsed).to_string(),
                        )))
                    }
                    (UnaryOp::Not, ComptimeValue::Literal(HirLiteral::Bool(v))) => {
                        Some(ComptimeValue::Literal(HirLiteral::Bool(!v)))
                    }
                    (UnaryOp::BitNot, ComptimeValue::Literal(HirLiteral::Integer(v))) => {
                        let parsed = parse_i64_literal(&v)?;
                        Some(ComptimeValue::Literal(HirLiteral::Integer(
                            (!parsed).to_string(),
                        )))
                    }
                    _ => None,
                }
            }
            Some(MirValue::Binary { op, left, right }) => {
                let left = self.try_eval_comptime_value_id(*left, depth + 1, cache, visiting)?;
                let right = self.try_eval_comptime_value_id(*right, depth + 1, cache, visiting)?;
                eval_comptime_binary(*op, left, right)
            }
            Some(MirValue::Assign { value, .. }) | Some(MirValue::LocalSet { value, .. }) => {
                self.try_eval_comptime_value_id(*value, depth + 1, cache, visiting)
            }
            Some(MirValue::Cast { value, .. }) => {
                self.try_eval_comptime_value_id(*value, depth + 1, cache, visiting)
            }
            _ => None,
        };

        visiting.remove(&value_id);
        cache.insert(value_id, evaluated.clone());
        evaluated
    }

    pub(super) fn report_comptime_eval_failure(
        &mut self,
        span: crate::compiler::diagnostics::SourceSpan,
    ) {
        self.diagnostics.push(
            Diagnostic::error(
                DiagnosticPhase::Mir,
                DiagnosticCode::E4009,
                "comptime expression must be compile-time evaluable",
            )
            .with_primary_file_label(
                self.source_file_path.clone(),
                Some(span),
                "this `comp` expression could not be evaluated at compile time",
            ),
        );
    }

    pub(super) fn report_inline_call_lowering_failure(
        &mut self,
        span: crate::compiler::diagnostics::SourceSpan,
    ) {
        self.diagnostics.push(
            Diagnostic::error(
                DiagnosticPhase::Mir,
                DiagnosticCode::E4010,
                "inline call could not be lowered",
            )
            .with_primary_file_label(
                self.source_file_path.clone(),
                Some(span),
                "use a direct call to an inline-lowerable function body",
            ),
        );
    }

    pub(super) fn report_inline_range_requires_comptime_bounds(
        &mut self,
        span: crate::compiler::diagnostics::SourceSpan,
    ) {
        self.diagnostics.push(
            Diagnostic::error(
                DiagnosticPhase::Mir,
                DiagnosticCode::E4011,
                "inline for requires compile-time range bounds",
            )
            .with_primary_file_label(
                self.source_file_path.clone(),
                Some(span),
                "use literals or comptime-evaluable bound expressions",
            ),
        );
    }

    pub(super) fn report_unsupported_inline_expression(
        &mut self,
        span: crate::compiler::diagnostics::SourceSpan,
    ) {
        self.diagnostics.push(
            Diagnostic::error(
                DiagnosticPhase::Mir,
                DiagnosticCode::E4012,
                "unsupported inline expression",
            )
            .with_primary_file_label(
                self.source_file_path.clone(),
                Some(span),
                "inline currently supports range loops, direct calls, and function literals",
            ),
        );
    }

    pub(super) fn should_force_comptime_call(&self, callee_name: &str) -> bool {
        if matches!(
            self.function_return_types.get(callee_name),
            Some(MirValueType::Type)
        ) {
            return true;
        }
        self.function_param_type_hints
            .get(callee_name)
            .map(|params| {
                params.iter().flatten().any(|hint| {
                    matches!(parse_type_hint(hint), MirValueType::Type)
                        || hint.trim() == "comp type"
                })
            })
            .unwrap_or(false)
    }

    pub(super) fn function_returns_errorable_aggregate(&self, callee_name: &str) -> bool {
        if let Some(Some(hint)) = self.function_return_hints.get(callee_name) {
            return return_hint_is_errorable_aggregate(hint);
        }
        let suffix = format!("::{callee_name}");
        self.function_return_hints
            .iter()
            .filter_map(|(name, hint)| {
                if name.ends_with(&suffix) {
                    hint.as_deref()
                } else {
                    None
                }
            })
            .any(return_hint_is_errorable_aggregate)
    }

    pub(super) fn eval_type_designator_name(
        &self,
        expr: &HirExpr,
        locals: &BTreeMap<String, ComptimeValue>,
    ) -> Option<String> {
        match self.try_eval_comptime_expr_with_locals(expr, 0, &mut locals.clone()) {
            Some(ComptimeValue::Type(name)) => Some(name),
            Some(ComptimeValue::Function(_)) => Some("fn".to_string()),
            _ => None,
        }
    }

    pub(super) fn try_lower_builtin_call(
        &mut self,
        block: MirBlockId,
        name: &str,
        args: &[HirCallArg],
    ) -> Option<(MirBlockId, Option<MirValueId>)> {
        match name {
            "$as" => {
                if args.len() != 2 {
                    return Some((block, None));
                }
                let empty_locals = BTreeMap::new();
                let target_name = self
                    .eval_type_designator_name(&args[0].value, &empty_locals)
                    .unwrap_or_else(|| "unknown".to_string());
                let target_ty = parse_type_hint(&target_name);
                let (arg_end, value) = self.lower_expr(block, &args[1].value);
                let Some(value) = value else {
                    return Some((arg_end, None));
                };
                if matches!(target_ty, MirValueType::Unknown) {
                    return Some((arg_end, Some(value)));
                }
                let casted = self.push_eval(
                    arg_end,
                    MirValue::Cast {
                        value,
                        target: target_ty.clone(),
                    },
                    target_ty,
                );
                Some((arg_end, Some(casted)))
            }
            "$sizeof" | "$alignof" | "$offsetof" => {
                let expected = if name == "$offsetof" { 2 } else { 1 };
                if args.len() != expected {
                    return Some((block, None));
                }
                let empty_locals = BTreeMap::new();
                let type_name = self
                    .eval_type_designator_name(&args[0].value, &empty_locals)
                    .unwrap_or_else(|| "unknown".to_string());
                let (size, align) = layout_for_builtin_type_name(&type_name);
                let raw = if name == "$sizeof" {
                    size
                } else if name == "$alignof" {
                    align
                } else {
                    builtin_offsetof_for_type_name(&type_name, &args[1].value).unwrap_or(0)
                };
                let value = self.push_eval(
                    block,
                    MirValue::Literal(HirLiteral::Integer(raw.to_string())),
                    MirValueType::Int {
                        signed: false,
                        bits: 64,
                    },
                );
                Some((block, Some(value)))
            }
            "$unreachable" => {
                self.set_terminator(block, MirTerminator::Unreachable);
                Some((block, None))
            }
            "$panic" => {
                if args.len() != 1 {
                    self.set_terminator(block, MirTerminator::Unreachable);
                    return Some((block, None));
                }
                let (arg_end, _) = self.lower_expr(block, &args[0].value);
                self.set_terminator(arg_end, MirTerminator::Unreachable);
                Some((arg_end, None))
            }
            "$Self" => {
                if !args.is_empty() {
                    return Some((block, None));
                }
                let self_name = self
                    .current_param_type_hints
                    .first()
                    .and_then(|hint| hint.as_ref())
                    .map(|hint| self_type_literal_from_param_hint(hint))
                    .unwrap_or_else(|| "unknown".to_string());
                let value =
                    self.push_eval(block, MirValue::TypeLiteral(self_name), MirValueType::Type);
                Some((block, Some(value)))
            }
            "$typeof" => {
                if args.len() != 1 {
                    return Some((block, None));
                }
                let (arg_end, arg_value) = self.lower_expr(block, &args[0].value);
                let Some(arg_value) = arg_value else {
                    return Some((arg_end, None));
                };
                let ty_name = match self
                    .value_types
                    .get(&arg_value)
                    .cloned()
                    .unwrap_or(MirValueType::Unknown)
                {
                    MirValueType::Bool => "u1".to_string(),
                    MirValueType::BytesSlice => "[]u8".to_string(),
                    MirValueType::Int { signed: true, bits } => format!("i{bits}"),
                    MirValueType::Int {
                        signed: false,
                        bits,
                    } => format!("u{bits}"),
                    MirValueType::Float { bits } => format!("f{bits}"),
                    MirValueType::Type => "type".to_string(),
                    MirValueType::Function | MirValueType::FunctionPointer => "fn".to_string(),
                    MirValueType::Unknown => "unknown".to_string(),
                };
                let value =
                    self.push_eval(arg_end, MirValue::TypeLiteral(ty_name), MirValueType::Type);
                Some((arg_end, Some(value)))
            }
            _ => None,
        }
    }

    pub(super) fn try_eval_comptime_expr(
        &self,
        expr: &HirExpr,
        depth: usize,
    ) -> Option<ComptimeValue> {
        let mut locals = self.current_comptime_locals();
        self.try_eval_comptime_expr_with_locals(expr, depth, &mut locals)
    }

    pub(super) fn try_eval_comptime_expr_with_locals(
        &self,
        expr: &HirExpr,
        depth: usize,
        locals: &mut BTreeMap<String, ComptimeValue>,
    ) -> Option<ComptimeValue> {
        if depth > 64 {
            return None;
        }
        match &expr.kind {
            HirExprKind::Literal(lit) => Some(ComptimeValue::Literal(lit.clone())),
            HirExprKind::TypeLiteral(name) => {
                Some(ComptimeValue::Type(substitute_type_locals(name, locals)))
            }
            HirExprKind::Ident(name) => {
                if let Some(value) = locals.get(name).cloned() {
                    return Some(value);
                }
                if let Some(type_name) =
                    type_literal_name_for_ident(name, &self.named_type_literals)
                {
                    return Some(ComptimeValue::Type(type_name));
                }
                if let Some(target) = self.function_exprs.get(name) {
                    if matches!(&target.kind, HirExprKind::Function { .. }) {
                        return Some(ComptimeValue::Function(name.clone()));
                    }
                    return self.try_eval_comptime_expr_with_locals(
                        target,
                        depth + 1,
                        &mut locals.clone(),
                    );
                }
                None
            }
            HirExprKind::Comptime { expr } | HirExprKind::Inline { expr } => {
                self.try_eval_comptime_expr_with_locals(expr, depth + 1, locals)
            }
            HirExprKind::Unary { op, expr } => {
                let value = self.try_eval_comptime_expr_with_locals(expr, depth + 1, locals)?;
                match (op, value) {
                    (UnaryOp::Neg, ComptimeValue::Literal(HirLiteral::Integer(v))) => {
                        let parsed = parse_i64_literal(&v)?;
                        Some(ComptimeValue::Literal(HirLiteral::Integer(
                            (-parsed).to_string(),
                        )))
                    }
                    (UnaryOp::Not, ComptimeValue::Literal(HirLiteral::Bool(v))) => {
                        Some(ComptimeValue::Literal(HirLiteral::Bool(!v)))
                    }
                    (UnaryOp::BitNot, ComptimeValue::Literal(HirLiteral::Integer(v))) => {
                        let parsed = parse_i64_literal(&v)?;
                        Some(ComptimeValue::Literal(HirLiteral::Integer(
                            (!parsed).to_string(),
                        )))
                    }
                    _ => None,
                }
            }
            HirExprKind::Binary { op, left, right } => {
                let left = self.try_eval_comptime_expr_with_locals(left, depth + 1, locals)?;
                let right = self.try_eval_comptime_expr_with_locals(right, depth + 1, locals)?;
                eval_comptime_binary(*op, left, right)
            }
            HirExprKind::Let { name, value, .. } => {
                let value = self.try_eval_comptime_expr_with_locals(value, depth + 1, locals)?;
                locals.insert(name.clone(), value.clone());
                Some(value)
            }
            HirExprKind::Assign { target, value, .. } => {
                let HirExprKind::Ident(name) = &target.kind else {
                    return None;
                };
                let value = self.try_eval_comptime_expr_with_locals(value, depth + 1, locals)?;
                locals.insert(name.clone(), value.clone());
                Some(value)
            }
            HirExprKind::Block { body } => {
                let mut scope = locals.clone();
                let mut last = None;
                for value in body {
                    if let HirExprKind::Return { value } = &value.kind {
                        if let Some(value) = value {
                            return self.try_eval_comptime_expr_with_locals(
                                value,
                                depth + 1,
                                &mut scope,
                            );
                        }
                        return None;
                    }
                    last = self.try_eval_comptime_expr_with_locals(value, depth + 1, &mut scope);
                }
                last
            }
            HirExprKind::If {
                condition,
                capture,
                then_branch,
                else_branch,
            } => {
                let condition_value =
                    self.try_eval_comptime_expr_with_locals(condition, depth + 1, locals)?;
                if comptime_truthy(&condition_value) {
                    let mut scope = locals.clone();
                    if let Some(capture) = capture {
                        if let Some(binding) = &capture.binding {
                            if binding != "_" {
                                scope.insert(binding.clone(), condition_value.clone());
                            }
                        }
                    }
                    self.try_eval_comptime_expr_with_locals(then_branch, depth + 1, &mut scope)
                } else if let Some(else_branch) = else_branch {
                    let mut scope = locals.clone();
                    self.try_eval_comptime_expr_with_locals(else_branch, depth + 1, &mut scope)
                } else {
                    None
                }
            }
            HirExprKind::Return { value } => value.as_ref().and_then(|value| {
                self.try_eval_comptime_expr_with_locals(value, depth + 1, locals)
            }),
            HirExprKind::Call { callee, args } => {
                let HirExprKind::Ident(name) = &callee.kind else {
                    return None;
                };
                match name.as_str() {
                    "$sizeof" | "$alignof" => {
                        if args.len() != 1 {
                            return None;
                        }
                        let type_name = self.comptime_type_name_from_expr_with_locals(
                            &args[0].value,
                            depth + 1,
                            locals,
                        )?;
                        let (size, align) = layout_for_builtin_type_name(&type_name);
                        let out = if name == "$sizeof" { size } else { align };
                        Some(ComptimeValue::Literal(HirLiteral::Integer(out.to_string())))
                    }
                    "$offsetof" => {
                        if args.len() != 2 {
                            return None;
                        }
                        let type_name = self.comptime_type_name_from_expr_with_locals(
                            &args[0].value,
                            depth + 1,
                            locals,
                        )?;
                        let off = builtin_offsetof_for_type_name(&type_name, &args[1].value)?;
                        Some(ComptimeValue::Literal(HirLiteral::Integer(off.to_string())))
                    }
                    "$typeof" => {
                        if args.len() != 1 {
                            return None;
                        }
                        let inner = self.try_eval_comptime_expr_with_locals(
                            &args[0].value,
                            depth + 1,
                            locals,
                        )?;
                        let ty_name = match inner {
                            ComptimeValue::Literal(HirLiteral::Integer(_)) => "i32".to_string(),
                            ComptimeValue::Literal(HirLiteral::Float(_)) => "f64".to_string(),
                            ComptimeValue::Literal(HirLiteral::Bool(_)) => "u1".to_string(),
                            ComptimeValue::Literal(HirLiteral::Char(_)) => "u8".to_string(),
                            ComptimeValue::Literal(HirLiteral::String(_)) => "[]u8".to_string(),
                            ComptimeValue::Literal(HirLiteral::Null) => "unknown".to_string(),
                            ComptimeValue::Type(_) => "type".to_string(),
                            ComptimeValue::Function(_) => "fn".to_string(),
                        };
                        Some(ComptimeValue::Type(ty_name))
                    }
                    "$as" => {
                        if args.len() != 2 {
                            return None;
                        }
                        let target = self.comptime_type_name_from_expr_with_locals(
                            &args[0].value,
                            depth + 1,
                            locals,
                        )?;
                        let value = self.try_eval_comptime_expr_with_locals(
                            &args[1].value,
                            depth + 1,
                            locals,
                        )?;
                        eval_comptime_cast(&target, value)
                    }
                    "$Self" => {
                        if !args.is_empty() {
                            return None;
                        }
                        let self_name = self
                            .current_param_type_hints
                            .first()
                            .and_then(|hint| hint.as_ref())
                            .map(|hint| self_type_literal_from_param_hint(hint))
                            .unwrap_or_else(|| "unknown".to_string());
                        Some(ComptimeValue::Type(self_name))
                    }
                    _ => self.try_eval_named_comptime_call(name, args, depth + 1, locals),
                }
            }
            _ => None,
        }
    }

    pub(super) fn try_eval_named_comptime_call(
        &self,
        name: &str,
        args: &[HirCallArg],
        depth: usize,
        caller_locals: &mut BTreeMap<String, ComptimeValue>,
    ) -> Option<ComptimeValue> {
        let (resolved_name, came_from_local_binding) =
            if let Some(ComptimeValue::Function(function_name)) = caller_locals.get(name) {
                (function_name.clone(), true)
            } else {
                (name.to_string(), false)
            };
        let (target, captures_caller_locals) = if came_from_local_binding {
            if let Some(local_target) = self.comptime_local_function_exprs.get(&resolved_name) {
                (local_target, true)
            } else {
                (self.function_exprs.get(&resolved_name)?, false)
            }
        } else {
            (self.function_exprs.get(&resolved_name)?, false)
        };
        match &target.kind {
            HirExprKind::Function {
                params,
                param_defaults,
                body,
                ..
            } => {
                if args.len() > params.len() {
                    return None;
                }

                let mut ordered = vec![None; params.len()];
                for arg in args {
                    if let Some(name) = &arg.name {
                        let index = params.iter().position(|param| param == name)?;
                        if ordered[index].is_some() {
                            return None;
                        }
                        ordered[index] = Some(&arg.value);
                    }
                }
                let mut positional = args.iter().filter(|arg| arg.name.is_none());
                for slot in &mut ordered {
                    if slot.is_none() {
                        *slot = positional.next().map(|arg| &arg.value);
                    }
                }

                let mut locals = if captures_caller_locals {
                    caller_locals.clone()
                } else {
                    BTreeMap::new()
                };
                for (idx, param_name) in params.iter().enumerate() {
                    let value = if let Some(expr) = ordered[idx] {
                        self.try_eval_comptime_expr_with_locals(expr, depth + 1, caller_locals)?
                    } else if let Some(Some(default_expr)) = param_defaults.get(idx) {
                        self.try_eval_comptime_expr_with_locals(
                            default_expr,
                            depth + 1,
                            &mut locals,
                        )?
                    } else {
                        return None;
                    };
                    locals.insert(param_name.clone(), value);
                }

                self.try_eval_comptime_expr_with_locals(body, depth + 1, &mut locals)
            }
            _ => {
                if !args.is_empty() {
                    return None;
                }
                let mut locals = BTreeMap::new();
                self.try_eval_comptime_expr_with_locals(target, depth + 1, &mut locals)
            }
        }
    }

    pub(super) fn comptime_type_name_from_expr_with_locals(
        &self,
        expr: &HirExpr,
        depth: usize,
        locals: &BTreeMap<String, ComptimeValue>,
    ) -> Option<String> {
        match &expr.kind {
            HirExprKind::TypeLiteral(name) => Some(substitute_type_locals(name, locals)),
            HirExprKind::Ident(name) => {
                if let Some(ComptimeValue::Type(type_name)) = locals.get(name) {
                    return Some(type_name.clone());
                }
                if let Some(resolved) = type_literal_name_for_ident(name, &self.named_type_literals)
                {
                    return Some(resolved);
                }
                if let Some(target) = self.function_exprs.get(name) {
                    if let Some(ComptimeValue::Type(type_name)) = self
                        .try_eval_comptime_expr_with_locals(target, depth + 1, &mut locals.clone())
                    {
                        return Some(type_name);
                    }
                }
                Some(name.clone())
            }
            _ => self
                .try_eval_comptime_expr_with_locals(expr, depth + 1, &mut locals.clone())
                .and_then(|value| match value {
                    ComptimeValue::Type(name) => Some(name),
                    ComptimeValue::Function(_) | ComptimeValue::Literal(_) => None,
                }),
        }
    }
}
