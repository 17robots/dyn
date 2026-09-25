/* WASI Preview 1 command entry; no libc or hidden allocation. */
extern int main(void);
__attribute__((import_module("wasi_snapshot_preview1"), import_name("proc_exit"), noreturn))
extern void wasi_proc_exit(unsigned status);
__attribute__((export_name("_start"))) void _start(void) {
  wasi_proc_exit((unsigned)main());
}
