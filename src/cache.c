#define _POSIX_C_SOURCE 200809L
#include "dyn.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <dirent.h>
#include <errno.h>
#include <unistd.h>

static uint64_t hash_bytes(uint64_t hash, const void *data, size_t length) {
  const unsigned char *bytes = data;
  for (size_t i = 0; i < length; ++i) {
    hash ^= bytes[i];
    hash *= UINT64_C(1099511628211);
  }
  return hash;
}

static bool make_directories(char *path) {
  for (char *p = path + 1; *p; ++p) if (*p == '/') {
    *p = 0;
    if (mkdir(path, 0777) && errno != EEXIST) { *p = '/'; return false; }
    *p = '/';
  }
  return !mkdir(path, 0777) || errno == EEXIST;
}

bool dyn_cache_directory(char *path, size_t capacity) {
  const char *configured = getenv("DYN_CACHE_DIR");
  const char *xdg = getenv("XDG_CACHE_HOME"), *home = getenv("HOME");
  int n;
  if (configured && *configured) n = snprintf(path, capacity, "%s", configured);
  else if (xdg && *xdg) n = snprintf(path, capacity, "%s/dyn/c-frontend-4", xdg);
  else if (home && *home) n = snprintf(path, capacity, "%s/.cache/dyn/c-frontend-4", home);
  else n = snprintf(path, capacity, "/tmp/dyn-cache-%ld/c-frontend-4", (long)getuid());
  return n > 0 && (size_t)n < capacity && make_directories(path);
}

static int cache_walk(const char *path, bool remove_files, uint64_t *bytes,
                      uint64_t *files) {
  DIR *directory=opendir(path);if(!directory)return errno==ENOENT?0:2;
  struct dirent *entry;int result=0;
  while(!result&&(entry=readdir(directory))){
    if(!strcmp(entry->d_name,".")||!strcmp(entry->d_name,".."))continue;
    char child[4096];if(snprintf(child,sizeof(child),"%s/%s",path,entry->d_name)>=(int)sizeof(child)){result=2;break;}
    struct stat st;if(lstat(child,&st)){result=2;break;}
    if(S_ISDIR(st.st_mode)){result=cache_walk(child,remove_files,bytes,files);if(remove_files&&!result&&rmdir(child))result=2;}
    else{*bytes+=(uint64_t)st.st_size;++*files;if(remove_files&&unlink(child))result=2;}
  }
  closedir(directory);return result;
}

int dyn_cache_command(const char *action) {
  char path[4096];if(!dyn_cache_directory(path,sizeof(path)))return 2;
  uint64_t bytes=0,files=0;
  if(!action||!strcmp(action,"stats")){
    int result=cache_walk(path,false,&bytes,&files);
    if(!result)printf("cache %s: %llu files, %llu bytes\n",path,
      (unsigned long long)files,(unsigned long long)bytes);
    return result;
  }
  if(!strcmp(action,"clean")){
    int result=cache_walk(path,true,&bytes,&files);
    if(!result)printf("removed %llu cache files (%llu bytes)\n",
      (unsigned long long)files,(unsigned long long)bytes);
    return result;
  }
  fprintf(stderr,"error: cache expects 'stats' or 'clean'\n");return 2;
}

static uint64_t hash_file(uint64_t hash, const char *path) {
  FILE *file = fopen(path, "rb");
  if (!file)
    return hash_bytes(hash, path, strlen(path));
  unsigned char bytes[16384];
  size_t count;
  while ((count = fread(bytes, 1, sizeof(bytes), file)) != 0)
    hash = hash_bytes(hash, bytes, count);
  fclose(file);
  return hash;
}

static int hash_module(const DynSources *sources, size_t first, size_t count,
                       void *context, uint64_t *value) {
  (void)context;
  uint64_t hash = UINT64_C(1469598103934665603);
  for (size_t i = first; i < first + count; ++i) {
    hash = hash_bytes(hash, sources->items[i].path,
                      strlen(sources->items[i].path));
    hash = hash_bytes(hash, sources->items[i].text, sources->items[i].length);
  }
  *value = hash;
  return 0;
}

