impl FunctionLowerer {
    pub(super) fn lower_for(
        &mut self,
        block: MirBlockId,
        for_expr: &HirForExpr,
    ) -> (MirBlockId, Option<MirValueId>) {
        match for_expr {
            HirForExpr::Infinite { body } => self.lower_infinite_loop(block, body),
            HirForExpr::WhileLike { condition, body } => {
                self.lower_while_like_loop(block, condition, body)
            }
            HirForExpr::Range {
                start,
                end,
                inclusive,
                binding,
                body,
            } => self.lower_range_loop(block, start, end, *inclusive, binding.as_deref(), body),
            HirForExpr::Iterate {
                iterable,
                binding,
                body,
            } => self.lower_iterate_loop(block, iterable, binding.as_deref(), body),
        }
    }

    pub(super) fn prepare_loop_carried_locals(
        &mut self,
        header: MirBlockId,
        incoming_block: MirBlockId,
        body: &HirExpr,
    ) -> Vec<(String, MirValueId)> {
        let mut carried = Vec::new();
        for name in assigned_local_names(body) {
            let Some(current) = self.locals.get(&name).copied() else {
                continue;
            };
            let ty = self
                .value_types
                .get(&current)
                .cloned()
                .unwrap_or(MirValueType::Unknown);
            let phi = self.fresh_value();
            self.function.blocks[header.0]
                .instructions
                .push(MirInstr::Phi {
                    dest: phi,
                    sources: vec![(incoming_block, current)],
                    ty,
                });
            self.value_types.insert(
                phi,
                self.value_types
                    .get(&current)
                    .cloned()
                    .unwrap_or(MirValueType::Unknown),
            );
            self.locals.insert(name.clone(), phi);
            carried.push((name, phi));
        }
        carried
    }

    pub(super) fn finalize_loop_carried_locals(
        &mut self,
        header: MirBlockId,
        backedge_block: MirBlockId,
        carried: &[(String, MirValueId)],
    ) {
        for (name, phi) in carried {
            let source = self.locals.get(name).copied().unwrap_or(*phi);
            for instr in &mut self.function.blocks[header.0].instructions {
                if let MirInstr::Phi { dest, sources, .. } = instr {
                    if *dest == *phi {
                        sources.push((backedge_block, source));
                        break;
                    }
                }
            }
            self.locals.insert(name.clone(), *phi);
        }
    }

    fn inferred_sequence_element_type(&self, value_id: MirValueId) -> MirValueType {
        self.aggregate_sequences
            .get(&value_id)
            .and_then(|sequence| sequence.first())
            .and_then(|first| self.value_types.get(first))
            .cloned()
            .unwrap_or(MirValueType::Unknown)
    }

    fn value_from_sequence_or_index(
        &mut self,
        block: MirBlockId,
        base: MirValueId,
        sequence_value: Option<MirValueId>,
        position: usize,
        result_ty: MirValueType,
    ) -> MirValueId {
        sequence_value.unwrap_or_else(|| {
            let index_value = self.push_eval(
                block,
                MirValue::Literal(HirLiteral::Integer(position.to_string())),
                MirValueType::Int {
                    signed: false,
                    bits: 32,
                },
            );
            self.push_eval(
                block,
                MirValue::Index {
                    base,
                    index: index_value,
                },
                result_ty,
            )
        })
    }

