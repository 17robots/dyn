use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use cranelift_codegen::ir::condcodes::IntCC;
use cranelift_codegen::ir::entities::StackSlot;
use cranelift_codegen::ir::stackslot::{StackSlotData, StackSlotKind};
use cranelift_codegen::ir::types::{F32, F64, I16, I32, I64, I8};
use cranelift_codegen::ir::{AbiParam, InstBuilder, TrapCode, Type, Value};
use cranelift_codegen::settings;
use cranelift_codegen::settings::Configurable;
use cranelift_frontend::{FunctionBuilder, FunctionBuilderContext};
use cranelift_module::{FuncId, Linkage, Module};
use cranelift_object::{ObjectBuilder, ObjectModule};

use crate::compiler::ast::{BinaryOp, UnaryOp};
use crate::compiler::backend::{BuildArtifact, BuildOptLevel};
use crate::compiler::diagnostics::{Diagnostic, DiagnosticCode, DiagnosticPhase};
use crate::compiler::hir::HirLiteral;
use crate::compiler::mir::{
    MirFunction, MirInstr, MirProgram, MirTerminator, MirValue, MirValueId, MirValueType,
};

pub fn build_executable(
    mir: &MirProgram,
    build_dir: &Path,
    output_path: Option<&Path>,
    opt_level: BuildOptLevel,
) -> Result<(BuildArtifact, Vec<Diagnostic>), String> {
    fs::create_dir_all(build_dir).map_err(|err| format!("failed to create build dir: {err}"))?;

    let executable_path = output_path
        .map(PathBuf::from)
        .unwrap_or_else(|| build_dir.join("dyn_out"));
    let object_path = build_dir.join("dyn_out.o");

    let mut diagnostics = Vec::new();
    if find_main_function(mir).is_none() {
        diagnostics.push(Diagnostic::error(
            DiagnosticPhase::Backend,
            DiagnosticCode::E5002,
            "no main function found in module 'main'",
        ));
        return Ok((
            BuildArtifact {
                executable_path,
                object_path,
            },
            diagnostics,
        ));
    }

    let mut flag_builder = settings::builder();
    flag_builder
        .set("is_pic", "false")
        .map_err(|err| format!("failed to configure target flags: {err}"))?;
    if let Some(opt) = opt_level.cranelift_opt_level() {
        flag_builder
            .set("opt_level", opt)
            .map_err(|err| format!("failed to configure optimization level: {err}"))?;
    }
    let isa = cranelift_native::builder()
        .map_err(|err| format!("failed to build host isa: {err}"))?
        .finish(settings::Flags::new(flag_builder))
        .map_err(|err| format!("failed to finalize host isa: {err}"))?;

    let object_builder =
        ObjectBuilder::new(isa, "dyn_module", cranelift_module::default_libcall_names())
            .map_err(|err| format!("failed to build object module: {err}"))?;
    let mut module = ObjectModule::new(object_builder);

    let symbols = declare_function_symbols(mir, &mut module)?;
    for mir_module in &mir.modules {
        for function in &mir_module.functions {
            compile_function(
                &mut module,
                function,
                mir_module.module_id.0,
                mir_module.key.module_name == "main" && function.name == "main",
                &symbols.by_key,
                &symbols.by_name,
                &symbols.param_types_by_id,
            )?;
        }
    }

    let object = module.finish();
    let bytes = object
        .emit()
        .map_err(|err| format!("failed to emit object bytes: {err}"))?;

    fs::write(&object_path, bytes).map_err(|err| format!("failed to write object file: {err}"))?;

    let runtime_object_path = build_dir.join("dyn_runtime_alloc.o");
    compile_runtime_allocator_object(build_dir, &runtime_object_path)?;

    link_executable_with_system_ld(&object_path, &runtime_object_path, &executable_path)?;

    Ok((
        BuildArtifact {
            executable_path,
            object_path,
        },
        diagnostics,
    ))
}

fn compile_runtime_allocator_object(_build_dir: &Path, output_path: &Path) -> Result<(), String> {
    let source_path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("src")
        .join("compiler")
        .join("backend")
        .join("runtime_support.rs");
    let status = Command::new("rustc")
        .arg("--crate-type=lib")
        .arg("--emit=obj")
        .arg("--edition=2021")
        .arg("-O")
        .arg("-C")
        .arg("panic=abort")
        .arg(&source_path)
        .arg("-o")
        .arg(output_path)
        .status()
        .map_err(|err| format!("failed to compile runtime support object (rustc): {err}"))?;
    if !status.success() {
        return Err("failed to compile runtime support object".to_string());
    }

    Ok(())
}

fn link_executable_with_system_ld(
    object_path: &Path,
    runtime_object_path: &Path,
    executable_path: &Path,
) -> Result<(), String> {
    let crt_dirs = [
        "/usr/lib",
        "/usr/lib64",
        "/usr/lib/x86_64-linux-gnu",
        "/lib",
        "/lib64",
        "/lib/x86_64-linux-gnu",
    ];
    let linker_paths = [
        "/lib64/ld-linux-x86-64.so.2",
        "/usr/lib/ld-linux-x86-64.so.2",
        "/lib/ld-linux-x86-64.so.2",
        "/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2",
    ];

    let Some(crt_dir) = crt_dirs.iter().find(|dir| {
        Path::new(dir).join("crt1.o").exists()
            && Path::new(dir).join("crti.o").exists()
            && Path::new(dir).join("crtn.o").exists()
    }) else {
        return Err("failed to locate crt startup objects for linker".to_string());
    };
    let Some(dynamic_linker) = linker_paths.iter().find(|path| Path::new(path).exists()) else {
        return Err("failed to locate system dynamic linker".to_string());
    };

    let status = Command::new("ld")
        .arg("-o")
        .arg(executable_path)
        .arg(Path::new(crt_dir).join("crt1.o"))
        .arg(Path::new(crt_dir).join("crti.o"))
        .arg(object_path)
        .arg(runtime_object_path)
        .arg(format!("-L{crt_dir}"))
        .arg("-lc")
        .arg(Path::new(crt_dir).join("crtn.o"))
        .arg("-dynamic-linker")
        .arg(dynamic_linker)
        .status()
        .map_err(|err| format!("failed to invoke linker (ld): {err}"))?;
    if !status.success() {
        return Err("linker failed to produce executable".to_string());
    }

    Ok(())
}

#[allow(dead_code)]
fn runtime_allocator_c_source() -> &'static str {
    r#"#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

size_t __dyn_alloc_with(size_t alloc, size_t size, size_t align);
size_t __dyn_realloc_with(size_t alloc, size_t ptr, size_t old_size, size_t new_size, size_t align);
uint32_t __dyn_free_with(size_t alloc, size_t ptr, size_t size, size_t align);

static int dyn_is_power_of_two(size_t value) {
    return value != 0 && (value & (value - 1)) == 0;
}

size_t __dyn_alloc(size_t size, size_t align) {
    if (!dyn_is_power_of_two(align)) {
        return 0;
    }
    if (size == 0) {
        return 0;
    }

    void* ptr = NULL;
    if (align <= sizeof(void*)) {
        ptr = malloc(size);
    } else {
        if (posix_memalign(&ptr, align, size) != 0) {
            ptr = NULL;
        }
    }
    return (size_t)ptr;
}

size_t __dyn_realloc(size_t ptr, size_t old_size, size_t new_size, size_t align) {
    if (!dyn_is_power_of_two(align)) {
        return 0;
    }
    if (ptr == 0) {
        return __dyn_alloc(new_size, align);
    }
    if (new_size == 0) {
        free((void*)ptr);
        return 0;
    }

    if (align <= sizeof(void*)) {
        void* grown = realloc((void*)ptr, new_size);
        return (size_t)grown;
    }

    size_t next = __dyn_alloc(new_size, align);
    if (next == 0) {
        return 0;
    }

    size_t copy = old_size < new_size ? old_size : new_size;
    if (copy > 0) {
        memcpy((void*)next, (const void*)ptr, copy);
    }
    free((void*)ptr);
    return next;
}

uint32_t __dyn_free(size_t ptr, size_t size, size_t align) {
    (void)size;
    if (!dyn_is_power_of_two(align)) {
        return 0;
    }
    if (ptr == 0) {
        return 1;
    }
    free((void*)ptr);
    return 1;
}

size_t __dyn_c_allocator(void) {
    return 1;
}

static size_t dyn_fail_after = (size_t)-1;

size_t __dyn_test_failing_allocator(void) {
    return 2;
}

static int32_t dyn_identity_i32(int32_t value) {
    return value;
}

size_t __dyn_test_identity_i32_fn(void) {
    return (size_t)&dyn_identity_i32;
}

uint32_t __dyn_test_set_fail_after(size_t remaining_successes) {
    dyn_fail_after = remaining_successes;
    return 1;
}

static int dyn_allocator_should_fail(size_t alloc) {
    if (alloc != 2) {
        return 0;
    }
    if (dyn_fail_after == 0) {
        return 1;
    }
    if (dyn_fail_after != (size_t)-1) {
        dyn_fail_after -= 1;
    }
    return 0;
}

typedef struct DynArenaAllocator {
    size_t backing;
    uint8_t* ptr;
    size_t cap;
    size_t used;
} DynArenaAllocator;

static int dyn_is_arena_allocator(size_t alloc) {
    return alloc != 0 && alloc != 1 && alloc != 2;
}

static size_t dyn_align_up(size_t value, size_t align) {
    if (!dyn_is_power_of_two(align)) {
        return (size_t)-1;
    }
    size_t mask = align - 1;
    if (value > ((size_t)-1) - mask) {
        return (size_t)-1;
    }
    return (value + mask) & ~mask;
}

size_t __dyn_arena_allocator(size_t backing) {
    DynArenaAllocator* arena = (DynArenaAllocator*)malloc(sizeof(DynArenaAllocator));
    if (arena == NULL) {
        return 0;
    }
    arena->backing = backing;
    arena->ptr = NULL;
    arena->cap = 0;
    arena->used = 0;
    return (size_t)arena;
}

uint32_t __dyn_arena_reset(size_t arena_handle) {
    DynArenaAllocator* arena = (DynArenaAllocator*)arena_handle;
    if (arena == NULL) {
        return 0;
    }
    arena->used = 0;
    return 1;
}

uint32_t __dyn_arena_deinit(size_t arena_handle) {
    DynArenaAllocator* arena = (DynArenaAllocator*)arena_handle;
    if (arena == NULL) {
        return 1;
    }
    if (arena->ptr != NULL && arena->cap != 0) {
        if (!__dyn_free_with(arena->backing, (size_t)arena->ptr, arena->cap, 16)) {
            return 0;
        }
    }
    free(arena);
    return 1;
}

static size_t dyn_arena_alloc(DynArenaAllocator* arena, size_t size, size_t align) {
    if (!dyn_is_power_of_two(align)) {
        return 0;
    }
    if (size == 0) {
        return 0;
    }

    size_t aligned_used = dyn_align_up(arena->used, align);
    if (aligned_used == (size_t)-1) {
        return 0;
    }
    size_t required = aligned_used + size;
    if (required < aligned_used) {
        return 0;
    }

    if (required > arena->cap) {
        size_t next_cap = arena->cap == 0 ? 4096 : arena->cap;
        while (next_cap < required) {
            if (next_cap > ((size_t)-1) / 2) {
                next_cap = required;
                break;
            }
            next_cap *= 2;
        }
        size_t next_ptr = __dyn_realloc_with(arena->backing, (size_t)arena->ptr, arena->cap, next_cap, 16);
        if (next_ptr == 0) {
            return 0;
        }
        arena->ptr = (uint8_t*)next_ptr;
        arena->cap = next_cap;
    }

    size_t out = (size_t)(arena->ptr + aligned_used);
    arena->used = required;
    return out;
}

