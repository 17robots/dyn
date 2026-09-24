#include <stdint.h>

#define DYN_LIMIT 64u
#define DYN_NAME "dyn"
#define DYN_SHIFTED (1u << 4)
#define DYN_SQUARE(x) ((x) * (x))

enum DynMode { DYN_MODE_OFF = 0, DYN_MODE_ON = 4 };

struct DynPoint { int32_t x; int32_t y; };
typedef struct { int32_t left; int32_t right; } DynPair;
struct DynNested { struct DynInner { int32_t value; } inner; };
union DynValue { int64_t integer; double real; };
struct DynFlags { unsigned ready : 1; unsigned mode : 3; };
struct DynAnonymous { struct { int32_t value; }; };
int32_t dyn_point_sum(const struct DynPoint *point);
void dyn_value_reset(union DynValue *value);
union DynValue dyn_value_get(void);
double dyn_sum(uint32_t count, ...);
void dyn_visit(int64_t (*callback)(int64_t, void *), void *context);
