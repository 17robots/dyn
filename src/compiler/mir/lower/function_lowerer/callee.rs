impl FunctionLowerer {
    pub(super) fn top_level_import_path(&self, name: &str) -> Option<&str> {
        self.function_exprs.get(name).and_then(|expr| {
            if let HirExprKind::Use { path } = &expr.kind {
                Some(path.as_str())
            } else {
                None
            }
        })
    }

    pub(super) fn resolve_import_member_ident(
        &self,
        import_path: &str,
        field: &str,
    ) -> Option<String> {
        let target_key =
            crate::compiler::module_resolver::module_key_for_import(&self.module_key, import_path);
        let target_module_id = self.module_ids_by_key.get(&target_key).copied()?;
        let exports = self.module_exports_by_id.get(&target_module_id)?;
        if exports.iter().any(|name| name == field) {
            Some(qualified_function_name(target_module_id, field))
        } else {
            None
        }
    }

    pub(super) fn infer_call_result_type(&self, callee: MirValueId, depth: usize) -> MirValueType {
        if depth > 8 {
            return MirValueType::Unknown;
        }
        if let Some(name) = self.resolve_callee_function_name(callee, depth) {
            let inferred = self
                .function_return_types
                .get(&name)
                .cloned()
                .unwrap_or(MirValueType::Unknown);
            if !matches!(inferred, MirValueType::Unknown) {
                return inferred;
            }
            return MirValueType::Unknown;
        }
        match self.value_defs.get(&callee) {
            Some(MirValue::Param { index }) => {
                if let Some(Some(hint)) = self.current_param_type_hints.get(*index) {
                    if let Some(ret) = parse_function_return_hint(hint) {
                        return ret;
                    }
                }
                self.value_types
                    .get(&callee)
                    .cloned()
                    .unwrap_or(MirValueType::Unknown)
            }
            _ => MirValueType::Unknown,
        }
    }

    pub(super) fn resolve_callee_function_name(
        &self,
        value: MirValueId,
        depth: usize,
    ) -> Option<String> {
        if depth > 8 {
            return None;
        }
        match self.value_defs.get(&value) {
            Some(MirValue::Ident(name)) => Some(name.clone()),
            Some(MirValue::LocalSet { value, .. }) | Some(MirValue::Assign { value, .. }) => {
                self.resolve_callee_function_name(*value, depth + 1)
            }
            _ => None,
        }
    }
}