size_t __dyn_alloc_with(size_t alloc, size_t size, size_t align) {
    if (dyn_is_arena_allocator(alloc)) {
        return dyn_arena_alloc((DynArenaAllocator*)alloc, size, align);
    }
    if (dyn_allocator_should_fail(alloc)) {
        return 0;
    }
    return __dyn_alloc(size, align);
}

size_t __dyn_realloc_with(size_t alloc, size_t ptr, size_t old_size, size_t new_size, size_t align) {
    if (dyn_is_arena_allocator(alloc)) {
        DynArenaAllocator* arena = (DynArenaAllocator*)alloc;
        if (ptr == 0) {
            return dyn_arena_alloc(arena, new_size, align);
        }
        if (new_size == 0) {
            return 0;
        }
        if (new_size <= old_size) {
            return ptr;
        }
        size_t next = dyn_arena_alloc(arena, new_size, align);
        if (next == 0) {
            return 0;
        }
        memcpy((void*)next, (const void*)ptr, old_size);
        return next;
    }
    if (dyn_allocator_should_fail(alloc)) {
        return 0;
    }
    return __dyn_realloc(ptr, old_size, new_size, align);
}

uint32_t __dyn_free_with(size_t alloc, size_t ptr, size_t size, size_t align) {
    if (dyn_is_arena_allocator(alloc)) {
        (void)ptr;
        (void)size;
        (void)align;
        return 1;
    }
    (void)alloc;
    return __dyn_free(ptr, size, align);
}

uint32_t __dyn_mem_copy(size_t dst, size_t src, size_t size) {
    if (size == 0) {
        return 1;
    }
    if (dst == 0 || src == 0) {
        return 0;
    }
    memcpy((void*)dst, (const void*)src, size);
    return 1;
}

uint32_t __dyn_mem_move(size_t dst, size_t src, size_t size) {
    if (size == 0) {
        return 1;
    }
    if (dst == 0 || src == 0) {
        return 0;
    }
    memmove((void*)dst, (const void*)src, size);
    return 1;
}

uint32_t __dyn_mem_set(size_t dst, uint32_t byte_value, size_t size) {
    if (size == 0) {
        return 1;
    }
    if (dst == 0) {
        return 0;
    }
    memset((void*)dst, (int)(byte_value & 0xFFu), size);
    return 1;
}

uint32_t __dyn_mem_eq(size_t lhs, size_t rhs, size_t size) {
    if (size == 0) {
        return 1;
    }
    if (lhs == 0 || rhs == 0) {
        return 0;
    }
    return memcmp((const void*)lhs, (const void*)rhs, size) == 0 ? 1u : 0u;
}

typedef struct DynVecI32 {
    size_t alloc;
    int32_t* ptr;
    size_t len;
    size_t cap;
} DynVecI32;

size_t __dyn_vec_i32_init(size_t alloc) {
    DynVecI32* vec = (DynVecI32*)malloc(sizeof(DynVecI32));
    if (vec == NULL) {
        return 0;
    }
    vec->alloc = alloc;
    vec->ptr = NULL;
    vec->len = 0;
    vec->cap = 0;
    return (size_t)vec;
}

uint32_t __dyn_vec_i32_deinit(size_t handle) {
    DynVecI32* vec = (DynVecI32*)handle;
    if (vec == NULL) {
        return 1;
    }
    if (vec->ptr != NULL) {
        if (!__dyn_free_with(vec->alloc, (size_t)vec->ptr, vec->cap * sizeof(int32_t), sizeof(int32_t))) {
            return 0;
        }
    }
    free(vec);
    return 1;
}

size_t __dyn_vec_i32_len(size_t handle) {
    DynVecI32* vec = (DynVecI32*)handle;
    if (vec == NULL) {
        return 0;
    }
    return vec->len;
}

size_t __dyn_vec_i32_cap(size_t handle) {
    DynVecI32* vec = (DynVecI32*)handle;
    if (vec == NULL) {
        return 0;
    }
    return vec->cap;
}

static uint32_t dyn_vec_i32_reserve_exact(DynVecI32* vec, size_t new_cap) {
    if (new_cap <= vec->cap) {
        return 1;
    }
    if (new_cap > ((size_t)-1) / sizeof(int32_t)) {
        return 0;
    }
    size_t new_size = new_cap * sizeof(int32_t);
    size_t old_size = vec->cap * sizeof(int32_t);
    size_t next = __dyn_realloc_with(vec->alloc, (size_t)vec->ptr, old_size, new_size, sizeof(int32_t));
    if (next == 0) {
        return 0;
    }
    vec->ptr = (int32_t*)next;
    vec->cap = new_cap;
    return 1;
}

uint32_t __dyn_vec_i32_push(size_t handle, int32_t value) {
    DynVecI32* vec = (DynVecI32*)handle;
    if (vec == NULL) {
        return 0;
    }
    if (vec->len == vec->cap) {
        size_t next_cap = vec->cap == 0 ? 4 : vec->cap * 2;
        if (next_cap < vec->cap) {
            return 0;
        }
        if (!dyn_vec_i32_reserve_exact(vec, next_cap)) {
            return 0;
        }
    }
    vec->ptr[vec->len] = value;
    vec->len += 1;
    return 1;
}

int32_t __dyn_vec_i32_get(size_t handle, size_t index) {
    DynVecI32* vec = (DynVecI32*)handle;
    if (vec == NULL || index >= vec->len) {
        return 0;
    }
    return vec->ptr[index];
}

uint32_t __dyn_vec_i32_set(size_t handle, size_t index, int32_t value) {
    DynVecI32* vec = (DynVecI32*)handle;
    if (vec == NULL || index >= vec->len) {
        return 0;
    }
    vec->ptr[index] = value;
    return 1;
}

int32_t __dyn_vec_i32_pop(size_t handle) {
    DynVecI32* vec = (DynVecI32*)handle;
    if (vec == NULL || vec->len == 0) {
        return 0;
    }
    vec->len -= 1;
    return vec->ptr[vec->len];
}

uint32_t __dyn_vec_i32_clear(size_t handle) {
    DynVecI32* vec = (DynVecI32*)handle;
    if (vec == NULL) {
        return 0;
    }
    vec->len = 0;
    return 1;
}

uint32_t __dyn_vec_i32_reserve(size_t handle, size_t new_cap) {
    DynVecI32* vec = (DynVecI32*)handle;
    if (vec == NULL) {
        return 0;
    }
    return dyn_vec_i32_reserve_exact(vec, new_cap);
}

size_t std_vec_i32_init(size_t alloc) {
    return __dyn_vec_i32_init(alloc);
}

uint32_t std_vec_i32_deinit(size_t handle) {
    return __dyn_vec_i32_deinit(handle);
}

size_t std_vec_i32_len(size_t handle) {
    return __dyn_vec_i32_len(handle);
}

size_t std_vec_i32_cap(size_t handle) {
    return __dyn_vec_i32_cap(handle);
}

uint32_t std_vec_i32_push(size_t handle, int32_t value) {
    return __dyn_vec_i32_push(handle, value);
}

int32_t std_vec_i32_get(size_t handle, size_t index) {
    return __dyn_vec_i32_get(handle, index);
}

uint32_t std_vec_i32_set(size_t handle, size_t index, int32_t value) {
    return __dyn_vec_i32_set(handle, index, value);
}

int32_t std_vec_i32_pop(size_t handle) {
    return __dyn_vec_i32_pop(handle);
}

uint32_t std_vec_i32_clear(size_t handle) {
    return __dyn_vec_i32_clear(handle);
}

uint32_t std_vec_i32_reserve(size_t handle, size_t new_cap) {
    return __dyn_vec_i32_reserve(handle, new_cap);
}

typedef struct DynVecRaw {
    size_t alloc;
    uint8_t* ptr;
    size_t len;
    size_t cap;
    size_t elem_size;
    size_t elem_align;
} DynVecRaw;

size_t __dyn_vec_raw_init(size_t alloc, size_t elem_size, size_t elem_align) {
    if (elem_size == 0 || !dyn_is_power_of_two(elem_align)) {
        return 0;
    }
    DynVecRaw* vec = (DynVecRaw*)malloc(sizeof(DynVecRaw));
    if (vec == NULL) {
        return 0;
    }
    vec->alloc = alloc;
    vec->ptr = NULL;
    vec->len = 0;
    vec->cap = 0;
    vec->elem_size = elem_size;
    vec->elem_align = elem_align;
    return (size_t)vec;
}

uint32_t __dyn_vec_raw_deinit(size_t handle) {
    DynVecRaw* vec = (DynVecRaw*)handle;
    if (vec == NULL) {
        return 1;
    }
    if (vec->ptr != NULL) {
        size_t size = vec->cap * vec->elem_size;
        if (!__dyn_free_with(vec->alloc, (size_t)vec->ptr, size, vec->elem_align)) {
            return 0;
        }
    }
    free(vec);
    return 1;
}

size_t __dyn_vec_raw_len(size_t handle) {
    DynVecRaw* vec = (DynVecRaw*)handle;
    if (vec == NULL) {
        return 0;
    }
    return vec->len;
}

size_t __dyn_vec_raw_cap(size_t handle) {
    DynVecRaw* vec = (DynVecRaw*)handle;
    if (vec == NULL) {
        return 0;
    }
    return vec->cap;
}

static uint32_t dyn_vec_raw_reserve_exact(DynVecRaw* vec, size_t new_cap) {
    if (new_cap <= vec->cap) {
        return 1;
    }
    if (vec->elem_size != 0 && new_cap > ((size_t)-1) / vec->elem_size) {
        return 0;
    }
    size_t old_size = vec->cap * vec->elem_size;
    size_t new_size = new_cap * vec->elem_size;
    size_t next = __dyn_realloc_with(vec->alloc, (size_t)vec->ptr, old_size, new_size, vec->elem_align);
    if (next == 0) {
        return 0;
    }
    vec->ptr = (uint8_t*)next;
    vec->cap = new_cap;
    return 1;
}

uint32_t __dyn_vec_raw_push_u64(size_t handle, uint64_t value) {
    DynVecRaw* vec = (DynVecRaw*)handle;
    if (vec == NULL || vec->elem_size > sizeof(uint64_t)) {
        return 0;
    }
    if (vec->len == vec->cap) {
        size_t next_cap = vec->cap == 0 ? 4 : vec->cap * 2;
        if (next_cap < vec->cap) {
            return 0;
        }
        if (!dyn_vec_raw_reserve_exact(vec, next_cap)) {
            return 0;
        }
    }
    uint8_t* dst = vec->ptr + (vec->len * vec->elem_size);
    memcpy(dst, &value, vec->elem_size);
    vec->len += 1;
    return 1;
}

uint64_t __dyn_vec_raw_get_u64(size_t handle, size_t index) {
    DynVecRaw* vec = (DynVecRaw*)handle;
    if (vec == NULL || index >= vec->len || vec->elem_size > sizeof(uint64_t)) {
        return 0;
    }
    uint64_t out = 0;
    const uint8_t* src = vec->ptr + (index * vec->elem_size);
    memcpy(&out, src, vec->elem_size);
    return out;
}

uint32_t __dyn_vec_raw_set_u64(size_t handle, size_t index, uint64_t value) {
    DynVecRaw* vec = (DynVecRaw*)handle;
    if (vec == NULL || index >= vec->len || vec->elem_size > sizeof(uint64_t)) {
        return 0;
    }
    uint8_t* dst = vec->ptr + (index * vec->elem_size);
    memcpy(dst, &value, vec->elem_size);
    return 1;
}

