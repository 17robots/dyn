/* Dependency-free LLVM textual IR builder used only by the independent
 * compiler. The API adapter lets the established semantic lowering serve both
 * backends. */
#ifndef DYN_LLVM_TEXT_H
#define DYN_LLVM_TEXT_H
#define LLVMAddAttributeAtIndex dyn_text_AddAttributeAtIndex
#define LLVMAddCallSiteAttribute dyn_text_AddCallSiteAttribute
#define LLVMAddFunction dyn_text_AddFunction
#define LLVMAddGlobal dyn_text_AddGlobal
#define LLVMAddIncoming dyn_text_AddIncoming
#define LLVMAddModuleFlag dyn_text_AddModuleFlag
#define LLVMAppendBasicBlockInContext dyn_text_AppendBasicBlockInContext
#define LLVMArrayType2 dyn_text_ArrayType2
#define LLVMBuildAShr dyn_text_BuildAShr
#define LLVMBuildAdd dyn_text_BuildAdd
#define LLVMBuildAlloca dyn_text_BuildAlloca
#define LLVMBuildAnd dyn_text_BuildAnd
#define LLVMBuildBitCast dyn_text_BuildBitCast
#define LLVMBuildBr dyn_text_BuildBr
#define LLVMBuildCall2 dyn_text_BuildCall2
#define LLVMBuildCondBr dyn_text_BuildCondBr
#define LLVMBuildExtractValue dyn_text_BuildExtractValue
#define LLVMBuildFAdd dyn_text_BuildFAdd
#define LLVMBuildFCmp dyn_text_BuildFCmp
#define LLVMBuildFDiv dyn_text_BuildFDiv
#define LLVMBuildFMul dyn_text_BuildFMul
#define LLVMBuildFNeg dyn_text_BuildFNeg
#define LLVMBuildFPExt dyn_text_BuildFPExt
#define LLVMBuildFPToSI dyn_text_BuildFPToSI
#define LLVMBuildFPToUI dyn_text_BuildFPToUI
#define LLVMBuildFPTrunc dyn_text_BuildFPTrunc
#define LLVMBuildFRem dyn_text_BuildFRem
#define LLVMBuildFSub dyn_text_BuildFSub
#define LLVMBuildGEP2 dyn_text_BuildGEP2
#define LLVMBuildGlobalStringPtr dyn_text_BuildGlobalStringPtr
#define LLVMBuildICmp dyn_text_BuildICmp
#define LLVMBuildInsertValue dyn_text_BuildInsertValue
#define LLVMBuildIntToPtr dyn_text_BuildIntToPtr
#define LLVMBuildLShr dyn_text_BuildLShr
#define LLVMBuildLoad2 dyn_text_BuildLoad2
#define LLVMBuildMemMove dyn_text_BuildMemMove
#define LLVMBuildMul dyn_text_BuildMul
#define LLVMBuildNeg dyn_text_BuildNeg
#define LLVMBuildNot dyn_text_BuildNot
#define LLVMBuildOr dyn_text_BuildOr
#define LLVMBuildPhi dyn_text_BuildPhi
#define LLVMBuildPtrToInt dyn_text_BuildPtrToInt
#define LLVMBuildRet dyn_text_BuildRet
#define LLVMBuildRetVoid dyn_text_BuildRetVoid
#define LLVMBuildSDiv dyn_text_BuildSDiv
#define LLVMBuildSExt dyn_text_BuildSExt
#define LLVMBuildSIToFP dyn_text_BuildSIToFP
#define LLVMBuildSRem dyn_text_BuildSRem
#define LLVMBuildSelect dyn_text_BuildSelect
#define LLVMBuildShl dyn_text_BuildShl
#define LLVMBuildStore dyn_text_BuildStore
#define LLVMBuildStructGEP2 dyn_text_BuildStructGEP2
#define LLVMBuildSub dyn_text_BuildSub
#define LLVMBuildTrunc dyn_text_BuildTrunc
#define LLVMBuildUDiv dyn_text_BuildUDiv
#define LLVMBuildUIToFP dyn_text_BuildUIToFP
#define LLVMBuildURem dyn_text_BuildURem
#define LLVMBuildUnreachable dyn_text_BuildUnreachable
#define LLVMBuildXor dyn_text_BuildXor
#define LLVMBuildZExt dyn_text_BuildZExt
#define LLVMConstAShr dyn_text_ConstAShr
#define LLVMConstAdd dyn_text_ConstAdd
#define LLVMConstAnd dyn_text_ConstAnd
#define LLVMConstArray2 dyn_text_ConstArray2
#define LLVMConstFAdd dyn_text_ConstFAdd
#define LLVMConstFDiv dyn_text_ConstFDiv
#define LLVMConstFMul dyn_text_ConstFMul
#define LLVMConstFPExt dyn_text_ConstFPExt
#define LLVMConstFRem dyn_text_ConstFRem
#define LLVMConstFSub dyn_text_ConstFSub
#define LLVMConstInt dyn_text_ConstInt
#define LLVMConstIntGetZExtValue dyn_text_ConstIntGetZExtValue
#define LLVMConstLShr dyn_text_ConstLShr
#define LLVMConstMul dyn_text_ConstMul
#define LLVMConstNamedStruct dyn_text_ConstNamedStruct
#define LLVMConstNeg dyn_text_ConstNeg
#define LLVMConstNot dyn_text_ConstNot
#define LLVMConstNull dyn_text_ConstNull
#define LLVMConstOr dyn_text_ConstOr
#define LLVMConstReal dyn_text_ConstReal
#define LLVMConstSDiv dyn_text_ConstSDiv
#define LLVMConstSExt dyn_text_ConstSExt
#define LLVMConstSIToFP dyn_text_ConstSIToFP
#define LLVMConstSRem dyn_text_ConstSRem
#define LLVMConstShl dyn_text_ConstShl
#define LLVMConstStringInContext dyn_text_ConstStringInContext
#define LLVMConstSub dyn_text_ConstSub
#define LLVMConstTrunc dyn_text_ConstTrunc
#define LLVMConstUDiv dyn_text_ConstUDiv
#define LLVMConstUIToFP dyn_text_ConstUIToFP
#define LLVMConstURem dyn_text_ConstURem
#define LLVMConstXor dyn_text_ConstXor
#define LLVMConstZExt dyn_text_ConstZExt
#define LLVMContextCreate dyn_text_ContextCreate
#define LLVMContextDispose dyn_text_ContextDispose
#define LLVMCopyStringRepOfTargetData dyn_text_CopyStringRepOfTargetData
#define LLVMCountParamTypes dyn_text_CountParamTypes
#define LLVMCountStructElementTypes dyn_text_CountStructElementTypes
#define LLVMCreateBuilderInContext dyn_text_CreateBuilderInContext
#define LLVMCreateDIBuilder dyn_text_CreateDIBuilder
#define LLVMCreateEnumAttribute dyn_text_CreateEnumAttribute
#define LLVMCreatePassBuilderOptions dyn_text_CreatePassBuilderOptions
#define LLVMCreateStringAttribute dyn_text_CreateStringAttribute
#define LLVMCreateTargetDataLayout dyn_text_CreateTargetDataLayout
#define LLVMCreateTargetMachine dyn_text_CreateTargetMachine
#define LLVMCreateTypeAttribute dyn_text_CreateTypeAttribute
#define LLVMDIBuilderCreateArrayType dyn_text_DIBuilderCreateArrayType
#define LLVMDIBuilderCreateAutoVariable dyn_text_DIBuilderCreateAutoVariable
#define LLVMDIBuilderCreateBasicType dyn_text_DIBuilderCreateBasicType
#define LLVMDIBuilderCreateCompileUnit dyn_text_DIBuilderCreateCompileUnit
#define LLVMDIBuilderCreateDebugLocation dyn_text_DIBuilderCreateDebugLocation
#define LLVMDIBuilderCreateEnumerationType                                     \
  dyn_text_DIBuilderCreateEnumerationType
