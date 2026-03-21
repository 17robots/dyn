pub mod lower;
pub mod verify;

pub use lower::*;
pub use verify::*;

use crate::compiler::module_resolver::{ModuleId, ModuleKey};
use crate::compiler::{
    ast::{AssignOp, BinaryOp, UnaryOp},
    hir::HirLiteral,
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MirProgram {
    pub modules: Vec<MirModule>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MirModule {
    pub module_id: ModuleId,
    pub key: ModuleKey,
    pub functions: Vec<MirFunction>,
    pub extern_functions: Vec<MirExternFunction>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MirExternFunction {
    pub name: String,
    pub symbol_name: String,
    pub return_type: Option<String>,
    pub param_type_hints: Vec<Option<String>>,
    pub param_types: Vec<MirValueType>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MirFunction {
    pub name: String,
    pub def_id: Option<usize>,
    pub return_type: Option<String>,
    pub param_type_hints: Vec<Option<String>>,
    pub param_types: Vec<MirValueType>,
    pub blocks: Vec<MirBasicBlock>,
    pub entry: MirBlockId,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum MirValueType {
    Unknown,
    Type,
    Bool,
    BytesSlice,
    Int { signed: bool, bits: u16 },
    Float { bits: u16 },
    Function,
    FunctionPointer,
}

#[derive(Debug, Copy, Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct MirBlockId(pub usize);

#[derive(Debug, Copy, Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct MirValueId(pub usize);

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MirBasicBlock {
    pub id: MirBlockId,
    pub instructions: Vec<MirInstr>,
    pub terminator: Option<MirTerminator>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum MirInstr {
    Eval {
        dest: MirValueId,
        value: MirValue,
        ty: MirValueType,
    },
    Phi {
        dest: MirValueId,
        sources: Vec<(MirBlockId, MirValueId)>,
        ty: MirValueType,
    },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum MirValue {
    Literal(HirLiteral),
    Ident(String),
    Unary {
        op: UnaryOp,
        operand: MirValueId,
    },
    Cast {
        value: MirValueId,
        target: MirValueType,
    },
    Binary {
        op: BinaryOp,
        left: MirValueId,
        right: MirValueId,
    },
    Assign {
        op: AssignOp,
        target: MirValueId,
        value: MirValueId,
    },
    LocalSet {
        name: String,
        value: MirValueId,
    },
    Param {
        index: usize,
    },
    Call {
        callee: MirValueId,
        args: Vec<MirValueId>,
    },
    ErrorStatus {
        value: MirValueId,
    },
    ErrorPayload {
        value: MirValueId,
    },
    FieldAccess {
        base: MirValueId,
        field: String,
    },
    DerefAccess {
        base: MirValueId,
    },
    Index {
        base: MirValueId,
        index: MirValueId,
    },
    Slice {
        base: MirValueId,
        start: Option<MirValueId>,
        end: Option<MirValueId>,
        inclusive: bool,
    },
    StructLiteral {
        fields: Vec<(String, MirValueId)>,
    },
    EnumVariant {
        root: Option<String>,
        variant: String,
        tag: i64,
        tag_bits: u16,
        payload: Vec<MirValueId>,
    },
    Use {
        path: String,
    },
    TypeLiteral(String),
    Unknown,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum MirTerminator {
    Return(Option<MirValueId>),
    Goto(MirBlockId),
    Branch {
        condition: MirValueId,
        then_block: MirBlockId,
        else_block: MirBlockId,
    },
    Unreachable,
}
