#include <iostream>
#include "lexer.h"

int main() {
  auto y = Lexer::tokenize(R"(
      import io;
      struct x {
        f32 z = 10.0;
      }
      x y = {};
      x hello() { return {};}
      io.println(hello().z);
    )");
  std::cout << "y: " << y.size() << '\n';
}
