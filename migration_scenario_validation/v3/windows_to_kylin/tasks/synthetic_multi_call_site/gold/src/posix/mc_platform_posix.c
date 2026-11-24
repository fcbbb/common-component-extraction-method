/*
 * Target-platform (Kylin / POSIX) implementation of the shared I/O layer.
 *
 * The call sites keep the Windows conventions: integer handles with -1 as
 * the invalid sentinel and '\' as the path separator.  This layer adapts
 * those conventions to POSIX file descriptors and absolute paths.
 */
#include "mc_platform.h"

#include <errno.h>
#include <fcntl.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static char *to_posix_path(const char *path)
{
    size_t len = strlen(path);
    char *out = malloc(len + 1);
    size_t i;

    if (out == NULL) {
        return NULL;
    }
    for (i = 0; i < len; i++) {
        out[i] = (path[i] == '\\') ? '/' : path[i];
    }
    out[len] = '\0';
    return out;
}

mc_handle_t mc_open(const char *path, int write_mode)
{
    char *posix_path = to_posix_path(path);
    int flags;
    int fd;

    if (posix_path == NULL) {
        return MC_INVALID_HANDLE;
    }
    flags = write_mode ? (O_WRONLY | O_CREAT | O_TRUNC) : O_RDONLY;
    fd = open(posix_path, flags, 0644);
    free(posix_path);
    if (fd < 0) {
        return MC_INVALID_HANDLE;
    }
    return (mc_handle_t)fd;
}

long mc_read(mc_handle_t handle, void *buf, size_t count)
{
    ssize_t got;

    do {
        got = read((int)handle, buf, count);
    } while (got < 0 && errno == EINTR);
    if (got < 0) {
        return -1;
    }
    return (long)got;
}

long mc_write(mc_handle_t handle, const void *buf, size_t count)
{
    const char *cursor = buf;
    size_t left = count;

    while (left > 0) {
        ssize_t put = write((int)handle, cursor, left);
        if (put < 0) {
            if (errno == EINTR) {
                continue;
            }
            return -1;
        }
        cursor += put;
        left -= (size_t)put;
    }
    return (long)count;
}

long mc_seek(mc_handle_t handle, long offset, int whence)
{
    int posix_whence;
    off_t pos;

    posix_whence = (whence == MC_SEEK_CUR) ? SEEK_CUR
                 : (whence == MC_SEEK_END) ? SEEK_END : SEEK_SET;
    pos = lseek((int)handle, (off_t)offset, posix_whence);
    if (pos < 0) {
        return -1;
    }
    return (long)pos;
}

long mc_size(mc_handle_t handle)
{
    struct stat info;

    if (fstat((int)handle, &info) != 0) {
        return -1;
    }
    return (long)info.st_size;
}

int mc_close(mc_handle_t handle)
{
    return close((int)handle) == 0 ? 0 : -1;
}