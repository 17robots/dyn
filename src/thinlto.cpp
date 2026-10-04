#include <llvm/Analysis/ModuleSummaryAnalysis.h>
#include <llvm/Analysis/ProfileSummaryInfo.h>
#include <llvm/Bitcode/BitcodeWriter.h>
#include <llvm/IR/Module.h>
#include <llvm/Support/FileSystem.h>
#include <llvm/Support/raw_ostream.h>

// The LLVM C bitcode writer cannot include a summary or module hash. Both are
// required for ThinLTO backend caching; plain bitcode silently selects full LTO.
extern "C" int dyn_write_thin_bitcode(LLVMModuleRef module, const char *path) {
  std::error_code error;
  llvm::raw_fd_ostream output(path, error, llvm::sys::fs::OF_None);
  if (error)
    return 1;
  auto &m = *llvm::unwrap(module);
  llvm::ProfileSummaryInfo profile(m);
  auto summary = llvm::buildModuleSummaryIndex(m, nullptr, &profile);
  llvm::WriteBitcodeToFile(m, output, false, &summary, true);
  output.close();
  if (output.has_error()) {
    output.clear_error();
    return 1;
  }
  return 0;
}
