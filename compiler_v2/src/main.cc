#include <iostream>
#include "lexer.h"

std::string read() {
  return R"(
  struct Apple {
    i32 x;
    f32 y;
    void eat(&self) {
      io.println("hello world");
    }
  };
)";
}

int main() {
  std::string in = read();
  auto y = lexer(in);
  for (auto x : y) {
    std::cout << (int)x.type << ' ' << x.val << '\n';
  }
}
