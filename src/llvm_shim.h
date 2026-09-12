#ifndef DYN_LLVM_SHIM_H
#define DYN_LLVM_SHIM_H

#include <stddef.h>
#include <stdint.h>

typedef struct LLVMOpaqueContext *LLVMContextRef;
typedef struct LLVMOpaqueModule *LLVMModuleRef;
typedef struct LLVMOpaqueType *LLVMTypeRef;
typedef struct LLVMOpaqueValue *LLVMValueRef;
typedef struct LLVMOpaqueBasicBlock *LLVMBasicBlockRef;
typedef struct LLVMOpaqueBuilder *LLVMBuilderRef;
typedef struct LLVMTarget *LLVMTargetRef;
typedef struct LLVMOpaqueTargetMachine *LLVMTargetMachineRef;
typedef struct LLVMOpaqueTargetData *LLVMTargetDataRef;
typedef struct LLVMOpaquePassBuilderOptions *LLVMPassBuilderOptionsRef;
typedef struct LLVMOpaqueError *LLVMErrorRef;
typedef struct LLVMOpaqueMetadata *LLVMMetadataRef;
typedef struct LLVMOpaqueDIBuilder *LLVMDIBuilderRef;
typedef struct LLVMOpaqueAttributeRef *LLVMAttributeRef;

enum { LLVMInternalLinkage = 8, LLVMPrivateLinkage = 9 };

extern void LLVMInitializeX86TargetInfo(void);
extern void LLVMInitializeX86Target(void);
extern void LLVMInitializeX86TargetMC(void);
extern void LLVMInitializeX86AsmPrinter(void);
extern void LLVMInitializeAArch64TargetInfo(void);
extern void LLVMInitializeAArch64Target(void);
extern void LLVMInitializeAArch64TargetMC(void);
extern void LLVMInitializeAArch64AsmPrinter(void);
extern LLVMContextRef LLVMContextCreate(void);
extern unsigned LLVMGetEnumAttributeKindForName(const char *, size_t);
extern LLVMAttributeRef LLVMCreateEnumAttribute(LLVMContextRef, unsigned,
                                                unsigned long long);
extern void LLVMAddAttributeAtIndex(LLVMValueRef, unsigned, LLVMAttributeRef);
extern void LLVMContextDispose(LLVMContextRef);
extern LLVMModuleRef LLVMModuleCreateWithNameInContext(const char *,
                                                       LLVMContextRef);
extern void LLVMDisposeModule(LLVMModuleRef);
extern LLVMTypeRef LLVMInt32TypeInContext(LLVMContextRef);
extern LLVMTypeRef LLVMInt1TypeInContext(LLVMContextRef);
extern LLVMTypeRef LLVMInt8TypeInContext(LLVMContextRef);
extern LLVMTypeRef LLVMInt16TypeInContext(LLVMContextRef);
extern LLVMTypeRef LLVMInt64TypeInContext(LLVMContextRef);
extern LLVMTypeRef LLVMIntTypeInContext(LLVMContextRef, unsigned);
extern LLVMTypeRef LLVMFloatTypeInContext(LLVMContextRef);
extern LLVMTypeRef LLVMDoubleTypeInContext(LLVMContextRef);
extern LLVMTypeRef LLVMPointerTypeInContext(LLVMContextRef, unsigned);
extern LLVMTypeRef LLVMArrayType2(LLVMTypeRef, unsigned long long);
extern LLVMTypeRef LLVMStructTypeInContext(LLVMContextRef, LLVMTypeRef *,
                                           unsigned, int);
extern LLVMTypeRef LLVMStructCreateNamed(LLVMContextRef, const char *);
extern void LLVMStructSetBody(LLVMTypeRef, LLVMTypeRef *, unsigned, int);
extern LLVMTypeRef LLVMVoidTypeInContext(LLVMContextRef);
extern LLVMTypeRef LLVMFunctionType(LLVMTypeRef, LLVMTypeRef *, unsigned, int);
extern LLVMValueRef LLVMAddFunction(LLVMModuleRef, const char *, LLVMTypeRef);
extern LLVMMetadataRef LLVMValueAsMetadata(LLVMValueRef);
extern void LLVMAddModuleFlag(LLVMModuleRef, int, const char *, size_t,
                              LLVMMetadataRef);
