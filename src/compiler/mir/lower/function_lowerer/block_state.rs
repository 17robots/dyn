impl FunctionLowerer {
    pub(super) fn new_block(&mut self) -> MirBlockId {
        let id = MirBlockId(self.function.blocks.len());
        self.function.blocks.push(MirBasicBlock {
            id,
            instructions: Vec::new(),
            terminator: None,
        });
        id
    }

    pub(super) fn push_eval(
        &mut self,
        block: MirBlockId,
        value: MirValue,
        ty: MirValueType,
    ) -> MirValueId {
        let dest = self.fresh_value();
        self.function.blocks[block.0]
            .instructions
            .push(MirInstr::Eval {
                dest,
                value: value.clone(),
                ty: ty.clone(),
            });
        self.value_types.insert(dest, ty);
        self.value_defs.insert(dest, value);
        dest
    }

    pub(super) fn literal_int_value(&self, value_id: MirValueId) -> Option<i64> {
        match self.value_defs.get(&value_id) {
            Some(MirValue::Literal(HirLiteral::Integer(v))) => {
                let normalized = v.replace('_', "");
                if let Some(bits) = normalized.strip_prefix("0x") {
                    i64::from_str_radix(bits, 16).ok()
                } else if let Some(bits) = normalized.strip_prefix("0b") {
                    i64::from_str_radix(bits, 2).ok()
                } else if let Some(bits) = normalized.strip_prefix("0o") {
                    i64::from_str_radix(bits, 8).ok()
                } else {
                    normalized.parse::<i64>().ok()
                }
            }
            _ => None,
        }
    }

    pub(super) fn variant_tag_for(&mut self, variant: &str) -> i64 {
        if let Some(tag) = self.variant_tag_ids.get(variant) {
            *tag
        } else {
            let tag = self.next_variant_tag;
            self.next_variant_tag += 1;
            self.variant_tag_ids.insert(variant.to_string(), tag);
            tag
        }
    }

    pub(super) fn fresh_value(&mut self) -> MirValueId {
        let id = MirValueId(self.next_value);
        self.next_value += 1;
        id
    }

    pub(super) fn is_terminated(&self, block: MirBlockId) -> bool {
        self.function.blocks[block.0].terminator.is_some()
    }

    pub(super) fn set_terminator(&mut self, block: MirBlockId, term: MirTerminator) {
        self.function.blocks[block.0].terminator = Some(term);
    }
}
