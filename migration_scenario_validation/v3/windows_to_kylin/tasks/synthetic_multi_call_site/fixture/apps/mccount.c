#include "mc_platform.h"
#include "mc_util.h"

#include <stdio.h>

int main(int argc, char **argv)
{
    mc_handle_t handle;
    long size;

    if (argc != 2) {
        mc_die("mccount", "usage: mccount <path>");
    }
    handle = mc_open(argv[1], 0);
    if (handle == MC_INVALID_HANDLE) {
        mc_die("mccount", "cannot open input");
    }
    size = mc_size(handle);
    if (size < 0) {
        mc_die("mccount", "cannot stat input");
    }
    printf("%ld\n", size);
    if (mc_close(handle) != 0) {
        mc_die("mccount", "close failed");
    }
    return 0;
}