static uint64_t hash_project_sources(uint64_t hash, const DynSources *sources) {
  uint64_t *modules = NULL;
  size_t count = 0;
  if (!dyn_build_plan_run(sources, 0, hash_module, NULL, &modules, &count)) {
    for (size_t i = 0; i < count; ++i)
      hash = hash_bytes(hash, &modules[i], sizeof(modules[i]));
    free(modules);
    return hash;
  }
  /* Allocation/thread setup failure only disables parallel fingerprinting. */
  for (size_t i = 0; i < sources->count; ++i) {
    hash = hash_bytes(hash, sources->items[i].path,
                      strlen(sources->items[i].path));
    hash = hash_bytes(hash, sources->items[i].text, sources->items[i].length);
  }
  return hash;
}

static uint64_t build_key(const DynSources *sources, const DynOptions *options,
                          const char *compiler_path) {
  uint64_t hash = UINT64_C(1469598103934665603);
  hash = hash_file(hash, compiler_path);
  hash = hash_bytes(hash, options->target, strlen(options->target));
  hash = hash_bytes(hash, &options->release, sizeof(options->release));
  hash = hash_bytes(hash, &options->debug_info, sizeof(options->debug_info));
  hash = hash_project_sources(hash, sources);
  for (size_t i = 0; i < options->link_input_count; ++i)
    hash = hash_file(hash, options->link_inputs[i]);
  return hash;
}

static uint64_t codegen_key(const DynSources *sources,
                            const DynOptions *options,
                            const char *compiler_path) {
  uint64_t hash = UINT64_C(1469598103934665603);
  hash = hash_file(hash, compiler_path);
  hash = hash_bytes(hash, options->target, strlen(options->target));
  hash = hash_bytes(hash, &options->release, sizeof(options->release));
  hash = hash_bytes(hash, &options->debug_info, sizeof(options->debug_info));
  hash = hash_project_sources(hash, sources);
  return hash;
}

static char *suffixed_path(const char *output, const char *suffix) {
  size_t a = strlen(output), b = strlen(suffix);
  char *path = malloc(a + b + 1);
  if (!path) return NULL;
  memcpy(path, output, a);
  memcpy(path + a, suffix, b + 1);
  return path;
}

static bool copy_file(const char *from, const char *to) {
  FILE *input = fopen(from, "rb"), *output = input ? fopen(to, "wb") : NULL;
  if (!output) { if (input) fclose(input); return false; }
  unsigned char bytes[16384];
  size_t count;
  bool ok = true;
  while ((count = fread(bytes, 1, sizeof(bytes), input)) != 0)
    if (fwrite(bytes, 1, count, output) != count) { ok = false; break; }
  if (ferror(input) || fclose(output) != 0) ok = false;
  fclose(input);
  if (!ok) remove(to);
  return ok;
}

static char *cache_path(const char *output) {
  size_t length = strlen(output);
  char *path = malloc(length + sizeof(".dyncache"));
  if (!path)
    return NULL;
  memcpy(path, output, length);
  memcpy(path + length, ".dyncache", sizeof(".dyncache"));
  return path;
}

typedef struct {
  uint64_t magic, options;
  uint32_t count;
} FastHeader;
typedef struct {
  uint64_t device, inode, size, seconds, nanoseconds, change_seconds,
           change_nanoseconds;
  uint32_t path_length;
} FastEntry;

static uint64_t fast_options(const DynOptions *options) {
  uint64_t hash = UINT64_C(1469598103934665603);
  hash = hash_bytes(hash, options->target, strlen(options->target));
  hash = hash_bytes(hash, &options->release, sizeof(options->release));
  return hash_bytes(hash, &options->debug_info, sizeof(options->debug_info));
}
static bool fast_stat(FILE *file, const char *path, bool write) {
  struct stat st; FastEntry entry = {0};
  size_t length = strlen(path);
  if (stat(path, &st) || length > UINT32_MAX) return false;
  entry.device = (uint64_t)st.st_dev;
  entry.inode = (uint64_t)st.st_ino;
  entry.size = (uint64_t)st.st_size;
  entry.seconds = (uint64_t)st.st_mtim.tv_sec;
  entry.nanoseconds = (uint64_t)st.st_mtim.tv_nsec;
  entry.change_seconds = (uint64_t)st.st_ctim.tv_sec;
  entry.change_nanoseconds = (uint64_t)st.st_ctim.tv_nsec;
  entry.path_length = (uint32_t)length;
  if (write)
    return fwrite(&entry, sizeof(entry), 1, file) == 1 &&
           fwrite(path, 1, length, file) == length;
  FastEntry stored; char *name;
  if (fread(&stored, sizeof(stored), 1, file) != 1 ||
      stored.path_length > 4096) return false;
  name = malloc((size_t)stored.path_length + 1);
  if (!name) return false;
  bool ok = fread(name, 1, stored.path_length, file) == stored.path_length;
  name[stored.path_length] = 0;
  ok = ok && !strcmp(name, path) && stored.device == entry.device &&
       stored.inode == entry.inode && stored.size == entry.size &&
       stored.seconds == entry.seconds && stored.nanoseconds == entry.nanoseconds;
  ok = ok && stored.change_seconds == entry.change_seconds &&
       stored.change_nanoseconds == entry.change_nanoseconds;
  free(name); return ok;
}
static char *fast_path(const char *output) {
  return suffixed_path(output, ".dyncache.files");
}