    pub(super) fn lower_range_loop(
        &mut self,
        block: MirBlockId,
        start: &HirExpr,
        end: &HirExpr,
        inclusive: bool,
        binding: Option<&str>,
        body: &HirExpr,
    ) -> (MirBlockId, Option<MirValueId>) {
        let (after_start, start_value) = self.lower_expr(block, start);
        let Some(start_value) = start_value else {
            return (after_start, None);
        };
        let (after_end, end_value) = self.lower_expr(after_start, end);
        let Some(end_value) = end_value else {
            return (after_end, None);
        };

        let iter_ty = self
            .value_types
            .get(&start_value)
            .cloned()
            .zip(self.value_types.get(&end_value).cloned())
            .map(|(left, right)| merge_types(&left, &right))
            .unwrap_or_else(|| {
                self.value_types
                    .get(&start_value)
                    .cloned()
                    .unwrap_or(MirValueType::Unknown)
            });

        let header = self.new_block();
        let body_block = self.new_block();
        let step_block = self.new_block();
        let exit = self.new_block();

        if !self.is_terminated(after_end) {
            self.set_terminator(after_end, MirTerminator::Goto(header));
        }

        let iter_value = self.fresh_value();
        self.function.blocks[header.0]
            .instructions
            .push(MirInstr::Phi {
                dest: iter_value,
                sources: vec![(after_end, start_value)],
                ty: iter_ty.clone(),
            });
        self.value_types.insert(iter_value, iter_ty.clone());

        let carried = self.prepare_loop_carried_locals(header, after_end, body);

        let cond_op = if inclusive {
            crate::compiler::ast::BinaryOp::Le
        } else {
            crate::compiler::ast::BinaryOp::Lt
        };
        let cond = self.push_eval(
            header,
            MirValue::Binary {
                op: cond_op,
                left: iter_value,
                right: end_value,
            },
            MirValueType::Bool,
        );
        if !self.is_terminated(header) {
            self.set_terminator(
                header,
                MirTerminator::Branch {
                    condition: cond,
                    then_block: body_block,
                    else_block: exit,
                },
            );
        }

        self.loop_stack.push(LoopContext {
            continue_target: step_block,
            break_target: exit,
            break_values: Vec::new(),
        });

        let prev_binding = binding.and_then(|name| {
            self.locals
                .insert(name.to_string(), iter_value)
                .map(|prev| (name.to_string(), prev))
        });
        let (body_end, _) = self.lower_expr(body_block, body);
        if let Some(name) = binding {
            if let Some((saved_name, prev)) = prev_binding {
                self.locals.insert(saved_name, prev);
            } else {
                self.locals.remove(name);
            }
        }
        if !self.is_terminated(body_end) {
            self.set_terminator(body_end, MirTerminator::Goto(step_block));
        }

        let one_literal = match iter_ty {
            MirValueType::Float { .. } => HirLiteral::Float("1.0".to_string()),
            _ => HirLiteral::Integer("1".to_string()),
        };
        let one = self.push_eval(step_block, MirValue::Literal(one_literal), iter_ty.clone());
        let next_iter = self.push_eval(
            step_block,
            MirValue::Binary {
                op: crate::compiler::ast::BinaryOp::Add,
                left: iter_value,
                right: one,
            },
            iter_ty,
        );
        if let Some(MirInstr::Phi { sources, .. }) =
            self.function.blocks[header.0].instructions.first_mut()
        {
            sources.push((step_block, next_iter));
        }
        self.finalize_loop_carried_locals(header, step_block, &carried);
        if !self.is_terminated(step_block) {
            self.set_terminator(step_block, MirTerminator::Goto(header));
        }

        let ctx = self.loop_stack.pop().expect("loop context should exist");
        (exit, self.build_loop_break_value(exit, ctx.break_values))
    }

