#include <stdio.h>
#include <string.h>
#include <zlib.h>
int main(void) {
  unsigned char input[512], output[64];
  size_t length = fread(input, 1, sizeof(input), stdin);
  z_stream stream = {0};
  if (inflateInit2(&stream, -15) != Z_OK) return 1;
  stream.next_in = input; stream.avail_in = (uInt)length;
  stream.next_out = output; stream.avail_out = sizeof(output);
  int status = inflate(&stream, Z_FINISH);
  inflateEnd(&stream);
  if (status != Z_STREAM_END || stream.total_out != 18 ||
      memcmp(output, "hello hello hello\n", 18)) {
    fprintf(stderr, "zlib status=%d input=%zu output=%lu\n", status, length,
            (unsigned long)stream.total_out);
    return 1;
  }
  return 0;
}
