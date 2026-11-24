#include "mc_platform.h"
#include "mc_util.h"

#include <stdio.h>

int main(int argc, char **argv)
{
    mc_handle_t handle;
    long want;
    long size;
    long start;
    char buf[256];
    long got;

    if (argc != 3) {
        mc_die("mctail", "usage: mctail <path> <bytes>");
    }
    want = mc_parse_long(argv[2]);
    if (want < 0) {
        mc_die("mctail", "invalid byte count");
    }
    handle = mc_open(argv[1], 0);
    if (handle == MC_INVALID_HANDLE) {
        mc_die("mctail", "cannot open input");
    }
    size = mc_size(handle);
    if (size < 0) {
        mc_die("mctail", "cannot stat input");
    }
    start = (want < size) ? size - want : 0;
    if (mc_seek(handle, start, MC_SEEK_SET) != start) {
        mc_die("mctail", "seek failed");
    }
    while ((got = mc_read(handle, buf, sizeof buf)) > 0) {
        if (fwrite(buf, 1, (size_t)got, stdout) != (size_t)got) {
            mc_die("mctail", "write to stdout failed");
        }
    }
    if (got < 0) {
        mc_die("mctail", "read failed");
    }
    if (mc_close(handle) != 0) {
        mc_die("mctail", "close failed");
    }
    return 0;
}