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
    pub globals: Vec<MirGlobal>,
    pub functions: Vec<MirFunction>,
    pub extern_functions: Vec<MirExternFunction>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MirGlobal {
    pub name: String,
    pub mutable: bool,
    pub type_hint: Option<String>,
    pub ty: MirValueType,
    pub init: MirGlobalInit,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum MirGlobalInit {
    Zero,
    Integer(i64),
    Bool(bool),
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
    /// Fat pointer: (fn_ptr, env_ptr) pair
    Closure,
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
    /// Creates a fat pointer closure value: (fn_ptr, env_ptr)
    /// fn_symbol is the hoisted lambda's MIR function name
    /// captures are the values of variables captured from the enclosing scope (in order)
    ClosureCreate {
        fn_symbol: String,
        captures: Vec<MirValueId>,
    },
    /// Loads a captured value from the environment pointer (first param of a closure)
    /// env_ptr is the MirValueId of the env_ptr parameter
    /// index is which capture to load (0-based)
    ClosureEnvField {
        env_ptr: MirValueId,
        index: usize,
    },
    /// Loads the current value of a module-level mutable global variable.
    GlobalLoad {
        name: String,
    },
    /// Stores a value to a module-level mutable global variable.
    GlobalStore {
        name: String,
        value: MirValueId,
    },
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