bool dyn_cache_fast_hit(const DynOptions *options, const char *compiler_path,
                        const char *output) {
  if (options->no_cache) return false;
  char *path = fast_path(output); FILE *file = path ? fopen(path, "rb") : NULL;
  FastHeader header;
  bool ok = file && fread(&header, sizeof(header), 1, file) == 1 &&
            header.magic == UINT64_C(0x44594e4641535431) &&
            header.options == fast_options(options) &&
            header.count == options->link_input_count + 2 &&
            fast_stat(file, output, false) && fast_stat(file, compiler_path, false);
  for (size_t i = 0; ok && i < options->link_input_count; ++i)
    ok = fast_stat(file, options->link_inputs[i], false);
  uint32_t source_count = 0;
  if (ok) ok = fread(&source_count, sizeof(source_count), 1, file) == 1 &&
               source_count <= 16384;
  for (uint32_t i = 0; ok && i < source_count; ++i) {
    FastEntry stored;
    if (fread(&stored, sizeof(stored), 1, file) != 1 || stored.path_length > 4096) { ok=false; break; }
    char *name=malloc((size_t)stored.path_length+1);if(!name){ok=false;break;}
    ok=fread(name,1,stored.path_length,file)==stored.path_length;name[stored.path_length]=0;
    struct stat st;
    ok=ok&&!stat(name,&st)&&stored.device==(uint64_t)st.st_dev&&
       stored.inode==(uint64_t)st.st_ino&&stored.size==(uint64_t)st.st_size&&
       stored.seconds==(uint64_t)st.st_mtim.tv_sec&&stored.nanoseconds==(uint64_t)st.st_mtim.tv_nsec&&
       stored.change_seconds==(uint64_t)st.st_ctim.tv_sec&&
       stored.change_nanoseconds==(uint64_t)st.st_ctim.tv_nsec;
    free(name);
  }
  if (file) fclose(file);
  free(path);
  return ok;
}

static void fast_store(const DynSources *sources, const DynOptions *options,
                       const char *compiler_path, const char *output) {
  char *path=fast_path(output);if(!path)return;
  size_t n=strlen(path)+32;char *temporary=malloc(n);if(!temporary){free(path);return;}
  snprintf(temporary,n,"%s.%ld.tmp",path,(long)getpid());FILE *file=fopen(temporary,"wb");
  FastHeader header={UINT64_C(0x44594e4641535431),fast_options(options),
                     (uint32_t)(options->link_input_count+2)};
  bool ok=file&&fwrite(&header,sizeof(header),1,file)==1&&fast_stat(file,output,true)&&
          fast_stat(file,compiler_path,true);
  for(size_t i=0;ok&&i<options->link_input_count;++i)ok=fast_stat(file,options->link_inputs[i],true);
  long count_position=ftell(file);uint32_t count=0;
  if(ok)ok=fwrite(&count,sizeof(count),1,file)==1;
  for(size_t i=0;ok&&i<sources->count;++i){
    ok=fast_stat(file,sources->items[i].path,true);if(ok)++count;
    char directory[4096];size_t length=strlen(sources->items[i].path);
    if(length>=sizeof(directory)){ok=false;break;}
    memcpy(directory,sources->items[i].path,length+1);char *slash=strrchr(directory,'/');
    if(slash){*slash=0;bool seen=false;for(size_t j=0;j<i;++j){
      const char *prior=sources->items[j].path;size_t n=(size_t)(strrchr(prior,'/')-prior);
      if(strlen(directory)==n&&!memcmp(directory,prior,n)){seen=true;break;}}
      if(!seen){ok=fast_stat(file,directory,true);if(ok)++count;
        char manifest[4096];if(snprintf(manifest,sizeof(manifest),"%s/dyn.project",directory)<(int)sizeof(manifest)&&!access(manifest,F_OK)){
          ok=fast_stat(file,manifest,true);if(ok)++count;}}
    }
  }
  if(ok){long end=ftell(file);ok=fseek(file,count_position,SEEK_SET)==0&&
      fwrite(&count,sizeof(count),1,file)==1&&fseek(file,end,SEEK_SET)==0;}
  if(file&&fclose(file))ok=false;
  if(!ok||rename(temporary,path))remove(temporary);
  free(temporary);free(path);
}

