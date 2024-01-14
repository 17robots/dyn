#pragma once

#include "lexer.h"
#include "ast.h"

inline std::vector<Node> parse(std::vector<Token> &tks) {
  for (auto t : tks) {
    switch(t.type) {
      case 0:
      case 1:
      case 2:
      case 3:
      case 4:
      case 5:
      default:
        break;
    }
  }
  return {};
}