extern LLVMValueRef LLVMGetNamedFunction(LLVMModuleRef, const char *);
extern LLVMTypeRef LLVMGlobalGetValueType(LLVMValueRef);
extern LLVMTypeRef LLVMTypeOf(LLVMValueRef);
extern LLVMTypeRef LLVMGetReturnType(LLVMTypeRef);
extern unsigned LLVMCountParamTypes(LLVMTypeRef);
extern void LLVMGetParamTypes(LLVMTypeRef, LLVMTypeRef *);
extern int LLVMGetTypeKind(LLVMTypeRef);
extern unsigned LLVMGetIntTypeWidth(LLVMTypeRef);
extern unsigned LLVMCountStructElementTypes(LLVMTypeRef);
extern LLVMTypeRef LLVMStructGetTypeAtIndex(LLVMTypeRef, unsigned);
extern LLVMValueRef LLVMAddGlobal(LLVMModuleRef, LLVMTypeRef, const char *);
extern unsigned LLVMGetMDKindIDInContext(LLVMContextRef, const char *, unsigned);
extern void LLVMGlobalSetMetadata(LLVMValueRef, unsigned, LLVMMetadataRef);
extern void LLVMSetLinkage(LLVMValueRef, int);
extern void LLVMSetInitializer(LLVMValueRef, LLVMValueRef);
extern void LLVMSetGlobalConstant(LLVMValueRef, int);
extern LLVMBasicBlockRef
LLVMAppendBasicBlockInContext(LLVMContextRef, LLVMValueRef, const char *);
extern LLVMBuilderRef LLVMCreateBuilderInContext(LLVMContextRef);
extern void LLVMDisposeBuilder(LLVMBuilderRef);
extern void LLVMPositionBuilderAtEnd(LLVMBuilderRef, LLVMBasicBlockRef);
extern LLVMValueRef LLVMConstInt(LLVMTypeRef, unsigned long long, int);
extern LLVMValueRef LLVMConstReal(LLVMTypeRef, double);
extern LLVMValueRef LLVMConstNull(LLVMTypeRef);
extern LLVMValueRef LLVMSizeOf(LLVMTypeRef);
extern LLVMValueRef LLVMConstArray2(LLVMTypeRef, LLVMValueRef *,
                                    unsigned long long);
extern LLVMValueRef LLVMConstNamedStruct(LLVMTypeRef, LLVMValueRef *, unsigned);
extern LLVMValueRef LLVMConstAdd(LLVMValueRef, LLVMValueRef);
extern LLVMValueRef LLVMConstSub(LLVMValueRef, LLVMValueRef);
extern LLVMValueRef LLVMConstMul(LLVMValueRef, LLVMValueRef);
extern LLVMValueRef LLVMConstUDiv(LLVMValueRef, LLVMValueRef);
extern LLVMValueRef LLVMConstSDiv(LLVMValueRef, LLVMValueRef);
extern LLVMValueRef LLVMConstURem(LLVMValueRef, LLVMValueRef);
extern LLVMValueRef LLVMConstSRem(LLVMValueRef, LLVMValueRef);
extern LLVMValueRef LLVMConstAnd(LLVMValueRef, LLVMValueRef);
extern LLVMValueRef LLVMConstOr(LLVMValueRef, LLVMValueRef);
extern LLVMValueRef LLVMConstXor(LLVMValueRef, LLVMValueRef);
extern LLVMValueRef LLVMConstShl(LLVMValueRef, LLVMValueRef);
extern LLVMValueRef LLVMConstLShr(LLVMValueRef, LLVMValueRef);
extern LLVMValueRef LLVMConstAShr(LLVMValueRef, LLVMValueRef);
extern LLVMValueRef LLVMConstNeg(LLVMValueRef);
extern LLVMValueRef LLVMConstNot(LLVMValueRef);
extern LLVMValueRef LLVMConstSExt(LLVMValueRef, LLVMTypeRef);
extern LLVMValueRef LLVMConstZExt(LLVMValueRef, LLVMTypeRef);
extern LLVMValueRef LLVMConstTrunc(LLVMValueRef, LLVMTypeRef);
extern LLVMValueRef LLVMConstFPExt(LLVMValueRef, LLVMTypeRef);
extern LLVMValueRef LLVMConstSIToFP(LLVMValueRef, LLVMTypeRef);
extern LLVMValueRef LLVMConstUIToFP(LLVMValueRef, LLVMTypeRef);
extern LLVMValueRef LLVMConstFAdd(LLVMValueRef, LLVMValueRef);
extern LLVMValueRef LLVMConstFSub(LLVMValueRef, LLVMValueRef);
extern LLVMValueRef LLVMConstFMul(LLVMValueRef, LLVMValueRef);
extern LLVMValueRef LLVMConstFDiv(LLVMValueRef, LLVMValueRef);
extern LLVMValueRef LLVMConstFRem(LLVMValueRef, LLVMValueRef);
extern LLVMValueRef LLVMGetUndef(LLVMTypeRef);
extern LLVMValueRef LLVMBuildRet(LLVMBuilderRef, LLVMValueRef);
extern LLVMValueRef LLVMBuildGlobalStringPtr(LLVMBuilderRef, const char *,
                                             const char *);
