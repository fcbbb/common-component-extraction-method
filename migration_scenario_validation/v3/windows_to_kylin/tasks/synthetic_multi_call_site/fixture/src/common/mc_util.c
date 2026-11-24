#include "mc_util.h"

#include <stdlib.h>
#include <string.h>

void mc_die(const char *tool, const char *message)
{
    fprintf(stderr, "%s: %s\n", tool, message);
    exit(1);
}

void mc_copy_string(char *dst, size_t dst_size, const char *src)
{
    if (dst_size == 0) {
        return;
    }
    strncpy(dst, src, dst_size - 1);
    dst[dst_size - 1] = '\0';
}

long mc_parse_long(const char *text)
{
    char *end = NULL;
    long value;

    if (text == NULL || *text == '\0') {
        return -1;
    }
    value = strtol(text, &end, 10);
    if (end == text || *end != '\0' || value < 0) {
        return -1;
    }
    return value;
}