uint64_t __dyn_vec_raw_pop_u64(size_t handle) {
    DynVecRaw* vec = (DynVecRaw*)handle;
    if (vec == NULL || vec->len == 0 || vec->elem_size > sizeof(uint64_t)) {
        return 0;
    }
    vec->len -= 1;
    uint64_t out = 0;
    const uint8_t* src = vec->ptr + (vec->len * vec->elem_size);
    memcpy(&out, src, vec->elem_size);
    return out;
}

uint32_t __dyn_vec_raw_clear(size_t handle) {
    DynVecRaw* vec = (DynVecRaw*)handle;
    if (vec == NULL) {
        return 0;
    }
    vec->len = 0;
    return 1;
}

uint32_t __dyn_vec_raw_reserve(size_t handle, size_t new_cap) {
    DynVecRaw* vec = (DynVecRaw*)handle;
    if (vec == NULL) {
        return 0;
    }
    return dyn_vec_raw_reserve_exact(vec, new_cap);
}

size_t __dyn_vec_raw_ptr(size_t handle, size_t index) {
    DynVecRaw* vec = (DynVecRaw*)handle;
    if (vec == NULL || index >= vec->len) {
        return 0;
    }
    return (size_t)(vec->ptr + (index * vec->elem_size));
}

uint32_t __dyn_vec_raw_push_bytes(size_t handle, size_t src, size_t src_size) {
    DynVecRaw* vec = (DynVecRaw*)handle;
    if (vec == NULL || src == 0 || src_size != vec->elem_size) {
        return 0;
    }
    if (vec->len == vec->cap) {
        size_t next_cap = vec->cap == 0 ? 4 : vec->cap * 2;
        if (next_cap < vec->cap) {
            return 0;
        }
        if (!dyn_vec_raw_reserve_exact(vec, next_cap)) {
            return 0;
        }
    }
    uint8_t* dst = vec->ptr + (vec->len * vec->elem_size);
    memcpy(dst, (const void*)src, vec->elem_size);
    vec->len += 1;
    return 1;
}

uint32_t __dyn_vec_raw_get_bytes(size_t handle, size_t index, size_t dst, size_t dst_size) {
    DynVecRaw* vec = (DynVecRaw*)handle;
    if (vec == NULL || index >= vec->len || dst == 0 || dst_size != vec->elem_size) {
        return 0;
    }
    const uint8_t* src = vec->ptr + (index * vec->elem_size);
    memcpy((void*)dst, src, vec->elem_size);
    return 1;
}

uint32_t __dyn_vec_raw_set_bytes(size_t handle, size_t index, size_t src, size_t src_size) {
    DynVecRaw* vec = (DynVecRaw*)handle;
    if (vec == NULL || index >= vec->len || src == 0 || src_size != vec->elem_size) {
        return 0;
    }
    uint8_t* dst = vec->ptr + (index * vec->elem_size);
    memcpy(dst, (const void*)src, vec->elem_size);
    return 1;
}

uint32_t __dyn_vec_raw_pop_bytes(size_t handle, size_t dst, size_t dst_size) {
    DynVecRaw* vec = (DynVecRaw*)handle;
    if (vec == NULL || vec->len == 0 || dst == 0 || dst_size != vec->elem_size) {
        return 0;
    }
    vec->len -= 1;
    const uint8_t* src = vec->ptr + (vec->len * vec->elem_size);
    memcpy((void*)dst, src, vec->elem_size);
    return 1;
}

size_t std_vec_init(size_t alloc, size_t elem_size, size_t elem_align) {
    return __dyn_vec_raw_init(alloc, elem_size, elem_align);
}

uint32_t std_vec_deinit(size_t handle) {
    return __dyn_vec_raw_deinit(handle);
}

size_t std_vec_len(size_t handle) {
    return __dyn_vec_raw_len(handle);
}

size_t std_vec_cap(size_t handle) {
    return __dyn_vec_raw_cap(handle);
}

uint32_t std_vec_push_u64(size_t handle, uint64_t value) {
    return __dyn_vec_raw_push_u64(handle, value);
}

uint64_t std_vec_get_u64(size_t handle, size_t index) {
    return __dyn_vec_raw_get_u64(handle, index);
}

uint32_t std_vec_set_u64(size_t handle, size_t index, uint64_t value) {
    return __dyn_vec_raw_set_u64(handle, index, value);
}

uint64_t std_vec_pop_u64(size_t handle) {
    return __dyn_vec_raw_pop_u64(handle);
}

uint32_t std_vec_clear(size_t handle) {
    return __dyn_vec_raw_clear(handle);
}

uint32_t std_vec_reserve(size_t handle, size_t new_cap) {
    return __dyn_vec_raw_reserve(handle, new_cap);
}

size_t std_vec_ptr(size_t handle, size_t index) {
    return __dyn_vec_raw_ptr(handle, index);
}

uint32_t std_vec_push_bytes(size_t handle, size_t src, size_t src_size) {
    return __dyn_vec_raw_push_bytes(handle, src, src_size);
}

uint32_t std_vec_get_bytes(size_t handle, size_t index, size_t dst, size_t dst_size) {
    return __dyn_vec_raw_get_bytes(handle, index, dst, dst_size);
}

uint32_t std_vec_set_bytes(size_t handle, size_t index, size_t src, size_t src_size) {
    return __dyn_vec_raw_set_bytes(handle, index, src, src_size);
}

uint32_t std_vec_pop_bytes(size_t handle, size_t dst, size_t dst_size) {
    return __dyn_vec_raw_pop_bytes(handle, dst, dst_size);
}

uint32_t __dyn_io_write_i32(int32_t value, uint32_t newline) {
    if (newline != 0) {
        return printf("%d\n", value) >= 0 ? 1u : 0u;
    }
    return printf("%d", value) >= 0 ? 1u : 0u;
}

uint32_t __dyn_io_write(size_t cstr, uint32_t newline) {
    if (cstr == 0) {
        return 0u;
    }
    if (newline != 0) {
        return fprintf(stdout, "%s\n", (const char*)cstr) >= 0 ? 1u : 0u;
    }
    return fputs((const char*)cstr, stdout) >= 0 ? 1u : 0u;
}

uint32_t std_io_print_i32(int32_t value) {
    return __dyn_io_write_i32(value, 0u);
}

uint32_t std_io_println_i32(int32_t value) {
    return __dyn_io_write_i32(value, 1u);
}

uint32_t std_io_print(size_t cstr) {
    return __dyn_io_write(cstr, 0u);
}

uint32_t std_io_println(size_t cstr) {
    return __dyn_io_write(cstr, 1u);
}
"#
}

struct FunctionSymbols {
    by_key: BTreeMap<(usize, String), FuncId>,
    by_name: BTreeMap<String, FuncId>,
    param_types_by_id: BTreeMap<u32, Vec<Type>>,
}

struct RuntimeIntrinsic {
    name: &'static str,
    params: Vec<Type>,
    ret: Type,
}

fn declare_function_symbols(
    mir: &MirProgram,
    module: &mut ObjectModule,
) -> Result<FunctionSymbols, String> {
    let mut by_key = BTreeMap::new();
    let mut by_name = BTreeMap::new();
    let mut param_types_by_id = BTreeMap::new();

    for mir_module in &mir.modules {
        for function in &mir_module.functions {
            let mut signature = module.make_signature();
            let ret_scalar = parse_return_scalar(function.return_type.as_deref());
            let mut param_types = Vec::with_capacity(function.param_types.len());
            for param in &function.param_types {
                let clif_ty = if matches!(param, MirValueType::Unknown | MirValueType::Function) {
                    module.target_config().pointer_type()
                } else {
                    mir_type_to_clif(param, ret_scalar)
                };
                signature.params.push(AbiParam::new(clif_ty));
                param_types.push(clif_ty);
            }

            let exported = mir_module.key.module_name == "main" && function.name == "main";
            signature
                .returns
                .push(AbiParam::new(if exported { I32 } else { ret_scalar.ty() }));
            let symbol_name = if exported {
                "main".to_string()
            } else {
                format!(
                    "dyn_m{}_{}",
                    mir_module.module_id.0,
                    sanitize_symbol_name(&function.name)
                )
            };

            let func_id = module
                .declare_function(
                    &symbol_name,
                    if exported {
                        Linkage::Export
                    } else {
                        Linkage::Local
                    },
                    &signature,
                )
                .map_err(|err| format!("failed to declare function '{}': {err}", function.name))?;

            by_key.insert((mir_module.module_id.0, function.name.clone()), func_id);
            by_name.insert(
                format!("#{}::{}", mir_module.module_id.0, function.name),
                func_id,
            );
            by_name.entry(function.name.clone()).or_insert(func_id);
            param_types_by_id.insert(func_id.as_u32(), param_types);
        }
    }

    for intrinsic in runtime_intrinsics(module.target_config().pointer_type()) {
        let mut signature = module.make_signature();
        for param in &intrinsic.params {
            signature.params.push(AbiParam::new(*param));
        }
        signature.returns.push(AbiParam::new(intrinsic.ret));
        let func_id = module
            .declare_function(intrinsic.name, Linkage::Import, &signature)
            .map_err(|err| {
                format!(
                    "failed to declare runtime intrinsic '{}': {err}",
                    intrinsic.name
                )
            })?;
        by_name.entry(intrinsic.name.to_string()).or_insert(func_id);
        param_types_by_id.insert(func_id.as_u32(), intrinsic.params);
    }

    Ok(FunctionSymbols {
        by_key,
        by_name,
        param_types_by_id,
    })
}