bool dyn_cache_hit(const DynSources *sources, const DynOptions *options,
                   const char *compiler_path, const char *output) {
  struct stat status;
  if (options->no_cache || stat(output, &status) != 0 ||
      !S_ISREG(status.st_mode))
    return false;
  char *path = cache_path(output);
  if (!path)
    return false;
  FILE *file = fopen(path, "r");
  unsigned long long stored = 0, artifact = 0;
  bool hit = file && fscanf(file, "%llx %llx", &stored, &artifact) == 2 &&
             (uint64_t)stored == build_key(sources, options, compiler_path) &&
             (uint64_t)artifact ==
                 hash_file(UINT64_C(1469598103934665603), output);
  if (file)
    fclose(file);
  free(path);
  return hit;
}

void dyn_cache_store(const DynSources *sources, const DynOptions *options,
                     const char *compiler_path, const char *output) {
  if (options->no_cache)
    return;
  char *path = cache_path(output);
  if (!path)
    return;
  FILE *file = fopen(path, "w");
  if (file) {
    fprintf(file, "%016llx %016llx\n",
            (unsigned long long)build_key(sources, options, compiler_path),
            (unsigned long long)hash_file(UINT64_C(1469598103934665603),
                                          output));
    fclose(file);
  }
  free(path);
  fast_store(sources, options, compiler_path, output);
}

bool dyn_object_cache_restore(const DynSources *sources,
                              const DynOptions *options,
                              const char *compiler_path, const char *output,
                              const char *object) {
  if (options->no_cache) return false;
  char *artifact = suffixed_path(output, ".dyncache.o");
  char *metadata = suffixed_path(output, ".dyncache.obj");
  FILE *file = metadata ? fopen(metadata, "r") : NULL;
  unsigned long long stored = 0, digest = 0;
  bool hit = artifact && file && fscanf(file, "%llx %llx", &stored, &digest) == 2 &&
             (uint64_t)stored == codegen_key(sources, options, compiler_path) &&
             (uint64_t)digest == hash_file(UINT64_C(1469598103934665603), artifact) &&
             copy_file(artifact, object);
  if (file) fclose(file);
  free(artifact); free(metadata);
  return hit;
}

void dyn_object_cache_store(const DynSources *sources, const DynOptions *options,
                            const char *compiler_path, const char *output,
                            const char *object) {
  if (options->no_cache) return;
  char *artifact = suffixed_path(output, ".dyncache.o");
  char *metadata = suffixed_path(output, ".dyncache.obj");
  if (artifact && metadata && copy_file(object, artifact)) {
    FILE *file = fopen(metadata, "w");
    if (file) {
      fprintf(file, "%016llx %016llx\n",
              (unsigned long long)codegen_key(sources, options, compiler_path),
              (unsigned long long)hash_file(UINT64_C(1469598103934665603), artifact));
      fclose(file);
    }
  }
  free(artifact); free(metadata);
}

/* One artifact per rewritten module. The key deliberately excludes output and
   link inputs: identical module code is reusable across executables and a
   link-only change never triggers LLVM. Stores are atomic, so process workers
   may populate the same cache safely. */
