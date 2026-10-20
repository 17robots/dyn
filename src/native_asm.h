#ifndef DYN_NATIVE_ASM_H
#define DYN_NATIVE_ASM_H
/* Print reassemblable target assembly for an independent native object.
   Instructions use exact byte encodings; relocations remain symbolic. */
int dyn_native_assembly(const char *object, const char *output);
#endif