#define LLVMDIBuilderCreateEnumerator dyn_text_DIBuilderCreateEnumerator
#define LLVMDIBuilderCreateExpression dyn_text_DIBuilderCreateExpression
#define LLVMDIBuilderCreateFile dyn_text_DIBuilderCreateFile
#define LLVMDIBuilderCreateFunction dyn_text_DIBuilderCreateFunction
#define LLVMDIBuilderCreateGlobalVariableExpression                            \
  dyn_text_DIBuilderCreateGlobalVariableExpression
#define LLVMDIBuilderCreateMemberType dyn_text_DIBuilderCreateMemberType
#define LLVMDIBuilderCreateParameterVariable                                   \
  dyn_text_DIBuilderCreateParameterVariable
#define LLVMDIBuilderCreatePointerType dyn_text_DIBuilderCreatePointerType
#define LLVMDIBuilderCreateReplaceableCompositeType                            \
  dyn_text_DIBuilderCreateReplaceableCompositeType
#define LLVMDIBuilderCreateStructType dyn_text_DIBuilderCreateStructType
#define LLVMDIBuilderCreateSubroutineType dyn_text_DIBuilderCreateSubroutineType
#define LLVMDIBuilderCreateUnionType dyn_text_DIBuilderCreateUnionType
#define LLVMDIBuilderFinalize dyn_text_DIBuilderFinalize
#define LLVMDIBuilderGetOrCreateSubrange dyn_text_DIBuilderGetOrCreateSubrange
#define LLVMDIBuilderInsertDbgValueRecordAtEnd                                 \
  dyn_text_DIBuilderInsertDbgValueRecordAtEnd