extern LLVMValueRef LLVMBuildRetVoid(LLVMBuilderRef);
extern LLVMValueRef LLVMGetParam(LLVMValueRef, unsigned);
extern LLVMValueRef LLVMBuildAlloca(LLVMBuilderRef, LLVMTypeRef, const char *);
extern LLVMValueRef LLVMBuildStore(LLVMBuilderRef, LLVMValueRef, LLVMValueRef);
extern LLVMValueRef LLVMBuildLoad2(LLVMBuilderRef, LLVMTypeRef, LLVMValueRef,
                                   const char *);
extern LLVMValueRef LLVMBuildInsertValue(LLVMBuilderRef, LLVMValueRef,
                                         LLVMValueRef, unsigned, const char *);
extern LLVMValueRef LLVMBuildExtractValue(LLVMBuilderRef, LLVMValueRef,
                                          unsigned, const char *);
extern LLVMValueRef LLVMBuildStructGEP2(LLVMBuilderRef, LLVMTypeRef,
                                        LLVMValueRef, unsigned, const char *);
extern LLVMValueRef LLVMBuildGEP2(LLVMBuilderRef, LLVMTypeRef, LLVMValueRef,
                                  LLVMValueRef *, unsigned, const char *);
extern LLVMValueRef LLVMBuildPtrToInt(LLVMBuilderRef, LLVMValueRef, LLVMTypeRef,
                                      const char *);
extern LLVMValueRef LLVMBuildIntToPtr(LLVMBuilderRef, LLVMValueRef, LLVMTypeRef,
                                      const char *);
extern LLVMValueRef LLVMBuildAdd(LLVMBuilderRef, LLVMValueRef, LLVMValueRef,
                                 const char *);
extern LLVMValueRef LLVMBuildSub(LLVMBuilderRef, LLVMValueRef, LLVMValueRef,
                                 const char *);
extern LLVMValueRef LLVMBuildMul(LLVMBuilderRef, LLVMValueRef, LLVMValueRef,
                                 const char *);
extern LLVMValueRef LLVMBuildSDiv(LLVMBuilderRef, LLVMValueRef, LLVMValueRef,
                                  const char *);
extern LLVMValueRef LLVMBuildUDiv(LLVMBuilderRef, LLVMValueRef, LLVMValueRef,
                                  const char *);
extern LLVMValueRef LLVMBuildSRem(LLVMBuilderRef, LLVMValueRef, LLVMValueRef,
                                  const char *);
extern LLVMValueRef LLVMBuildURem(LLVMBuilderRef, LLVMValueRef, LLVMValueRef,
                                  const char *);
extern LLVMValueRef LLVMBuildFAdd(LLVMBuilderRef, LLVMValueRef, LLVMValueRef,
                                  const char *);
extern LLVMValueRef LLVMBuildFSub(LLVMBuilderRef, LLVMValueRef, LLVMValueRef,
                                  const char *);
extern LLVMValueRef LLVMBuildFMul(LLVMBuilderRef, LLVMValueRef, LLVMValueRef,
                                  const char *);
extern LLVMValueRef LLVMBuildFDiv(LLVMBuilderRef, LLVMValueRef, LLVMValueRef,
                                  const char *);
