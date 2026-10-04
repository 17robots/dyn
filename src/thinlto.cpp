#include <llvm/Analysis/ModuleSummaryAnalysis.h>
#include <llvm/Analysis/ProfileSummaryInfo.h>
#include <llvm/Bitcode/BitcodeWriter.h>
#include <llvm/IR/Module.h>
#include <llvm/IR/DiagnosticHandler.h>
#include <llvm/IR/LLVMContext.h>
#include <llvm/Support/FileSystem.h>
#include <llvm/Support/raw_ostream.h>
#include <memory>

namespace {
struct OptimizationRemarks final : llvm::DiagnosticHandler {
  static bool selected(llvm::StringRef pass) {
    return pass == "inline" || pass == "loop-vectorize" ||
           pass == "slp-vectorizer" || pass == "loop-unroll" || pass == "sample-profile";
  }
  bool isAnalysisRemarkEnabled(llvm::StringRef pass) const override { return selected(pass); }
  bool isMissedOptRemarkEnabled(llvm::StringRef pass) const override { return selected(pass); }
  bool isPassedOptRemarkEnabled(llvm::StringRef pass) const override { return selected(pass); }
  bool isAnyRemarkEnabled() const override { return true; }
};
}
extern "C" void dyn_enable_optimization_remarks(LLVMContextRef context) {
  llvm::unwrap(context)->setDiagnosticHandler(std::make_unique<OptimizationRemarks>());
}

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