fn runtime_intrinsics(pointer_ty: Type) -> Vec<RuntimeIntrinsic> {
    vec![
        RuntimeIntrinsic {
            name: "__dyn_alloc",
            params: vec![pointer_ty, pointer_ty],
            ret: pointer_ty,
        },
        RuntimeIntrinsic {
            name: "__dyn_realloc",
            params: vec![pointer_ty, pointer_ty, pointer_ty, pointer_ty],
            ret: pointer_ty,
        },
        RuntimeIntrinsic {
            name: "__dyn_free",
            params: vec![pointer_ty, pointer_ty, pointer_ty],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "__dyn_c_allocator",
            params: vec![],
            ret: pointer_ty,
        },
        RuntimeIntrinsic {
            name: "__dyn_test_failing_allocator",
            params: vec![],
            ret: pointer_ty,
        },
        RuntimeIntrinsic {
            name: "__dyn_test_set_fail_after",
            params: vec![pointer_ty],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "__dyn_test_identity_i32_fn",
            params: vec![],
            ret: pointer_ty,
        },
        RuntimeIntrinsic {
            name: "__dyn_arena_allocator",
            params: vec![pointer_ty],
            ret: pointer_ty,
        },
        RuntimeIntrinsic {
            name: "__dyn_arena_reset",
            params: vec![pointer_ty],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "__dyn_arena_deinit",
            params: vec![pointer_ty],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "__dyn_alloc_with",
            params: vec![pointer_ty, pointer_ty, pointer_ty],
            ret: pointer_ty,
        },
        RuntimeIntrinsic {
            name: "__dyn_realloc_with",
            params: vec![pointer_ty, pointer_ty, pointer_ty, pointer_ty, pointer_ty],
            ret: pointer_ty,
        },
        RuntimeIntrinsic {
            name: "__dyn_free_with",
            params: vec![pointer_ty, pointer_ty, pointer_ty, pointer_ty],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "__dyn_mem_copy",
            params: vec![pointer_ty, pointer_ty, pointer_ty],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "__dyn_mem_move",
            params: vec![pointer_ty, pointer_ty, pointer_ty],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "__dyn_mem_set",
            params: vec![pointer_ty, I32, pointer_ty],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "__dyn_mem_eq",
            params: vec![pointer_ty, pointer_ty, pointer_ty],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "__dyn_vec_i32_init",
            params: vec![pointer_ty],
            ret: pointer_ty,
        },
        RuntimeIntrinsic {
            name: "__dyn_vec_i32_deinit",
            params: vec![pointer_ty],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "__dyn_vec_i32_len",
            params: vec![pointer_ty],
            ret: pointer_ty,
        },
        RuntimeIntrinsic {
            name: "__dyn_vec_i32_cap",
            params: vec![pointer_ty],
            ret: pointer_ty,
        },
        RuntimeIntrinsic {
            name: "__dyn_vec_i32_push",
            params: vec![pointer_ty, I32],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "__dyn_vec_i32_get",
            params: vec![pointer_ty, pointer_ty],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "__dyn_vec_i32_set",
            params: vec![pointer_ty, pointer_ty, I32],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "__dyn_vec_i32_pop",
            params: vec![pointer_ty],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "__dyn_vec_i32_clear",
            params: vec![pointer_ty],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "__dyn_vec_i32_reserve",
            params: vec![pointer_ty, pointer_ty],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "std_vec_i32_init",
            params: vec![pointer_ty],
            ret: pointer_ty,
        },
        RuntimeIntrinsic {
            name: "std_vec_i32_deinit",
            params: vec![pointer_ty],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "std_vec_i32_len",
            params: vec![pointer_ty],
            ret: pointer_ty,
        },
        RuntimeIntrinsic {
            name: "std_vec_i32_cap",
            params: vec![pointer_ty],
            ret: pointer_ty,
        },
        RuntimeIntrinsic {
            name: "std_vec_i32_push",
            params: vec![pointer_ty, I32],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "std_vec_i32_get",
            params: vec![pointer_ty, pointer_ty],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "std_vec_i32_set",
            params: vec![pointer_ty, pointer_ty, I32],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "std_vec_i32_pop",
            params: vec![pointer_ty],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "std_vec_i32_clear",
            params: vec![pointer_ty],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "std_vec_i32_reserve",
            params: vec![pointer_ty, pointer_ty],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "__dyn_vec_raw_init",
            params: vec![pointer_ty, pointer_ty, pointer_ty],
            ret: pointer_ty,
        },
        RuntimeIntrinsic {
            name: "__dyn_vec_raw_deinit",
            params: vec![pointer_ty],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "__dyn_vec_raw_len",
            params: vec![pointer_ty],
            ret: pointer_ty,
        },
        RuntimeIntrinsic {
            name: "__dyn_vec_raw_cap",
            params: vec![pointer_ty],
            ret: pointer_ty,
        },
        RuntimeIntrinsic {
            name: "__dyn_vec_raw_push_u64",
            params: vec![pointer_ty, I64],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "__dyn_vec_raw_get_u64",
            params: vec![pointer_ty, pointer_ty],
            ret: I64,
        },
        RuntimeIntrinsic {
            name: "__dyn_vec_raw_set_u64",
            params: vec![pointer_ty, pointer_ty, I64],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "__dyn_vec_raw_pop_u64",
            params: vec![pointer_ty],
            ret: I64,
        },
        RuntimeIntrinsic {
            name: "__dyn_vec_raw_clear",
            params: vec![pointer_ty],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "__dyn_vec_raw_reserve",
            params: vec![pointer_ty, pointer_ty],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "__dyn_vec_raw_ptr",
            params: vec![pointer_ty, pointer_ty],
            ret: pointer_ty,
        },
        RuntimeIntrinsic {
            name: "__dyn_vec_raw_push_bytes",
            params: vec![pointer_ty, pointer_ty, pointer_ty],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "__dyn_vec_raw_get_bytes",
            params: vec![pointer_ty, pointer_ty, pointer_ty, pointer_ty],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "__dyn_vec_raw_set_bytes",
            params: vec![pointer_ty, pointer_ty, pointer_ty, pointer_ty],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "__dyn_vec_raw_pop_bytes",
            params: vec![pointer_ty, pointer_ty, pointer_ty],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "std_vec_init",
            params: vec![pointer_ty, pointer_ty, pointer_ty],
            ret: pointer_ty,
        },
        RuntimeIntrinsic {
            name: "std_vec_deinit",
            params: vec![pointer_ty],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "std_vec_len",
            params: vec![pointer_ty],
            ret: pointer_ty,
        },
        RuntimeIntrinsic {
            name: "std_vec_cap",
            params: vec![pointer_ty],
            ret: pointer_ty,
        },
        RuntimeIntrinsic {
            name: "std_vec_push_u64",
            params: vec![pointer_ty, I64],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "std_vec_get_u64",
            params: vec![pointer_ty, pointer_ty],
            ret: I64,
        },
        RuntimeIntrinsic {
            name: "std_vec_set_u64",
            params: vec![pointer_ty, pointer_ty, I64],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "std_vec_pop_u64",
            params: vec![pointer_ty],
            ret: I64,
        },
        RuntimeIntrinsic {
            name: "std_vec_clear",
            params: vec![pointer_ty],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "std_vec_reserve",
            params: vec![pointer_ty, pointer_ty],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "std_vec_ptr",
            params: vec![pointer_ty, pointer_ty],
            ret: pointer_ty,
        },
        RuntimeIntrinsic {
            name: "std_vec_push_bytes",
            params: vec![pointer_ty, pointer_ty, pointer_ty],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "std_vec_get_bytes",
            params: vec![pointer_ty, pointer_ty, pointer_ty, pointer_ty],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "std_vec_set_bytes",
            params: vec![pointer_ty, pointer_ty, pointer_ty, pointer_ty],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "std_vec_pop_bytes",
            params: vec![pointer_ty, pointer_ty, pointer_ty],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "__dyn_io_write_i32",
            params: vec![I32, I32],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "__dyn_io_write",
            params: vec![pointer_ty, I32],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "std_io_print_i32",
            params: vec![I32],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "std_io_println_i32",
            params: vec![I32],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "std_io_print",
            params: vec![pointer_ty],
            ret: I32,
        },
        RuntimeIntrinsic {
            name: "std_io_println",
            params: vec![pointer_ty],
            ret: I32,
        },
    ]
}

fn sanitize_symbol_name(name: &str) -> String {
    name.chars()
        .map(|ch| {
            if ch.is_ascii_alphanumeric() || ch == '_' {
                ch
            } else {
                '_'
            }
        })
        .collect()
}

#[derive(Debug, Copy, Clone)]
enum ScalarType {
    Int { ty: Type, signed: bool },
    Float { ty: Type },
}

impl ScalarType {
    fn ty(self) -> Type {
        match self {
            Self::Int { ty, .. } | Self::Float { ty } => ty,
        }
    }
}

fn compile_function(
    module: &mut ObjectModule,
    function: &MirFunction,
    current_module_id: usize,
    exported: bool,
    symbols_by_key: &BTreeMap<(usize, String), FuncId>,
    symbols_by_name: &BTreeMap<String, FuncId>,
    symbol_param_types_by_id: &BTreeMap<u32, Vec<Type>>,
) -> Result<(), String> {
    let func_id = symbols_by_key
        .get(&(current_module_id, function.name.clone()))
        .copied()
        .ok_or_else(|| format!("missing symbol for function '{}'", function.name))?;

    let scalar = parse_return_scalar(function.return_type.as_deref());
    let mut ctx = module.make_context();
    let signature_ret_ty = if exported { I32 } else { scalar.ty() };
    for param in &function.param_types {
        let param_ty = if matches!(param, MirValueType::Unknown | MirValueType::Function) {
            module.target_config().pointer_type()
        } else {
            mir_type_to_clif(param, scalar)
        };
        ctx.func.signature.params.push(AbiParam::new(param_ty));
    }
    ctx.func
        .signature
        .returns
        .push(AbiParam::new(signature_ret_ty));

    let mut fn_builder_ctx = FunctionBuilderContext::new();
    let mut builder = FunctionBuilder::new(&mut ctx.func, &mut fn_builder_ctx);

    let mut clif_blocks = Vec::with_capacity(function.blocks.len());
    for _ in &function.blocks {
        clif_blocks.push(builder.create_block());
    }

    let mut phi_layout =
        BTreeMap::<usize, Vec<(MirValueId, BTreeMap<usize, MirValueId>, MirValueType)>>::new();
    for block in &function.blocks {
        let mut entries = Vec::new();
        for instruction in &block.instructions {
            if let MirInstr::Phi { dest, sources, ty } = instruction {
                let mut source_map = BTreeMap::new();
                for (pred, value) in sources {
                    source_map.insert(pred.0, *value);
                }
                entries.push((*dest, source_map, ty.clone()));
            }
        }
        phi_layout.insert(block.id.0, entries);
    }

    for block in &function.blocks {
        if let Some(phi_entries) = phi_layout.get(&block.id.0) {
            for (_, _, ty) in phi_entries {
                builder.append_block_param(clif_blocks[block.id.0], mir_type_to_clif(ty, scalar));
            }
        }
    }

    let mut global_lowered = BTreeMap::<MirValueId, LoweredValue>::new();

    for block in &function.blocks {
        let clif_block = clif_blocks[block.id.0];
        builder.switch_to_block(clif_block);
        if block.id.0 == function.entry.0 {
            builder.append_block_params_for_function_params(clif_block);
            builder.seal_block(clif_block);
        }

        let mut lowered = global_lowered.clone();
        if let Some(phi_entries) = phi_layout.get(&block.id.0) {
            for (idx, (dest, _, ty)) in phi_entries.iter().enumerate() {
                let val = builder.block_params(clif_block)[idx];
                lowered.insert(*dest, LoweredValue::from_typed_value(val, ty));
                global_lowered.insert(*dest, LoweredValue::from_typed_value(val, ty));
            }
        }

        for instruction in &block.instructions {
            match instruction {
                MirInstr::Eval { dest, value, ty } => {
                    let lowered_value = lower_value(
                        value,
                        ty,
                        &mut builder,
                        &lowered,
                        current_module_id,
                        scalar,
                        symbols_by_key,
                        symbols_by_name,
                        symbol_param_types_by_id,
                        module,
                    );
                    lowered.insert(*dest, lowered_value.clone());
                    global_lowered.insert(*dest, lowered_value);
                }
                MirInstr::Phi { .. } => {}
            }
        }

        match &block.terminator {
            Some(MirTerminator::Return(value)) => {
                let ret = value
                    .and_then(|id| lowered.get(&id))
                    .and_then(|value| match value {
                        LoweredValue::FunctionSymbol(func_id) => {
                            let func_ref = module.declare_func_in_func(*func_id, builder.func);
                            Some(
                                builder
                                    .ins()
                                    .func_addr(module.target_config().pointer_type(), func_ref),
                            )
                        }
                        _ => value.as_value(),
                    })
                    .map(|value| cast_scalar(&mut builder, value, signature_ret_ty, scalar))
                    .unwrap_or_else(|| zero_for_type(&mut builder, signature_ret_ty));
                builder.ins().return_(&[ret]);
            }
            Some(MirTerminator::Goto(target)) => {
                let args = edge_args(
                    block.id.0,
                    target.0,
                    &phi_layout,
                    &lowered,
                    scalar,
                    &mut builder,
                );
                builder.ins().jump(clif_blocks[target.0], &args);
            }
            Some(MirTerminator::Branch {
                condition,
                then_block,
                else_block,
            }) => {
                let cond = lowered
                    .get(condition)
                    .and_then(LoweredValue::as_int)
                    .unwrap_or_else(|| zero_for_scalar(&mut builder, scalar));
                let then_args = edge_args(
                    block.id.0,
                    then_block.0,
                    &phi_layout,
                    &lowered,
                    scalar,
                    &mut builder,
                );
                let else_args = edge_args(
                    block.id.0,
                    else_block.0,
                    &phi_layout,
                    &lowered,
                    scalar,
                    &mut builder,
                );
                builder.ins().brif(
                    cond,
                    clif_blocks[then_block.0],
                    &then_args,
                    clif_blocks[else_block.0],
                    &else_args,
                );
            }
            Some(MirTerminator::Unreachable) => {
                builder.ins().trap(TrapCode::unwrap_user(1));
            }
            None => {
                let ret = zero_for_type(&mut builder, signature_ret_ty);
                builder.ins().return_(&[ret]);
            }
        }
    }

    let mut sealed = std::collections::BTreeSet::new();
    sealed.insert(function.entry.0);
    for block in &function.blocks {
        match &block.terminator {
            Some(MirTerminator::Goto(target)) => {
                if sealed.insert(target.0) {
                    builder.seal_block(clif_blocks[target.0]);
                }
            }
            Some(MirTerminator::Branch {
                then_block,
                else_block,
                ..
            }) => {
                if sealed.insert(then_block.0) {
                    builder.seal_block(clif_blocks[then_block.0]);
                }
                if sealed.insert(else_block.0) {
                    builder.seal_block(clif_blocks[else_block.0]);
                }
            }
            _ => {}
        }
    }

    for (idx, clif_block) in clif_blocks.iter().enumerate() {
        if sealed.insert(idx) {
            builder.seal_block(*clif_block);
        }
    }

    builder.finalize();

    module
        .define_function(func_id, &mut ctx)
        .map_err(|err| format!("failed to define function '{}': {err}", function.name))?;
    module.clear_context(&mut ctx);
    Ok(())
}

