#ifndef DYN_HOST_H
#define DYN_HOST_H
/* Operating-system services used by the compiler, independent of output target. */
#include <errno.h>
#include <stdio.h>
#include <stdint.h>
#include <time.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>
#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <direct.h>
#include <fcntl.h>
#include <io.h>
#define DYN_PATH_SEPARATOR ';'
#define DYN_HOST_TARGET "x86_64-windows"
#define DYN_WINDOWS_LINKER "ld.lld.exe"
static inline void dyn_host_slashes(char *path) {
  for (; *path; ++path) if (*path == '\\') *path = '/';
}
static inline wchar_t *dyn_host_wide(const char *text) {
  int n = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text, -1, NULL, 0);
  wchar_t *out = n ? malloc((size_t)n * sizeof(*out)) : NULL;
  if (out) MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text, -1, out, n);
  return out;
}
static inline char *dyn_host_realpath(const char *path, char *out) {
  wchar_t *wide = dyn_host_wide(path);
  if (!wide) return NULL;
  HANDLE file = CreateFileW(wide, 0, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
      NULL, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, NULL);
  free(wide);
  if (file == INVALID_HANDLE_VALUE) { errno = ENOENT; return NULL; }
  wchar_t buffer[32768];
  DWORD n = GetFinalPathNameByHandleW(file, buffer, 32768, FILE_NAME_NORMALIZED);
  CloseHandle(file);
  if (!n || n >= 32768) { errno = ENAMETOOLONG; return NULL; }
  const wchar_t *start = buffer;
  if (!wcsncmp(start, L"\\\\?\\", 4)) start += 4;
  wchar_t unc[32768];
  if (!wcsncmp(start, L"UNC\\", 4)) {
    swprintf(unc, 32768, L"\\\\%ls", start + 4); start = unc;
  }
  int bytes = WideCharToMultiByte(CP_UTF8, 0, start, -1, NULL, 0, NULL, NULL);
  if (bytes > 4096) { errno = ENAMETOOLONG; return NULL; }
  if (!out) out = malloc((size_t)bytes);
  if (out) { WideCharToMultiByte(CP_UTF8, 0, start, -1, out, bytes, NULL, NULL); dyn_host_slashes(out); }
  return out;
}
#define realpath dyn_host_realpath
static inline char *dyn_host_strndup(const char *text, size_t limit) {
  size_t n = 0;
  while (n < limit && text[n]) ++n;
  char *copy = malloc(n + 1);
  if (copy) { memcpy(copy, text, n); copy[n] = 0; }
  return copy;
}
#define strndup dyn_host_strndup
static inline int dyn_host_mkdir(const char *path, int mode) { (void)mode; return _mkdir(path); }
#define mkdir dyn_host_mkdir
#define fsync _commit
static inline int dyn_host_fchmod(int fd, int mode) { (void)fd; (void)mode; return 0; }
#define fchmod dyn_host_fchmod
/* Windows rename must replace an existing cache/output file atomically. */
static inline int dyn_host_rename(const char *from, const char *to) {
  wchar_t *a = dyn_host_wide(from), *b = dyn_host_wide(to);
  int result = a && b && MoveFileExW(a, b, MOVEFILE_REPLACE_EXISTING) ? 0 : -1;
  free(a); free(b); if (result) errno = EACCES; return result;
}
#define rename dyn_host_rename
struct dyn_host_stat {
  uint64_t st_dev, st_ino, st_size;
  unsigned st_mode;
  struct timespec st_mtim, st_ctim;
};
static inline struct timespec dyn_host_filetime(int64_t ticks) {
  ticks -= INT64_C(116444736000000000);
  return (struct timespec){(time_t)(ticks / 10000000), (long)(ticks % 10000000) * 100};
}
static inline int dyn_host_stat(const char *path, struct dyn_host_stat *out) {
  wchar_t *wide = dyn_host_wide(path);
  if (!wide) return -1;
  HANDLE file = CreateFileW(wide, FILE_READ_ATTRIBUTES,
      FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL, OPEN_EXISTING,
      FILE_FLAG_BACKUP_SEMANTICS, NULL);
  free(wide);
  if (file == INVALID_HANDLE_VALUE) { errno = ENOENT; return -1; }
  BY_HANDLE_FILE_INFORMATION info;
  FILE_BASIC_INFO basic;
  int ok = GetFileInformationByHandle(file, &info) &&
      GetFileInformationByHandleEx(file, FileBasicInfo, &basic, sizeof(basic));
  CloseHandle(file);
  if (!ok) { errno = EIO; return -1; }
  out->st_dev = info.dwVolumeSerialNumber;
  out->st_ino = ((uint64_t)info.nFileIndexHigh << 32) | info.nFileIndexLow;
  out->st_size = ((uint64_t)info.nFileSizeHigh << 32) | info.nFileSizeLow;
  out->st_mode = (info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) ? S_IFDIR | 0755 : S_IFREG | 0644;
  out->st_mtim = dyn_host_filetime(basic.LastWriteTime.QuadPart);
  out->st_ctim = dyn_host_filetime(basic.ChangeTime.QuadPart);
  return 0;
}
#define stat dyn_host_stat
/* Never traverse a Windows junction/symlink when walking a deletable cache. */
static inline int dyn_host_lstat(const char *path, struct dyn_host_stat *out) {
  wchar_t *wide = dyn_host_wide(path);
  if (!wide) return -1;
  DWORD attributes = GetFileAttributesW(wide);
  free(wide);
  if (attributes != INVALID_FILE_ATTRIBUTES && (attributes & FILE_ATTRIBUTE_REPARSE_POINT)) {
    errno = ELOOP; return -1;
  }
  return dyn_host_stat(path, out);
}
#define lstat dyn_host_lstat
static inline int dyn_host_setenv(const char *key, const char *value, int overwrite) {
  if (!overwrite && getenv(key)) return 0;
  return _putenv_s(key, value);
}
#define setenv dyn_host_setenv
#else
#include <sys/wait.h>
#define DYN_PATH_SEPARATOR ':'
#define DYN_WINDOWS_LINKER "ld"
#ifdef __APPLE__
#include <mach-o/dyld.h>
#if !defined(_POSIX_C_SOURCE) || defined(_DARWIN_C_SOURCE)
#define st_mtim st_mtimespec
#define st_ctim st_ctimespec
#endif
#define DYN_HOST_TARGET "aarch64-macos"
#define DYN_DARWIN_LINKER "ld64.lld"
#elif defined(__aarch64__)
#define DYN_HOST_TARGET "aarch64-linux"
#else
#define DYN_HOST_TARGET "x86_64-linux"
#endif
#endif

