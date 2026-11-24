#include "mc_platform.h"
#include "mc_util.h"

#include <stdio.h>

int main(int argc, char **argv)
{
    mc_handle_t in;
    mc_handle_t out;
    char buf[4096];
    long got;
    long put;

    if (argc != 3) {
        mc_die("mccopy", "usage: mccopy <source> <destination>");
    }
    in = mc_open(argv[1], 0);
    if (in == MC_INVALID_HANDLE) {
        mc_die("mccopy", "cannot open source");
    }
    out = mc_open(argv[2], 1);
    if (out == MC_INVALID_HANDLE) {
        mc_die("mccopy", "cannot open destination");
    }
    while ((got = mc_read(in, buf, sizeof buf)) > 0) {
        put = mc_write(out, buf, (size_t)got);
        if (put != got) {
            mc_die("mccopy", "short write");
        }
    }
    if (got < 0) {
        mc_die("mccopy", "read failed");
    }
    if (mc_close(in) != 0 || mc_close(out) != 0) {
        mc_die("mccopy", "close failed");
    }
    return 0;
}