fn edge_args(
    from_block: usize,
    to_block: usize,
    phi_layout: &BTreeMap<usize, Vec<(MirValueId, BTreeMap<usize, MirValueId>, MirValueType)>>,
    lowered: &BTreeMap<MirValueId, LoweredValue>,
    scalar: ScalarType,
    builder: &mut FunctionBuilder,
) -> Vec<Value> {
    let mut args = Vec::new();
    if let Some(phi_entries) = phi_layout.get(&to_block) {
        for (_, source_map, ty) in phi_entries {
            let value = source_map
                .get(&from_block)
                .and_then(|id| lowered.get(id))
                .and_then(LoweredValue::as_value)
                .map(|value| cast_scalar(builder, value, mir_type_to_clif(ty, scalar), scalar))
                .unwrap_or_else(|| zero_for_type(builder, mir_type_to_clif(ty, scalar)));
            args.push(value);
        }
    }
    args
}

#[derive(Debug, Clone)]
enum LoweredValue {
    Int(Value),
    Float(Value),
    FunctionSymbol(FuncId),
    Struct(BTreeMap<String, LoweredValue>),
    StructMemory {
        slot: StackSlot,
        fields: BTreeMap<String, (Type, i32)>,
        ordered: Vec<(Type, i32)>,
    },
    PointerSlice {
        base_addr: Value,
        elem_ty: Type,
        stride: i64,
    },
    EnumVariant {
        variant: String,
        payload: Vec<LoweredValue>,
    },
    EnumMemory {
        slot: StackSlot,
        ordered: Vec<(Type, i32)>,
    },
}

impl LoweredValue {
    fn from_typed_value(value: Value, ty: &MirValueType) -> Self {
        match ty {
            MirValueType::Float { .. } => Self::Float(value),
            MirValueType::Int { .. } | MirValueType::Bool => Self::Int(value),
            MirValueType::Function => Self::Int(value),
            MirValueType::Unknown => Self::Int(value),
            MirValueType::Type => Self::Int(value),
        }
    }

    fn as_int(&self) -> Option<Value> {
        match self {
            Self::Int(value) => Some(*value),
            Self::PointerSlice { base_addr, .. } => Some(*base_addr),
            Self::Float(_)
            | Self::FunctionSymbol(_)
            | Self::Struct(_)
            | Self::StructMemory { .. }
            | Self::EnumVariant { .. }
            | Self::EnumMemory { .. } => None,
        }
    }

    fn as_float(&self) -> Option<Value> {
        match self {
            Self::Float(value) => Some(*value),
            Self::Int(_)
            | Self::FunctionSymbol(_)
            | Self::Struct(_)
            | Self::StructMemory { .. }
            | Self::PointerSlice { .. }
            | Self::EnumVariant { .. }
            | Self::EnumMemory { .. } => None,
        }
    }

    fn as_value(&self) -> Option<Value> {
        match self {
            Self::Int(value) | Self::Float(value) => Some(*value),
            Self::PointerSlice { base_addr, .. } => Some(*base_addr),
            Self::FunctionSymbol(_)
            | Self::Struct(_)
            | Self::StructMemory { .. }
            | Self::EnumVariant { .. }
            | Self::EnumMemory { .. } => None,
        }
    }
}