#define LLVMDIBuilderInsertDeclareRecordAtEnd                                  \
  dyn_text_DIBuilderInsertDeclareRecordAtEnd
#define LLVMDebugMetadataVersion dyn_text_DebugMetadataVersion
#define LLVMDisposeBuilder dyn_text_DisposeBuilder
#define LLVMDisposeDIBuilder dyn_text_DisposeDIBuilder
#define LLVMDisposeErrorMessage dyn_text_DisposeErrorMessage
#define LLVMDisposeMessage dyn_text_DisposeMessage
#define LLVMDisposeModule dyn_text_DisposeModule
#define LLVMDisposePassBuilderOptions dyn_text_DisposePassBuilderOptions
#define LLVMDisposeTargetData dyn_text_DisposeTargetData
#define LLVMDisposeTargetMachine dyn_text_DisposeTargetMachine
#define LLVMDoubleTypeInContext dyn_text_DoubleTypeInContext
#define LLVMFloatTypeInContext dyn_text_FloatTypeInContext
#define LLVMFunctionType dyn_text_FunctionType
#define LLVMGetBasicBlockTerminator dyn_text_GetBasicBlockTerminator
#define LLVMGetDefaultTargetTriple dyn_text_GetDefaultTargetTriple
#define LLVMGetEntryBasicBlock dyn_text_GetEntryBasicBlock
#define LLVMGetEnumAttributeKindForName dyn_text_GetEnumAttributeKindForName
#define LLVMGetErrorMessage dyn_text_GetErrorMessage
#define LLVMGetFirstBasicBlock dyn_text_GetFirstBasicBlock
#define LLVMGetFirstInstruction dyn_text_GetFirstInstruction
#define LLVMGetHostCPUFeatures dyn_text_GetHostCPUFeatures
#define LLVMGetHostCPUName dyn_text_GetHostCPUName
#define LLVMGetInsertBlock dyn_text_GetInsertBlock
#define LLVMGetIntTypeWidth dyn_text_GetIntTypeWidth
#define LLVMGetMDKindIDInContext dyn_text_GetMDKindIDInContext
#define LLVMGetNamedFunction dyn_text_GetNamedFunction
#define LLVMGetNextBasicBlock dyn_text_GetNextBasicBlock
#define LLVMGetNumSuccessors dyn_text_GetNumSuccessors
#define LLVMGetOperand dyn_text_GetOperand
#define LLVMGetParam dyn_text_GetParam
#define LLVMGetParamTypes dyn_text_GetParamTypes
#define LLVMGetReturnType dyn_text_GetReturnType
#define LLVMGetSuccessor dyn_text_GetSuccessor
#define LLVMGetTargetFromTriple dyn_text_GetTargetFromTriple
#define LLVMGetTypeKind dyn_text_GetTypeKind
#define LLVMGetUndef dyn_text_GetUndef
#define LLVMGetValueName2 dyn_text_GetValueName2
#define LLVMGlobalGetValueType dyn_text_GlobalGetValueType
#define LLVMGlobalSetMetadata dyn_text_GlobalSetMetadata
#define LLVMInitializeAArch64AsmPrinter dyn_text_InitializeAArch64AsmPrinter
#define LLVMInitializeAArch64Target dyn_text_InitializeAArch64Target
#define LLVMInitializeAArch64TargetInfo dyn_text_InitializeAArch64TargetInfo
#define LLVMInitializeAArch64TargetMC dyn_text_InitializeAArch64TargetMC
#define LLVMInitializeWebAssemblyAsmPrinter                                    \
  dyn_text_InitializeWebAssemblyAsmPrinter
