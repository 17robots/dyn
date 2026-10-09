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

// Debug builds select instructions with FastISel, which cannot lower
// first-class aggregate values (slice loads, insertvalue, aggregate stores).
// One such instruction sends the rest of its block to SelectionDAG, several
// times slower. Rewrite aggregate SSA values as their scalar leaves; rebuild
// an aggregate only where a call, return or other user needs one.
#include <llvm/ADT/DenseMap.h>
#include <llvm/ADT/PostOrderIterator.h>
#include <llvm/IR/CFG.h>
#include <llvm/ADT/SmallVector.h>
#include <llvm/IR/Constants.h>
#include <llvm/IR/DataLayout.h>
#include <llvm/IR/IRBuilder.h>
#include <llvm/IR/Instructions.h>
#include <vector>

namespace {
constexpr unsigned MaxLeaves = 16;

struct Leaf {
  llvm::SmallVector<unsigned, 4> path;
  llvm::Type *type;
};

bool flatten(llvm::Type *type, llvm::SmallVectorImpl<unsigned> &path,
             std::vector<Leaf> &leaves) {
  if (auto *s = llvm::dyn_cast<llvm::StructType>(type)) {
    for (unsigned i = 0; i < s->getNumElements(); ++i) {
      path.push_back(i);
      if (!flatten(s->getElementType(i), path, leaves))
        return false;
      path.pop_back();
    }
    return true;
  }
  if (auto *a = llvm::dyn_cast<llvm::ArrayType>(type)) {
    if (a->getNumElements() > MaxLeaves)
      return false;
    for (unsigned i = 0; i < a->getNumElements(); ++i) {
      path.push_back(i);
      if (!flatten(a->getElementType(), path, leaves))
        return false;
      path.pop_back();
    }
    return true;
  }
  if (leaves.size() >= MaxLeaves)
    return false;
  leaves.push_back({llvm::SmallVector<unsigned, 4>(path.begin(), path.end()), type});
  return true;
}

bool aggregate(llvm::Type *type) {
  return type->isStructTy() || type->isArrayTy();
}

class Scalarizer {
public:
  Scalarizer(llvm::Function &f, const llvm::DataLayout &layout)
      : function(f), layout(layout) {}
  void run();

private:
  llvm::Function &function;
  const llvm::DataLayout &layout;
  llvm::DenseMap<llvm::Type *, std::vector<Leaf>> shapes;
  llvm::DenseMap<llvm::Type *, bool> scalable;
  llvm::DenseMap<llvm::Value *, std::vector<llvm::Value *>> values;
  std::vector<llvm::Instruction *> dead;

