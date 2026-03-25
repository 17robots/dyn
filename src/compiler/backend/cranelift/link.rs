use std::collections::BTreeMap;

use object::read::{File as ObjFile, Object as ObjRead, ObjectSection, ObjectSymbol};
use object::{
    Architecture, BinaryFormat, RelocationEncoding, RelocationFlags, RelocationKind,
    RelocationTarget, SectionKind,
};

use super::driver::host_object_format;

const PAGE: u64 = 0x1000;
const ELF_BASE: u64 = 0x400000;

fn align_up(v: u64, a: u64) -> u64 {
    (v + a - 1) & !(a - 1)
}

/// Attempt to produce a complete executable in memory without an external linker.
///
/// Returns `None` when the current host target is not yet supported — the caller
/// should fall back to an external linker in that case.
/// Returns `Some(Err(_))` when the target is supported but linking failed (e.g. an
/// unknown relocation type was encountered).
pub(super) fn try_link_direct(
    cranelift_obj: &[u8],
    syscall_code: &[u8],
    entry_symbol: &str,
) -> Option<Result<Vec<u8>, String>> {
    let (fmt, arch, _) = host_object_format();
    match (fmt, arch) {
        (BinaryFormat::Elf, Architecture::X86_64) => {
            Some(link_elf(cranelift_obj, syscall_code, entry_symbol, ElfArch::X86_64))
        }
        (BinaryFormat::Elf, Architecture::Aarch64) => {
            Some(link_elf(cranelift_obj, syscall_code, entry_symbol, ElfArch::Aarch64))
        }
        (BinaryFormat::Coff, Architecture::X86_64) => {
            Some(link_pe_x86_64(cranelift_obj, syscall_code, entry_symbol))
        }
        (BinaryFormat::MachO, Architecture::X86_64) => {
            Some(link_macho(cranelift_obj, syscall_code, entry_symbol, false))
        }
        (BinaryFormat::MachO, Architecture::Aarch64) => {
            Some(link_macho(cranelift_obj, syscall_code, entry_symbol, true))
        }
        // Windows aarch64: not yet implemented — fall back to external linker
        _ => None,
    }
}

// ---------------------------------------------------------------------------
// Architecture-specific parameters for the shared ELF linker
// ---------------------------------------------------------------------------

enum ElfArch {
    X86_64,
    Aarch64,
}

impl ElfArch {
    fn em_machine(&self) -> u16 {
        match self {
            ElfArch::X86_64 => 62,  // EM_X86_64
            ElfArch::Aarch64 => 183, // EM_AARCH64
        }
    }

    fn start_size(&self) -> u64 {
        match self {
            // call + mov rdi,rax + mov eax,60 + syscall = 15 bytes
            ElfArch::X86_64 => 15,
            // bl + mov x8,#93 + svc #0 = 12 bytes
            ElfArch::Aarch64 => 12,
        }
    }

    fn write_start(&self, buf: &mut [u8], entry_addr: u64, start_vaddr: u64) {
        match self {
            ElfArch::X86_64 => write_start_x86_64_linux(buf, entry_addr, start_vaddr),
            ElfArch::Aarch64 => write_start_aarch64_linux(buf, entry_addr, start_vaddr),
        }
    }