fn lower_value(
    value: &MirValue,
    value_ty: &MirValueType,
    builder: &mut FunctionBuilder,
    lowered: &BTreeMap<MirValueId, LoweredValue>,
    current_module_id: usize,
    scalar: ScalarType,
    symbols_by_key: &BTreeMap<(usize, String), FuncId>,
    symbols_by_name: &BTreeMap<String, FuncId>,
    symbol_param_types_by_id: &BTreeMap<u32, Vec<Type>>,
    module: &mut ObjectModule,
) -> LoweredValue {
    match value {
        MirValue::Literal(literal) => lower_literal(literal, value_ty, scalar, builder),
        MirValue::Ident(name) => {
            if let Some(func_id) = symbols_by_key
                .get(&(current_module_id, name.clone()))
                .copied()
                .or_else(|| symbols_by_name.get(name).copied())
            {
                LoweredValue::FunctionSymbol(func_id)
            } else {
                zero_lowered_for_type(builder, value_ty, scalar)
            }
        }
        MirValue::Param { index } => {
            let Some(block) = builder.current_block() else {
                return zero_lowered_for_type(builder, value_ty, scalar);
            };
            let Some(value) = builder.block_params(block).get(*index).copied() else {
                return zero_lowered_for_type(builder, value_ty, scalar);
            };
            LoweredValue::from_typed_value(value, value_ty)
        }
        MirValue::Unary { op, operand } => {
            let Some(operand_value) = lowered.get(operand).cloned() else {
                return zero_lowered_for_type(builder, value_ty, scalar);
            };
            match op {
                UnaryOp::Ref => match operand_value {
                    LoweredValue::StructMemory { slot, .. } => {
                        let addr = builder.ins().stack_addr(
                            module.target_config().pointer_type(),
                            slot,
                            0,
                        );
                        LoweredValue::Int(addr)
                    }
                    LoweredValue::Struct(fields) => {
                        let lowered_pairs = fields.into_iter().collect::<Vec<_>>();
                        match materialize_struct_memory(builder, &lowered_pairs) {
                            Some(LoweredValue::StructMemory { slot, .. }) => {
                                let addr = builder.ins().stack_addr(
                                    module.target_config().pointer_type(),
                                    slot,
                                    0,
                                );
                                LoweredValue::Int(addr)
                            }
                            Some(other) => other,
                            None => zero_lowered_for_type(builder, value_ty, scalar),
                        }
                    }
                    LoweredValue::Int(value) => LoweredValue::Int(value),
                    LoweredValue::Float(value) => LoweredValue::Float(value),
                    _ => zero_lowered_for_type(builder, value_ty, scalar),
                },
                _ => {
                    let Some(operand) = operand_value.as_value() else {
                        return zero_lowered_for_type(builder, value_ty, scalar);
                    };
                    match (op, value_ty) {
                        (UnaryOp::Neg, MirValueType::Float { .. }) => {
                            LoweredValue::Float(builder.ins().fneg(operand))
                        }
                        (UnaryOp::Neg, _) => LoweredValue::Int(builder.ins().ineg(operand)),
                        (UnaryOp::Not, _) => {
                            let one = builder.ins().iconst(bool_storage_type(scalar), 1);
                            let casted =
                                cast_scalar(builder, operand, bool_storage_type(scalar), scalar);
                            LoweredValue::Int(builder.ins().bxor(casted, one))
                        }
                        (UnaryOp::BitNot, _) => {
                            let casted =
                                cast_scalar(builder, operand, bool_storage_type(scalar), scalar);
                            LoweredValue::Int(builder.ins().bnot(casted))
                        }
                        (UnaryOp::Ref, MirValueType::Float { .. }) => LoweredValue::Float(operand),
                        (UnaryOp::Ref, _) => LoweredValue::Int(operand),
                    }
                }
            }
        }
        MirValue::Binary { op, left, right } => {
            let left_val = lowered.get(left);
            let right_val = lowered.get(right);

            if matches!(value_ty, MirValueType::Float { .. }) {
                let Some(left) = left_val.and_then(LoweredValue::as_float).or_else(|| {
                    left_val.and_then(LoweredValue::as_int).map(|v| {
                        builder
                            .ins()
                            .fcvt_from_sint(mir_type_to_clif(value_ty, scalar), v)
                    })
                }) else {
                    return zero_lowered_for_type(builder, value_ty, scalar);
                };
                let Some(right) = right_val.and_then(LoweredValue::as_float).or_else(|| {
                    right_val.and_then(LoweredValue::as_int).map(|v| {
                        builder
                            .ins()
                            .fcvt_from_sint(mir_type_to_clif(value_ty, scalar), v)
                    })
                }) else {
                    return zero_lowered_for_type(builder, value_ty, scalar);
                };

                return match op {
                    BinaryOp::Add => LoweredValue::Float(builder.ins().fadd(left, right)),
                    BinaryOp::Sub => LoweredValue::Float(builder.ins().fsub(left, right)),
                    BinaryOp::Mul => LoweredValue::Float(builder.ins().fmul(left, right)),
                    BinaryOp::Div => LoweredValue::Float(builder.ins().fdiv(left, right)),
                    BinaryOp::Eq => {
                        let cmp = builder.ins().fcmp(
                            cranelift_codegen::ir::condcodes::FloatCC::Equal,
                            left,
                            right,
                        );
                        LoweredValue::Int(bool_to_int(builder, bool_storage_type(scalar), cmp))
                    }
                    BinaryOp::Ne => {
                        let cmp = builder.ins().fcmp(
                            cranelift_codegen::ir::condcodes::FloatCC::NotEqual,
                            left,
                            right,
                        );
                        LoweredValue::Int(bool_to_int(builder, bool_storage_type(scalar), cmp))
                    }
                    BinaryOp::Lt => {
                        let cmp = builder.ins().fcmp(
                            cranelift_codegen::ir::condcodes::FloatCC::LessThan,
                            left,
                            right,
                        );
                        LoweredValue::Int(bool_to_int(builder, bool_storage_type(scalar), cmp))
                    }
                    BinaryOp::Le => {
                        let cmp = builder.ins().fcmp(
                            cranelift_codegen::ir::condcodes::FloatCC::LessThanOrEqual,
                            left,
                            right,
                        );
                        LoweredValue::Int(bool_to_int(builder, bool_storage_type(scalar), cmp))
                    }
                    BinaryOp::Gt => {
                        let cmp = builder.ins().fcmp(
                            cranelift_codegen::ir::condcodes::FloatCC::GreaterThan,
                            left,
                            right,
                        );
                        LoweredValue::Int(bool_to_int(builder, bool_storage_type(scalar), cmp))
                    }
                    BinaryOp::Ge => {
                        let cmp = builder.ins().fcmp(
                            cranelift_codegen::ir::condcodes::FloatCC::GreaterThanOrEqual,
                            left,
                            right,
                        );
                        LoweredValue::Int(bool_to_int(builder, bool_storage_type(scalar), cmp))
                    }
                    _ => LoweredValue::Float(zero_for_type(
                        builder,
                        mir_type_to_clif(value_ty, scalar),
                    )),
                };
            }

            let signed = match value_ty {
                MirValueType::Int { signed, .. } => *signed,
                _ => matches!(scalar, ScalarType::Int { signed: true, .. }),
            };
            let int_ty = mir_type_to_clif(value_ty, scalar);
            let Some(left) = left_val
                .and_then(LoweredValue::as_int)
                .map(|v| cast_scalar(builder, v, int_ty, scalar))
            else {
                return zero_lowered_for_type(builder, value_ty, scalar);
            };
            let Some(right) = right_val
                .and_then(LoweredValue::as_int)
                .map(|v| cast_scalar(builder, v, int_ty, scalar))
            else {
                return zero_lowered_for_type(builder, value_ty, scalar);
            };

            let out = match op {
                BinaryOp::Add => builder.ins().iadd(left, right),
                BinaryOp::Sub => builder.ins().isub(left, right),
                BinaryOp::Mul => builder.ins().imul(left, right),
                BinaryOp::Div => {
                    if signed {
                        builder.ins().sdiv(left, right)
                    } else {
                        builder.ins().udiv(left, right)
                    }
                }
                BinaryOp::Mod => {
                    if signed {
                        builder.ins().srem(left, right)
                    } else {
                        builder.ins().urem(left, right)
                    }
                }
                BinaryOp::Eq => {
                    let cmp = builder.ins().icmp(IntCC::Equal, left, right);
                    return LoweredValue::Int(bool_to_int(builder, bool_storage_type(scalar), cmp));
                }
                BinaryOp::Ne => {
                    let cmp = builder.ins().icmp(IntCC::NotEqual, left, right);
                    return LoweredValue::Int(bool_to_int(builder, bool_storage_type(scalar), cmp));
                }
                BinaryOp::Lt => {
                    let cmp = builder.ins().icmp(
                        if signed {
                            IntCC::SignedLessThan
                        } else {
                            IntCC::UnsignedLessThan
                        },
                        left,
                        right,
                    );
                    return LoweredValue::Int(bool_to_int(builder, bool_storage_type(scalar), cmp));
                }
                BinaryOp::Le => {
                    let cmp = builder.ins().icmp(
                        if signed {
                            IntCC::SignedLessThanOrEqual
                        } else {
                            IntCC::UnsignedLessThanOrEqual
                        },
                        left,
                        right,
                    );
                    return LoweredValue::Int(bool_to_int(builder, bool_storage_type(scalar), cmp));
                }
                BinaryOp::Gt => {
                    let cmp = builder.ins().icmp(
                        if signed {
                            IntCC::SignedGreaterThan
                        } else {
                            IntCC::UnsignedGreaterThan
                        },
                        left,
                        right,
                    );
                    return LoweredValue::Int(bool_to_int(builder, bool_storage_type(scalar), cmp));
                }
                BinaryOp::Ge => {
                    let cmp = builder.ins().icmp(
                        if signed {
                            IntCC::SignedGreaterThanOrEqual
                        } else {
                            IntCC::UnsignedGreaterThanOrEqual
                        },
                        left,
                        right,
                    );
                    return LoweredValue::Int(bool_to_int(builder, bool_storage_type(scalar), cmp));
                }
                BinaryOp::LogicalAnd => {
                    let l_cmp = builder.ins().icmp_imm(IntCC::NotEqual, left, 0);
                    let l = bool_to_int(builder, int_ty, l_cmp);
                    let r_cmp = builder.ins().icmp_imm(IntCC::NotEqual, right, 0);
                    let r = bool_to_int(builder, int_ty, r_cmp);
                    let both = builder.ins().band(l, r);
                    let out_cmp = builder.ins().icmp_imm(IntCC::NotEqual, both, 0);
                    return LoweredValue::Int(bool_to_int(builder, int_ty, out_cmp));
                }
                BinaryOp::LogicalOr => {
                    let l_cmp = builder.ins().icmp_imm(IntCC::NotEqual, left, 0);
                    let l = bool_to_int(builder, int_ty, l_cmp);
                    let r_cmp = builder.ins().icmp_imm(IntCC::NotEqual, right, 0);
                    let r = bool_to_int(builder, int_ty, r_cmp);
                    let any = builder.ins().bor(l, r);
                    let out_cmp = builder.ins().icmp_imm(IntCC::NotEqual, any, 0);
                    return LoweredValue::Int(bool_to_int(builder, int_ty, out_cmp));
                }
                BinaryOp::BitAnd => builder.ins().band(left, right),
                BinaryOp::BitOr => builder.ins().bor(left, right),
                BinaryOp::BitXor => builder.ins().bxor(left, right),
                BinaryOp::Shl => builder.ins().ishl(left, right),
                BinaryOp::Shr => {
                    if signed {
                        builder.ins().sshr(left, right)
                    } else {
                        builder.ins().ushr(left, right)
                    }
                }
                _ => zero_for_type(builder, int_ty),
            };
            LoweredValue::Int(out)
        }
        MirValue::Assign { value, .. } => lowered
            .get(value)
            .cloned()
            .unwrap_or_else(|| zero_lowered_for_type(builder, value_ty, scalar)),
        MirValue::LocalSet { value, .. } => lowered
            .get(value)
            .cloned()
            .unwrap_or_else(|| zero_lowered_for_type(builder, value_ty, scalar)),
        MirValue::Call { callee, args } => {
            let mut arg_vals = Vec::with_capacity(args.len());
            for arg in args {
                let Some(value) = (match lowered.get(arg) {
                    Some(LoweredValue::FunctionSymbol(func_id)) => {
                        let func_ref = module.declare_func_in_func(*func_id, builder.func);
                        Some(
                            builder
                                .ins()
                                .func_addr(module.target_config().pointer_type(), func_ref),
                        )
                    }
                    Some(LoweredValue::StructMemory { slot, .. }) => Some(
                        builder
                            .ins()
                            .stack_addr(module.target_config().pointer_type(), *slot, 0),
                    ),
                    Some(other) => other.as_value(),
                    None => None,
                }) else {
                    return zero_lowered_for_type(builder, value_ty, scalar);
                };
                arg_vals.push(value);
            }

            let ret = if let Some(LoweredValue::FunctionSymbol(func_id)) =
                lowered.get(callee).cloned()
            {
                if let Some(param_types) = symbol_param_types_by_id.get(&func_id.as_u32()) {
                    if param_types.len() != arg_vals.len() {
                        return zero_lowered_for_type(builder, value_ty, scalar);
                    }
                    for (arg, ty) in arg_vals.iter_mut().zip(param_types) {
                        *arg = cast_scalar(builder, *arg, *ty, scalar);
                    }
                }
                let func_ref = module.declare_func_in_func(func_id, builder.func);
                let inst = builder.ins().call(func_ref, &arg_vals);
                builder
                    .inst_results(inst)
                    .first()
                    .cloned()
                    .unwrap_or_else(|| zero_for_scalar(builder, scalar))
            } else {
                let Some(callee_val) = lowered.get(callee).and_then(LoweredValue::as_value) else {
                    return zero_lowered_for_type(builder, value_ty, scalar);
                };
                let mut signature = module.make_signature();
                for arg in &arg_vals {
                    signature
                        .params
                        .push(AbiParam::new(builder.func.dfg.value_type(*arg)));
                }
                let return_ty = if matches!(value_ty, MirValueType::Unknown) {
                    scalar.ty()
                } else {
                    mir_type_to_clif(value_ty, scalar)
                };
                signature.returns.push(AbiParam::new(return_ty));
                let sig_ref = builder.import_signature(signature);
                let callee_ptr = cast_scalar(
                    builder,
                    callee_val,
                    module.target_config().pointer_type(),
                    scalar,
                );
                let inst = builder.ins().call_indirect(sig_ref, callee_ptr, &arg_vals);
                builder
                    .inst_results(inst)
                    .first()
                    .cloned()
                    .unwrap_or_else(|| zero_for_scalar(builder, scalar))
            };
            if matches!(value_ty, MirValueType::Unknown) {
                let ret_ty = builder.func.dfg.value_type(ret);
                if ret_ty.is_float() {
                    return LoweredValue::Float(ret);
                }
                return LoweredValue::Int(ret);
            }
            if matches!(value_ty, MirValueType::Float { .. }) {
                LoweredValue::Float(cast_scalar(
                    builder,
                    ret,
                    mir_type_to_clif(value_ty, scalar),
                    scalar,
                ))
            } else {
                LoweredValue::Int(cast_scalar(
                    builder,
                    ret,
                    mir_type_to_clif(value_ty, scalar),
                    scalar,
                ))
            }
        }
        MirValue::DerefAccess { base } => lowered
            .get(base)
            .cloned()
            .unwrap_or_else(|| zero_lowered_for_type(builder, value_ty, scalar)),
        MirValue::StructLiteral { fields } => {
            let mut lowered_pairs = Vec::with_capacity(fields.len());
            let mut lowered_fields = BTreeMap::new();
            for (name, value_id) in fields {
                let lowered_value = lowered
                    .get(value_id)
                    .cloned()
                    .unwrap_or_else(|| zero_lowered_for_type(builder, value_ty, scalar));
                lowered_pairs.push((name.clone(), lowered_value.clone()));
                lowered_fields.insert(name.clone(), lowered_value);
            }
            materialize_struct_memory(builder, &lowered_pairs)
                .unwrap_or(LoweredValue::Struct(lowered_fields))
        }
        MirValue::FieldAccess { base, field } => match lowered.get(base) {
            Some(LoweredValue::Struct(fields)) => fields
                .get(field)
                .cloned()
                .unwrap_or_else(|| zero_lowered_for_type(builder, value_ty, scalar)),
            Some(LoweredValue::StructMemory { slot, fields, .. }) => {
                if let Some((ty, offset)) = fields.get(field).copied() {
                    let loaded = builder.ins().stack_load(ty, *slot, offset);
                    if ty.is_float() {
                        LoweredValue::Float(loaded)
                    } else {
                        LoweredValue::Int(loaded)
                    }
                } else {
                    zero_lowered_for_type(builder, value_ty, scalar)
                }
            }
            _ => zero_lowered_for_type(builder, value_ty, scalar),
        },
        MirValue::EnumVariant { variant, payload } => {
            let mut lowered_payload = Vec::with_capacity(payload.len());
            for value_id in payload {
                lowered_payload.push(
                    lowered
                        .get(value_id)
                        .cloned()
                        .unwrap_or_else(|| zero_lowered_for_type(builder, value_ty, scalar)),
                );
            }
            let lowered_enum = LoweredValue::EnumVariant {
                variant: variant.clone(),
                payload: lowered_payload.clone(),
            };
            materialize_enum_memory(builder, variant, &lowered_payload).unwrap_or(lowered_enum)
        }
        MirValue::Index { base, .. } => match lowered.get(base) {
            Some(LoweredValue::EnumMemory { slot, ordered }) => {
                let Some(index_value) = (match value {
                    MirValue::Index { index, .. } => {
                        lowered.get(index).and_then(LoweredValue::as_int)
                    }
                    _ => None,
                }) else {
                    return zero_lowered_for_type(builder, value_ty, scalar);
                };
                if let Some((elem_ty, base_offset, stride)) = homogeneous_sequence_layout(ordered) {
                    let ptr_ty = module.target_config().pointer_type();
                    let base = builder.ins().stack_addr(ptr_ty, *slot, base_offset);
                    let idx = cast_scalar(builder, index_value, ptr_ty, scalar);
                    let scaled = if stride == 1 {
                        idx
                    } else {
                        builder.ins().imul_imm(idx, stride)
                    };
                    let addr = builder.ins().iadd(base, scaled);
                    let loaded = builder.ins().load(
                        elem_ty,
                        cranelift_codegen::ir::MemFlags::new(),
                        addr,
                        0,
                    );
                    if elem_ty.is_float() {
                        LoweredValue::Float(loaded)
                    } else {
                        LoweredValue::Int(loaded)
                    }
                } else {
                    zero_lowered_for_type(builder, value_ty, scalar)
                }
            }
            Some(LoweredValue::EnumVariant { payload, .. }) => payload
                .first()
                .cloned()
                .unwrap_or_else(|| zero_lowered_for_type(builder, value_ty, scalar)),
            Some(LoweredValue::Struct(fields)) => fields
                .values()
                .next()
                .cloned()
                .unwrap_or_else(|| zero_lowered_for_type(builder, value_ty, scalar)),
            Some(LoweredValue::StructMemory { slot, ordered, .. }) => {
                let Some(index_value) = (match value {
                    MirValue::Index { index, .. } => {
                        lowered.get(index).and_then(LoweredValue::as_int)
                    }
                    _ => None,
                }) else {
                    return zero_lowered_for_type(builder, value_ty, scalar);
                };
                if let Some((elem_ty, base_offset, stride)) = homogeneous_sequence_layout(ordered) {
                    let ptr_ty = module.target_config().pointer_type();
                    let base = builder.ins().stack_addr(ptr_ty, *slot, base_offset);
                    let idx = cast_scalar(builder, index_value, ptr_ty, scalar);
                    let scaled = if stride == 1 {
                        idx
                    } else {
                        builder.ins().imul_imm(idx, stride)
                    };
                    let addr = builder.ins().iadd(base, scaled);
                    let loaded = builder.ins().load(
                        elem_ty,
                        cranelift_codegen::ir::MemFlags::new(),
                        addr,
                        0,
                    );
                    if elem_ty.is_float() {
                        LoweredValue::Float(loaded)
                    } else {
                        LoweredValue::Int(loaded)
                    }
                } else {
                    zero_lowered_for_type(builder, value_ty, scalar)
                }
            }
            Some(LoweredValue::PointerSlice {
                base_addr,
                elem_ty,
                stride,
            }) => {
                let Some(index_value) = (match value {
                    MirValue::Index { index, .. } => {
                        lowered.get(index).and_then(LoweredValue::as_int)
                    }
                    _ => None,
                }) else {
                    return zero_lowered_for_type(builder, value_ty, scalar);
                };
                let ptr_ty = module.target_config().pointer_type();
                let idx = cast_scalar(builder, index_value, ptr_ty, scalar);
                let scaled = if *stride == 1 {
                    idx
                } else {
                    builder.ins().imul_imm(idx, *stride)
                };
                let addr = builder.ins().iadd(*base_addr, scaled);
                let loaded =
                    builder
                        .ins()
                        .load(*elem_ty, cranelift_codegen::ir::MemFlags::new(), addr, 0);
                if elem_ty.is_float() {
                    LoweredValue::Float(loaded)
                } else {
                    LoweredValue::Int(loaded)
                }
            }
            Some(LoweredValue::Int(base_addr)) => {
                let Some(index_value) = (match value {
                    MirValue::Index { index, .. } => {
                        lowered.get(index).and_then(LoweredValue::as_int)
                    }
                    _ => None,
                }) else {
                    return zero_lowered_for_type(builder, value_ty, scalar);
                };
                let elem_ty = mir_type_to_clif(value_ty, scalar);
                let stride = (elem_ty.bits() / 8).max(1) as i64;
                let ptr_ty = module.target_config().pointer_type();
                let idx = cast_scalar(builder, index_value, ptr_ty, scalar);
                let scaled = if stride == 1 {
                    idx
                } else {
                    builder.ins().imul_imm(idx, stride)
                };
                let base = cast_scalar(builder, *base_addr, ptr_ty, scalar);
                let addr = builder.ins().iadd(base, scaled);
                let loaded =
                    builder
                        .ins()
                        .load(elem_ty, cranelift_codegen::ir::MemFlags::new(), addr, 0);
                if elem_ty.is_float() {
                    LoweredValue::Float(loaded)
                } else {
                    LoweredValue::Int(loaded)
                }
            }
            _ => zero_lowered_for_type(builder, value_ty, scalar),
        },
        MirValue::Slice { base, start, .. } => match lowered.get(base).cloned() {
            Some(LoweredValue::EnumMemory { slot, ordered }) => {
                if let Some((elem_ty, base_offset, stride)) = homogeneous_sequence_layout(&ordered)
                {
                    let ptr_ty = module.target_config().pointer_type();
                    let mut addr = builder.ins().stack_addr(ptr_ty, slot, base_offset);
                    if let Some(start) = start {
                        if let Some(start_value) = lowered.get(start).and_then(LoweredValue::as_int)
                        {
                            let start_idx = cast_scalar(builder, start_value, ptr_ty, scalar);
                            let scaled = if stride == 1 {
                                start_idx
                            } else {
                                builder.ins().imul_imm(start_idx, stride)
                            };
                            addr = builder.ins().iadd(addr, scaled);
                        }
                    }
                    LoweredValue::PointerSlice {
                        base_addr: addr,
                        elem_ty,
                        stride,
                    }
                } else {
                    zero_lowered_for_type(builder, value_ty, scalar)
                }
            }
            Some(LoweredValue::StructMemory { slot, ordered, .. }) => {
                if let Some((elem_ty, base_offset, stride)) = homogeneous_sequence_layout(&ordered)
                {
                    let ptr_ty = module.target_config().pointer_type();
                    let mut addr = builder.ins().stack_addr(ptr_ty, slot, base_offset);
                    if let Some(start) = start {
                        if let Some(start_value) = lowered.get(start).and_then(LoweredValue::as_int)
                        {
                            let start_idx = cast_scalar(builder, start_value, ptr_ty, scalar);
                            let scaled = if stride == 1 {
                                start_idx
                            } else {
                                builder.ins().imul_imm(start_idx, stride)
                            };
                            addr = builder.ins().iadd(addr, scaled);
                        }
                    }
                    LoweredValue::PointerSlice {
                        base_addr: addr,
                        elem_ty,
                        stride,
                    }
                } else {
                    zero_lowered_for_type(builder, value_ty, scalar)
                }
            }
            Some(LoweredValue::EnumVariant { variant, payload }) => {
                LoweredValue::EnumVariant { variant, payload }
            }
            Some(other) => other,
            None => zero_lowered_for_type(builder, value_ty, scalar),
        },
        MirValue::TypeLiteral(name) => {
            let hash = i64::from(variant_tag(name));
            let ty = mir_type_to_clif(value_ty, scalar);
            LoweredValue::Int(builder.ins().iconst(ty, hash))
        }
        MirValue::Use { .. } | MirValue::Unknown => {
            zero_lowered_for_type(builder, value_ty, scalar)
        }
    }
}