#ifndef DYN_DARWIN_LINKER
#define DYN_DARWIN_LINKER "zig"
#endif

static inline ssize_t dyn_host_executable(char *out, size_t size) {
#ifdef _WIN32
  wchar_t buffer[32768];
  DWORD n = GetModuleFileNameW(NULL, buffer, 32768);
  if (!n || n >= 32768) return -1;
  int bytes = WideCharToMultiByte(CP_UTF8, 0, buffer, -1, out, (int)size, NULL, NULL);
  if (!bytes) return -1;
  dyn_host_slashes(out);
  return bytes - 1;
#elif defined(__APPLE__)
  uint32_t capacity = (uint32_t)size;
  if (_NSGetExecutablePath(out, &capacity)) return -1;
  return (ssize_t)strlen(out);
#else
  return readlink("/proc/self/exe", out, size);
#endif
}

/* Return child exit status; also use 127 if the program cannot be launched. */
static inline int dyn_host_spawn(char *const *args) {
#ifdef _WIN32
  size_t capacity = 1;
  for (size_t i = 0; args[i]; ++i) capacity += strlen(args[i]) * 2 + 3;
  char *command = malloc(capacity);
  if (!command) return 127;
  size_t at = 0;
  for (size_t i = 0; args[i]; ++i) {
    if (i) command[at++] = ' ';
    command[at++] = '"';
    const char *p = args[i];
    while (*p) {
      size_t slashes = 0;
      while (*p == '\\') { ++slashes; ++p; }
      size_t copies = (*p == '"' || !*p) ? slashes * 2 : slashes;
      while (copies--) command[at++] = '\\';
      if (*p == '"') command[at++] = '\\';
      if (*p) command[at++] = *p++;
    }
    command[at++] = '"';
  }
  command[at] = 0;
  wchar_t *wide = dyn_host_wide(command); free(command);
  if (!wide) return 127;
  STARTUPINFOW start = {0}; start.cb = sizeof(start);
  PROCESS_INFORMATION process;
  BOOL ok = CreateProcessW(NULL, wide, NULL, NULL, TRUE, 0, NULL, NULL, &start, &process);
  free(wide);
  if (!ok) return 127;
  WaitForSingleObject(process.hProcess, INFINITE);
  DWORD status = 127;
  GetExitCodeProcess(process.hProcess, &status);
  CloseHandle(process.hThread); CloseHandle(process.hProcess);
  return (int)status;
#else
  pid_t child = fork();
  if (child < 0) return 127;
  if (!child) { execvp(args[0], args); _exit(127); }
  int status;
  pid_t waited;
  do waited = waitpid(child, &status, 0); while (waited < 0 && errno == EINTR);
  if (waited < 0) return 127;
  return WIFEXITED(status) ? WEXITSTATUS(status) : 128 + WTERMSIG(status);
#endif
}
#endif