extern LLVMValueRef LLVMBuildFRem(LLVMBuilderRef, LLVMValueRef, LLVMValueRef,
                                  const char *);
extern LLVMValueRef LLVMBuildAnd(LLVMBuilderRef, LLVMValueRef, LLVMValueRef,
                                 const char *);
extern LLVMValueRef LLVMBuildOr(LLVMBuilderRef, LLVMValueRef, LLVMValueRef,
                                const char *);
extern LLVMValueRef LLVMBuildXor(LLVMBuilderRef, LLVMValueRef, LLVMValueRef,
                                 const char *);
extern LLVMValueRef LLVMBuildShl(LLVMBuilderRef, LLVMValueRef, LLVMValueRef,
                                 const char *);
extern LLVMValueRef LLVMBuildAShr(LLVMBuilderRef, LLVMValueRef, LLVMValueRef,
                                  const char *);
extern LLVMValueRef LLVMBuildLShr(LLVMBuilderRef, LLVMValueRef, LLVMValueRef,
                                  const char *);
extern LLVMValueRef LLVMBuildNeg(LLVMBuilderRef, LLVMValueRef, const char *);
extern LLVMValueRef LLVMBuildFNeg(LLVMBuilderRef, LLVMValueRef, const char *);
extern LLVMValueRef LLVMBuildNot(LLVMBuilderRef, LLVMValueRef, const char *);
extern LLVMValueRef LLVMBuildICmp(LLVMBuilderRef, int, LLVMValueRef,
                                  LLVMValueRef, const char *);
extern LLVMBasicBlockRef LLVMGetInsertBlock(LLVMBuilderRef);
extern LLVMValueRef LLVMBuildFCmp(LLVMBuilderRef, int, LLVMValueRef,
                                  LLVMValueRef, const char *);
extern LLVMValueRef LLVMBuildSExt(LLVMBuilderRef, LLVMValueRef, LLVMTypeRef,
                                  const char *);
extern LLVMValueRef LLVMBuildZExt(LLVMBuilderRef, LLVMValueRef, LLVMTypeRef,
                                  const char *);
extern LLVMValueRef LLVMBuildTrunc(LLVMBuilderRef, LLVMValueRef, LLVMTypeRef,
                                   const char *);
extern LLVMValueRef LLVMBuildSIToFP(LLVMBuilderRef, LLVMValueRef, LLVMTypeRef,
                                    const char *);
extern LLVMValueRef LLVMBuildUIToFP(LLVMBuilderRef, LLVMValueRef, LLVMTypeRef,
                                    const char *);
extern LLVMValueRef LLVMBuildFPExt(LLVMBuilderRef, LLVMValueRef, LLVMTypeRef,
                                   const char *);
extern LLVMValueRef LLVMBuildFPTrunc(LLVMBuilderRef, LLVMValueRef, LLVMTypeRef,
                                     const char *);
extern LLVMValueRef LLVMBuildFPToSI(LLVMBuilderRef, LLVMValueRef, LLVMTypeRef,
                                    const char *);
extern LLVMValueRef LLVMBuildFPToUI(LLVMBuilderRef, LLVMValueRef, LLVMTypeRef,
                                    const char *);
extern LLVMValueRef LLVMBuildBitCast(LLVMBuilderRef, LLVMValueRef, LLVMTypeRef,
                                     const char *);
extern LLVMValueRef LLVMBuildCall2(LLVMBuilderRef, LLVMTypeRef, LLVMValueRef,
                                   LLVMValueRef *, unsigned, const char *);
extern LLVMValueRef LLVMBuildCondBr(LLVMBuilderRef, LLVMValueRef,
                                    LLVMBasicBlockRef, LLVMBasicBlockRef);
extern LLVMValueRef LLVMBuildBr(LLVMBuilderRef, LLVMBasicBlockRef);
extern LLVMValueRef LLVMBuildPhi(LLVMBuilderRef, LLVMTypeRef, const char *);
extern void LLVMAddIncoming(LLVMValueRef, LLVMValueRef *, LLVMBasicBlockRef *,
                            unsigned);