#define LLVMInitializeWebAssemblyTarget dyn_text_InitializeWebAssemblyTarget
#define LLVMInitializeWebAssemblyTargetInfo                                    \
  dyn_text_InitializeWebAssemblyTargetInfo
#define LLVMInitializeWebAssemblyTargetMC dyn_text_InitializeWebAssemblyTargetMC
#define LLVMInitializeX86AsmPrinter dyn_text_InitializeX86AsmPrinter
#define LLVMInitializeX86Target dyn_text_InitializeX86Target
#define LLVMInitializeX86TargetInfo dyn_text_InitializeX86TargetInfo
#define LLVMInitializeX86TargetMC dyn_text_InitializeX86TargetMC
#define LLVMInt16TypeInContext dyn_text_Int16TypeInContext
#define LLVMInt1TypeInContext dyn_text_Int1TypeInContext
#define LLVMInt32TypeInContext dyn_text_Int32TypeInContext
#define LLVMInt64TypeInContext dyn_text_Int64TypeInContext
#define LLVMInt8TypeInContext dyn_text_Int8TypeInContext
#define LLVMIntTypeInContext dyn_text_IntTypeInContext
#define LLVMIsAConstantInt dyn_text_IsAConstantInt
#define LLVMIsALoadInst dyn_text_IsALoadInst
#define LLVMMetadataReplaceAllUsesWith dyn_text_MetadataReplaceAllUsesWith
#define LLVMModuleCreateWithNameInContext dyn_text_ModuleCreateWithNameInContext
#define LLVMPassBuilderOptionsSetLoopVectorization                             \
  dyn_text_PassBuilderOptionsSetLoopVectorization
#define LLVMPassBuilderOptionsSetSLPVectorization                              \
  dyn_text_PassBuilderOptionsSetSLPVectorization
