/* Thin WASI Preview 1 import adapter. Dyn owns storage and policy. */
typedef __UINT32_TYPE__ u32;
typedef __UINT64_TYPE__ u64;
#define IMPORT(name) __attribute__((import_module("wasi_snapshot_preview1"), import_name(#name)))
IMPORT(fd_write) extern unsigned wasi_fd_write(u32, const void *, u32, u32 *);
IMPORT(fd_read) extern unsigned wasi_fd_read(u32, const void *, u32, u32 *);
IMPORT(fd_close) extern unsigned wasi_fd_close(u32);
IMPORT(args_sizes_get) extern unsigned wasi_args_sizes_get(u32 *, u32 *);
IMPORT(args_get) extern unsigned wasi_args_get(void *, void *);
IMPORT(path_open) extern unsigned wasi_path_open(u32, u32, const char *, u32, u32, u64, u64, u32, u32 *);
IMPORT(random_get) extern unsigned wasi_random_get(void *, u32);
IMPORT(clock_time_get) extern unsigned wasi_clock_time_get(u32, u64, u64 *);
struct Buffer { void *data; u32 length; };
unsigned dyn_wasi_write(u32 fd, void *data, u32 length, u32 *written) {
  struct Buffer buffer = {data, length}; return wasi_fd_write(fd, &buffer, 1, written);
}
unsigned dyn_wasi_read(u32 fd, void *data, u32 length, u32 *read) {
  struct Buffer buffer = {data, length}; return wasi_fd_read(fd, &buffer, 1, read);
}
unsigned dyn_wasi_close(u32 fd) { return wasi_fd_close(fd); }
unsigned dyn_wasi_args_sizes(u32 *count, u32 *bytes) { return wasi_args_sizes_get(count, bytes); }
unsigned dyn_wasi_args(void *pointers, void *bytes) { return wasi_args_get(pointers, bytes); }
unsigned dyn_wasi_open_read(u32 directory, const char *path, u32 length, u32 *fd) {
  /* No symlink-follow flag; request only FD_READ, no inherited rights. */
  return wasi_path_open(directory, 0, path, length, 0, 2, 0, 0, fd);
}
unsigned dyn_wasi_random(void *data, u32 length) { return wasi_random_get(data, length); }
unsigned dyn_wasi_clock(u32 clock, u64 precision, u64 *time) { return wasi_clock_time_get(clock, precision, time); }

unsigned dyn_time_wasi_clock(u32 clock, u64 precision, u64 *time) { return wasi_clock_time_get(clock, precision, time); }
