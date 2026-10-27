// Force a real asynchronous GLX context-version failure through the driver.
#define _GNU_SOURCE
#include <GL/glx.h>
#include <GL/glxext.h>
#include <dlfcn.h>
#include <string.h>
typedef __GLXextFuncPtr (*Resolve)(const GLubyte *);
static GLXContext failing_context(Display *display, GLXFBConfig config,
                                  GLXContext share, Bool direct,
                                  const int *attributes) {
  (void)attributes;
  Resolve resolve = (Resolve)dlsym(RTLD_NEXT, "glXGetProcAddressARB");
  PFNGLXCREATECONTEXTATTRIBSARBPROC create =
      (PFNGLXCREATECONTEXTATTRIBSARBPROC)resolve(
          (const GLubyte *)"glXCreateContextAttribsARB");
  const int invalid[] = {GLX_CONTEXT_MAJOR_VERSION_ARB, 99,
                         GLX_CONTEXT_MINOR_VERSION_ARB, 0, None};
  return create(display, config, share, direct, invalid);
}
__GLXextFuncPtr glXGetProcAddressARB(const GLubyte *name) {
  Resolve resolve = (Resolve)dlsym(RTLD_NEXT, "glXGetProcAddressARB");
  if (!strcmp((const char *)name, "glXCreateContextAttribsARB"))
    return (__GLXextFuncPtr)failing_context;
  return resolve(name);
}
