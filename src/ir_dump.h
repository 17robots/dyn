#ifndef DYN_IR_DUMP_H
#define DYN_IR_DUMP_H
#include <stdio.h>
#include "ir.h"

/* Canonical structured semantic snapshot, version dyn-ir1.
 * Returns 0 on success, 2 on invalid input, allocation failure or stream error.
 * Validates all serialized tables, tags, types, references and ranges before
 * writing any bytes. An I/O failure may leave partial output. Does not flush or
 * close out. The caller supplies readable, stable arrays and NUL-terminated
 * names; pointer validity and concurrent mutation cannot be checked in C.
 * No lowering, preparation, code generation, linking or cache operations occur.
 *
 * Grammar (ASCII, exactly one space between tokens, LF after EVERY line):
 *   file = "dyn-ir1" LF target section* "end" LF
 *   target = "target" name triple arch kernel abi libc endian pointer_bits
 *            executable_link LF
 *   section = "section " plural " " decimal LF record{section-count}
 *   record = singular " " index (" " key "=" value)* LF
 * Each target word above denotes a key=value. All record keys below are ordered.
 * decimal/index/count are unsigned decimal with no leading zeros except 0.
 * bool = true | false; bits = exactly 16 lowercase hexadecimal digits (no 0x).
 * bytes = decimal-byte-length ":" lowercase-hex-byte-pairs (including 0:).
 * Names are bytes of the C string excluding NUL; string contents include NULs.
 * ref = table ":" index | none; range = table ":" start "+" count.
 * Empty ranges retain their start. Indices are snapshot-local allocation order.
 * type = infer | error | void | bool | i8 | i16 | i32 | i64 | u8 | u16 |
 *        u32 | u64 | isize | usize | f32 | f64 | string | rawptr | any |
 *        struct:N | enum:N | pointer:N | array:N | slice:N | fn_type:N |
 *        type_param:N. Distinct aliases have already been erased by lowering.
 * op = none | neg | not | bit_not | address | deref | add | sub | mul | div |
 *      rem | eq | ne | lt | le | gt | ge | logical_and | logical_or | bit_and |
 *      bit_or | bit_xor | shl | shr.
 *
 * Fixed section order, singular record names and exact ordered keys:
 * structs / struct: owner name packed public fields(field range)
 * enums / enum: owner name tag_type public variants(variant range)
 * fields / field: name type default(expression ref)
 * variants / variant: name payload_type tag(bits)
 * globals / global: owner name [link_name if foreign] type initializer
 *                   const foreign public
 * global_init_order / global_init: global(global ref)
 * functions / function: owner name [link_name if foreign] return_type params
 *                       body locals main foreign variadic public generic instance
 *                       [variadic_type variadic_local if variadic]
 * params / param: name type local
 * pointers / pointer: pointee const
 * arrays / array: element length(bits)
 * slices / slice: element const
 * fn_types / fn_type: return_type params(fn_type_param range) variadic
 * fn_type_params / fn_type_param: type
 * strings / string: bytes
 * locals / local: name type
 * expressions / expression: kind type check_origin [kind payload below]
 * items / item: expression field(field_index:N or none)
 * statements / statement: kind check_origin [kind payload below]
 * patterns / pattern: enum signed is_type [type if is_type; otherwise
 *                     variant if enum; otherwise first(bits) last(bits)]
 * case_arms / case_arm: patterns body local wildcard pointer_binding
 * children / child: statement
 * Range tags: fields=field, variants=variant, function params=param,
 * locals=local, body/else=child, items=item, arms=case_arm, patterns=pattern.
 * Ref tags equal their key except: initializer/default/value/target/condition/
 * operand/base/index/start/stop/callee/left/right=expression; variadic_local=local;
 * check_origin=function; signature=fn_type. check_origin zero becomes none,
 * otherwise the retained one-based function ID becomes function:(ID-1).
 * All optional UINT32_MAX references become none. owner is a decimal ordinal.
 *
 * Expression kind payloads (all listed fields emitted in this order):
 * int/char: bits; float: bits (double representation copied with memcpy);
 * bool: value(bool); string: string; name: local; global: global;
 * function: function; call: function items; indirect_call: signature callee items;
 * struct: struct items; enum: variant items; array/syscall: items;
 * field: base field(decimal relative field index); slice: base start stop;
 * binary: op left right wrap; unary: op operand wrap [signed_literal(bool)
 * if op=neg]; index: base index;
 * convert/cast/bitcast/len: operand; size/align/typeof: type_operand then
 * operand_type(type) if true or operand(expression ref) if false; nil/type: no payload.
 * Unary neg signed_literal preserves the semantic marker that its operand is
 * a signed literal magnitude (including the minimum signed integer magnitude).
 * The boolean storage on other unary operators is not serialized.
 * offset is rejected: its remaining field selector is a source span, and
 * semantic lowering must fold it before this format can represent it.
 *
 * Statement kind payloads:
 * invalid: none; local: local initializer; assign: value target [local if target
 * is none] op; return/expr/panic: expression; if: condition body else;
 * for: expression target local body loop pointer const range inclusive reverse;
 * break/continue: target_loop; case: expression arms; defer: block body.
 * loop/target_loop are loop:N handles, not statement references; their namespace
 * is the lowered loop allocator, bounded by statement_count.
 *
 * Module owner ordinals start at 0 and follow first encounter in the above
 * section order (structs, enums, globals, functions), including owner value 0.
 * Structural declaration names matching dyn_m<16 hex>_<name> become the byte
 * string module.<owner ordinal>.<name>. Instance function names become the byte
 * string instance.<function index>; debug_name is never interpreted. Foreign
 * link_name bytes, field/variant/param/local names and string bytes are verbatim.
 * Internal link_name is redundant with declaration identity and omitted.
 * Capacities, spans, paths (including target dynamic_linker), source locations,
 * interface hashes, liveness, layout sizes/alignments/has_payload, bounds and
 * overflow proofs, unstable_locals and local_statements are excluded as derived
 * facts. Integer literals/tags/range endpoints/array lengths are raw uint64 bits;
 * no floating conversion or locale-sensitive floating formatting is performed.
 */
int dyn_ir_dump(FILE *out, const DynIrProgram *program, const DynTarget *target);
#endif
