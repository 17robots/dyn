#include <iostream>
#include "lexer.h"

std::string read() {
  return R"(
  i8 x = 4;
  mut i8 y = x;
)";
}

int main() {
  std::string in = read();
  auto y = lexer(in);
  for (auto x : y) {
    std::cout << (int)x.type << ' ' << x.val << '\n';
  }
}