#define LLVMPointerTypeInContext dyn_text_PointerTypeInContext
#define LLVMPositionBuilderAtEnd dyn_text_PositionBuilderAtEnd
#define LLVMPositionBuilderBefore dyn_text_PositionBuilderBefore
#define LLVMPrintModuleToString dyn_text_PrintModuleToString
#define LLVMRunPasses dyn_text_RunPasses
#define LLVMSetAlignment dyn_text_SetAlignment
#define LLVMSetCurrentDebugLocation2 dyn_text_SetCurrentDebugLocation2
#define LLVMSetDataLayout dyn_text_SetDataLayout
#define LLVMSetGlobalConstant dyn_text_SetGlobalConstant
#define LLVMSetInitializer dyn_text_SetInitializer
#define LLVMSetLinkage dyn_text_SetLinkage
#define LLVMSetSection dyn_text_SetSection
#define LLVMSetSubprogram dyn_text_SetSubprogram
#define LLVMSetTarget dyn_text_SetTarget
#define LLVMSetVisibility dyn_text_SetVisibility
#define LLVMSizeOf dyn_text_SizeOf
#define LLVMStructCreateNamed dyn_text_StructCreateNamed
#define LLVMStructGetTypeAtIndex dyn_text_StructGetTypeAtIndex
#define LLVMStructSetBody dyn_text_StructSetBody
#define LLVMStructTypeInContext dyn_text_StructTypeInContext
#define LLVMTargetMachineEmitToFile dyn_text_TargetMachineEmitToFile
#define LLVMTypeOf dyn_text_TypeOf
#define LLVMValueAsMetadata dyn_text_ValueAsMetadata
#define LLVMVectorType dyn_text_VectorType
#define LLVMVerifyModule dyn_text_VerifyModule
#define LLVMVoidTypeInContext dyn_text_VoidTypeInContext
#define LLVMWriteBitcodeToFile dyn_text_WriteBitcodeToFile
/* Local syntax-builder interface. Names above map to dyn_text_* symbols;
 * these declarations do not import or link the LLVM C API. */

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
enum { LLVMDefaultVisibility = 0, LLVMHiddenVisibility = 1 };

extern void LLVMInitializeWebAssemblyTargetInfo(void);
extern void LLVMInitializeWebAssemblyTarget(void);
extern void LLVMInitializeWebAssemblyTargetMC(void);
extern void LLVMInitializeWebAssemblyAsmPrinter(void);
extern LLVMAttributeRef LLVMCreateStringAttribute(LLVMContextRef, const char *, unsigned, const char *, unsigned);
extern void LLVMInitializeX86TargetInfo(void);
extern void LLVMInitializeX86Target(void);
extern void LLVMInitializeX86TargetMC(void);
extern void LLVMInitializeX86AsmPrinter(void);
extern void LLVMInitializeAArch64TargetInfo(void);
extern void LLVMInitializeAArch64Target(void);
extern void LLVMInitializeAArch64TargetMC(void);
extern void LLVMInitializeAArch64AsmPrinter(void);
extern LLVMContextRef LLVMContextCreate(void);
extern char *LLVMGetHostCPUName(void);
extern char *LLVMGetHostCPUFeatures(void);
extern void dyn_enable_optimization_remarks(LLVMContextRef);
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
extern LLVMTypeRef LLVMVectorType(LLVMTypeRef, unsigned);
extern LLVMAttributeRef LLVMCreateTypeAttribute(LLVMContextRef, unsigned, LLVMTypeRef);
extern void LLVMAddCallSiteAttribute(LLVMValueRef, unsigned, LLVMAttributeRef);
extern const char *LLVMGetValueName2(LLVMValueRef, size_t *);
extern void LLVMSetSection(LLVMValueRef, const char *);
extern void LLVMSetAlignment(LLVMValueRef, unsigned);
extern LLVMValueRef LLVMGetUndef(LLVMTypeRef);
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
extern unsigned LLVMGetMDKindIDInContext(LLVMContextRef, const char *,
                                         unsigned);
