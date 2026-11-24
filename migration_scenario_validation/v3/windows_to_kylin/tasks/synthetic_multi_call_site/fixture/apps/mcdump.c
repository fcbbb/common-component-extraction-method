#include "mc_platform.h"
#include "mc_util.h"

#include <stdio.h>

int main(int argc, char **argv)
{
    mc_handle_t handle;
    char buf[64];
    long got;

    if (argc != 2) {
        mc_die("mcdump", "usage: mcdump <path>");
    }
    handle = mc_open(argv[1], 0);
    if (handle == MC_INVALID_HANDLE) {
        mc_die("mcdump", "cannot open input");
    }
    while ((got = mc_read(handle, buf, sizeof buf)) > 0) {
        if (fwrite(buf, 1, (size_t)got, stdout) != (size_t)got) {
            mc_die("mcdump", "write to stdout failed");
        }
    }
    if (got < 0) {
        mc_die("mcdump", "read failed");
    }
    if (mc_close(handle) != 0) {
        mc_die("mcdump", "close failed");
    }
    return 0;
}