  const std::vector<Leaf> *shape(llvm::Type *type) {
    auto known = scalable.find(type);
    if (known != scalable.end())
      return known->second ? &shapes[type] : nullptr;
    std::vector<Leaf> leaves;
    llvm::SmallVector<unsigned, 4> path;
    bool ok = flatten(type, path, leaves) && !leaves.empty();
    scalable[type] = ok;
    if (!ok)
      return nullptr;
    shapes[type] = std::move(leaves);
    return &shapes[type];
  }
  llvm::Value *element(llvm::Constant *c, const Leaf &leaf) {
    for (unsigned index : leaf.path)
      c = c->getAggregateElement(index);
    return c;
  }
  // Scalar leaves of an aggregate value, or null when it must stay whole.
  const std::vector<llvm::Value *> *leaves(llvm::Value *v) {
    auto found = values.find(v);
    if (found != values.end())
      return &found->second;
    auto *c = llvm::dyn_cast<llvm::Constant>(v);
    const std::vector<Leaf> *s = shape(v->getType());
    if (!c || !s)
      return nullptr;
    std::vector<llvm::Value *> out;
    for (const Leaf &leaf : *s) {
      llvm::Value *e = element(c, leaf);
      if (!e)
        return nullptr;
      out.push_back(e);
    }
    return &(values[v] = std::move(out));
  }
  // Leaves of any aggregate value: constants and tracked values directly,
  // others (arguments, call results) through extractvalue at the definition.
  const std::vector<llvm::Value *> *any_leaves(llvm::Value *v) {
    if (const auto *known = leaves(v))
      return known;
    const std::vector<Leaf> *s = shape(v->getType());
    if (!s)
      return nullptr;
    llvm::Instruction *at;
    if (auto *argument = llvm::dyn_cast<llvm::Argument>(v))
      at = &*argument->getParent()->getEntryBlock().getFirstInsertionPt();
    else if (auto *i = llvm::dyn_cast<llvm::Instruction>(v)) {
      if (llvm::isa<llvm::PHINode>(i))
        at = &*i->getParent()->getFirstInsertionPt();
      else if (i->isTerminator())
        return nullptr;
      else
        at = i->getNextNode();
    } else
      return nullptr;
    llvm::IRBuilder<> b(at);
    std::vector<llvm::Value *> out;
    for (const Leaf &leaf : *s)
      out.push_back(b.CreateExtractValue(v, leaf.path));
    return &(values[v] = std::move(out));
  }
  llvm::Value *rebuild(llvm::Type *type, const std::vector<llvm::Value *> &parts,
                       llvm::IRBuilder<> &b) {
    const std::vector<Leaf> &s = *shape(type);
    llvm::Value *result = llvm::PoisonValue::get(type);
    for (size_t i = 0; i < s.size(); ++i)
      result = b.CreateInsertValue(result, parts[i], s[i].path);
    return result;
  }
  llvm::Value *address(llvm::IRBuilder<> &b, llvm::Type *type, llvm::Value *base,
                       const Leaf &leaf) {
    if (leaf.path.empty())
      return base;
    llvm::SmallVector<llvm::Value *, 5> indices{b.getInt32(0)};
    for (unsigned index : leaf.path)
      indices.push_back(b.getInt32(index));
    return b.CreateInBoundsGEP(type, base, indices);
  }
  uint64_t offset(llvm::Type *type, const Leaf &leaf) {
    uint64_t at = 0;
    for (unsigned index : leaf.path) {
      if (auto *s = llvm::dyn_cast<llvm::StructType>(type)) {
        at += layout.getStructLayout(s)->getElementOffset(index);
        type = s->getElementType(index);
      } else {
        type = llvm::cast<llvm::ArrayType>(type)->getElementType();
        at += index * layout.getTypeAllocSize(type);
      }
    }
    return at;
  }
  bool zero(llvm::Value *v) {
    auto *c = llvm::dyn_cast<llvm::Constant>(v);
    return c && c->isNullValue();
  }
  void visit(llvm::Instruction &i);
  void finish_phis();
  std::vector<llvm::PHINode *> phis;
};

void Scalarizer::visit(llvm::Instruction &i) {
  llvm::IRBuilder<> b(&i);
  if (auto *store = llvm::dyn_cast<llvm::StoreInst>(&i)) {
    llvm::Value *value = store->getValueOperand();
    llvm::Type *type = value->getType();
    if (!aggregate(type) || !store->isSimple())
      return;
    uint64_t size = layout.getTypeStoreSize(type);
    if (zero(value)) {
      b.CreateMemSet(store->getPointerOperand(), b.getInt8(0), size, store->getAlign());
      dead.push_back(store);
      return;
    }
    if (auto *load = llvm::dyn_cast<llvm::LoadInst>(value);
        load && load->isSimple() && !shape(type) && load->hasOneUse()) {
      b.CreateMemCpy(store->getPointerOperand(), store->getAlign(),
                     load->getPointerOperand(), load->getAlign(), size);
      dead.push_back(store);
      dead.push_back(load);
      return;
    }
    const std::vector<llvm::Value *> *parts = any_leaves(value);
    if (!parts)
      return;
    const std::vector<Leaf> &s = *shape(type);
    for (size_t k = 0; k < s.size(); ++k)
      b.CreateAlignedStore((*parts)[k],
                           address(b, type, store->getPointerOperand(), s[k]),
                           llvm::commonAlignment(store->getAlign(), offset(type, s[k])));
    dead.push_back(store);
    return;
  }
  llvm::Type *type = i.getType();
  std::vector<llvm::Value *> extracted;
  if (auto *extract = llvm::dyn_cast<llvm::ExtractValueInst>(&i)) {
    llvm::Value *from = extract->getAggregateOperand();
    const std::vector<Leaf> *s = shape(from->getType());
    auto found = values.find(from);
    if (!s || found == values.end() && !llvm::isa<llvm::Constant>(from))
      return;
    const std::vector<llvm::Value *> *parts = leaves(from);
    if (!parts)
      return;
    // Leaves under the extracted path, in order.
    llvm::ArrayRef<unsigned> path = extract->getIndices();
    std::vector<llvm::Value *> selected;
    for (size_t k = 0; k < s->size(); ++k)
      if ((*s)[k].path.size() >= path.size() &&
          std::equal(path.begin(), path.end(), (*s)[k].path.begin()))
        selected.push_back((*parts)[k]);
    if (!aggregate(type)) {
      if (selected.size() != 1)
        return;
      i.replaceAllUsesWith(selected[0]);
      dead.push_back(&i);
      return;
    }
    if (!shape(type))
      return;
    extracted = std::move(selected);
  }
  if (!aggregate(type) || !shape(type))
    return;
  const std::vector<Leaf> &s = *shape(type);
  std::vector<llvm::Value *> parts;
  if (llvm::isa<llvm::ExtractValueInst>(&i))
    parts = std::move(extracted);
  else if (auto *load = llvm::dyn_cast<llvm::LoadInst>(&i)) {
    if (!load->isSimple())
      return;
    for (const Leaf &leaf : s)
      parts.push_back(b.CreateAlignedLoad(
          leaf.type, address(b, type, load->getPointerOperand(), leaf),
          llvm::commonAlignment(load->getAlign(), offset(type, leaf))));
  } else if (auto *insert = llvm::dyn_cast<llvm::InsertValueInst>(&i)) {
    const std::vector<llvm::Value *> *base = any_leaves(insert->getAggregateOperand());
    if (!base)
      return;
    parts = *base;
    llvm::ArrayRef<unsigned> path = insert->getIndices();
    llvm::Value *inserted = insert->getInsertedValueOperand();
    std::vector<size_t> slots;
    for (size_t k = 0; k < s.size(); ++k)
      if (s[k].path.size() >= path.size() &&
          std::equal(path.begin(), path.end(), s[k].path.begin()))
        slots.push_back(k);
    if (slots.size() == 1 && !aggregate(inserted->getType()))
      parts[slots[0]] = inserted;
    else {
      const std::vector<llvm::Value *> *sub = any_leaves(inserted);
      if (!sub || sub->size() != slots.size())
        return;
      for (size_t k = 0; k < slots.size(); ++k)
        parts[slots[k]] = (*sub)[k];
    }
  } else if (auto *phi = llvm::dyn_cast<llvm::PHINode>(&i)) {
    for (const Leaf &leaf : s)
      parts.push_back(b.CreatePHI(leaf.type, phi->getNumIncomingValues()));
    phis.push_back(phi);
  } else if (auto *select = llvm::dyn_cast<llvm::SelectInst>(&i)) {
    const std::vector<llvm::Value *> *t = any_leaves(select->getTrueValue()),
                                     *f = t ? any_leaves(select->getFalseValue()) : nullptr;
    if (!t || !f)
      return;
    std::vector<llvm::Value *> tv = *t, fv = *f;
    for (size_t k = 0; k < s.size(); ++k)
      parts.push_back(b.CreateSelect(select->getCondition(), tv[k], fv[k]));
  } else
    return;
  values[&i] = parts;
  // Remaining users that need the whole value get a rebuilt aggregate.
  bool whole = false;
  for (llvm::User *user : i.users()) {
    auto *u = llvm::dyn_cast<llvm::Instruction>(user);
    bool handled = u && (llvm::isa<llvm::ExtractValueInst>(u) ||
        (llvm::isa<llvm::StoreInst>(u) && u->getOperand(0) == &i) ||
        (llvm::isa<llvm::InsertValueInst>(u) && u->getOperand(0) == &i) ||
        llvm::isa<llvm::PHINode>(u) || llvm::isa<llvm::SelectInst>(u));
    whole |= !handled;
  }
  if (whole) {
    llvm::IRBuilder<> after(llvm::isa<llvm::PHINode>(&i)
                                ? &*i.getParent()->getFirstInsertionPt()
                                : i.getNextNode());
    llvm::Value *rebuilt = rebuild(type, parts, after);
    i.replaceUsesWithIf(rebuilt, [&](llvm::Use &use) {
      auto *u = llvm::dyn_cast<llvm::Instruction>(use.getUser());
      return u && !(llvm::isa<llvm::ExtractValueInst>(u) ||
          (llvm::isa<llvm::StoreInst>(u) && use.getOperandNo() == 0) ||
          (llvm::isa<llvm::InsertValueInst>(u) && use.getOperandNo() == 0) ||
          llvm::isa<llvm::PHINode>(u) || llvm::isa<llvm::SelectInst>(u)) &&
          u != rebuilt;
    });
  }
  dead.push_back(&i);
}

void Scalarizer::finish_phis() {
  for (llvm::PHINode *phi : phis) {
    std::vector<llvm::Value *> &parts = values[phi];
    for (unsigned n = 0; n < phi->getNumIncomingValues(); ++n) {
      llvm::Value *incoming = phi->getIncomingValue(n);
      const std::vector<llvm::Value *> *in = any_leaves(incoming);
      for (size_t k = 0; k < parts.size(); ++k) {
        llvm::Value *v = in ? (*in)[k] : nullptr;
        if (!v) {
          llvm::IRBuilder<> b(phi->getIncomingBlock(n)->getTerminator());
          v = b.CreateExtractValue(incoming, (*shape(phi->getType()))[k].path);
        }
        llvm::cast<llvm::PHINode>(parts[k])->addIncoming(v, phi->getIncomingBlock(n));
      }
    }
  }
}

void Scalarizer::run() {
  // Reverse post-order visits definitions before non-phi uses; phis are
  // completed afterwards. Unreachable blocks are left unchanged.
  std::vector<llvm::Instruction *> order;
  for (llvm::BasicBlock *block : llvm::ReversePostOrderTraversal<llvm::Function *>(&function))
    for (llvm::Instruction &i : *block)
      order.push_back(&i);
  for (llvm::Instruction *i : order)
    visit(*i);
  finish_phis();
  // Users of replaced values that were not rewritten get a rebuilt aggregate.
  for (llvm::Instruction *i : dead) {
    if (i->use_empty() || i->getType()->isVoidTy())
      continue;
    auto found = values.find(i);
    if (found == values.end())
      continue;
    llvm::IRBuilder<> after(llvm::isa<llvm::PHINode>(i)
                                ? &*i->getParent()->getFirstInsertionPt()
                                : i->getNextNode());
    i->replaceAllUsesWith(rebuild(i->getType(), found->second, after));
  }
  // Delete in reverse so users go before their operands.
  for (auto it = dead.rbegin(); it != dead.rend(); ++it)
    if ((*it)->use_empty())
      (*it)->eraseFromParent();
}
} // namespace

extern "C" void dyn_scalarize_aggregates(LLVMModuleRef module) {
  llvm::Module &m = *llvm::unwrap(module);
  for (llvm::Function &f : m)
    if (!f.isDeclaration())
      Scalarizer(f, m.getDataLayout()).run();
}