    pub(super) fn lower_iterate_loop(
        &mut self,
        block: MirBlockId,
        iterable: &HirExpr,
        binding: Option<&str>,
        body: &HirExpr,
    ) -> (MirBlockId, Option<MirValueId>) {
        let (after_iterable, iterable_value) = self.lower_expr(block, iterable);
        let Some(iterable_value) = iterable_value else {
            return (after_iterable, None);
        };

        let len = self
            .aggregate_sequences
            .get(&iterable_value)
            .map(|values| values.len())
            .unwrap_or(0);

        let index_ty = MirValueType::Int {
            signed: false,
            bits: 64,
        };
        let index_start = self.push_eval(
            after_iterable,
            MirValue::Literal(HirLiteral::Integer("0".to_string())),
            index_ty.clone(),
        );
        let len_value = self.push_eval(
            after_iterable,
            MirValue::Literal(HirLiteral::Integer(len.to_string())),
            index_ty.clone(),
        );

        let header = self.new_block();
        let body_block = self.new_block();
        let step_block = self.new_block();
        let exit = self.new_block();

        if !self.is_terminated(after_iterable) {
            self.set_terminator(after_iterable, MirTerminator::Goto(header));
        }

        let index_value = self.fresh_value();
        self.function.blocks[header.0]
            .instructions
            .push(MirInstr::Phi {
                dest: index_value,
                sources: vec![(after_iterable, index_start)],
                ty: index_ty.clone(),
            });
        self.value_types.insert(index_value, index_ty.clone());

        let carried = self.prepare_loop_carried_locals(header, after_iterable, body);

        let cond = self.push_eval(
            header,
            MirValue::Binary {
                op: crate::compiler::ast::BinaryOp::Lt,
                left: index_value,
                right: len_value,
            },
            MirValueType::Bool,
        );
        if !self.is_terminated(header) {
            self.set_terminator(
                header,
                MirTerminator::Branch {
                    condition: cond,
                    then_block: body_block,
                    else_block: exit,
                },
            );
        }

        self.loop_stack.push(LoopContext {
            continue_target: step_block,
            break_target: exit,
            break_values: Vec::new(),
        });

        let (body_start, prev_binding) = if let Some(name) = binding {
            let element_value = if self
                .aggregate_sequences
                .get(&iterable_value)
                .is_some_and(Vec::is_empty)
            {
                self.push_eval(body_block, MirValue::Unknown, MirValueType::Unknown)
            } else {
                self.push_eval(
                    body_block,
                    MirValue::Index {
                        base: iterable_value,
                        index: index_value,
                    },
                    self.inferred_sequence_element_type(iterable_value),
                )
            };
            let prev = self
                .locals
                .insert(name.to_string(), element_value)
                .map(|existing| (name.to_string(), existing));
            (body_block, prev)
        } else {
            (body_block, None)
        };

        let (body_end, _) = self.lower_expr(body_start, body);
        if let Some(name) = binding {
            if let Some((saved_name, prev)) = prev_binding {
                self.locals.insert(saved_name, prev);
            } else {
                self.locals.remove(name);
            }
        }
        if !self.is_terminated(body_end) {
            self.set_terminator(body_end, MirTerminator::Goto(step_block));
        }

        let one = self.push_eval(
            step_block,
            MirValue::Literal(HirLiteral::Integer("1".to_string())),
            index_ty.clone(),
        );
        let next_index = self.push_eval(
            step_block,
            MirValue::Binary {
                op: crate::compiler::ast::BinaryOp::Add,
                left: index_value,
                right: one,
            },
            index_ty,
        );
        if let Some(MirInstr::Phi { sources, .. }) =
            self.function.blocks[header.0].instructions.first_mut()
        {
            sources.push((step_block, next_index));
        }
        self.finalize_loop_carried_locals(header, step_block, &carried);
        if !self.is_terminated(step_block) {
            self.set_terminator(step_block, MirTerminator::Goto(header));
        }

        let ctx = self.loop_stack.pop().expect("loop context should exist");
        (exit, self.build_loop_break_value(exit, ctx.break_values))
    }

    pub(super) fn lower_infinite_loop(
        &mut self,
        block: MirBlockId,
        body: &HirExpr,
    ) -> (MirBlockId, Option<MirValueId>) {
        let header = self.new_block();
        let body_block = self.new_block();
        let exit = self.new_block();

        if !self.is_terminated(block) {
            self.set_terminator(block, MirTerminator::Goto(header));
        }
        if !self.is_terminated(header) {
            self.set_terminator(header, MirTerminator::Goto(body_block));
        }

        self.loop_stack.push(LoopContext {
            continue_target: header,
            break_target: exit,
            break_values: Vec::new(),
        });

        let (body_end, _) = self.lower_expr(body_block, body);
        if !self.is_terminated(body_end) {
            self.set_terminator(body_end, MirTerminator::Goto(header));
        }
        let ctx = self.loop_stack.pop().expect("loop context should exist");

        (exit, self.build_loop_break_value(exit, ctx.break_values))
    }

