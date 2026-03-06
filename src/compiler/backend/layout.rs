#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub struct TypeLayout {
    pub size: u64,
    pub align: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AggregateRepr {
    Struct(Vec<TypeLayout>),
    Enum {
        tag: TypeLayout,
        payload: TypeLayout,
    },
    Slice {
        ptr: TypeLayout,
        len: TypeLayout,
    },
}

pub fn scalar_layout(type_name: &str) -> Option<TypeLayout> {
    match type_name.trim() {
        "bool" | "i8" | "u8" => Some(TypeLayout { size: 1, align: 1 }),
        "i16" | "u16" => Some(TypeLayout { size: 2, align: 2 }),
        "i32" | "u32" | "f32" => Some(TypeLayout { size: 4, align: 4 }),
        "i64" | "u64" | "isize" | "usize" | "f64" => Some(TypeLayout { size: 8, align: 8 }),
        "type" => Some(TypeLayout { size: 8, align: 8 }),
        _ => None,
    }
}

pub fn pointer_layout() -> TypeLayout {
    TypeLayout { size: 8, align: 8 }
}

pub fn slice_layout() -> AggregateRepr {
    AggregateRepr::Slice {
        ptr: pointer_layout(),
        len: TypeLayout { size: 8, align: 8 },
    }
}

pub fn optional_layout(inner: TypeLayout) -> AggregateRepr {
    AggregateRepr::Enum {
        tag: TypeLayout { size: 1, align: 1 },
        payload: inner,
    }
}

pub fn errorable_layout(inner: TypeLayout) -> AggregateRepr {
    AggregateRepr::Enum {
        tag: TypeLayout { size: 4, align: 4 },
        payload: inner,
    }
}

pub fn struct_layout(fields: &[TypeLayout]) -> TypeLayout {
    let mut size = 0u64;
    let mut align = 1u64;
    for field in fields {
        align = align.max(field.align);
        let mask = field.align - 1;
        if size & mask != 0 {
            size = (size + mask) & !mask;
        }
        size += field.size;
    }
    let mask = align - 1;
    if size & mask != 0 {
        size = (size + mask) & !mask;
    }
    TypeLayout { size, align }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn computes_padded_struct_layout() {
        let layout = struct_layout(&[
            TypeLayout { size: 1, align: 1 },
            TypeLayout { size: 8, align: 8 },
            TypeLayout { size: 1, align: 1 },
        ]);
        assert_eq!(layout.size, 24);
        assert_eq!(layout.align, 8);
    }
}