    fn apply_reloc(
        &self,
        buf: &mut [u8],
        offset: usize,
        flags: RelocationFlags,
        sym_addr: u64,
        addend: i64,
        reloc_addr: u64,
    ) -> Result<(), String> {
        match self {
            ElfArch::X86_64 => apply_reloc_x86_64(buf, offset, flags, sym_addr, addend, reloc_addr),
            ElfArch::Aarch64 => {
                apply_reloc_aarch64(buf, offset, flags, sym_addr, addend, reloc_addr)
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Section collected from a parsed object
// ---------------------------------------------------------------------------

struct Section {
    name: String,
    kind: SectionKind,
    data: Vec<u8>,
    align: u64,
    orig_idx: usize,
    /// Byte offset of this section within its merged segment buffer.
    seg_offset: u64,
    /// Virtual address assigned during layout.
    vaddr: u64,
}

// ---------------------------------------------------------------------------
// Shared ELF linker (x86-64 and aarch64)
// ---------------------------------------------------------------------------

fn link_elf(
    obj_bytes: &[u8],
    syscall_bytes: &[u8],
    entry_sym: &str,
    arch: ElfArch,
) -> Result<Vec<u8>, String> {
    let obj =
        ObjFile::parse(obj_bytes).map_err(|e| format!("failed to parse cranelift object: {e}"))?;

    // ---- Collect and categorise sections ----
    let mut text_secs: Vec<Section> = Vec::new();
    let mut data_secs: Vec<Section> = Vec::new();

    for sec in obj.sections() {
        let name = sec.name().unwrap_or("").to_string();
        let raw = sec
            .data()
            .map_err(|e| format!("section '{name}' data error: {e}"))?;
        let align = sec.align().max(1);
        let idx = sec.index().0;

        match sec.kind() {
            SectionKind::Text => {
                text_secs.push(Section {
                    name,
                    kind: SectionKind::Text,
                    data: raw.to_vec(),
                    align,
                    orig_idx: idx,
                    seg_offset: 0,
                    vaddr: 0,
                });
            }
            SectionKind::Data | SectionKind::ReadOnlyData => {
                data_secs.push(Section {
                    name,
                    kind: sec.kind(),
                    data: raw.to_vec(),
                    align,
                    orig_idx: idx,
                    seg_offset: 0,
                    vaddr: 0,
                });
            }
            SectionKind::UninitializedData => {
                // BSS: represent as explicit zeros so we can write them to the file.
                // (p_memsz > p_filesz for true BSS optimisation is a future improvement.)
                data_secs.push(Section {
                    name,
                    kind: SectionKind::UninitializedData,
                    data: vec![0u8; raw.len()],
                    align,
                    orig_idx: idx,
                    seg_offset: 0,
                    vaddr: 0,
                });
            }
            _ => {} // metadata sections — skip
        }
    }

    // ---- Layout: text segment ----
    //
    //   File offset 0x000 : ELF header + program headers (not in any PT_LOAD)
    //   File offset PAGE  : text segment   →  vaddr ELF_BASE + PAGE
    //   File offset next  : data segment   →  vaddr ELF_BASE + next
    //
    let text_file_off: u64 = PAGE;
    let text_vaddr: u64 = ELF_BASE + text_file_off;

    let mut cursor: u64 = 0;
    for s in &mut text_secs {
        cursor = align_up(cursor, s.align);
        s.seg_offset = cursor;
        s.vaddr = text_vaddr + cursor;
        cursor += s.data.len() as u64;
    }

    // syscall stub immediately after compiled code
    cursor = align_up(cursor, 16);
    let syscall_seg_off = cursor;
    let syscall_vaddr = text_vaddr + cursor;
    cursor += syscall_bytes.len() as u64;

    // _start stub at the very end of text
    let start_align = match arch {
        ElfArch::Aarch64 => 4, // aarch64 instructions are 4-byte aligned
        _ => 16,
    };
    cursor = align_up(cursor, start_align);
    let start_seg_off = cursor;
    let start_vaddr = text_vaddr + cursor;
    let start_size = arch.start_size();
    cursor += start_size;

    let text_total = cursor;

    // ---- Layout: data segment ----
    let data_file_off = align_up(text_file_off + text_total, PAGE);
    let data_vaddr: u64 = ELF_BASE + data_file_off;

    cursor = 0;
    for s in &mut data_secs {
        cursor = align_up(cursor, s.align);
        s.seg_offset = cursor;
        s.vaddr = data_vaddr + cursor;
        cursor += s.data.len() as u64;
    }
    let data_total = cursor;
    let has_data = data_total > 0;

    // ---- Build symbol map ----
    let mut syms: BTreeMap<String, u64> = BTreeMap::new();
    syms.insert("dyn_syscall".to_string(), syscall_vaddr);
    syms.insert("_start".to_string(), start_vaddr);

    for sym in obj.symbols() {
        let Ok(name) = sym.name() else { continue };
        if name.is_empty() {
            continue;
        }
        let sec_idx = match sym.section() {
            object::read::SymbolSection::Section(i) => i.0,
            _ => continue,
        };
        let offset = sym.address();
        let addr = text_secs
            .iter()
            .find(|s| s.orig_idx == sec_idx)
            .map(|s| s.vaddr + offset)
            .or_else(|| {
                data_secs
                    .iter()
                    .find(|s| s.orig_idx == sec_idx)
                    .map(|s| s.vaddr + offset)
            });
        if let Some(a) = addr {
            syms.insert(name.to_string(), a);
        }
    }

    // Find entry
    let entry_addr = *syms
        .get(entry_sym)
        .ok_or_else(|| format!("entry symbol '{entry_sym}' not found in object"))?;

    // ---- Merge section data into segment buffers ----
    let mut text_buf = vec![0u8; text_total as usize];
    for s in &text_secs {
        let end = s.seg_offset as usize + s.data.len();
        text_buf[s.seg_offset as usize..end].copy_from_slice(&s.data);
    }
    // syscall stub
    let sc_end = syscall_seg_off as usize + syscall_bytes.len();
    text_buf[syscall_seg_off as usize..sc_end].copy_from_slice(syscall_bytes);
    // _start stub (written after we know entry_addr)
    arch.write_start(&mut text_buf[start_seg_off as usize..], entry_addr, start_vaddr);

    let mut data_buf = vec![0u8; data_total as usize];
    for s in &data_secs {
        let end = s.seg_offset as usize + s.data.len();
        data_buf[s.seg_offset as usize..end].copy_from_slice(&s.data);
    }

    // ---- Resolve relocations ----
    for sec in obj.sections() {
        let sec_idx = sec.index().0;
        let (is_text, seg_off, sec_vaddr) =
            if let Some(s) = text_secs.iter().find(|s| s.orig_idx == sec_idx) {
                (true, s.seg_offset, s.vaddr)
            } else if let Some(s) = data_secs.iter().find(|s| s.orig_idx == sec_idx) {
                (false, s.seg_offset, s.vaddr)
            } else {
                continue;
            };

        for (reloc_off, reloc) in sec.relocations() {
            let sym_addr = match reloc.target() {
                RelocationTarget::Symbol(sym_idx) => {
                    let sym = obj
                        .symbol_by_index(sym_idx)
                        .map_err(|e| format!("bad relocation symbol index: {e}"))?;
                    let name = sym.name().unwrap_or("");
                    *syms.get(name).ok_or_else(|| format!("undefined symbol '{name}'"))?
                }
                RelocationTarget::Section(target_sec_idx) => {
                    let tidx = target_sec_idx.0;
                    text_secs
                        .iter()
                        .find(|s| s.orig_idx == tidx)
                        .map(|s| s.vaddr)
                        .or_else(|| {
                            data_secs
                                .iter()
                                .find(|s| s.orig_idx == tidx)
                                .map(|s| s.vaddr)
                        })
                        .ok_or_else(|| {
                            format!("section relocation target section {tidx} not found")
                        })?
                }
                _ => continue,
            };

            let size = reloc.size();
            let addend = if reloc.has_implicit_addend() {
                // REL format: addend embedded in the target bytes
                let off = (seg_off + reloc_off) as usize;
                match size {
                    32 => i32::from_le_bytes(text_buf[off..off + 4].try_into().unwrap()) as i64,
                    64 => i64::from_le_bytes(text_buf[off..off + 8].try_into().unwrap()),
                    _ => 0,
                }
            } else {
                reloc.addend()
            };

            let patch_loc = (seg_off + reloc_off) as usize;
            let reloc_addr = sec_vaddr + reloc_off;
            let buf = if is_text { &mut text_buf } else { &mut data_buf };

            arch.apply_reloc(buf, patch_loc, reloc.flags(), sym_addr, addend, reloc_addr)?;
        }
    }

    // ---- Write ELF executable ----
    let num_phdrs: u64 = if has_data { 2 } else { 1 };
    let text_file_end = text_file_off + text_total;
    let data_file_end = if has_data {
        data_file_off + data_total
    } else {
        text_file_end
    };
    let file_size = data_file_end;

    let mut file = vec![0u8; file_size as usize];

    // ELF64 header (64 bytes)
    {
        let h = &mut file[0..64];
        h[0..4].copy_from_slice(b"\x7fELF");
        h[4] = 2; // ELFCLASS64
        h[5] = 1; // ELFDATA2LSB
        h[6] = 1; // EV_CURRENT
        h[7] = 0; // ELFOSABI_NONE
        // h[8..16] = ABI version + padding (already 0)
        put_u16(&mut h[16..], 2); // ET_EXEC
        put_u16(&mut h[18..], arch.em_machine());
        put_u32(&mut h[20..], 1); // e_version
        put_u64(&mut h[24..], start_vaddr); // e_entry (_start)
        put_u64(&mut h[32..], 64); // e_phoff (program headers right after)
        put_u64(&mut h[40..], 0); // e_shoff (no section headers)
        put_u32(&mut h[48..], 0); // e_flags
        put_u16(&mut h[52..], 64); // e_ehsize
        put_u16(&mut h[54..], 56); // e_phentsize
        put_u16(&mut h[56..], num_phdrs as u16); // e_phnum
        put_u16(&mut h[58..], 64); // e_shentsize
        put_u16(&mut h[60..], 0); // e_shnum
        put_u16(&mut h[62..], 0); // e_shstrndx
    }

    // Text PT_LOAD (RX)  — offset 64, size 56
    write_phdr(
        &mut file[64..120],
        text_file_off,
        text_vaddr,
        text_total,
        text_total,
        5, // PF_R | PF_X
        PAGE,
    );

    // Data PT_LOAD (RW)  — offset 120, size 56
    if has_data {
        write_phdr(
            &mut file[120..176],
            data_file_off,
            data_vaddr,
            data_total,
            data_total,
            6, // PF_R | PF_W
            PAGE,
        );
    }

    // Copy segment bytes
    file[text_file_off as usize..text_file_end as usize].copy_from_slice(&text_buf);
    if has_data {
        file[data_file_off as usize..(data_file_off + data_total) as usize]
            .copy_from_slice(&data_buf);
    }

    Ok(file)
}

// ---------------------------------------------------------------------------
// _start stub for x86-64 Linux
//   call <entry>       e8 XX XX XX XX   (5)
//   mov rdi, rax       48 89 c7         (3)
//   mov eax, 60        b8 3c 00 00 00   (5)
//   syscall            0f 05            (2)
//                                      = 15 bytes total
// ---------------------------------------------------------------------------
fn write_start_x86_64_linux(buf: &mut [u8], entry_addr: u64, start_vaddr: u64) {
    let rel = ((entry_addr as i64) - (start_vaddr as i64 + 5)) as i32;
    buf[0] = 0xe8;
    buf[1..5].copy_from_slice(&rel.to_le_bytes());
    buf[5] = 0x48;
    buf[6] = 0x89;
    buf[7] = 0xc7;
    buf[8] = 0xb8;
    buf[9] = 60;
    buf[10] = 0;
    buf[11] = 0;
    buf[12] = 0;
    buf[13] = 0x0f;
    buf[14] = 0x05;
}

// ---------------------------------------------------------------------------
// _start stub for aarch64 Linux
//   bl <entry>         (4) — call main; return value arrives in x0
//   mov x8, #93        (4) — sys_exit syscall number (Linux aarch64)
//   svc #0             (4) — kernel entry
//                         = 12 bytes total
// ---------------------------------------------------------------------------
fn write_start_aarch64_linux(buf: &mut [u8], entry_addr: u64, start_vaddr: u64) {
    // BL: opcode 0x94000000 | imm26, where imm26 = (target - pc) >> 2
    let delta = ((entry_addr as i64) - (start_vaddr as i64)) >> 2;
    let imm26 = (delta as u32) & 0x3FFFFFF;
    let bl = 0x94000000u32 | imm26;
    buf[0..4].copy_from_slice(&bl.to_le_bytes());

    // MOVZ x8, #93  →  0xD2800000 | (93 << 5) | 8
    let movz: u32 = 0xD280_0000 | (93u32 << 5) | 8;
    buf[4..8].copy_from_slice(&movz.to_le_bytes());

    // SVC #0  →  0xD4000001
    buf[8..12].copy_from_slice(&0xD400_0001u32.to_le_bytes());
}

// ---------------------------------------------------------------------------
// Relocation application for x86-64
// ---------------------------------------------------------------------------
fn apply_reloc_x86_64(
    buf: &mut [u8],
    offset: usize,
    flags: RelocationFlags,
    sym_addr: u64,
    addend: i64,
    reloc_addr: u64,
) -> Result<(), String> {
    let (kind, size) = match flags {
        RelocationFlags::Generic { kind, size, .. } => (kind, size),
        other => {
            return Err(format!("unsupported x86-64 relocation flags: {other:?} at {offset:#x}"));
        }
    };
    match (kind, size) {
        // R_X86_64_64 — 64-bit absolute: S + A
        (RelocationKind::Absolute, 64) => {
            let v = (sym_addr as i64).wrapping_add(addend) as u64;
            buf[offset..offset + 8].copy_from_slice(&v.to_le_bytes());
        }
        // R_X86_64_32 / R_X86_64_32S — 32-bit absolute: (S + A) truncated
        (RelocationKind::Absolute, 32) => {
            let v = (sym_addr as i64).wrapping_add(addend) as i32;
            buf[offset..offset + 4].copy_from_slice(&v.to_le_bytes());
        }
        // R_X86_64_PC32 — 32-bit PC-relative: S + A - P
        // R_X86_64_PLT32 — same formula (PLT → direct call for static link)
        (RelocationKind::Relative | RelocationKind::PltRelative, 32) => {
            let v = ((sym_addr as i64) + addend - (reloc_addr as i64)) as i32;
            buf[offset..offset + 4].copy_from_slice(&v.to_le_bytes());
        }
        // R_X86_64_GOTPCREL / R_X86_64_GOTPCRELX — for static linking we treat as PC32.
        // Cranelift in non-PIC mode uses `lea`/`mov [rip+disp]` patterns where the
        // GOT entry holds the symbol address directly; resolving as PC32 works for the
        // `lea` pattern (address of data). The `mov` (load-through-GOT) pattern would
        // require a real GOT entry; if that case arises the value will be wrong and the
        // caller should fall back to the external linker.
        (RelocationKind::GotRelative, 32) => {
            let v = ((sym_addr as i64) + addend - (reloc_addr as i64)) as i32;
            buf[offset..offset + 4].copy_from_slice(&v.to_le_bytes());
        }
        _ => {
            return Err(format!(
                "unsupported x86-64 relocation: {kind:?} size={size} at {offset:#x}"
            ));
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Relocation application for aarch64
// ---------------------------------------------------------------------------
fn apply_reloc_aarch64(
    buf: &mut [u8],
    offset: usize,
    flags: RelocationFlags,
    sym_addr: u64,
    addend: i64,
    reloc_addr: u64,
) -> Result<(), String> {
    match flags {
        // Architecture-specific ELF relocations: ADRP, ADD, LDST patterns
        RelocationFlags::Elf { r_type } => {
            apply_reloc_aarch64_elf(buf, offset, r_type, sym_addr, addend, reloc_addr)?;
        }
        RelocationFlags::Generic { kind, encoding, size } => {
            match (kind, encoding, size) {
                // R_AARCH64_ABS64
                (RelocationKind::Absolute, _, 64) => {
                    let v = (sym_addr as i64).wrapping_add(addend) as u64;
                    buf[offset..offset + 8].copy_from_slice(&v.to_le_bytes());
                }
                // R_AARCH64_ABS32
                (RelocationKind::Absolute, _, 32) => {
                    let v = (sym_addr as i64).wrapping_add(addend) as u32;
                    buf[offset..offset + 4].copy_from_slice(&v.to_le_bytes());
                }
                // R_AARCH64_PREL32
                (RelocationKind::Relative, _, 32) => {
                    let v = ((sym_addr as i64) + addend - (reloc_addr as i64)) as i32;
                    buf[offset..offset + 4].copy_from_slice(&v.to_le_bytes());
                }
                // R_AARCH64_CALL26 / R_AARCH64_JUMP26
                // Encodes (S + A - P) >> 2 into bits [25:0] of the BL/B instruction.
                (RelocationKind::PltRelative, RelocationEncoding::AArch64Call, 26) => {
                    let delta = ((sym_addr as i64) + addend - (reloc_addr as i64)) >> 2;
                    let imm26 = (delta as i32) & 0x3FF_FFFF;
                    let insn = u32::from_le_bytes(buf[offset..offset + 4].try_into().unwrap());
                    let new_insn = (insn & 0xFC00_0000) | (imm26 as u32 & 0x3FF_FFFF);
                    buf[offset..offset + 4].copy_from_slice(&new_insn.to_le_bytes());
                }
                _ => {
                    return Err(format!(
                        "unsupported aarch64 relocation: {kind:?} enc={encoding:?} size={size} at {offset:#x}"
                    ));
                }
            }
        }
        other => {
            return Err(format!(
                "unsupported aarch64 relocation flags: {other:?} at {offset:#x}"
            ));
        }
    }
    Ok(())
}

fn apply_reloc_aarch64_elf(
    buf: &mut [u8],
    offset: usize,
    r_type: u32,
    sym_addr: u64,
    addend: i64,
    reloc_addr: u64,
) -> Result<(), String> {
    let target = (sym_addr as i64).wrapping_add(addend);

    match r_type {
        // R_AARCH64_ADR_PREL_PG_HI21 (275)
        // ADRP: page-relative. Encodes ((page(sym+A) - page(P)) >> 12) into the instruction.
        // immlo in [30:29], immhi in [23:5].
        275 => {
            let sym_page = target & !0xFFF;
            let pc_page = (reloc_addr as i64) & !0xFFF;
            let delta = (sym_page - pc_page) >> 12;
            let immlo = (delta as u32) & 0x3;
            let immhi = ((delta as u32) >> 2) & 0x7_FFFF;
            let insn = u32::from_le_bytes(buf[offset..offset + 4].try_into().unwrap());
            // ADRP instruction: [31]=1,[30:29]=immlo,[28:24]=10000,[23:5]=immhi,[4:0]=Rd
            let new_insn = (insn & 0x9F00_001F) | (immlo << 29) | (immhi << 5);
            buf[offset..offset + 4].copy_from_slice(&new_insn.to_le_bytes());
        }
        // R_AARCH64_ADD_ABS_LO12_NC (277)
        // ADD: low 12 bits of sym+A, in bits [21:10] of ADD immediate instruction.
        277 => {
            let lo12 = (target as u32) & 0xFFF;
            let insn = u32::from_le_bytes(buf[offset..offset + 4].try_into().unwrap());
            let new_insn = (insn & 0xFFC0_03FF) | (lo12 << 10);
            buf[offset..offset + 4].copy_from_slice(&new_insn.to_le_bytes());
        }
        // R_AARCH64_LDST8_ABS_LO12_NC (278)
        // 8-bit load/store: low 12 bits (unscaled), in bits [21:10].
        278 => {
            let lo12 = (target as u32) & 0xFFF;
            let insn = u32::from_le_bytes(buf[offset..offset + 4].try_into().unwrap());
            let new_insn = (insn & 0xFFC0_03FF) | (lo12 << 10);
            buf[offset..offset + 4].copy_from_slice(&new_insn.to_le_bytes());
        }
        // R_AARCH64_LDST16_ABS_LO12_NC (284)
        // 16-bit load/store: low 12 bits >> 1, in bits [21:10].
        284 => {
            let lo12 = (target as u32) & 0xFFF;
            let scaled = lo12 >> 1;
            let insn = u32::from_le_bytes(buf[offset..offset + 4].try_into().unwrap());
            let new_insn = (insn & 0xFFC0_03FF) | (scaled << 10);
            buf[offset..offset + 4].copy_from_slice(&new_insn.to_le_bytes());
        }
        // R_AARCH64_LDST32_ABS_LO12_NC (285)
        // 32-bit load/store: low 12 bits >> 2, in bits [21:10].
        285 => {
            let lo12 = (target as u32) & 0xFFF;
            let scaled = lo12 >> 2;
            let insn = u32::from_le_bytes(buf[offset..offset + 4].try_into().unwrap());
            let new_insn = (insn & 0xFFC0_03FF) | (scaled << 10);
            buf[offset..offset + 4].copy_from_slice(&new_insn.to_le_bytes());
        }
        // R_AARCH64_LDST64_ABS_LO12_NC (286)
        // 64-bit load/store: low 12 bits >> 3, in bits [21:10].
        286 => {
            let lo12 = (target as u32) & 0xFFF;
            let scaled = lo12 >> 3;
            let insn = u32::from_le_bytes(buf[offset..offset + 4].try_into().unwrap());
            let new_insn = (insn & 0xFFC0_03FF) | (scaled << 10);
            buf[offset..offset + 4].copy_from_slice(&new_insn.to_le_bytes());
        }
        // R_AARCH64_LDST128_ABS_LO12_NC (299)
        // 128-bit load/store: low 12 bits >> 4, in bits [21:10].
        299 => {
            let lo12 = (target as u32) & 0xFFF;
            let scaled = lo12 >> 4;
            let insn = u32::from_le_bytes(buf[offset..offset + 4].try_into().unwrap());
            let new_insn = (insn & 0xFFC0_03FF) | (scaled << 10);
            buf[offset..offset + 4].copy_from_slice(&new_insn.to_le_bytes());
        }
        _ => {
            return Err(format!(
                "unsupported aarch64 ELF relocation type {r_type} at {offset:#x}"
            ));
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// ELF writing helpers
// ---------------------------------------------------------------------------

fn write_phdr(
    buf: &mut [u8],
    file_offset: u64,
    vaddr: u64,
    filesz: u64,
    memsz: u64,
    flags: u32,
    align: u64,
) {
    put_u32(&mut buf[0..], 1); // p_type  PT_LOAD
    put_u32(&mut buf[4..], flags); // p_flags
    put_u64(&mut buf[8..], file_offset); // p_offset
    put_u64(&mut buf[16..], vaddr); // p_vaddr
    put_u64(&mut buf[24..], vaddr); // p_paddr
    put_u64(&mut buf[32..], filesz); // p_filesz
    put_u64(&mut buf[40..], memsz); // p_memsz
    put_u64(&mut buf[48..], align); // p_align
}

fn put_u16(buf: &mut [u8], v: u16) {
    buf[..2].copy_from_slice(&v.to_le_bytes());
}
fn put_u32(buf: &mut [u8], v: u32) {
    buf[..4].copy_from_slice(&v.to_le_bytes());
}
fn put_u64(buf: &mut [u8], v: u64) {
    buf[..8].copy_from_slice(&v.to_le_bytes());
}

// ===========================================================================
// PE/COFF x86-64 direct linker  (Windows, no MSVC or lld required)
// ===========================================================================
//
// Produces a minimal PE32+ (64-bit) executable that imports exactly one
// symbol from the Win32 API: kernel32!ExitProcess.  That single import gives
// us a clean process exit; everything else is generated by Cranelift.
//
// Layout (all sizes page-aligned for memory, sector-aligned for file):
//
//   [0x000..hdr_file_size)  PE headers (DOS stub + COFF + OptHdr + section hdrs)
//   [text_file_off ..)      .text  — RX  — Cranelift code + syscall stub + _start
//   [data_file_off ..)      .data  — RW  — globals / bss (optional)
//   [idata_file_off..)      .idata — RW  — import directory + IAT for ExitProcess

// Preferred image base.  Not using DYNAMIC_BASE so the loader uses this
// address directly; no .reloc section is needed for position-independent data.
const PE_IMAGE_BASE: u64 = 0x0000_0001_4000_0000;
const PE_SEC_ALIGN: u64 = 0x1000;
const PE_FILE_ALIGN: u64 = 0x0200;

// .idata section — fixed layout (all offsets relative to section start):
//
//   0  ..  20  Import Directory Entry for kernel32.dll
//   20 ..  40  Null terminator IDT
//   40 ..  48  Import Lookup Table entry  (Hint/Name RVA, 8 bytes)
//   48 ..  56  ILT null terminator
//   56 ..  64  Import Address Table entry (same value; loader patches this)
//   64 ..  72  IAT null terminator
//   72 ..  86  Hint/Name:  hint(2) + "ExitProcess\0"(12)
//   86 ..  99  DLL name:   "kernel32.dll\0"
//   99 .. 104  padding
const IDATA_ILT_OFF: usize = 40;
const IDATA_IAT_OFF: usize = 56;
const IDATA_HN_OFF: usize = 72;
const IDATA_DLL_OFF: usize = 86;
const IDATA_SIZE: usize = 104;

fn link_pe_x86_64(
    obj_bytes: &[u8],
    syscall_bytes: &[u8],
    entry_sym: &str,
) -> Result<Vec<u8>, String> {
    let obj = ObjFile::parse(obj_bytes)
        .map_err(|e| format!("failed to parse COFF object: {e}"))?;

    // ---- Collect sections ----
    let mut text_secs: Vec<Section> = Vec::new();
    let mut data_secs: Vec<Section> = Vec::new();
    for sec in obj.sections() {
        let name = sec.name().unwrap_or("").to_string();
        let raw = sec.data().map_err(|e| format!("section '{name}' data: {e}"))?;
        let align = sec.align().max(1);
        let idx = sec.index().0;
        match sec.kind() {
            SectionKind::Text => text_secs.push(Section {
                name, kind: SectionKind::Text, data: raw.to_vec(),
                align, orig_idx: idx, seg_offset: 0, vaddr: 0,
            }),
            SectionKind::Data | SectionKind::ReadOnlyData => data_secs.push(Section {
                name, kind: sec.kind(), data: raw.to_vec(),
                align, orig_idx: idx, seg_offset: 0, vaddr: 0,
            }),
            SectionKind::UninitializedData => data_secs.push(Section {
                name, kind: SectionKind::UninitializedData,
                data: vec![0u8; sec.size() as usize],
                align, orig_idx: idx, seg_offset: 0, vaddr: 0,
            }),
            _ => {}
        }
    }
    let has_data = !data_secs.is_empty();

    // ---- PE header region size ----
    // DOS(64) + PE-sig(4) + COFF-hdr(20) + OptHdr(240) + n_secs*40
    let n_secs: usize = 1 + (if has_data { 1 } else { 0 }) + 1; // text [+data] +idata
    let hdr_raw = 64 + 4 + 20 + 240 + n_secs * 40;
    let hdr_file_size = align_up(hdr_raw as u64, PE_FILE_ALIGN);

    // ---- Layout: .text ----
    let text_rva: u64 = PE_SEC_ALIGN; // 0x1000
    let text_vaddr = PE_IMAGE_BASE + text_rva;

    let mut cursor: u64 = 0;
    for s in &mut text_secs {
        cursor = align_up(cursor, s.align);
        s.seg_offset = cursor;
        s.vaddr = text_vaddr + cursor;
        cursor += s.data.len() as u64;
    }
    cursor = align_up(cursor, 16);
    let syscall_seg_off = cursor;
    let syscall_vaddr = text_vaddr + cursor;
    cursor += syscall_bytes.len() as u64;
    cursor = align_up(cursor, 16);
    let start_seg_off = cursor;
    let start_vaddr = text_vaddr + cursor;
    // sub+call+mov+call[mem] = 4+5+3+6 = 18 bytes
    const PE_START_SIZE: u64 = 18;
    cursor += PE_START_SIZE;

    let text_vsz = cursor; // actual content bytes
    let text_raw_size = align_up(text_vsz, PE_FILE_ALIGN);
    let text_virt_aligned = align_up(text_vsz, PE_SEC_ALIGN);

    // ---- Layout: .data (optional) ----
    let data_rva = text_rva + text_virt_aligned;
    let data_vaddr = PE_IMAGE_BASE + data_rva;
    cursor = 0;
    for s in &mut data_secs {
        cursor = align_up(cursor, s.align);
        s.seg_offset = cursor;
        s.vaddr = data_vaddr + cursor;
        cursor += s.data.len() as u64;
    }
    let data_vsz = cursor;
    let data_raw_size = if has_data { align_up(data_vsz, PE_FILE_ALIGN) } else { 0 };
    let data_virt_aligned = if has_data { align_up(data_vsz, PE_SEC_ALIGN) } else { 0 };

    // ---- Layout: .idata ----
    let idata_rva = data_rva + data_virt_aligned;
    let idata_vaddr = PE_IMAGE_BASE + idata_rva;
    let idata_raw_size = align_up(IDATA_SIZE as u64, PE_FILE_ALIGN);
    let idata_virt_aligned = align_up(IDATA_SIZE as u64, PE_SEC_ALIGN);

    // VA of the IAT entry for ExitProcess (patched by the loader at runtime)
    let iat_vaddr = idata_vaddr + IDATA_IAT_OFF as u64;

    // ---- Symbol map ----
    let mut syms: BTreeMap<String, u64> = BTreeMap::new();
    syms.insert("dyn_syscall".to_string(), syscall_vaddr);
    syms.insert("_start".to_string(), start_vaddr);
    for sym in obj.symbols() {
        let Ok(name) = sym.name() else { continue };
        if name.is_empty() { continue }
        let sec_idx = match sym.section() {
            object::read::SymbolSection::Section(i) => i.0,
            _ => continue,
        };
        let offset = sym.address();
        let addr = text_secs.iter().find(|s| s.orig_idx == sec_idx)
            .map(|s| s.vaddr + offset)
            .or_else(|| data_secs.iter().find(|s| s.orig_idx == sec_idx)
                .map(|s| s.vaddr + offset));
        if let Some(a) = addr { syms.insert(name.to_string(), a); }
    }

    let entry_addr = *syms.get(entry_sym)
        .ok_or_else(|| format!("entry symbol '{entry_sym}' not found in object"))?;

    // ---- Merge section content into buffers ----
    let mut text_buf = vec![0u8; text_raw_size as usize];
    for s in &text_secs {
        let e = s.seg_offset as usize + s.data.len();
        text_buf[s.seg_offset as usize..e].copy_from_slice(&s.data);
    }
    let sc_end = syscall_seg_off as usize + syscall_bytes.len();
    text_buf[syscall_seg_off as usize..sc_end].copy_from_slice(syscall_bytes);
    write_start_pe_x86_64(
        &mut text_buf[start_seg_off as usize..],
        entry_addr, start_vaddr, iat_vaddr,
    );

    let mut data_buf = vec![0u8; data_raw_size as usize];
    for s in &data_secs {
        let e = s.seg_offset as usize + s.data.len();
        data_buf[s.seg_offset as usize..e].copy_from_slice(&s.data);
    }

    let idata_buf = build_idata_pe(idata_rva);

    // ---- Apply COFF relocations ----
    for sec in obj.sections() {
        let sec_idx = sec.index().0;
        let (is_text, seg_off, sec_vaddr) =
            if let Some(s) = text_secs.iter().find(|s| s.orig_idx == sec_idx) {
                (true, s.seg_offset, s.vaddr)
            } else if let Some(s) = data_secs.iter().find(|s| s.orig_idx == sec_idx) {
                (false, s.seg_offset, s.vaddr)
            } else { continue };

        for (reloc_off, reloc) in sec.relocations() {
            let sym_addr = match reloc.target() {
                RelocationTarget::Symbol(sym_idx) => {
                    let sym = obj.symbol_by_index(sym_idx)
                        .map_err(|e| format!("bad symbol index: {e}"))?;
                    let name = sym.name().unwrap_or("");
                    *syms.get(name).ok_or_else(|| format!("undefined symbol '{name}'"))?
                }
                RelocationTarget::Section(tidx) => {
                    let t = tidx.0;
                    text_secs.iter().find(|s| s.orig_idx == t).map(|s| s.vaddr)
                        .or_else(|| data_secs.iter().find(|s| s.orig_idx == t).map(|s| s.vaddr))
                        .ok_or_else(|| format!("section reloc target {t} not found"))?
                }
                _ => continue,
            };

            // COFF always uses implicit addends; read from the correct buffer.
            let patch_loc = (seg_off + reloc_off) as usize;
            let reloc_va = sec_vaddr + reloc_off;
            let addend: i64 = {
                let src = if is_text { &text_buf } else { &data_buf };
                match reloc.size() {
                    32 => i32::from_le_bytes(src[patch_loc..patch_loc + 4].try_into().unwrap()) as i64,
                    64 => i64::from_le_bytes(src[patch_loc..patch_loc + 8].try_into().unwrap()),
                    _ => 0,
                }
            };

            let buf = if is_text { &mut text_buf } else { &mut data_buf };
            apply_reloc_coff_x86_64(buf, patch_loc, reloc.flags(), sym_addr, addend, reloc_va)?;
        }
    }

    // ---- File offset assignments ----
    let text_file_off = hdr_file_size;
    let data_file_off = text_file_off + text_raw_size;
    let idata_file_off = data_file_off + data_raw_size;
    let total_size = idata_file_off + idata_raw_size;
    let image_size = (idata_rva + idata_virt_aligned) as u32;

    // ---- Assemble PE file ----
    let mut file = vec![0u8; total_size as usize];

    // DOS stub: just the MZ magic and e_lfanew pointer
    put_u16(&mut file[0..], 0x5A4D); // MZ
    put_u16(&mut file[0x3C..], 0x40); // e_lfanew = 0x40

    // PE signature
    file[0x40..0x44].copy_from_slice(b"PE\0\0");

    // COFF file header (20 bytes at 0x44)
    {
        let h = &mut file[0x44..0x58];
        put_u16(&mut h[0..], 0x8664); // Machine: AMD64
        put_u16(&mut h[2..], n_secs as u16);
        put_u32(&mut h[4..], 0);   // TimeDateStamp
        put_u32(&mut h[8..], 0);   // PointerToSymbolTable
        put_u32(&mut h[12..], 0);  // NumberOfSymbols
        put_u16(&mut h[16..], 240); // SizeOfOptionalHeader
        put_u16(&mut h[18..], 0x0022); // Characteristics: EXEC | LARGE_ADDR_AWARE
    }

    // PE32+ optional header (240 bytes at 0x58)
    {
        let h = &mut file[0x58..0x58 + 240];
        put_u16(&mut h[0..], 0x020B); // Magic: PE32+
        // MajorLinkerVersion, MinorLinkerVersion = 0 (already)
        put_u32(&mut h[4..],  text_raw_size as u32);  // SizeOfCode
        put_u32(&mut h[8..],  (data_raw_size + idata_raw_size) as u32); // SizeOfInitData
        put_u32(&mut h[12..], 0); // SizeOfUninitData
        put_u32(&mut h[16..], (start_vaddr - PE_IMAGE_BASE) as u32); // AddressOfEntryPoint
        put_u32(&mut h[20..], text_rva as u32); // BaseOfCode
        put_u64(&mut h[24..], PE_IMAGE_BASE);   // ImageBase
        put_u32(&mut h[32..], PE_SEC_ALIGN as u32);  // SectionAlignment
        put_u32(&mut h[36..], PE_FILE_ALIGN as u32); // FileAlignment
        put_u16(&mut h[40..], 6); // MajorOperatingSystemVersion
        // MinorOperatingSystemVersion = 0
        // MajorImageVersion, MinorImageVersion = 0
        put_u16(&mut h[48..], 6); // MajorSubsystemVersion
        // MinorSubsystemVersion = 0
        // Win32VersionValue = 0
        put_u32(&mut h[56..], image_size);           // SizeOfImage
        put_u32(&mut h[60..], hdr_file_size as u32); // SizeOfHeaders
        // CheckSum = 0
        put_u16(&mut h[68..], 3);    // Subsystem: IMAGE_SUBSYSTEM_WINDOWS_CUI
        put_u16(&mut h[70..], 0x0100); // DllCharacteristics: NX_COMPAT
        put_u64(&mut h[72..], 0x10_0000); // SizeOfStackReserve (1 MB)
        put_u64(&mut h[80..], 0x1000);    // SizeOfStackCommit  (4 KB)
        put_u64(&mut h[88..], 0x10_0000); // SizeOfHeapReserve
        put_u64(&mut h[96..], 0x1000);    // SizeOfHeapCommit
        // LoaderFlags = 0
        put_u32(&mut h[108..], 16); // NumberOfRvaAndSizes
        // DataDirectory[1]: Import Table (IDT = 2 entries × 20 bytes)
        put_u32(&mut h[112 + 8 ..], idata_rva as u32);
        put_u32(&mut h[112 + 12..], 40);
        // DataDirectory[12]: IAT (ExitProcess entry + null × 8 bytes each)
        put_u32(&mut h[112 + 96..], (idata_rva + IDATA_IAT_OFF as u64) as u32);
        put_u32(&mut h[112 + 100..], 16);
    }

    // Section headers (40 bytes each, starting at 0x148)
    let mut shdr = 0x58 + 240;

    write_pe_sec_hdr(&mut file[shdr..shdr + 40],
        b".text\0\0\0", text_vsz as u32, text_rva as u32,
        text_raw_size as u32, text_file_off as u32, 0x6000_0020);
    shdr += 40;

    if has_data {
        write_pe_sec_hdr(&mut file[shdr..shdr + 40],
            b".data\0\0\0", data_vsz as u32, data_rva as u32,
            data_raw_size as u32, data_file_off as u32, 0xC000_0040);
        shdr += 40;
    }

    write_pe_sec_hdr(&mut file[shdr..shdr + 40],
        b".idata\0\0", IDATA_SIZE as u32, idata_rva as u32,
        idata_raw_size as u32, idata_file_off as u32, 0xC000_0040);

    // Copy section data
    let te = text_file_off as usize + text_raw_size as usize;
    file[text_file_off as usize..te].copy_from_slice(&text_buf);
    if has_data && data_raw_size > 0 {
        let de = data_file_off as usize + data_raw_size as usize;
        file[data_file_off as usize..de].copy_from_slice(&data_buf);
    }
    file[idata_file_off as usize..idata_file_off as usize + IDATA_SIZE]
        .copy_from_slice(&idata_buf);

    Ok(file)
}

// ---------------------------------------------------------------------------
// Build the .idata section (import table for kernel32!ExitProcess)
// ---------------------------------------------------------------------------
fn build_idata_pe(idata_rva: u64) -> Vec<u8> {
    let mut b = vec![0u8; IDATA_SIZE];

    // Import Directory Entry for kernel32.dll (offset 0)
    put_u32(&mut b[0..],  (idata_rva + IDATA_ILT_OFF as u64) as u32); // OriginalFirstThunk
    // TimeDateStamp, ForwarderChain = 0 (already)
    put_u32(&mut b[12..], (idata_rva + IDATA_DLL_OFF as u64) as u32); // Name RVA
    put_u32(&mut b[16..], (idata_rva + IDATA_IAT_OFF as u64) as u32); // FirstThunk (IAT)
    // Null IDT entry at [20..40]: already zero

    // ILT entry (offset 40): RVA of Hint/Name (bit63=0 → by-name import)
    let hn_rva = (idata_rva + IDATA_HN_OFF as u64) as u64;
    put_u64(&mut b[IDATA_ILT_OFF..], hn_rva);
    // ILT null at [48..56]: already zero

    // IAT entry (offset 56): same value initially; loader overwrites with VA
    put_u64(&mut b[IDATA_IAT_OFF..], hn_rva);
    // IAT null at [64..72]: already zero

    // Hint/Name (offset 72): hint(2 bytes, 0) + "ExitProcess\0"
    // hint bytes already zero
    b[IDATA_HN_OFF + 2..IDATA_HN_OFF + 14].copy_from_slice(b"ExitProcess\0");

    // DLL name (offset 86)
    b[IDATA_DLL_OFF..IDATA_DLL_OFF + 13].copy_from_slice(b"kernel32.dll\0");

    b
}

// ---------------------------------------------------------------------------
// _start stub for PE x86-64 Windows (18 bytes)
//
//   sub  rsp, 0x28          48 83 EC 28        (4) stack alignment + shadow
//   call <entry>            E8 XX XX XX XX     (5) rax = main()
//   mov  rcx, rax           48 89 C1           (3) ExitProcess(exit_code)
//   call [rip + <iat_disp>] FF 15 XX XX XX XX  (6) indirect via IAT
// ---------------------------------------------------------------------------
fn write_start_pe_x86_64(buf: &mut [u8], entry_addr: u64, start_vaddr: u64, iat_vaddr: u64) {
    // sub rsp, 0x28  (at entry RSP%16==8; after this RSP%16==0 → call aligns correctly)
    buf[0] = 0x48; buf[1] = 0x83; buf[2] = 0xEC; buf[3] = 0x28;
    // call <entry>  — relative to next instruction (offset 9)
    let call_rel = (entry_addr as i64 - (start_vaddr as i64 + 9)) as i32;
    buf[4] = 0xE8;
    buf[5..9].copy_from_slice(&call_rel.to_le_bytes());
    // mov rcx, rax
    buf[9] = 0x48; buf[10] = 0x89; buf[11] = 0xC1;
    // call [rip + iat_disp]  — RIP is start_vaddr+18 when this executes
    let iat_disp = (iat_vaddr as i64 - (start_vaddr as i64 + 18)) as i32;
    buf[12] = 0xFF; buf[13] = 0x15;
    buf[14..18].copy_from_slice(&iat_disp.to_le_bytes());
}

// ---------------------------------------------------------------------------
// PE section header (40 bytes)
// ---------------------------------------------------------------------------
fn write_pe_sec_hdr(
    buf: &mut [u8],
    name: &[u8; 8],
    virtual_size: u32,
    virtual_addr: u32,
    raw_size: u32,
    raw_off: u32,
    characteristics: u32,
) {
    buf[0..8].copy_from_slice(name);
    put_u32(&mut buf[8..],  virtual_size);
    put_u32(&mut buf[12..], virtual_addr);
    put_u32(&mut buf[16..], raw_size);
    put_u32(&mut buf[20..], raw_off);
    // PointerToRelocations, PointerToLinenumbers, counts = 0 (already)
    put_u32(&mut buf[36..], characteristics);
}

// ---------------------------------------------------------------------------
// COFF x86-64 relocation application
//
// COFF IMAGE_REL_AMD64_REL32 formula: S + A - P - 4
// (P is the VA of the 4-byte field; the -4 accounts for the end-of-field
//  RIP-relative base that x86-64 CALL/JMP use.  Cranelift initialises the
//  field to 0, so A is typically 0.)
// ---------------------------------------------------------------------------
fn apply_reloc_coff_x86_64(
    buf: &mut [u8],
    offset: usize,
    flags: RelocationFlags,
    sym_addr: u64,
    addend: i64,
    reloc_va: u64,
) -> Result<(), String> {
    let (kind, size) = match flags {
        RelocationFlags::Generic { kind, size, .. } => (kind, size),
        other => return Err(format!("unexpected COFF relocation flags {other:?} at {offset:#x}")),
    };
    match (kind, size) {
        // IMAGE_REL_AMD64_ADDR64 — 64-bit absolute VA
        (RelocationKind::Absolute, 64) => {
            let v = (sym_addr as i64 + addend) as u64;
            buf[offset..offset + 8].copy_from_slice(&v.to_le_bytes());
        }
        // IMAGE_REL_AMD64_ADDR32 — 32-bit absolute VA (truncated)
        (RelocationKind::Absolute, 32) => {
            let v = (sym_addr as i64 + addend) as u32;
            buf[offset..offset + 4].copy_from_slice(&v.to_le_bytes());
        }
        // IMAGE_REL_AMD64_REL32 — 32-bit RIP-relative (end-of-field base)
        (RelocationKind::Relative, 32) => {
            let v = (sym_addr as i64 + addend - reloc_va as i64 - 4) as i32;
            buf[offset..offset + 4].copy_from_slice(&v.to_le_bytes());
        }
        _ => return Err(format!(
            "unsupported COFF x86-64 relocation: {kind:?} size={size} at {offset:#x}"
        )),
    }
    Ok(())
}

// ===========================================================================
// Mach-O direct linker  (macOS x86-64 and arm64, no Xcode / ld required)
// ===========================================================================
//
// Uses LC_UNIXTHREAD (no dyld startup, no __LINKEDIT) with raw syscalls.
// For arm64 (Apple Silicon), appends an ad-hoc code signature — required
// by the kernel for all arm64 executables.
//
// Layout:
//   [0, 0x1000)                Mach-O header + load commands + padding
//   [0x1000, 0x1000+text_sz)  __text  (code + syscall stub + _start)
//   [data_off, data_off+d_sz) __data  (globals, optional)
//   [sig_off, sig_off+sig_sz) code signature (arm64 only)

const MACHO_BASE: u64 = 0x0000_0001_0000_0000; // standard macOS 64-bit load address
const MACHO_PAGE: u64 = 0x1000;

// Mach-O header + load command constants (little-endian)
const MH_MAGIC_64: u32 = 0xFEED_FACF;
const MH_EXECUTE: u32 = 2;
const MH_NOUNDEFS: u32 = 0x1;
const LC_SEGMENT_64: u32 = 0x19;
const LC_UNIXTHREAD: u32 = 0x5;
const LC_CODE_SIGNATURE: u32 = 0x1D;
const VM_PROT_RX: i32 = 5; // READ | EXECUTE
const VM_PROT_RW: i32 = 3; // READ | WRITE
const VM_PROT_RWX: i32 = 7; // READ | WRITE | EXECUTE (maxprot)
const S_ATTR_PURE_INST: u32 = 0x8000_0000;
const S_ATTR_SOME_INST: u32 = 0x0000_0400;

fn link_macho(
    obj_bytes: &[u8],
    syscall_bytes: &[u8],
    entry_sym: &str,
    arm64: bool,
) -> Result<Vec<u8>, String> {
    let obj = ObjFile::parse(obj_bytes)
        .map_err(|e| format!("failed to parse Mach-O object: {e}"))?;

    // ---- Collect sections ----
    let mut text_secs: Vec<Section> = Vec::new();
    let mut data_secs: Vec<Section> = Vec::new();
    for sec in obj.sections() {
        let name = sec.name().unwrap_or("").to_string();
        let raw = sec.data().map_err(|e| format!("section '{name}' data: {e}"))?;
        let align = sec.align().max(1);
        let idx = sec.index().0;
        match sec.kind() {
            SectionKind::Text => text_secs.push(Section {
                name, kind: SectionKind::Text, data: raw.to_vec(),
                align, orig_idx: idx, seg_offset: 0, vaddr: 0,
            }),
            SectionKind::Data | SectionKind::ReadOnlyData => data_secs.push(Section {
                name, kind: sec.kind(), data: raw.to_vec(),
                align, orig_idx: idx, seg_offset: 0, vaddr: 0,
            }),
            SectionKind::UninitializedData => data_secs.push(Section {
                name, kind: SectionKind::UninitializedData,
                data: vec![0u8; sec.size() as usize],
                align, orig_idx: idx, seg_offset: 0, vaddr: 0,
            }),
            _ => {}
        }
    }
    let has_data = !data_secs.is_empty();

    // ---- Layout: __text (file starts at 0x1000, header occupies first page) ----
    let text_file_off: u64 = MACHO_PAGE;
    let text_vaddr = MACHO_BASE + text_file_off;

    let mut cursor: u64 = 0;
    for s in &mut text_secs {
        cursor = align_up(cursor, s.align);
        s.seg_offset = cursor;
        s.vaddr = text_vaddr + cursor;
        cursor += s.data.len() as u64;
    }
    let syscall_align: u64 = if arm64 { 4 } else { 16 };
    cursor = align_up(cursor, syscall_align);
    let syscall_seg_off = cursor;
    let syscall_vaddr = text_vaddr + cursor;
    cursor += syscall_bytes.len() as u64;
    cursor = align_up(cursor, syscall_align);
    let start_seg_off = cursor;
    let start_vaddr = text_vaddr + cursor;
    let start_size: u64 = if arm64 { 12 } else { 14 };
    cursor += start_size;

    let text_content_size = cursor;
    let text_seg_filesize = align_up(text_file_off + text_content_size, MACHO_PAGE);
    // __TEXT vmsize covers header+cmds page + text content
    let text_seg_vmsize = text_seg_filesize;

    // ---- Layout: __data (if any) ----
    let data_file_off = text_seg_filesize;
    let data_vaddr = MACHO_BASE + data_file_off;
    cursor = 0;
    for s in &mut data_secs {
        cursor = align_up(cursor, s.align);
        s.seg_offset = cursor;
        s.vaddr = data_vaddr + cursor;
        cursor += s.data.len() as u64;
    }
    let data_content_size = cursor;
    let data_seg_filesize = if has_data { align_up(data_content_size, MACHO_PAGE) } else { 0 };

    // ---- Signature size (arm64 only) ----
    // code_limit = everything before the signature
    let code_limit = data_file_off + data_seg_filesize;
    let n_pages = ((code_limit + MACHO_PAGE - 1) / MACHO_PAGE) as usize;
    // SuperBlob(12) + BlobIndex(8) + CodeDirectory(88) + ident(4) + hashes(n*32)
    let sig_size_raw: u64 = if arm64 { (12 + 8 + 88 + 4 + n_pages as u64 * 32) } else { 0 };
    let sig_size = align_up(sig_size_raw, 16);
    let sig_off = code_limit;

    let total_size = code_limit + sig_size;

    // ---- Load commands ----
    // Sizes: __PAGEZERO(72) + __TEXT(152) + __DATA(152?) + LC_UNIXTHREAD + LC_CODE_SIG?
    let unixthread_size: u64 = if arm64 { 288 } else { 184 };
    let codesig_lc_size: u64 = if arm64 { 16 } else { 0 };
    let mut sizeofcmds: u64 = 72 + 152 + unixthread_size + codesig_lc_size;
    if has_data { sizeofcmds += 152; }
    let ncmds: u32 = 3 + (if has_data { 1 } else { 0 }) + (if arm64 { 1 } else { 0 });

    // ---- Symbol map ----
    let mut syms: BTreeMap<String, u64> = BTreeMap::new();
    syms.insert("dyn_syscall".to_string(), syscall_vaddr);
    syms.insert("_start".to_string(), start_vaddr);
    for sym in obj.symbols() {
        let Ok(name) = sym.name() else { continue };
        if name.is_empty() { continue }
        let sec_idx = match sym.section() {
            object::read::SymbolSection::Section(i) => i.0,
            _ => continue,
        };
        let offset = sym.address();
        let addr = text_secs.iter().find(|s| s.orig_idx == sec_idx)
            .map(|s| s.vaddr + offset)
            .or_else(|| data_secs.iter().find(|s| s.orig_idx == sec_idx)
                .map(|s| s.vaddr + offset));
        if let Some(a) = addr { syms.insert(name.to_string(), a); }
    }

    let entry_addr = *syms.get(entry_sym)
        .ok_or_else(|| format!("entry symbol '{entry_sym}' not found"))?;

    // ---- Merge section data ----
    let text_buf_size = align_up(text_content_size, MACHO_PAGE);
    let mut text_buf = vec![0u8; text_buf_size as usize];
    for s in &text_secs {
        let e = s.seg_offset as usize + s.data.len();
        text_buf[s.seg_offset as usize..e].copy_from_slice(&s.data);
    }
    let sc_end = syscall_seg_off as usize + syscall_bytes.len();
    text_buf[syscall_seg_off as usize..sc_end].copy_from_slice(syscall_bytes);
    if arm64 {
        write_start_macho_arm64(&mut text_buf[start_seg_off as usize..], entry_addr, start_vaddr);
    } else {
        write_start_macho_x86_64(&mut text_buf[start_seg_off as usize..], entry_addr, start_vaddr);
    }

    let data_buf_size = data_seg_filesize;
    let mut data_buf = vec![0u8; data_buf_size as usize];
    for s in &data_secs {
        let e = s.seg_offset as usize + s.data.len();
        data_buf[s.seg_offset as usize..e].copy_from_slice(&s.data);
    }

    // ---- Apply relocations ----
    for sec in obj.sections() {
        let sec_idx = sec.index().0;
        let (is_text, seg_off, sec_vaddr) =
            if let Some(s) = text_secs.iter().find(|s| s.orig_idx == sec_idx) {
                (true, s.seg_offset, s.vaddr)
            } else if let Some(s) = data_secs.iter().find(|s| s.orig_idx == sec_idx) {
                (false, s.seg_offset, s.vaddr)
            } else { continue };

        for (reloc_off, reloc) in sec.relocations() {
            let sym_addr = match reloc.target() {
                RelocationTarget::Symbol(sym_idx) => {
                    let sym = obj.symbol_by_index(sym_idx)
                        .map_err(|e| format!("bad symbol index: {e}"))?;
                    let name = sym.name().unwrap_or("");
                    *syms.get(name).ok_or_else(|| format!("undefined symbol '{name}'"))?
                }
                RelocationTarget::Section(tidx) => {
                    let t = tidx.0;
                    text_secs.iter().find(|s| s.orig_idx == t).map(|s| s.vaddr)
                        .or_else(|| data_secs.iter().find(|s| s.orig_idx == t).map(|s| s.vaddr))
                        .ok_or_else(|| format!("section reloc target {t} not found"))?
                }
                _ => continue,
            };

            let patch_loc = (seg_off + reloc_off) as usize;
            let reloc_va = sec_vaddr + reloc_off;
            // For Mach-O: addend = bytes_at_place + reloc.addend()
            // (reloc.addend() carries the -4 adjustment for x86-64 PC-relative,
            //  or the ARM64_RELOC_ADDEND value for arm64)
            let addend: i64 = {
                let src: &[u8] = if is_text { &text_buf } else { &data_buf };
                let implicit: i64 = if reloc.has_implicit_addend() {
                    match reloc.size() {
                        32 => i32::from_le_bytes(src[patch_loc..patch_loc + 4].try_into().unwrap()) as i64,
                        64 => i64::from_le_bytes(src[patch_loc..patch_loc + 8].try_into().unwrap()),
                        _ => 0,
                    }
                } else { 0 };
                implicit + reloc.addend()
            };

            let buf = if is_text { &mut text_buf } else { &mut data_buf };
            if arm64 {
                apply_reloc_macho_arm64(buf, patch_loc, reloc.flags(), sym_addr, addend, reloc_va)?;
            } else {
                apply_reloc_macho_x86_64(buf, patch_loc, reloc.flags(), sym_addr, addend, reloc_va)?;
            }
        }
    }

    // ---- Assemble file ----
    let mut file = vec![0u8; total_size as usize];

    // Mach-O header (32 bytes at offset 0)
    {
        let (cputype, cpusubtype): (i32, i32) = if arm64 {
            (0x0100_000C, 0) // ARM64, ALL
        } else {
            (0x0100_0007, 3) // X86_64, ALL
        };
        let h = &mut file[0..32];
        put_u32(&mut h[0..],  MH_MAGIC_64);
        put_u32(&mut h[4..],  cputype as u32);
        put_u32(&mut h[8..],  cpusubtype as u32);
        put_u32(&mut h[12..], MH_EXECUTE);
        put_u32(&mut h[16..], ncmds);
        put_u32(&mut h[20..], sizeofcmds as u32);
        put_u32(&mut h[24..], MH_NOUNDEFS);
        // h[28]: reserved (already 0)
    }

    // Load commands starting at offset 32
    let mut lc = 32usize;

    // LC_SEGMENT_64 __PAGEZERO
    macho_segment(&mut file[lc..], "__PAGEZERO\0\0\0\0\0\0",
        0, 0x100000000u64, 0, 0, 0, 0, 0, 0, 0);
    lc += 72;

    // LC_SEGMENT_64 __TEXT (contains __text section)
    macho_segment(&mut file[lc..], "__TEXT\0\0\0\0\0\0\0\0\0\0",
        MACHO_BASE, text_seg_vmsize, 0, text_seg_filesize,
        VM_PROT_RWX, VM_PROT_RX, 1, 0, 72 + 80);
    macho_section(&mut file[lc + 72..],
        "__text\0\0\0\0\0\0\0\0\0\0", "__TEXT\0\0\0\0\0\0\0\0\0\0",
        text_vaddr, text_content_size,
        text_file_off as u32, if arm64 { 2 } else { 4 },
        S_ATTR_PURE_INST | S_ATTR_SOME_INST);
    lc += 152;

    // LC_SEGMENT_64 __DATA (optional)
    if has_data {
        macho_segment(&mut file[lc..], "__DATA\0\0\0\0\0\0\0\0\0\0",
            data_vaddr, data_seg_filesize, data_file_off, data_seg_filesize,
            VM_PROT_RWX, VM_PROT_RW, 1, 0, 72 + 80);
        macho_section(&mut file[lc + 72..],
            "__data\0\0\0\0\0\0\0\0\0\0", "__DATA\0\0\0\0\0\0\0\0\0\0",
            data_vaddr, data_content_size,
            data_file_off as u32, 3, 0);
        lc += 152;
    }

    // LC_UNIXTHREAD
    if arm64 {
        macho_unixthread_arm64(&mut file[lc..], start_vaddr);
        lc += 288;
    } else {
        macho_unixthread_x86_64(&mut file[lc..], start_vaddr);
        lc += 184;
    }

    // LC_CODE_SIGNATURE (arm64)
    if arm64 {
        let h = &mut file[lc..lc + 16];
        put_u32(&mut h[0..], LC_CODE_SIGNATURE);
        put_u32(&mut h[4..], 16);
        put_u32(&mut h[8..], sig_off as u32);
        put_u32(&mut h[12..], sig_size as u32);
        lc += 16;
    }
    let _ = lc; // suppress unused warning

    // Copy section data
    let te = text_file_off as usize + text_buf.len();
    file[text_file_off as usize..te].copy_from_slice(&text_buf);
    if has_data && data_seg_filesize > 0 {
        file[data_file_off as usize..data_file_off as usize + data_buf.len()]
            .copy_from_slice(&data_buf);
    }

    // Append code signature (arm64)
    if arm64 {
        let sig = build_adhoc_signature(&file[..code_limit as usize], n_pages, sig_size as usize);
        file[sig_off as usize..sig_off as usize + sig.len()].copy_from_slice(&sig);
    }

    Ok(file)
}

// ---------------------------------------------------------------------------
// Mach-O load command writers
// ---------------------------------------------------------------------------

fn macho_segment(
    buf: &mut [u8], segname: &str,
    vmaddr: u64, vmsize: u64, fileoff: u64, filesize: u64,
    maxprot: i32, initprot: i32, nsects: u32, flags: u32,
    cmdsize: u32,
) {
    put_u32(&mut buf[0..], LC_SEGMENT_64);
    put_u32(&mut buf[4..], cmdsize);
    let nb = segname.len().min(16);
    buf[8..8 + nb].copy_from_slice(&segname.as_bytes()[..nb]);
    put_u64(&mut buf[24..], vmaddr);
    put_u64(&mut buf[32..], vmsize);
    put_u64(&mut buf[40..], fileoff);
    put_u64(&mut buf[48..], filesize);
    put_u32(&mut buf[56..], maxprot as u32);
    put_u32(&mut buf[60..], initprot as u32);
    put_u32(&mut buf[64..], nsects);
    put_u32(&mut buf[68..], flags);
}

fn macho_section(
    buf: &mut [u8], sectname: &str, segname: &str,
    addr: u64, size: u64, offset: u32, align_pow2: u32, flags: u32,
) {
    let sn = sectname.len().min(16);
    buf[0..sn].copy_from_slice(&sectname.as_bytes()[..sn]);
    let gn = segname.len().min(16);
    buf[16..16 + gn].copy_from_slice(&segname.as_bytes()[..gn]);
    put_u64(&mut buf[32..], addr);
    put_u64(&mut buf[40..], size);
    put_u32(&mut buf[48..], offset);
    put_u32(&mut buf[52..], align_pow2);
    // reloff, nreloc = 0 (already zero)
    put_u32(&mut buf[64..], flags);
    // reserved1,2,3 = 0
}

fn macho_unixthread_x86_64(buf: &mut [u8], rip: u64) {
    put_u32(&mut buf[0..], LC_UNIXTHREAD);
    put_u32(&mut buf[4..], 184);
    put_u32(&mut buf[8..], 4);  // x86_THREAD_STATE64
    put_u32(&mut buf[12..], 42); // count = 168 / 4
    // thread state: 168 bytes, all zeros except rip at offset 128 (= buf offset 16+128=144)
    put_u64(&mut buf[144..], rip);
}

fn macho_unixthread_arm64(buf: &mut [u8], pc: u64) {
    put_u32(&mut buf[0..], LC_UNIXTHREAD);
    put_u32(&mut buf[4..], 288);
    put_u32(&mut buf[8..], 6);  // ARM_THREAD_STATE64
    put_u32(&mut buf[12..], 68); // count = 272 / 4
    // thread state: 272 bytes, all zeros except pc at offset 256 (= buf offset 16+256=272)
    put_u64(&mut buf[272..], pc);
}

// ---------------------------------------------------------------------------
// _start stubs for macOS
// ---------------------------------------------------------------------------

// x86-64 macOS _start (14 bytes)
//   call <entry>       E8 XX XX XX XX  (5)
//   mov edi, eax       89 C7           (2)  -- exit code in edi (SysV arg1)
//   mov eax, 0x2000001 B8 01 00 00 02  (5)  -- macOS exit syscall
//   syscall            0F 05           (2)
fn write_start_macho_x86_64(buf: &mut [u8], entry_addr: u64, start_vaddr: u64) {
    let rel = (entry_addr as i64 - (start_vaddr as i64 + 5)) as i32;
    buf[0] = 0xE8;
    buf[1..5].copy_from_slice(&rel.to_le_bytes());
    buf[5] = 0x89; buf[6] = 0xC7; // mov edi, eax
    buf[7] = 0xB8;
    buf[8] = 0x01; buf[9] = 0x00; buf[10] = 0x00; buf[11] = 0x02; // 0x2000001
    buf[12] = 0x0F; buf[13] = 0x05; // syscall
}

// arm64 macOS _start (12 bytes)
//   bl <entry>   4 bytes — x0 = return value
//   mov x16, #1  4 bytes — macOS exit syscall (MOVZ x16, #1)
//   svc #0x80    4 bytes — 0xD4001001
fn write_start_macho_arm64(buf: &mut [u8], entry_addr: u64, start_vaddr: u64) {
    let delta = ((entry_addr as i64) - (start_vaddr as i64)) >> 2;
    let imm26 = (delta as u32) & 0x3FF_FFFF;
    put_u32(&mut buf[0..], 0x9400_0000 | imm26); // BL
    put_u32(&mut buf[4..], 0xD280_0000 | (1u32 << 5) | 16); // MOVZ x16, #1
    put_u32(&mut buf[8..], 0xD400_1001); // SVC #0x80
}


// ---------------------------------------------------------------------------
// Mach-O x86-64 relocation application
//
// The object crate pre-adjusts addend for x86-64 PC-relative relocations:
// addend already has -4 applied (for end-of-field RIP base), so the standard
// S + A - P formula produces the correct result.
// ---------------------------------------------------------------------------
fn apply_reloc_macho_x86_64(
    buf: &mut [u8],
    offset: usize,
    flags: RelocationFlags,
    sym_addr: u64,
    addend: i64,
    reloc_va: u64,
) -> Result<(), String> {
    match flags {
        RelocationFlags::Generic { kind, size, .. } => match (kind, size) {
            // X86_64_RELOC_UNSIGNED (r_type=0, r_pcrel=false) — absolute
            (RelocationKind::Absolute, 64) => {
                let v = (sym_addr as i64 + addend) as u64;
                buf[offset..offset + 8].copy_from_slice(&v.to_le_bytes());
            }
            (RelocationKind::Absolute, 32) => {
                let v = (sym_addr as i64 + addend) as u32;
                buf[offset..offset + 4].copy_from_slice(&v.to_le_bytes());
            }
            // X86_64_RELOC_BRANCH / X86_64_RELOC_SIGNED (r_pcrel=true)
            // addend already includes -4 from object crate; formula: S + A - P
            (RelocationKind::Relative, 32) => {
                let v = (sym_addr as i64 + addend - reloc_va as i64) as i32;
                buf[offset..offset + 4].copy_from_slice(&v.to_le_bytes());
            }
            // X86_64_RELOC_GOT / GOT_LOAD — treat as PC-relative for static link
            (RelocationKind::GotRelative, 32) => {
                let v = (sym_addr as i64 + addend - reloc_va as i64) as i32;
                buf[offset..offset + 4].copy_from_slice(&v.to_le_bytes());
            }
            _ => return Err(format!(
                "unsupported Mach-O x86-64 reloc: {kind:?} size={size} at {offset:#x}"
            )),
        },
        other => return Err(format!(
            "unexpected Mach-O x86-64 reloc flags: {other:?} at {offset:#x}"
        )),
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Mach-O arm64 relocation application
//
// Most arm64 Mach-O relocations come as RelocationFlags::MachO { r_type, ... }
// since the object crate only maps ARM64_RELOC_UNSIGNED to a Generic kind.
// ARM64_RELOC_ADDEND pairs are consumed by the object crate; the resulting
// addend arrives in the `addend` parameter.
// ---------------------------------------------------------------------------
fn apply_reloc_macho_arm64(
    buf: &mut [u8],
    offset: usize,
    flags: RelocationFlags,
    sym_addr: u64,
    addend: i64,
    reloc_va: u64,
) -> Result<(), String> {
    let r_type = match flags {
        RelocationFlags::MachO { r_type, .. } => r_type,
        RelocationFlags::Generic { kind: RelocationKind::Absolute, size: 64, .. } => 0,
        other => return Err(format!(
            "unexpected Mach-O arm64 reloc flags: {other:?} at {offset:#x}"
        )),
    };

    let target = (sym_addr as i64).wrapping_add(addend);

    match r_type {
        // ARM64_RELOC_UNSIGNED (0) — absolute 64-bit (r_length=3) or 32-bit (r_length=2)
        0 => {
            match flags {
                RelocationFlags::MachO { r_length: 3, .. } | RelocationFlags::Generic { size: 64, .. } => {
                    buf[offset..offset + 8].copy_from_slice(&(target as u64).to_le_bytes());
                }
                _ => {
                    buf[offset..offset + 4].copy_from_slice(&(target as u32).to_le_bytes());
                }
            }
        }
        // ARM64_RELOC_BRANCH26 (2) — BL/B: (S+A-P)>>2 into bits[25:0]
        2 => {
            let delta = (target - reloc_va as i64) >> 2;
            let imm26 = (delta as i32) & 0x3FF_FFFF;
            let insn = u32::from_le_bytes(buf[offset..offset + 4].try_into().unwrap());
            buf[offset..offset + 4]
                .copy_from_slice(&((insn & 0xFC00_0000) | (imm26 as u32 & 0x3FF_FFFF)).to_le_bytes());
        }
        // ARM64_RELOC_PAGE21 (3) — ADRP
        3 => {
            let sym_page = target & !0xFFF;
            let pc_page = (reloc_va as i64) & !0xFFF;
            let delta = (sym_page - pc_page) >> 12;
            let immlo = (delta as u32) & 0x3;
            let immhi = ((delta as u32) >> 2) & 0x7_FFFF;
            let insn = u32::from_le_bytes(buf[offset..offset + 4].try_into().unwrap());
            buf[offset..offset + 4]
                .copy_from_slice(&((insn & 0x9F00_001F) | (immlo << 29) | (immhi << 5)).to_le_bytes());
        }
        // ARM64_RELOC_PAGEOFF12 (4) — ADD imm12 or LDR/STR scaled offset
        4 => {
            let lo12 = (target as u32) & 0xFFF;
            let insn = u32::from_le_bytes(buf[offset..offset + 4].try_into().unwrap());
            // Detect ADD (opcode 0x91 = 64-bit ADD imm, 0x11 = 32-bit ADD imm)
            let opcode_byte = (insn >> 24) as u8;
            let scaled = if opcode_byte == 0x91 || opcode_byte == 0x11 {
                lo12 // ADD: no scaling
            } else {
                lo12 >> ((insn >> 30) as u32) // LDR/STR: scale by access size
            };
            buf[offset..offset + 4]
                .copy_from_slice(&((insn & 0xFFC0_03FF) | (scaled << 10)).to_le_bytes());
        }
        // ARM64_RELOC_GOT_LOAD_PAGE21 (5) — treat as PAGE21 for static link
        5 => {
            let sym_page = target & !0xFFF;
            let pc_page = (reloc_va as i64) & !0xFFF;
            let delta = (sym_page - pc_page) >> 12;
            let immlo = (delta as u32) & 0x3;
            let immhi = ((delta as u32) >> 2) & 0x7_FFFF;
            let insn = u32::from_le_bytes(buf[offset..offset + 4].try_into().unwrap());
            buf[offset..offset + 4]
                .copy_from_slice(&((insn & 0x9F00_001F) | (immlo << 29) | (immhi << 5)).to_le_bytes());
        }
        // ARM64_RELOC_GOT_LOAD_PAGEOFF12 (6) — treat as PAGEOFF12 for static link
        6 => {
            let lo12 = (target as u32) & 0xFFF;
            let insn = u32::from_le_bytes(buf[offset..offset + 4].try_into().unwrap());
            let opcode_byte = (insn >> 24) as u8;
            let scaled = if opcode_byte == 0x91 || opcode_byte == 0x11 {
                lo12
            } else {
                lo12 >> ((insn >> 30) as u32)
            };
            buf[offset..offset + 4]
                .copy_from_slice(&((insn & 0xFFC0_03FF) | (scaled << 10)).to_le_bytes());
        }
        _ => return Err(format!(
            "unsupported Mach-O arm64 reloc r_type={r_type} at {offset:#x}"
        )),
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Ad-hoc code signature for arm64 macOS
//
// Structure: CS_SuperBlob → CS_BlobIndex → CS_CodeDirectory → hashes
// The signature data is appended after all mapped content (code_limit bytes).
// ---------------------------------------------------------------------------
fn build_adhoc_signature(data: &[u8], n_pages: usize, total_sig_size: usize) -> Vec<u8> {
    const CSMAGIC_EMBEDDED_SIGNATURE: u32 = 0xFADE_0CC0;
    const CSMAGIC_CODEDIRECTORY: u32 = 0xFADE_0C02;
    const CS_ADHOC: u32 = 0x0000_0002;
    const CS_EXECSEG_MAIN_BINARY: u64 = 0x1;
    const CD_VERSION: u32 = 0x0002_0400;
    const HASH_SHA256: u8 = 2;
    const PAGE_LOG: u8 = 12; // log2(4096)
    const HASH_SIZE: u8 = 32;

    let code_limit = data.len() as u32;

    // Identifier string embedded in CodeDirectory: "dyn\0"
    let ident = b"dyn\0";

    // CodeDirectory layout:
    //   [0..88)    fixed fields
    //   [88..92)   identifier ("dyn\0")
    //   [92..)     n_pages × 32-byte SHA-256 hashes
    let cd_fixed: usize = 88;
    let ident_off: u32 = cd_fixed as u32;
    let hash_off: u32 = cd_fixed as u32 + ident.len() as u32;
    let cd_size = cd_fixed + ident.len() + n_pages * 32;

    // SuperBlob: 12-byte header + 8-byte BlobIndex + CodeDirectory
    let superblob_size = 12 + 8 + cd_size;

    let mut sig = vec![0u8; total_sig_size];

    // SuperBlob header
    put_u32_be(&mut sig[0..], CSMAGIC_EMBEDDED_SIGNATURE);
    put_u32_be(&mut sig[4..], superblob_size as u32);
    put_u32_be(&mut sig[8..], 1); // count = 1

    // BlobIndex[0]: type=0 (CSSLOT_CODEDIRECTORY), offset=20 (after 12+8)
    put_u32_be(&mut sig[12..], 0);
    put_u32_be(&mut sig[16..], 20);

    // CodeDirectory (starts at sig[20])
    let cd = &mut sig[20..20 + cd_size];
    put_u32_be(&mut cd[0..],  CSMAGIC_CODEDIRECTORY);
    put_u32_be(&mut cd[4..],  cd_size as u32);
    put_u32_be(&mut cd[8..],  CD_VERSION);
    put_u32_be(&mut cd[12..], CS_ADHOC);
    put_u32_be(&mut cd[16..], hash_off);       // hashOffset
    put_u32_be(&mut cd[20..], ident_off);      // identOffset
    // nSpecialSlots = 0 (already 0)
    put_u32_be(&mut cd[28..], n_pages as u32); // nCodeSlots
    put_u32_be(&mut cd[32..], code_limit);
    cd[36] = HASH_SIZE;
    cd[37] = HASH_SHA256;
    // platform = 0
    cd[39] = PAGE_LOG;
    // spare2, scatterOffset, teamOffset, spare3 = 0
    // codeLimit64 = 0
    // execSegBase = 0 (TEXT segment starts at file offset 0)
    let text_seg_limit = align_up(0x1000 + (code_limit as u64), MACHO_PAGE); // __TEXT filesize
    put_u64_be(&mut cd[72..], text_seg_limit);
    put_u64_be(&mut cd[80..], CS_EXECSEG_MAIN_BINARY);

    // Identifier
    cd[cd_fixed..cd_fixed + ident.len()].copy_from_slice(ident);

    // Page hashes
    for i in 0..n_pages {
        let start = i * 4096;
        let end = ((i + 1) * 4096).min(data.len());
        let hash = if end - start < 4096 {
            let mut page = [0u8; 4096];
            page[..end - start].copy_from_slice(&data[start..end]);
            sha256(&page)
        } else {
            sha256(&data[start..end])
        };
        let h_off = cd_fixed + ident.len() + i * 32;
        cd[h_off..h_off + 32].copy_from_slice(&hash);
    }

    sig
}

fn put_u32_be(buf: &mut [u8], v: u32) { buf[..4].copy_from_slice(&v.to_be_bytes()); }
fn put_u64_be(buf: &mut [u8], v: u64) { buf[..8].copy_from_slice(&v.to_be_bytes()); }

// ---------------------------------------------------------------------------
// SHA-256 (inline, no external dependency)
// ---------------------------------------------------------------------------
fn sha256(data: &[u8]) -> [u8; 32] {
    #[rustfmt::skip]
    const K: [u32; 64] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5,
        0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
        0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
        0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
        0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
        0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
        0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
        0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
        0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
        0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3,
        0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
        0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5,
        0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
        0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
    ];
    let mut h: [u32; 8] = [
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
        0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
    ];

    let bit_len = (data.len() as u64) * 8;
    let mut padded = data.to_vec();
    padded.push(0x80);
    while padded.len() % 64 != 56 { padded.push(0); }
    padded.extend_from_slice(&bit_len.to_be_bytes());

    for chunk in padded.chunks(64) {
        let mut w = [0u32; 64];
        for i in 0..16 {
            w[i] = u32::from_be_bytes(chunk[i * 4..i * 4 + 4].try_into().unwrap());
        }
        for i in 16..64 {
            let s0 = w[i-15].rotate_right(7) ^ w[i-15].rotate_right(18) ^ (w[i-15] >> 3);
            let s1 = w[i-2].rotate_right(17) ^ w[i-2].rotate_right(19) ^ (w[i-2] >> 10);
            w[i] = w[i-16].wrapping_add(s0).wrapping_add(w[i-7]).wrapping_add(s1);
        }
        let [mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut hh] = h;
        for i in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch = (e & f) ^ (!e & g);
            let t1 = hh.wrapping_add(s1).wrapping_add(ch).wrapping_add(K[i]).wrapping_add(w[i]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let t2 = s0.wrapping_add(maj);
            hh = g; g = f; f = e; e = d.wrapping_add(t1);
            d = c; c = b; b = a; a = t1.wrapping_add(t2);
        }
        h[0] = h[0].wrapping_add(a); h[1] = h[1].wrapping_add(b);
        h[2] = h[2].wrapping_add(c); h[3] = h[3].wrapping_add(d);
        h[4] = h[4].wrapping_add(e); h[5] = h[5].wrapping_add(f);
        h[6] = h[6].wrapping_add(g); h[7] = h[7].wrapping_add(hh);
    }

    let mut out = [0u8; 32];
    for (i, word) in h.iter().enumerate() {
        out[i * 4..i * 4 + 4].copy_from_slice(&word.to_be_bytes());
    }
    out
}
