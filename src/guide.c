/* `dyn guide`: the guide pages built into the compiler. */
#include "dyn.h"
#include <stdio.h>
#include <string.h>
#include "guide.inc"

static void print_page(const char *const *page) {
  for (; *page; ++page) fputs(*page, stdout);
}

int dyn_guide(const char *topic, bool brief) {
  size_t count = sizeof(guide_topics) / sizeof(guide_topics[0]);
  if (brief && topic) {
    fprintf(stderr, "error: guide takes --brief or a topic, not both\n");
    return 2;
  }
  if (brief) topic = "brief";
  if (topic) {
    for (size_t i = 0; i < count; ++i)
      if (!strcmp(guide_topics[i].topic, topic)) {
        print_page(guide_topics[i].page);
        return 0;
      }
    fprintf(stderr, "error: no guide topic '%s'; run `dyn guide` for the list\n", topic);
    return 2;
  }
  print_page(guide_topics[0].page);
  puts("\n## More topics\n\nRun `dyn guide TOPIC`:\n");
  for (size_t i = 1; i < count; ++i) printf("- `%s`: %s\n", guide_topics[i].topic, guide_topics[i].summary);
  return 0;
}