    pub(super) fn lower_while_like_loop(
        &mut self,
        block: MirBlockId,
        condition: &HirExpr,
        body: &HirExpr,
    ) -> (MirBlockId, Option<MirValueId>) {
        let header = self.new_block();
        let body_block = self.new_block();
        let step_block = self.new_block();
        let exit = self.new_block();

        if !self.is_terminated(block) {
            self.set_terminator(block, MirTerminator::Goto(header));
        }

        let carried = self.prepare_loop_carried_locals(header, block, body);

        let (cond_end, cond_value) = self.lower_expr(header, condition);
        let cond_value = cond_value.unwrap_or_else(|| {
            self.push_eval(
                cond_end,
                MirValue::Literal(HirLiteral::Bool(false)),
                MirValueType::Bool,
            )
        });
        if !self.is_terminated(cond_end) {
            self.set_terminator(
                cond_end,
                MirTerminator::Branch {
                    condition: cond_value,
                    then_block: body_block,
                    else_block: exit,
                },
            );
        }

        self.loop_stack.push(LoopContext {
            continue_target: step_block,
            break_target: exit,
            break_values: Vec::new(),
        });
        let (body_end, _) = self.lower_expr(body_block, body);
        if !self.is_terminated(body_end) {
            self.set_terminator(body_end, MirTerminator::Goto(step_block));
        }
        self.finalize_loop_carried_locals(header, step_block, &carried);
        if !self.is_terminated(step_block) {
            self.set_terminator(step_block, MirTerminator::Goto(header));
        }
        let ctx = self.loop_stack.pop().expect("loop context should exist");

        (exit, self.build_loop_break_value(exit, ctx.break_values))
    }

    pub(super) fn build_loop_break_value(
        &mut self,
        exit: MirBlockId,
        break_values: Vec<(MirBlockId, MirValueId)>,
    ) -> Option<MirValueId> {
        if break_values.is_empty() {
            return None;
        }
        if break_values.len() == 1 {
            return Some(break_values[0].1);
        }

        let dest = self.fresh_value();
        let phi_ty = break_values
            .iter()
            .filter_map(|(_, value)| self.value_types.get(value))
            .cloned()
            .reduce(|left, right| merge_types(&left, &right))
            .unwrap_or(MirValueType::Unknown);
        self.function.blocks[exit.0]
            .instructions
            .push(MirInstr::Phi {
                dest,
                sources: break_values,
                ty: phi_ty.clone(),
            });
        self.value_types.insert(dest, phi_ty);
        Some(dest)
    }

    pub(super) fn lower_match(
        &mut self,
        block: MirBlockId,
        scrutinee: &HirExpr,
        arms: &[crate::compiler::hir::HirMatchArm],
    ) -> (MirBlockId, Option<MirValueId>) {
        let (start_test, scrutinee_value) = self.lower_expr(block, scrutinee);
        let Some(scrutinee_value) = scrutinee_value else {
            return (start_test, None);
        };

        let join = self.new_block();
        let mut test_block = start_test;
        let mut join_sources: Vec<(MirBlockId, MirValueId)> = Vec::new();

        for (idx, arm) in arms.iter().enumerate() {
            let arm_block = self.new_block();
            let fallback_block = if idx + 1 == arms.len() {
                join
            } else {
                self.new_block()
            };

            let guard_block = if arm.guard.is_some() {
                Some(self.new_block())
            } else {
                None
            };

            let pattern_pass_block = guard_block.unwrap_or(arm_block);
            self.lower_match_pattern(
                test_block,
                scrutinee_value,
                &arm.pattern,
                pattern_pass_block,
                fallback_block,
            );

            if let Some(guard_expr) = &arm.guard {
                let guard_block = guard_block.expect("guard block should exist");
                let (guard_start, guard_saved) =
                    self.bind_match_pattern_values(guard_block, scrutinee_value, &arm.pattern);
                let (guard_end, guard_value) = self.lower_expr(guard_start, guard_expr);
                self.restore_local_bindings(guard_saved);
                let guard_cond = guard_value.unwrap_or_else(|| {
                    self.push_eval(
                        guard_end,
                        MirValue::Literal(HirLiteral::Bool(false)),
                        MirValueType::Bool,
                    )
                });
                if !self.is_terminated(guard_end) {
                    self.set_terminator(
                        guard_end,
                        MirTerminator::Branch {
                            condition: guard_cond,
                            then_block: arm_block,
                            else_block: fallback_block,
                        },
                    );
                }
            }

            let (arm_start, arm_saved) =
                self.bind_match_pattern_values(arm_block, scrutinee_value, &arm.pattern);
            let (arm_end, arm_value) = self.lower_expr(arm_start, &arm.value);
            self.restore_local_bindings(arm_saved);
            if !self.is_terminated(arm_end) {
                self.set_terminator(arm_end, MirTerminator::Goto(join));
                if let Some(arm_value) = arm_value {
                    join_sources.push((arm_end, arm_value));
                }
            }

            test_block = fallback_block;
        }

        if test_block != join && !self.is_terminated(test_block) {
            self.set_terminator(test_block, MirTerminator::Goto(join));
        }

        if join_sources.is_empty() {
            (join, None)
        } else if join_sources.len() == 1 {
            (join, Some(join_sources[0].1))
        } else {
            let dest = self.fresh_value();
            let phi_ty = join_sources
                .iter()
                .filter_map(|(_, value)| self.value_types.get(value))
                .cloned()
                .reduce(|left, right| merge_types(&left, &right))
                .unwrap_or(MirValueType::Unknown);
            self.function.blocks[join.0]
                .instructions
                .push(MirInstr::Phi {
                    dest,
                    sources: join_sources,
                    ty: phi_ty.clone(),
                });
            self.value_types.insert(dest, phi_ty);
            (join, Some(dest))
        }
    }

