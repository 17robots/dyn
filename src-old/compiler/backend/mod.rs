pub mod cranelift;

use std::path::PathBuf;

#[derive(Debug, Clone)]
pub struct BuildConfig {
    pub opt_level: BuildOptLevel,
    pub sanitize: bool,
    pub target: Option<String>,
    /// When `Some`, only the module with this name (relative to project root, e.g. `"bin1"`)
    /// is treated as an entry point. When `None`, any `main` function is accepted.
    pub bin: Option<String>,
}

impl Default for BuildConfig {
    fn default() -> Self {
        Self {
            opt_level: BuildOptLevel::Default,
            sanitize: false,
            target: None,
            bin: None,
        }
    }
}

#[derive(Debug, Clone)]
pub struct BuildArtifact {
    pub executable_path: PathBuf,
    pub object_path: PathBuf,
}

#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub enum BuildOptLevel {
    Default,
    O0,
    O1,
    O2,
    O3,
    Os,
    Oz,
}

impl BuildOptLevel {
    pub fn cranelift_opt_level(self) -> Option<&'static str> {
        match self {
            Self::Default => None,
            Self::O0 => Some("none"),
            Self::O1 => Some("speed_and_size"),
            Self::O2 => Some("speed"),
            Self::O3 => Some("speed"),
            Self::Os => Some("speed_and_size"),
            Self::Oz => Some("speed_and_size"),
        }
    }

    pub fn rustc_opt_level(self) -> &'static str {
        match self {
            Self::Default | Self::O2 => "2",
            Self::O0 => "0",
            Self::O1 => "1",
            Self::O3 => "3",
            Self::Os => "s",
            Self::Oz => "z",
        }
    }

    pub fn cc_opt_flag(self) -> &'static str {
        match self {
            Self::Default | Self::O2 => "-O2",
            Self::O0 => "-O0",
            Self::O1 => "-O1",
            Self::O3 => "-O3",
            Self::Os => "-Os",
            Self::Oz => "-Oz",
        }
    }

    pub fn file_suffix(self) -> &'static str {
        match self {
            Self::Default => "Default",
            Self::O0 => "O0",
            Self::O1 => "O1",
            Self::O2 => "O2",
            Self::O3 => "O3",
            Self::Os => "Os",
            Self::Oz => "Oz",
        }
    }
}

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
        "u1" | "i8" | "u8" => Some(TypeLayout { size: 1, align: 1 }),
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
