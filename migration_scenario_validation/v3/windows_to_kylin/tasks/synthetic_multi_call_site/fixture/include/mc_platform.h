#ifndef MC_PLATFORM_H
#define MC_PLATFORM_H

#include <stddef.h>

/*
 * Minimal platform I/O layer shared by the four tools.
 *
 * Conventions every call site relies on:
 *   - a handle is a small integer with -1 as the invalid sentinel;
 *   - paths are written with the Windows separator '\';
 *   - read/write return the byte count, 0 at end of file, -1 on error;
 *   - seek returns the new absolute offset, -1 on error;
 *   - size returns the byte size, -1 on error;
 *   - close returns 0 on success, -1 on error.
 */

#ifdef _WIN32
typedef intptr_t mc_handle_t;
#else
typedef int mc_handle_t;
#endif

#define MC_INVALID_HANDLE (-1)

#define MC_SEEK_SET 0
#define MC_SEEK_CUR 1
#define MC_SEEK_END 2

mc_handle_t mc_open(const char *path, int write_mode);
long mc_read(mc_handle_t handle, void *buf, size_t count);
long mc_write(mc_handle_t handle, const void *buf, size_t count);
long mc_seek(mc_handle_t handle, long offset, int whence);
long mc_size(mc_handle_t handle);
int mc_close(mc_handle_t handle);

#endif /* MC_PLATFORM_H */