    pub(super) fn lower_match_pattern(
        &mut self,
        test_block: MirBlockId,
        scrutinee_value: MirValueId,
        pattern: &HirPattern,
        then_block: MirBlockId,
        else_block: MirBlockId,
    ) {
        match pattern {
            HirPattern::Wildcard | HirPattern::IdentBind(_) | HirPattern::Other => {
                if !self.is_terminated(test_block) {
                    self.set_terminator(test_block, MirTerminator::Goto(then_block));
                }
            }
            HirPattern::EnumVariant { root, variant, .. } => {
                let (variant_tag, tag_bits) = if let Some((tag, bits)) =
                    self.enum_tag_and_bits_for_variant(root.as_deref(), variant)
                {
                    (tag, bits)
                } else if root.is_none() {
                    self.anonymous_variant_tag_for(variant)
                } else {
                    self.diagnostics.push(
                        Diagnostic::error(
                            DiagnosticPhase::Mir,
                            DiagnosticCode::E4005,
                            format!(
                                "cannot resolve enum match pattern '{}'; use an explicit enum root",
                                variant
                            ),
                        )
                        .with_primary_file_label(
                            self.source_file_path.clone(),
                            None,
                            "qualify the enum pattern (for example `MyEnum.Variant`)",
                        ),
                    );
                    if !self.is_terminated(test_block) {
                        self.set_terminator(test_block, MirTerminator::Goto(else_block));
                    }
                    return;
                };
                let scrutinee_tag = self
                    .aggregate_sequences
                    .get(&scrutinee_value)
                    .and_then(|sequence| sequence.first().copied());
                let scrutinee_tag = self.value_from_sequence_or_index(
                    test_block,
                    scrutinee_value,
                    scrutinee_tag,
                    0,
                    MirValueType::Int {
                        signed: false,
                        bits: tag_bits,
                    },
                );
                let expected_tag = self.push_eval(
                    test_block,
                    MirValue::Literal(HirLiteral::Integer(variant_tag.to_string())),
                    MirValueType::Int {
                        signed: false,
                        bits: tag_bits,
                    },
                );
                let cond = self.push_eval(
                    test_block,
                    MirValue::Binary {
                        op: crate::compiler::ast::BinaryOp::Eq,
                        left: scrutinee_tag,
                        right: expected_tag,
                    },
                    MirValueType::Bool,
                );
                if !self.is_terminated(test_block) {
                    self.set_terminator(
                        test_block,
                        MirTerminator::Branch {
                            condition: cond,
                            then_block,
                            else_block,
                        },
                    );
                }
            }
            HirPattern::Literal(literal) => {
                let lit_ty = literal_type(literal);
                let literal_value =
                    self.push_eval(test_block, MirValue::Literal(literal.clone()), lit_ty);
                let cond = self.push_eval(
                    test_block,
                    MirValue::Binary {
                        op: crate::compiler::ast::BinaryOp::Eq,
                        left: scrutinee_value,
                        right: literal_value,
                    },
                    MirValueType::Bool,
                );
                if !self.is_terminated(test_block) {
                    self.set_terminator(
                        test_block,
                        MirTerminator::Branch {
                            condition: cond,
                            then_block,
                            else_block,
                        },
                    );
                }
            }
            HirPattern::RangeLiteral {
                start,
                end,
                inclusive,
            } => {
                let start_value = self.push_eval(
                    test_block,
                    MirValue::Literal(start.clone()),
                    literal_type(start),
                );
                let end_value = self.push_eval(
                    test_block,
                    MirValue::Literal(end.clone()),
                    literal_type(end),
                );
                let lower_ok = self.push_eval(
                    test_block,
                    MirValue::Binary {
                        op: crate::compiler::ast::BinaryOp::Ge,
                        left: scrutinee_value,
                        right: start_value,
                    },
                    MirValueType::Bool,
                );
                let upper_op = if *inclusive {
                    crate::compiler::ast::BinaryOp::Le
                } else {
                    crate::compiler::ast::BinaryOp::Lt
                };
                let upper_ok = self.push_eval(
                    test_block,
                    MirValue::Binary {
                        op: upper_op,
                        left: scrutinee_value,
                        right: end_value,
                    },
                    MirValueType::Bool,
                );
                let cond = self.push_eval(
                    test_block,
                    MirValue::Binary {
                        op: crate::compiler::ast::BinaryOp::LogicalAnd,
                        left: lower_ok,
                        right: upper_ok,
                    },
                    MirValueType::Bool,
                );
                if !self.is_terminated(test_block) {
                    self.set_terminator(
                        test_block,
                        MirTerminator::Branch {
                            condition: cond,
                            then_block,
                            else_block,
                        },
                    );
                }
            }
        }
    }

