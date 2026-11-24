#include "mc_platform.h"

#include <stdio.h>
#include <string.h>

#ifdef _WIN32
#include <direct.h>
#define make_dir(path) _mkdir(path)
#else
#include <sys/stat.h>
#define make_dir(path) mkdir(path, 0755)
#endif

#define CHECK(cond, message)                     \
    do {                                         \
        if (!(cond)) {                           \
            fprintf(stderr, "FAIL: %s\n", message); \
            return 1;                            \
        }                                        \
    } while (0)

int main(void)
{
    const char *rel = "sub\\one.txt";
    mc_handle_t handle;
    char buf[8];

    make_dir("sub");

    handle = mc_open(rel, 1);
    CHECK(handle != MC_INVALID_HANDLE, "create backslash path");
    CHECK(mc_write(handle, "abc", 3) == 3, "write three bytes");
    CHECK(mc_close(handle) == 0, "close after write");

    handle = mc_open(rel, 0);
    CHECK(handle != MC_INVALID_HANDLE, "reopen backslash path");
    CHECK(mc_size(handle) == 3, "size is three");
    memset(buf, 0, sizeof buf);
    CHECK(mc_read(handle, buf, sizeof buf) == 3, "read three bytes");
    CHECK(memcmp(buf, "abc", 3) == 0, "content matches");
    CHECK(mc_read(handle, buf, sizeof buf) == 0, "read at eof returns zero");
    CHECK(mc_seek(handle, -1, MC_SEEK_END) == 2, "seek from end");
    CHECK(mc_read(handle, buf, 1) == 1 && buf[0] == 'c', "last byte");
    CHECK(mc_close(handle) == 0, "close after read");

    handle = mc_open(rel, 0);
    CHECK(handle != MC_INVALID_HANDLE, "reopen for relative seek");
    CHECK(mc_seek(handle, 1, MC_SEEK_CUR) == 1, "seek from current");
    CHECK(mc_read(handle, buf, 2) == 2 && memcmp(buf, "bc", 2) == 0, "relative read");
    CHECK(mc_close(handle) == 0, "close after relative seek");

    CHECK(mc_open("sub\\missing.txt", 0) == MC_INVALID_HANDLE, "missing file is invalid");
    CHECK(mc_close(MC_INVALID_HANDLE) == -1, "closing invalid handle fails");

    handle = mc_open("sub\\empty.txt", 1);
    CHECK(handle != MC_INVALID_HANDLE, "create empty file");
    CHECK(mc_size(handle) == 0, "empty file has size zero");
    CHECK(mc_close(handle) == 0, "close empty file");

    remove("sub/one.txt");
    remove("sub/empty.txt");
    puts("platform checks passed");
    return 0;
}