fn zero_lowered_for_type(
    builder: &mut FunctionBuilder,
    value_ty: &MirValueType,
    scalar: ScalarType,
) -> LoweredValue {
    let ty = if matches!(value_ty, MirValueType::Unknown) {
        scalar.ty()
    } else {
        mir_type_to_clif(value_ty, scalar)
    };
    if ty.is_float() {
        LoweredValue::Float(zero_for_type(builder, ty))
    } else {
        LoweredValue::Int(zero_for_type(builder, ty))
    }
}

fn lower_literal(
    literal: &HirLiteral,
    value_ty: &MirValueType,
    scalar: ScalarType,
    builder: &mut FunctionBuilder,
) -> LoweredValue {
    match literal {
        HirLiteral::Integer(value) => {
            let int_ty = mir_type_to_clif(value_ty, scalar);
            LoweredValue::Int(
                builder
                    .ins()
                    .iconst(int_ty, parse_int_literal(value).unwrap_or(0)),
            )
        }
        HirLiteral::Bool(value) => {
            let ty = bool_storage_type(scalar);
            LoweredValue::Int(builder.ins().iconst(ty, i64::from(*value)))
        }
        HirLiteral::Char(value) => {
            let int_ty = mir_type_to_clif(value_ty, scalar);
            LoweredValue::Int(builder.ins().iconst(int_ty, *value as i64))
        }
        HirLiteral::Float(value) => {
            let float_ty = mir_type_to_clif(value_ty, scalar);
            if float_ty == F32 {
                let bits = value.parse::<f32>().unwrap_or(0.0).to_bits();
                LoweredValue::Float(
                    builder
                        .ins()
                        .f32const(cranelift_codegen::ir::immediates::Ieee32::with_bits(bits)),
                )
            } else {
                let bits = value.parse::<f64>().unwrap_or(0.0).to_bits();
                LoweredValue::Float(
                    builder
                        .ins()
                        .f64const(cranelift_codegen::ir::immediates::Ieee64::with_bits(bits)),
                )
            }
        }
        HirLiteral::Null => match scalar {
            ScalarType::Float { ty } => LoweredValue::Float(zero_for_type(builder, ty)),
            ScalarType::Int { ty, .. } => LoweredValue::Int(builder.ins().iconst(ty, 0)),
        },
        HirLiteral::String(value) => {
            let text = if value.len() >= 2 && value.starts_with('"') && value.ends_with('"') {
                &value[1..value.len() - 1]
            } else {
                value.as_str()
            };
            let bytes = text.as_bytes();
            let size = (bytes.len() + 1) as u32;
            let slot = builder.func.create_sized_stack_slot(StackSlotData::new(
                StackSlotKind::ExplicitSlot,
                size.max(1),
                0,
            ));
            for (idx, byte) in bytes.iter().enumerate() {
                let byte_val = builder.ins().iconst(I8, i64::from(*byte));
                builder.ins().stack_store(byte_val, slot, idx as i32);
            }
            let nul = builder.ins().iconst(I8, 0);
            builder.ins().stack_store(nul, slot, bytes.len() as i32);
            let addr = builder.ins().stack_addr(I64, slot, 0);
            LoweredValue::Int(addr)
        }
    }
}

fn materialize_struct_memory(
    builder: &mut FunctionBuilder,
    fields: &[(String, LoweredValue)],
) -> Option<LoweredValue> {
    let mut layout = BTreeMap::new();
    let mut ordered = Vec::with_capacity(fields.len());
    let mut size = 0u32;
    let mut max_align = 1u32;

    for (name, value) in fields {
        let (field_value, field_ty) = match value {
            LoweredValue::Int(v) | LoweredValue::Float(v) => (*v, builder.func.dfg.value_type(*v)),
            LoweredValue::PointerSlice { base_addr, .. } => {
                (*base_addr, builder.func.dfg.value_type(*base_addr))
            }
            _ => return None,
        };
        let align = ((field_ty.bits() / 8).max(1)) as u32;
        max_align = max_align.max(align);
        size = align_to(size, align);
        let offset = size as i32;
        size += align;
        layout.insert(name.clone(), (field_ty, offset));
        ordered.push((field_value, offset));
    }

    size = align_to(size, max_align).max(1);
    let align_shift = (max_align.max(1)).trailing_zeros() as u8;
    let slot = builder.func.create_sized_stack_slot(StackSlotData::new(
        StackSlotKind::ExplicitSlot,
        size,
        align_shift,
    ));
    for (value, offset) in &ordered {
        builder.ins().stack_store(*value, slot, *offset);
    }

    Some(LoweredValue::StructMemory {
        slot,
        fields: layout,
        ordered: ordered
            .into_iter()
            .map(|(value, offset)| (builder.func.dfg.value_type(value), offset))
            .collect(),
    })
}

