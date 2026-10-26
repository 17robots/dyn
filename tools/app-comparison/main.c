#define _GNU_SOURCE
#include <yyjson.h>
#include <dirent.h>
#include <sys/stat.h>
#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <errno.h>

static unsigned char *read_all(const char *path, size_t *len) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    size_t cap = 8192, n = 0;
    unsigned char *buf = malloc(cap);
    if (!buf) { fclose(f); return NULL; }
    for (;;) {
        if (n == cap) {
            if (cap > SIZE_MAX / 2) { free(buf); fclose(f); return NULL; }
            cap *= 2;
            void *p = realloc(buf, cap);
            if (!p) { free(buf); fclose(f); return NULL; }
            buf = p;
        }
        size_t got = fread(buf + n, 1, cap - n, f);
        n += got;
        if (!got) break;
    }
    int failed = ferror(f);
    if (fclose(f)) failed = 1;
    if (failed) { free(buf); return NULL; }
    *len = n;
    return buf;
}
static int add(uint64_t *dst, uint64_t n) {
    if (n > UINT64_C(9007199254740991) || *dst > UINT64_C(9007199254740991) - n) return 0;
    *dst += n; return 1;
}
static int number(yyjson_val *v, uint64_t max, uint64_t *out) {
    if (yyjson_is_uint(v)) {
        *out = yyjson_get_uint(v); return *out <= max;
    }
    if (yyjson_is_sint(v)) {
        int64_t n = yyjson_get_sint(v);
        if (n < 0) return 0;
        *out = (uint64_t)n; return *out <= max;
    }
    if (yyjson_is_real(v)) {
        double n = yyjson_get_real(v);
        if (!isfinite(n) || n < 0 || n > (double)max || floor(n) != n) return 0;
        *out = (uint64_t)n; return 1;
    }
    return 0;
}
static int record(char *data, size_t len, uint64_t totals[4], uint64_t services[16][4]) {
    yyjson_doc *doc = yyjson_read(data, len, 0);
    if (!doc) return 0;
    yyjson_val *obj = yyjson_doc_get_root(doc);
    int ok = 0;
    if (!yyjson_is_obj(obj)) goto done;
    yyjson_val *v = yyjson_obj_get(obj, "service");
    if (!yyjson_is_str(v) || yyjson_get_len(v) != 5) goto done;
    const char *s = yyjson_get_str(v);
    static const char *names[16] = {
        "svc00", "svc01", "svc02", "svc03", "svc04", "svc05", "svc06", "svc07",
        "svc08", "svc09", "svc10", "svc11", "svc12", "svc13", "svc14", "svc15"
    };
    unsigned svc = 0;
    while (svc < 16 && memcmp(s, names[svc], 5)) svc++;
    if (svc == 16) goto done;
    uint64_t status, bytes, latency;
    if (!number(yyjson_obj_get(obj, "status"), 599, &status) ||
        !number(yyjson_obj_get(obj, "bytes"), UINT64_C(9007199254740991), &bytes) ||
        !number(yyjson_obj_get(obj, "latency_us"), UINT64_C(9007199254740991), &latency)) goto done;
    uint64_t row[4] = {1, bytes, latency, status >= 500};
    for (unsigned i = 0; i < 4; i++)
        if (!add(&totals[i], row[i]) || !add(&services[svc][i], row[i])) goto done;
    ok = 1;
done:
    yyjson_doc_free(doc); return ok;
}
static int report(const char *path) {
    size_t len;
    unsigned char *data = read_all(path, &len);
    if (!data) return 0;
    uint64_t totals[4] = {0}, services[16][4] = {{0}};
    size_t start = 0;
    for (size_t i = 0; i <= len; i++) {
        if (i != len && data[i] != '\n') continue;
        if (i > start && !record((char *)data + start, i - start, totals, services)) { free(data); return 0; }
        start = i + 1;
    }
    free(data);
    printf("{\"records\":%"PRIu64",\"bytes\":%"PRIu64",\"latency_us\":%"PRIu64",\"errors\":%"PRIu64",\"services\":[", totals[0], totals[1], totals[2], totals[3]);
    for (unsigned i = 0; i < 16; i++) printf("%s[%"PRIu64",%"PRIu64",%"PRIu64",%"PRIu64"]", i ? "," : "", services[i][0], services[i][1], services[i][2], services[i][3]);
    puts("]}"); return fflush(stdout) == 0 && !ferror(stdout);
}
/* files, bytes, lines, matching_lines, matching_files */
static int search_dir(const char *path, uint64_t counts[5]) {
    DIR *dir = opendir(path);
    if (!dir) return 0;
    int ok = 1;
    struct dirent *entry;
    for (;;) {
        errno = 0;
        entry = readdir(dir);
        if (!entry) { if (errno) ok = 0; break; }
        if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, "..")) continue;
        char *child;
        if (asprintf(&child, "%s/%s", path, entry->d_name) < 0) { ok = 0; break; }
        struct stat st;
        if (lstat(child, &st)) ok = 0;
        else if (S_ISDIR(st.st_mode)) ok = search_dir(child, counts);
        else if (S_ISREG(st.st_mode)) {
            size_t namelen = strlen(entry->d_name);
            if (namelen >= 4 && !memcmp(entry->d_name + namelen - 4, ".txt", 4)) {
                size_t len;
                unsigned char *data = read_all(child, &len);
                if (!data) ok = 0;
                else {
                    uint64_t lines = 0, matches = 0;
                    size_t start = 0;
                    for (size_t i = 0; i < len; i++) {
                        if (data[i] != '\n') continue;
                        lines++;
                        if (memmem(data + start, i - start, "ERROR", 5)) matches++;
                        start = i + 1;
                    }
                    if (start < len) { lines++; if (memmem(data + start, len - start, "ERROR", 5)) matches++; }
                    ok = add(&counts[0], 1) && add(&counts[1], len) && add(&counts[2], lines) && add(&counts[3], matches) && add(&counts[4], matches > 0);
                    free(data);
                }
            }
        }
        free(child);
        if (!ok) break;
    }
    if (closedir(dir)) ok = 0;
    return ok;
}
int main(int argc, char **argv) {
    int ok = 0;
    if (argc == 3 && !strcmp(argv[1], "report")) ok = report(argv[2]);
    else if (argc == 3 && !strcmp(argv[1], "search")) {
        uint64_t counts[5] = {0}; struct stat st;
        if (!lstat(argv[2], &st) && S_ISDIR(st.st_mode) && search_dir(argv[2], counts)) {
            printf("{\"files\":%"PRIu64",\"bytes\":%"PRIu64",\"lines\":%"PRIu64",\"matching_lines\":%"PRIu64",\"matching_files\":%"PRIu64"}\n", counts[0], counts[1], counts[2], counts[3], counts[4]);
            ok = fflush(stdout) == 0 && !ferror(stdout);
        }
    }
    if (!ok) { fputs("invalid input or I/O failure\n", stderr); return 1; }
    return 0;
}
