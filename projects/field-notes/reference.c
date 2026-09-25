#define _GNU_SOURCE
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>

enum { ROOT_CAPACITY = 64 * 1024, TASK_CAPACITY = 64 };

typedef struct { unsigned char *data; size_t capacity, offset; } Arena;
typedef struct { uint32_t id; const char *title; bool done; size_t completed_at; } Task;
typedef struct { Task *tasks; size_t count, command_count; uint32_t next_id; } App;

static void *push(Arena *arena, size_t size, size_t alignment) {
  uintptr_t address = (uintptr_t)arena->data + arena->offset;
  size_t padding = (alignment - address % alignment) % alignment;
  if (padding > arena->capacity - arena->offset ||
      size > arena->capacity - arena->offset - padding) abort();
  void *result = (void *)(address + padding);
  arena->offset += padding + size;
  memset(result, 0, size);
  return result;
}

static Arena sub_arena(Arena *parent, size_t capacity) {
  return (Arena){push(parent, capacity, 8), capacity, 0};
}

static char *clone(Arena *arena, const char *text) {
  size_t length = strlen(text);
  char *result = push(arena, length + 1, 1);
  memcpy(result, text, length + 1);
  return result;
}

static bool add(App *app, Arena *permanent, const char *title) {
  if (!*title || app->count == TASK_CAPACITY) return false;
  app->tasks[app->count++] = (Task){app->next_id++, clone(permanent, title), false, 0};
  return true;
}

static Task *find(App *app, uint32_t id) {
  for (size_t i = 0; i < app->count; ++i)
    if (app->tasks[i].id == id) return &app->tasks[i];
  return NULL;
}

static void list(const App *app, Arena *scratch) {
  size_t mark = scratch->offset, complete = 0;
  char *output = push(scratch, 4096, 1);
  size_t at = 0;
  for (size_t i = 0; i < app->count; ++i) {
    const Task *task = &app->tasks[i];
    complete += task->done;
    at += (size_t)snprintf(output + at, 4096 - at, "[%c] %u: %s\n",
                          task->done ? 'x' : ' ', task->id, task->title);
  }
  at += (size_t)snprintf(output + at, 4096 - at, "%zu/%zu complete\n",
                        complete, app->count);
  fwrite(output, 1, at, stdout);
  scratch->offset = mark;
}

int main(void) {
  setvbuf(stdout, NULL, _IONBF, 0);
  unsigned char *mapping = mmap(NULL, ROOT_CAPACITY, PROT_READ | PROT_WRITE,
                                MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
  if (mapping == MAP_FAILED) return 1;
  Arena root = {mapping, ROOT_CAPACITY, 0};
  Arena permanent = sub_arena(&root, 24 * 1024);
  Arena frame = sub_arena(&root, 8 * 1024);
  Arena scratch[2] = {sub_arena(&root, 12 * 1024), sub_arena(&root, 12 * 1024)};
  App app = {(Task *)push(&permanent, TASK_CAPACITY * sizeof(Task), _Alignof(Task)), 0, 0, 1};
  add(&app, &permanent, "learn slices");
  add(&app, &permanent, "partition arenas");

  char *line;
  while (true) {
    frame.offset = 0;
    line = push(&frame, 512, 1);
    fwrite("> ", 1, 2, stdout);
    if (!fgets(line, 512, stdin)) break;
    line[strcspn(line, "\r\n")] = 0;
    ++app.command_count;
    Arena *temp = &scratch[app.command_count & 1];
    if (!strcmp(line, "quit") || !strcmp(line, "exit")) break;
    if (!strcmp(line, "list")) list(&app, temp);
    else if (!strncmp(line, "add ", 4)) add(&app, &permanent, line + 4);
    else if (!strncmp(line, "done ", 5)) {
      Task *task = find(&app, (uint32_t)strtoul(line + 5, NULL, 10));
      if (task) { task->done = true; task->completed_at = app.command_count; }
    }
  }
  munmap(mapping, ROOT_CAPACITY);
  return 0;
}