extern void LLVMGlobalSetMetadata(LLVMValueRef, unsigned, LLVMMetadataRef);
extern void LLVMSetLinkage(LLVMValueRef, int);
extern void LLVMSetVisibility(LLVMValueRef, int);
extern void LLVMSetInitializer(LLVMValueRef, LLVMValueRef);
extern void LLVMSetGlobalConstant(LLVMValueRef, int);
extern LLVMBasicBlockRef
LLVMAppendBasicBlockInContext(LLVMContextRef, LLVMValueRef, const char *);
extern LLVMBuilderRef LLVMCreateBuilderInContext(LLVMContextRef);
extern void LLVMDisposeBuilder(LLVMBuilderRef);
extern void LLVMPositionBuilderAtEnd(LLVMBuilderRef, LLVMBasicBlockRef);
extern LLVMValueRef LLVMConstInt(LLVMTypeRef, unsigned long long, int);
extern LLVMValueRef LLVMConstStringInContext(LLVMContextRef, const char *, unsigned, int);
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
extern LLVMValueRef LLVMBuildSelect(LLVMBuilderRef, LLVMValueRef, LLVMValueRef, LLVMValueRef, const char *);
extern LLVMValueRef LLVMBuildStore(LLVMBuilderRef, LLVMValueRef, LLVMValueRef);
extern LLVMValueRef LLVMBuildMemMove(LLVMBuilderRef, LLVMValueRef, unsigned,
                                     LLVMValueRef, unsigned, LLVMValueRef);
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
extern LLVMBasicBlockRef LLVMGetEntryBasicBlock(LLVMValueRef);
extern LLVMValueRef LLVMGetFirstInstruction(LLVMBasicBlockRef);
extern void LLVMPositionBuilderBefore(LLVMBuilderRef, LLVMValueRef);
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
/* ThinLTO summary/hash writer implemented through the LLVM C++ API. */
extern int dyn_write_thin_bitcode(LLVMModuleRef module, const char *path);
/* Debug builds only: split first-class aggregate values into scalars so
   FastISel can select them. */
extern void dyn_scalarize_aggregates(LLVMModuleRef module);
extern int LLVMWriteBitcodeToFile(LLVMModuleRef, const char *);
extern void LLVMSetTarget(LLVMModuleRef, const char *);
extern int LLVMVerifyModule(LLVMModuleRef, int, char **);
extern LLVMPassBuilderOptionsRef LLVMCreatePassBuilderOptions(void);
extern void LLVMDisposePassBuilderOptions(LLVMPassBuilderOptionsRef);
extern void
LLVMPassBuilderOptionsSetLoopVectorization(LLVMPassBuilderOptionsRef, int);
extern void LLVMPassBuilderOptionsSetSLPVectorization(LLVMPassBuilderOptionsRef,
                                                      int);
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
extern LLVMMetadataRef LLVMDIBuilderCreateSubroutineType(LLVMDIBuilderRef,
                                                         LLVMMetadataRef,
                                                         LLVMMetadataRef *,
                                                         unsigned, unsigned);
extern LLVMMetadataRef
LLVMDIBuilderCreateFunction(LLVMDIBuilderRef, LLVMMetadataRef, const char *,
                            size_t, const char *, size_t, LLVMMetadataRef,
                            unsigned, LLVMMetadataRef, int, int, unsigned,
                            unsigned, int);
extern LLVMMetadataRef LLVMDIBuilderCreateDebugLocation(LLVMContextRef,
                                                        unsigned, unsigned,
                                                        LLVMMetadataRef,
                                                        LLVMMetadataRef);
extern LLVMMetadataRef LLVMDIBuilderCreateBasicType(LLVMDIBuilderRef,
                                                    const char *, size_t,
                                                    uint64_t, unsigned,
                                                    unsigned);
extern LLVMMetadataRef LLVMDIBuilderCreatePointerType(LLVMDIBuilderRef,
                                                      LLVMMetadataRef, uint64_t,
                                                      uint32_t, unsigned,
                                                      const char *, size_t);
