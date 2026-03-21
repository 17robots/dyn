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

    pub(super) fn enum_tag_and_bits_for_variant(
        &self,
        root: Option<&str>,
        variant: &str,
    ) -> Option<(i64, u16)> {
        let root = root?;
        let tags = self.enum_variant_tags_by_name.get(root)?;
        let tag = tags.get(variant).copied()?;
        let bits = self.enum_repr_bits_by_name.get(root).copied().unwrap_or(32);
        Some((tag, bits))
    }

    pub(super) fn anonymous_variant_tag_for(&self, variant: &str) -> (i64, u16) {
        let mut hash = 2166136261u32;
        for byte in variant.as_bytes() {
            hash ^= u32::from(*byte);
            hash = hash.wrapping_mul(16777619);
        }
        let tag = if hash == 0 { 1 } else { i64::from(hash) };
        (tag, 32)
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