extern LLVMValueRef LLVMBuildUnreachable(LLVMBuilderRef);
extern char *LLVMPrintModuleToString(LLVMModuleRef);
extern void LLVMDisposeMessage(char *);
extern char *LLVMGetDefaultTargetTriple(void);
extern int LLVMGetTargetFromTriple(const char *, LLVMTargetRef *, char **);
extern LLVMTargetMachineRef LLVMCreateTargetMachine(LLVMTargetRef, const char *,
                                                    const char *, const char *,
                                                    int, int, int);
extern void LLVMDisposeTargetMachine(LLVMTargetMachineRef);
extern LLVMTargetDataRef LLVMCreateTargetDataLayout(LLVMTargetMachineRef);
extern char *LLVMCopyStringRepOfTargetData(LLVMTargetDataRef);
extern void LLVMDisposeTargetData(LLVMTargetDataRef);
extern void LLVMSetDataLayout(LLVMModuleRef, const char *);
extern int LLVMTargetMachineEmitToFile(LLVMTargetMachineRef, LLVMModuleRef,
                                       char *, int, char **);
extern int LLVMWriteBitcodeToFile(LLVMModuleRef, const char *);
extern void LLVMSetTarget(LLVMModuleRef, const char *);
extern int LLVMVerifyModule(LLVMModuleRef, int, char **);
extern LLVMPassBuilderOptionsRef LLVMCreatePassBuilderOptions(void);
extern void LLVMDisposePassBuilderOptions(LLVMPassBuilderOptionsRef);
extern void LLVMPassBuilderOptionsSetLoopVectorization(LLVMPassBuilderOptionsRef, int);
extern void LLVMPassBuilderOptionsSetSLPVectorization(LLVMPassBuilderOptionsRef, int);
extern LLVMErrorRef LLVMRunPasses(LLVMModuleRef, const char *,
                                  LLVMTargetMachineRef,
                                  LLVMPassBuilderOptionsRef);
extern char *LLVMGetErrorMessage(LLVMErrorRef);
extern void LLVMDisposeErrorMessage(char *);

extern unsigned LLVMDebugMetadataVersion(void);
extern LLVMDIBuilderRef LLVMCreateDIBuilder(LLVMModuleRef);
extern void LLVMDisposeDIBuilder(LLVMDIBuilderRef);
extern void LLVMDIBuilderFinalize(LLVMDIBuilderRef);
extern LLVMMetadataRef LLVMDIBuilderCreateFile(LLVMDIBuilderRef, const char *,
                                               size_t, const char *, size_t);
extern LLVMMetadataRef LLVMDIBuilderCreateCompileUnit(
    LLVMDIBuilderRef, unsigned, LLVMMetadataRef, const char *, size_t, int,
    const char *, size_t, unsigned, const char *, size_t, unsigned, unsigned,
    int, int, const char *, size_t, const char *, size_t);
extern LLVMMetadataRef LLVMDIBuilderCreateSubroutineType(
    LLVMDIBuilderRef, LLVMMetadataRef, LLVMMetadataRef *, unsigned, unsigned);
extern LLVMMetadataRef LLVMDIBuilderCreateFunction(
    LLVMDIBuilderRef, LLVMMetadataRef, const char *, size_t, const char *,
    size_t, LLVMMetadataRef, unsigned, LLVMMetadataRef, int, int, unsigned,
    unsigned, int);
extern LLVMMetadataRef LLVMDIBuilderCreateDebugLocation(
    LLVMContextRef, unsigned, unsigned, LLVMMetadataRef, LLVMMetadataRef);
extern LLVMMetadataRef LLVMDIBuilderCreateBasicType(
    LLVMDIBuilderRef, const char *, size_t, uint64_t, unsigned, unsigned);
extern LLVMMetadataRef LLVMDIBuilderCreatePointerType(
    LLVMDIBuilderRef, LLVMMetadataRef, uint64_t, uint32_t, unsigned,
    const char *, size_t);
extern LLVMMetadataRef LLVMDIBuilderCreateMemberType(
    LLVMDIBuilderRef, LLVMMetadataRef, const char *, size_t, LLVMMetadataRef,
    unsigned, uint64_t, uint32_t, uint64_t, unsigned, LLVMMetadataRef);
extern LLVMMetadataRef LLVMDIBuilderCreateStructType(
    LLVMDIBuilderRef, LLVMMetadataRef, const char *, size_t, LLVMMetadataRef,
    unsigned, uint64_t, uint32_t, unsigned, LLVMMetadataRef,
    LLVMMetadataRef *, unsigned, unsigned, LLVMMetadataRef, const char *,
    size_t);