fn materialize_enum_memory(
    builder: &mut FunctionBuilder,
    variant: &str,
    payload: &[LoweredValue],
) -> Option<LoweredValue> {
    let mut values = Vec::with_capacity(payload.len() + 1);
    let payload_ty = payload.first().and_then(|value| match value {
        LoweredValue::Int(v) | LoweredValue::Float(v) => Some(builder.func.dfg.value_type(*v)),
        _ => None,
    });
    let tag_ty = payload_ty.filter(|ty| ty.is_int()).unwrap_or(I32);
    let tag_value = builder
        .ins()
        .iconst(tag_ty, i64::from(variant_tag(variant)));
    values.push(("__tag".to_string(), LoweredValue::Int(tag_value)));
    for (idx, value) in payload.iter().cloned().enumerate() {
        values.push((format!("__payload_{idx}"), value));
    }

    let mut ordered_values = Vec::new();
    for (_name, value) in values {
        if !matches!(value, LoweredValue::Int(_) | LoweredValue::Float(_)) {
            return None;
        }
        ordered_values.push((String::new(), value));
    }
    let mem = materialize_struct_memory(builder, &ordered_values)?;
    match mem {
        LoweredValue::StructMemory { slot, ordered, .. } => {
            Some(LoweredValue::EnumMemory { slot, ordered })
        }
        _ => None,
    }
}

fn variant_tag(variant: &str) -> u32 {
    let mut hash = 2166136261u32;
    for byte in variant.as_bytes() {
        hash ^= u32::from(*byte);
        hash = hash.wrapping_mul(16777619);
    }
    hash
}

fn homogeneous_sequence_layout(ordered: &[(Type, i32)]) -> Option<(Type, i32, i64)> {
    let (first_ty, first_off) = ordered.first().copied()?;
    let stride = (first_ty.bits() / 8).max(1) as i64;
    for (idx, (ty, off)) in ordered.iter().copied().enumerate() {
        if ty != first_ty {
            return None;
        }
        let expected = first_off as i64 + (idx as i64 * stride);
        if off as i64 != expected {
            return None;
        }
    }
    Some((first_ty, first_off, stride))
}

fn align_to(value: u32, align: u32) -> u32 {
    let mask = align.saturating_sub(1);
    if value & mask == 0 {
        value
    } else {
        (value + mask) & !mask
    }
}

fn bool_to_int(builder: &mut FunctionBuilder, int_type: Type, condition: Value) -> Value {
    builder.ins().uextend(int_type, condition)
}

fn cast_int(builder: &mut FunctionBuilder, value: Value, target_type: Type, signed: bool) -> Value {
    let source_type = builder.func.dfg.value_type(value);
    if source_type == target_type {
        value
    } else if source_type.bits() > target_type.bits() {
        builder.ins().ireduce(target_type, value)
    } else {
        if signed {
            builder.ins().sextend(target_type, value)
        } else {
            builder.ins().uextend(target_type, value)
        }
    }
}

fn parse_return_scalar(return_type: Option<&str>) -> ScalarType {
    let mut ty = return_type.unwrap_or("").trim();
    if let Some(stripped) = ty.strip_prefix('?') {
        ty = stripped.trim();
    }
    if let Some((ok, _errs)) = ty.split_once('!') {
        ty = ok.trim();
    }
    if ty.starts_with("fn/") || ty.starts_with("fn(") || ty == "fn" {
        return ScalarType::Int {
            ty: I64,
            signed: false,
        };
    }

    match ty {
        "u1" | "bool" => ScalarType::Int {
            ty: I8,
            signed: false,
        },
        "i8" => ScalarType::Int {
            ty: I8,
            signed: true,
        },
        "i16" => ScalarType::Int {
            ty: I16,
            signed: true,
        },
        "i64" => ScalarType::Int {
            ty: I64,
            signed: true,
        },
        "isize" => ScalarType::Int {
            ty: I64,
            signed: true,
        },
        "u8" => ScalarType::Int {
            ty: I8,
            signed: false,
        },
        "u16" => ScalarType::Int {
            ty: I16,
            signed: false,
        },
        "u64" => ScalarType::Int {
            ty: I64,
            signed: false,
        },
        "type" => ScalarType::Int {
            ty: I64,
            signed: false,
        },
        "usize" => ScalarType::Int {
            ty: I64,
            signed: false,
        },
        "u32" => ScalarType::Int {
            ty: I32,
            signed: false,
        },
        "f32" => ScalarType::Float { ty: F32 },
        "f64" => ScalarType::Float { ty: F64 },
        _ => ScalarType::Int {
            ty: I32,
            signed: true,
        },
    }
}

fn mir_type_to_clif(ty: &MirValueType, fallback: ScalarType) -> Type {
    match ty {
        MirValueType::Int { bits, .. } => match bits {
            8 => I8,
            16 => I16,
            64 => I64,
            _ => I32,
        },
        MirValueType::Float { bits } => {
            if *bits <= 32 {
                F32
            } else {
                F64
            }
        }
        MirValueType::Bool => bool_storage_type(fallback),
        MirValueType::Type => I64,
        MirValueType::Function | MirValueType::Unknown => fallback.ty(),
    }
}

fn bool_storage_type(fallback: ScalarType) -> Type {
    match fallback {
        ScalarType::Float { .. } => I32,
        ScalarType::Int { ty, .. } => ty,
    }
}

fn zero_for_type(builder: &mut FunctionBuilder, ty: Type) -> Value {
    if ty == F32 {
        builder
            .ins()
            .f32const(cranelift_codegen::ir::immediates::Ieee32::with_bits(0))
    } else if ty == F64 {
        builder
            .ins()
            .f64const(cranelift_codegen::ir::immediates::Ieee64::with_bits(0))
    } else {
        builder.ins().iconst(ty, 0)
    }
}

fn zero_for_scalar(builder: &mut FunctionBuilder, scalar: ScalarType) -> Value {
    zero_for_type(builder, scalar.ty())
}

fn cast_scalar(
    builder: &mut FunctionBuilder,
    value: Value,
    target_type: Type,
    scalar: ScalarType,
) -> Value {
    let source = builder.func.dfg.value_type(value);
    if source == target_type {
        return value;
    }
    if source.is_int() && target_type.is_int() {
        let signed = matches!(scalar, ScalarType::Int { signed: true, .. });
        return cast_int(builder, value, target_type, signed);
    }
    if source.is_int() && target_type.is_float() {
        return match scalar {
            ScalarType::Int { signed: true, .. } => {
                builder.ins().fcvt_from_sint(target_type, value)
            }
            ScalarType::Int { signed: false, .. } => {
                builder.ins().fcvt_from_uint(target_type, value)
            }
            ScalarType::Float { .. } => builder.ins().fcvt_from_sint(target_type, value),
        };
    }
    if source.is_float() && target_type.is_int() {
        return match scalar {
            ScalarType::Int { signed: true, .. } => builder.ins().fcvt_to_sint(target_type, value),
            ScalarType::Int { signed: false, .. } => builder.ins().fcvt_to_uint(target_type, value),
            ScalarType::Float { .. } => builder.ins().fcvt_to_sint(target_type, value),
        };
    }
    if source.is_float() && target_type.is_float() {
        if source.bits() > target_type.bits() {
            return builder.ins().fdemote(target_type, value);
        }
        return builder.ins().fpromote(target_type, value);
    }
    value
}

fn parse_int_literal(value: &str) -> Option<i64> {
    let normalized = value.replace('_', "");
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

fn find_main_function(mir: &MirProgram) -> Option<&MirFunction> {
    mir.modules
        .iter()
        .find(|module| module.key.module_name == "main")
        .and_then(|module| {
            module
                .functions
                .iter()
                .find(|function| function.name == "main")
        })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sanitize_symbol_name_replaces_non_identifier_chars() {
        assert_eq!(sanitize_symbol_name("ok_name123"), "ok_name123");
        assert_eq!(
            sanitize_symbol_name("with-dash.and space"),
            "with_dash_and_space"
        );
    }

    #[test]
    fn parse_return_scalar_strips_optional_and_errorable_wrappers() {
        match parse_return_scalar(Some("?i64!Err")) {
            ScalarType::Int { ty, signed } => {
                assert_eq!(ty, I64);
                assert!(signed);
            }
            ScalarType::Float { .. } => panic!("expected integer scalar"),
        }

        match parse_return_scalar(Some("?f32!Err")) {
            ScalarType::Float { ty } => assert_eq!(ty, F32),
            ScalarType::Int { .. } => panic!("expected float scalar"),
        }
    }

    #[test]
    fn parse_return_scalar_defaults_to_i32_for_unknown_type() {
        match parse_return_scalar(Some("MyUnknownType")) {
            ScalarType::Int { ty, signed } => {
                assert_eq!(ty, I32);
                assert!(signed);
            }
            ScalarType::Float { .. } => panic!("expected integer scalar"),
        }
    }

    #[test]
    fn parse_return_scalar_supports_type_keyword() {
        match parse_return_scalar(Some("type")) {
            ScalarType::Int { ty, signed } => {
                assert_eq!(ty, I64);
                assert!(!signed);
            }
            ScalarType::Float { .. } => panic!("expected integer scalar"),
        }
    }

    #[test]
    fn parse_return_scalar_supports_u1_keyword() {
        match parse_return_scalar(Some("u1")) {
            ScalarType::Int { ty, signed } => {
                assert_eq!(ty, I8);
                assert!(!signed);
            }
            ScalarType::Float { .. } => panic!("expected integer scalar"),
        }
    }

    #[test]
    fn parse_return_scalar_supports_function_type() {
        match parse_return_scalar(Some("fn(i32) i32")) {
            ScalarType::Int { ty, signed } => {
                assert_eq!(ty, I64);
                assert!(!signed);
            }
            ScalarType::Float { .. } => panic!("expected integer scalar"),
        }
        match parse_return_scalar(Some("fn/1")) {
            ScalarType::Int { ty, signed } => {
                assert_eq!(ty, I64);
                assert!(!signed);
            }
            ScalarType::Float { .. } => panic!("expected integer scalar"),
        }
    }

    #[test]
    fn variant_tag_is_stable_fnv1a_32() {
        assert_eq!(variant_tag("Ready"), 197800596);
        assert_eq!(variant_tag("Waiting"), 3376746056);
    }

    #[test]
    fn runtime_allocator_source_defines_intrinsic_symbols() {
        let source = include_str!("runtime_support.rs");
        assert!(source.contains("__dyn_alloc"));
        assert!(source.contains("__dyn_realloc"));
        assert!(source.contains("__dyn_free"));
        assert!(source.contains("__dyn_c_allocator"));
        assert!(source.contains("__dyn_test_failing_allocator"));
        assert!(source.contains("__dyn_test_set_fail_after"));
        assert!(source.contains("__dyn_test_identity_i32_fn"));
        assert!(source.contains("__dyn_arena_allocator"));
        assert!(source.contains("__dyn_arena_reset"));
        assert!(source.contains("__dyn_arena_deinit"));
        assert!(source.contains("__dyn_alloc_with"));
        assert!(source.contains("__dyn_mem_copy"));
        assert!(source.contains("__dyn_vec_i32_push"));
        assert!(source.contains("std_vec_i32_push"));
        assert!(source.contains("__dyn_vec_raw_push_u64"));
        assert!(source.contains("std_vec_push_u64"));
        assert!(source.contains("__dyn_vec_raw_ptr"));
        assert!(source.contains("__dyn_vec_raw_push_bytes"));
        assert!(source.contains("__dyn_vec_raw_get_bytes"));
        assert!(source.contains("__dyn_vec_raw_set_bytes"));
        assert!(source.contains("__dyn_vec_raw_pop_bytes"));
        assert!(source.contains("std_vec_ptr"));
        assert!(source.contains("std_vec_push_bytes"));
        assert!(source.contains("std_vec_get_bytes"));
        assert!(source.contains("std_vec_set_bytes"));
        assert!(source.contains("std_vec_pop_bytes"));
    }
}