    pub(super) fn bind_match_pattern_values(
        &mut self,
        block: MirBlockId,
        scrutinee_value: MirValueId,
        pattern: &HirPattern,
    ) -> (MirBlockId, Vec<(String, Option<MirValueId>)>) {
        let (end, bindings) = self.pattern_binding_values(block, scrutinee_value, pattern);
        let mut saved = Vec::with_capacity(bindings.len());
        for (name, value) in bindings {
            let prev = self.locals.insert(name.clone(), value);
            saved.push((name, prev));
        }
        (end, saved)
    }

    pub(super) fn restore_local_bindings(&mut self, saved: Vec<(String, Option<MirValueId>)>) {
        for (name, previous) in saved {
            if let Some(previous) = previous {
                self.locals.insert(name, previous);
            } else {
                self.locals.remove(&name);
            }
        }
    }

    pub(super) fn pattern_binding_values(
        &mut self,
        block: MirBlockId,
        scrutinee_value: MirValueId,
        pattern: &HirPattern,
    ) -> (MirBlockId, Vec<(String, MirValueId)>) {
        match pattern {
            HirPattern::IdentBind(name) if name != "_" => {
                (block, vec![(name.clone(), scrutinee_value)])
            }
            HirPattern::EnumVariant { bindings, .. } => {
                let at = block;
                let sequence = self.aggregate_sequences.get(&scrutinee_value).cloned();
                let mut out = Vec::new();
                for (idx, name) in bindings.iter().enumerate() {
                    if name == "_" {
                        continue;
                    }
                    let payload_index = idx + 1;
                    let payload_value = self.value_from_sequence_or_index(
                        at,
                        scrutinee_value,
                        sequence
                            .as_ref()
                            .and_then(|values| values.get(payload_index).copied()),
                        payload_index,
                        MirValueType::Unknown,
                    );
                    out.push((name.clone(), payload_value));
                }
                (at, out)
            }
            _ => (block, Vec::new()),
        }
    }