extern LLVMMetadataRef LLVMDIBuilderCreateReplaceableCompositeType(
    LLVMDIBuilderRef, unsigned, const char *, size_t, LLVMMetadataRef,
    LLVMMetadataRef, unsigned, unsigned, uint64_t, uint32_t, unsigned,
    const char *, size_t);
extern LLVMMetadataRef LLVMDIBuilderCreateUnionType(
    LLVMDIBuilderRef, LLVMMetadataRef, const char *, size_t, LLVMMetadataRef,
    unsigned, uint64_t, uint32_t, unsigned, LLVMMetadataRef *, unsigned,
    unsigned, const char *, size_t);
extern void LLVMMetadataReplaceAllUsesWith(LLVMMetadataRef, LLVMMetadataRef);
extern LLVMMetadataRef LLVMDIBuilderGetOrCreateSubrange(LLVMDIBuilderRef,
                                                        int64_t, int64_t);
extern LLVMMetadataRef LLVMDIBuilderCreateArrayType(
    LLVMDIBuilderRef, uint64_t, uint32_t, LLVMMetadataRef, LLVMMetadataRef *,
    unsigned);
extern LLVMMetadataRef LLVMDIBuilderCreateEnumerator(
    LLVMDIBuilderRef, const char *, size_t, int64_t, int);
extern LLVMMetadataRef LLVMDIBuilderCreateEnumerationType(
    LLVMDIBuilderRef, LLVMMetadataRef, const char *, size_t, LLVMMetadataRef,
    unsigned, uint64_t, uint32_t, LLVMMetadataRef *, unsigned,
    LLVMMetadataRef);
extern LLVMMetadataRef LLVMDIBuilderCreateAutoVariable(
    LLVMDIBuilderRef, LLVMMetadataRef, const char *, size_t, LLVMMetadataRef,
    unsigned, LLVMMetadataRef, int, unsigned, uint32_t);
extern LLVMMetadataRef LLVMDIBuilderCreateParameterVariable(
    LLVMDIBuilderRef, LLVMMetadataRef, const char *, size_t, unsigned,
    LLVMMetadataRef, unsigned, LLVMMetadataRef, int, unsigned);
extern LLVMMetadataRef LLVMDIBuilderCreateExpression(LLVMDIBuilderRef,
                                                     int64_t *, size_t);
extern LLVMValueRef LLVMDIBuilderInsertDeclareRecordAtEnd(
    LLVMDIBuilderRef, LLVMValueRef, LLVMMetadataRef, LLVMMetadataRef,
    LLVMMetadataRef, LLVMBasicBlockRef);
extern LLVMValueRef LLVMDIBuilderInsertDbgValueRecordAtEnd(
    LLVMDIBuilderRef, LLVMValueRef, LLVMMetadataRef, LLVMMetadataRef,
    LLVMMetadataRef, LLVMBasicBlockRef);
extern LLVMMetadataRef LLVMDIBuilderCreateGlobalVariableExpression(
    LLVMDIBuilderRef, LLVMMetadataRef, const char *, size_t, const char *,
    size_t, LLVMMetadataRef, unsigned, LLVMMetadataRef, int, LLVMMetadataRef,
    LLVMMetadataRef, uint32_t);
extern void LLVMSetSubprogram(LLVMValueRef, LLVMMetadataRef);
extern void LLVMSetCurrentDebugLocation2(LLVMBuilderRef, LLVMMetadataRef);
extern LLVMBasicBlockRef LLVMGetFirstBasicBlock(LLVMValueRef);
extern LLVMBasicBlockRef LLVMGetNextBasicBlock(LLVMBasicBlockRef);
extern LLVMValueRef LLVMGetBasicBlockTerminator(LLVMBasicBlockRef);
extern unsigned LLVMGetNumSuccessors(LLVMValueRef);
extern LLVMBasicBlockRef LLVMGetSuccessor(LLVMValueRef, unsigned);
extern LLVMValueRef LLVMIsALoadInst(LLVMValueRef);
extern LLVMValueRef LLVMGetOperand(LLVMValueRef, unsigned);

#endif
