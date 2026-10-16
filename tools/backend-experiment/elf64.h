/* The ELF64 subset the native emitter writes. Defined here rather than taken
   from <elf.h> so the backend builds on hosts without glibc headers. */
#ifndef DYN_BACKEND_ELF64_H
#define DYN_BACKEND_ELF64_H
#include <stdint.h>

typedef uint16_t Elf64_Half;
typedef uint32_t Elf64_Word;
typedef uint64_t Elf64_Xword;
typedef int64_t Elf64_Sxword;
typedef uint64_t Elf64_Addr;
typedef uint64_t Elf64_Off;

typedef struct {
  unsigned char e_ident[16];
  Elf64_Half e_type, e_machine;
  Elf64_Word e_version;
  Elf64_Addr e_entry;
  Elf64_Off e_phoff, e_shoff;
  Elf64_Word e_flags;
  Elf64_Half e_ehsize, e_phentsize, e_phnum, e_shentsize, e_shnum, e_shstrndx;
} Elf64_Ehdr;
typedef struct {
  Elf64_Word sh_name, sh_type;
  Elf64_Xword sh_flags;
  Elf64_Addr sh_addr;
  Elf64_Off sh_offset;
  Elf64_Xword sh_size;
  Elf64_Word sh_link, sh_info;
  Elf64_Xword sh_addralign, sh_entsize;
} Elf64_Shdr;
typedef struct {
  Elf64_Word st_name;
  unsigned char st_info, st_other;
  Elf64_Half st_shndx;
  Elf64_Addr st_value;
  Elf64_Xword st_size;
} Elf64_Sym;
typedef struct {
  Elf64_Addr r_offset;
  Elf64_Xword r_info;
  Elf64_Sxword r_addend;
} Elf64_Rela;

#define ELF64_R_SYM(i) ((i) >> 32)
#define ELF64_R_TYPE(i) ((i) & 0xffffffffu)
#define ELF64_R_INFO(sym, type) ((((Elf64_Xword)(sym)) << 32) + (type))
#define ELF64_ST_INFO(bind, type) (((bind) << 4) + ((type) & 0xf))
#define ELF64_ST_BIND(info) ((info) >> 4)

enum { ELFCLASS64 = 2, ELFDATA2LSB = 1, EV_CURRENT = 1, ET_REL = 1, EM_X86_64 = 62, EM_AARCH64 = 183 };
enum { SHT_PROGBITS = 1, SHT_SYMTAB = 2, SHT_STRTAB = 3, SHT_RELA = 4, SHT_INIT_ARRAY = 14 };
enum { SHF_WRITE = 1, SHF_ALLOC = 2, SHF_EXECINSTR = 4 };
enum { SHN_UNDEF = 0 };
enum { STB_LOCAL = 0, STB_GLOBAL = 1, STT_NOTYPE = 0, STT_OBJECT = 1, STT_FUNC = 2, STT_SECTION = 3 };
enum { R_X86_64_64 = 1, R_X86_64_PC32 = 2, R_X86_64_PLT32 = 4, R_X86_64_GOTPCREL = 9, R_X86_64_32 = 10 };
enum { R_AARCH64_ABS64 = 257, R_AARCH64_ABS32 = 258, R_AARCH64_ADR_PREL_PG_HI21 = 275,
       R_AARCH64_ADD_ABS_LO12_NC = 277, R_AARCH64_CALL26 = 283, R_AARCH64_ADR_GOT_PAGE = 311,
       R_AARCH64_LD64_GOT_LO12_NC = 312 };
#endif