static uint64_t module_key(const DynSources *sources, size_t first, size_t count,
                           const DynOptions *options,
                           const char *compiler_path, const char *object) {
  uint64_t hash = UINT64_C(1469598103934665603);
  hash = hash_file(hash, compiler_path);
  hash = hash_bytes(hash, options->target, strlen(options->target));
  hash = hash_bytes(hash, &options->release, sizeof(options->release));
  hash = hash_bytes(hash, &options->debug_info, sizeof(options->debug_info));
  size_t object_length = strlen(object);
  bool bitcode = object_length >= 3 &&
                 !strcmp(object + object_length - 3, ".bc");
  hash = hash_bytes(hash, &bitcode, sizeof(bitcode));
  /* Public declaration text is the module object ABI. Function bodies are not
     part of that ABI, so implementation-only edits retain dependent objects. */
  for (size_t source = 0; source < sources->count; ++source) {
    const char *p = sources->items[source].text;
    while ((p = strstr(p, "pub "))) {
      const char *end = strchr(p, '\n');
      if (!end) end = p + strlen(p);
      bool aggregate = !strncmp(p + 4, "struct ", 7) ||
                       !strncmp(p + 4, "enum ", 5);
      const char *open = strchr(p, '{');
      if (aggregate && open) {
        unsigned depth = 1;
        end = open + 1;
        while (*end && depth) {
          if (*end == '{') ++depth;
          else if (*end == '}') --depth;
          ++end;
        }
      } else if (!strncmp(p + 4, "fn ", 3) && open && open < end) {
        end = open;
      }
      hash = hash_bytes(hash, p, (size_t)(end - p));
      p = end;
    }
  }
  uint64_t value = 0;
  if (hash_module(sources, first, count, NULL, &value)) return 0;
  return hash_bytes(hash, &value, sizeof(value));
}

static bool module_artifact(char *path, size_t capacity, const char *root,
                            uint64_t key) {
  if (mkdir(root, 0777) && errno != EEXIST) return false;
  int n = snprintf(path, capacity, "%s/%016llx.o", root,
                   (unsigned long long)key);
  return n > 0 && (size_t)n < capacity;
}

bool dyn_module_cache_restore(const DynSources *sources, size_t first,
                              size_t count, const DynOptions *options,
                              const char *compiler_path, const char *cache_root,
                              const char *object) {
  if (options->no_cache) return false;
  char artifact[4096];
  uint64_t key = module_key(sources, first, count, options, compiler_path,
                            object);
  if (!key || !module_artifact(artifact, sizeof(artifact), cache_root, key))
    return false;
  char metadata[4096];
  if (snprintf(metadata, sizeof(metadata), "%s.sum", artifact) >=
      (int)sizeof(metadata))
    return false;
  FILE *file = fopen(metadata, "r");
  unsigned long long digest = 0;
  bool valid = file && fscanf(file, "%llx", &digest) == 1 &&
               (uint64_t)digest ==
                   hash_file(UINT64_C(1469598103934665603), artifact);
  if (file) fclose(file);
  return valid && copy_file(artifact, object);
}

void dyn_module_cache_store(const DynSources *sources, size_t first,
                            size_t count, const DynOptions *options,
                            const char *compiler_path, const char *cache_root,
                            const char *object) {
  if (options->no_cache) return;
  char artifact[4096], temporary[4096], metadata[4096], metadata_temporary[4096];
  uint64_t key = module_key(sources, first, count, options, compiler_path,
                            object);
  if (!key || !module_artifact(artifact, sizeof(artifact), cache_root, key) ||
      snprintf(temporary, sizeof(temporary), "%s.%ld.tmp", artifact,
               (long)getpid()) >= (int)sizeof(temporary) ||
      snprintf(metadata, sizeof(metadata), "%s.sum", artifact) >=
          (int)sizeof(metadata) ||
      snprintf(metadata_temporary, sizeof(metadata_temporary), "%s.%ld.tmp",
               metadata, (long)getpid()) >= (int)sizeof(metadata_temporary))
    return;
  if (!copy_file(object, temporary) || rename(temporary, artifact)) {
    remove(temporary);
    return;
  }
  FILE *file = fopen(metadata_temporary, "w");
  if (!file) return;
  fprintf(file, "%016llx\n", (unsigned long long)hash_file(
                                   UINT64_C(1469598103934665603), artifact));
  if (fclose(file) || rename(metadata_temporary, metadata))
    remove(metadata_temporary);
}