extern LLVMMetadataRef
LLVMDIBuilderCreateMemberType(LLVMDIBuilderRef, LLVMMetadataRef, const char *,
                              size_t, LLVMMetadataRef, unsigned, uint64_t,
                              uint32_t, uint64_t, unsigned, LLVMMetadataRef);
extern LLVMMetadataRef LLVMDIBuilderCreateStructType(
    LLVMDIBuilderRef, LLVMMetadataRef, const char *, size_t, LLVMMetadataRef,
    unsigned, uint64_t, uint32_t, unsigned, LLVMMetadataRef, LLVMMetadataRef *,
    unsigned, unsigned, LLVMMetadataRef, const char *, size_t);
extern LLVMMetadataRef LLVMDIBuilderCreateReplaceableCompositeType(
    LLVMDIBuilderRef, unsigned, const char *, size_t, LLVMMetadataRef,
    LLVMMetadataRef, unsigned, unsigned, uint64_t, uint32_t, unsigned,
    const char *, size_t);
extern LLVMMetadataRef
LLVMDIBuilderCreateUnionType(LLVMDIBuilderRef, LLVMMetadataRef, const char *,
                             size_t, LLVMMetadataRef, unsigned, uint64_t,
                             uint32_t, unsigned, LLVMMetadataRef *, unsigned,
                             unsigned, const char *, size_t);
extern void LLVMMetadataReplaceAllUsesWith(LLVMMetadataRef, LLVMMetadataRef);
extern LLVMMetadataRef LLVMDIBuilderGetOrCreateSubrange(LLVMDIBuilderRef,
                                                        int64_t, int64_t);
extern LLVMMetadataRef LLVMDIBuilderCreateArrayType(LLVMDIBuilderRef, uint64_t,
                                                    uint32_t, LLVMMetadataRef,
                                                    LLVMMetadataRef *,
                                                    unsigned);
extern LLVMMetadataRef LLVMDIBuilderCreateEnumerator(LLVMDIBuilderRef,
                                                     const char *, size_t,
                                                     int64_t, int);
extern LLVMMetadataRef LLVMDIBuilderCreateEnumerationType(
    LLVMDIBuilderRef, LLVMMetadataRef, const char *, size_t, LLVMMetadataRef,
    unsigned, uint64_t, uint32_t, LLVMMetadataRef *, unsigned, LLVMMetadataRef);
extern LLVMMetadataRef
LLVMDIBuilderCreateAutoVariable(LLVMDIBuilderRef, LLVMMetadataRef, const char *,
                                size_t, LLVMMetadataRef, unsigned,
                                LLVMMetadataRef, int, unsigned, uint32_t);
extern LLVMMetadataRef LLVMDIBuilderCreateParameterVariable(
    LLVMDIBuilderRef, LLVMMetadataRef, const char *, size_t, unsigned,
    LLVMMetadataRef, unsigned, LLVMMetadataRef, int, unsigned);
extern LLVMMetadataRef LLVMDIBuilderCreateExpression(LLVMDIBuilderRef,
                                                     int64_t *, size_t);
extern LLVMValueRef
    LLVMDIBuilderInsertDeclareRecordAtEnd(LLVMDIBuilderRef, LLVMValueRef,
                                          LLVMMetadataRef, LLVMMetadataRef,
                                          LLVMMetadataRef, LLVMBasicBlockRef);
extern LLVMValueRef
    LLVMDIBuilderInsertDbgValueRecordAtEnd(LLVMDIBuilderRef, LLVMValueRef,
                                           LLVMMetadataRef, LLVMMetadataRef,
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
extern LLVMValueRef LLVMIsAConstantInt(LLVMValueRef);
extern unsigned long long LLVMConstIntGetZExtValue(LLVMValueRef);
extern LLVMValueRef LLVMGetOperand(LLVMValueRef, unsigned);


#include <setjmp.h>
jmp_buf *dyn_text_jump(LLVMContextRef);
int dyn_text_verify(LLVMModuleRef, char **);
#endif