    pub(super) fn lower_if(
        &mut self,
        block: MirBlockId,
        condition: &HirExpr,
        capture: Option<&crate::compiler::hir::HirIfCapture>,
        then_branch: &HirExpr,
        else_branch: Option<&HirExpr>,
    ) -> (MirBlockId, Option<MirValueId>) {
        let (cond_end, cond_value) = self.lower_expr(block, condition);
        let Some(cond_value) = cond_value else {
            return (cond_end, None);
        };
        let branch_condition = if capture.is_some() {
            let cond_ty = self
                .value_types
                .get(&cond_value)
                .cloned()
                .unwrap_or(MirValueType::Unknown);
            self.emit_nonzero_check(cond_end, cond_value, &cond_ty)
        } else {
            cond_value
        };

        let then_block = self.new_block();
        let else_block = self.new_block();
        let join_block = self.new_block();

        self.set_terminator(
            cond_end,
            MirTerminator::Branch {
                condition: branch_condition,
                then_block,
                else_block,
            },
        );

        // Snapshot locals before any branch lowering so we can properly merge
        // at the join block. Without this, assignments inside if-branches produce
        // SSA values that don't dominate the join block, causing Cranelift errors.
        let pre_locals = self.locals.clone();

        let capture_binding = capture.and_then(|capture| capture.binding.as_deref());
        let prev_capture_binding = capture_binding.and_then(|name| {
            self.locals
                .insert(name.to_string(), cond_value)
                .map(|prev| (name.to_string(), prev))
        });
        let (then_end, then_value) = self.lower_expr(then_block, then_branch);
        if let Some(name) = capture_binding {
            if let Some((saved_name, prev)) = prev_capture_binding {
                self.locals.insert(saved_name, prev);
            } else {
                self.locals.remove(name);
            }
        }
        let then_locals = self.locals.clone();
        let then_pred = if self.is_terminated(then_end) {
            None
        } else {
            self.set_terminator(then_end, MirTerminator::Goto(join_block));
            Some((then_end, then_value))
        };

        // Restore pre-branch locals before lowering the else branch so that
        // the else branch sees the correct incoming state, not the then-branch's
        // modifications.
        self.locals = pre_locals.clone();

        let else_pred = if let Some(else_branch) = else_branch {
            let (else_end, else_value) = self.lower_expr(else_block, else_branch);
            if self.is_terminated(else_end) {
                None
            } else {
                self.set_terminator(else_end, MirTerminator::Goto(join_block));
                Some((else_end, else_value))
            }
        } else {
            self.set_terminator(else_block, MirTerminator::Goto(join_block));
            Some((else_block, None))
        };
        let else_locals = self.locals.clone();

        // Merge locals at the join block.
        match (&then_pred, &else_pred) {
            (Some((then_end_blk, _)), Some((else_end_blk, _))) => {
                // Both paths reach the join block — create phi nodes for any
                // local that was modified in either branch.
                self.locals = pre_locals.clone();
                for name in pre_locals.keys() {
                    let pre_val = pre_locals[name];
                    let tv = then_locals.get(name).copied().unwrap_or(pre_val);
                    let ev = else_locals.get(name).copied().unwrap_or(pre_val);
                    if tv == ev {
                        // Same value from both paths — use it directly.
                        self.locals.insert(name.clone(), tv);
                    } else {
                        // Different values — create a phi.
                        let phi = self.fresh_value();
                        let phi_ty = [tv, ev]
                            .iter()
                            .filter_map(|v| self.value_types.get(v))
                            .cloned()
                            .reduce(|a, b| merge_types(&a, &b))
                            .unwrap_or(MirValueType::Unknown);
                        self.function.blocks[join_block.0]
                            .instructions
                            .push(MirInstr::Phi {
                                dest: phi,
                                sources: vec![(*then_end_blk, tv), (*else_end_blk, ev)],
                                ty: phi_ty.clone(),
                            });
                        self.value_types.insert(phi, phi_ty);
                        self.locals.insert(name.clone(), phi);
                    }
                }
            }
            (Some(_), None) => {
                // Only the then path reaches join.
                self.locals = then_locals;
            }
            (None, Some(_)) => {
                // Only the else path reaches join.
                self.locals = else_locals;
            }
            (None, None) => {
                // Neither path reaches join (both terminate).
                self.locals = pre_locals;
            }
        }

        let mut sources = Vec::new();
        if let Some((pred, Some(value))) = then_pred {
            sources.push((pred, value));
        }
        if let Some((pred, Some(value))) = else_pred {
            sources.push((pred, value));
        }

        if sources.is_empty() {
            (join_block, None)
        } else if sources.len() == 1 {
            (join_block, Some(sources[0].1))
        } else {
            let dest = self.fresh_value();
            let phi_ty = sources
                .iter()
                .filter_map(|(_, value)| self.value_types.get(value))
                .cloned()
                .reduce(|left, right| merge_types(&left, &right))
                .unwrap_or(MirValueType::Unknown);
            self.function.blocks[join_block.0]
                .instructions
                .push(MirInstr::Phi {
                    dest,
                    sources,
                    ty: phi_ty.clone(),
                });
            self.value_types.insert(dest, phi_ty);
            (join_block, Some(dest))
        }
    }
}
