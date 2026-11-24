#ifndef MC_UTIL_H
#define MC_UTIL_H

#include <stddef.h>
#include <stdio.h>

/* Print a prefixed diagnostic and exit with status 1. */
void mc_die(const char *tool, const char *message);

/* Copy at most dst_size-1 bytes of src and NUL-terminate. */
void mc_copy_string(char *dst, size_t dst_size, const char *src);

/* Parse a non-negative decimal argument; returns -1 on malformed input. */
long mc_parse_long(const char *text);

#endif /* MC_UTIL_H */