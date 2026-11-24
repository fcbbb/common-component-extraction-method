/*
 * Windows reference implementation of the platform layer.
 *
 * Only compiled when CMake sees WIN32.  Kept in the snapshot as the
 * reference for the target-platform implementation.
 */
#include "mc_platform.h"

#include <windows.h>

static HANDLE to_win(mc_handle_t handle)
{
    return (HANDLE)(intptr_t)handle;
}

mc_handle_t mc_open(const char *path, int write_mode)
{
    DWORD access = write_mode ? GENERIC_WRITE : GENERIC_READ;
    DWORD share = FILE_SHARE_READ;
    DWORD create = write_mode ? CREATE_ALWAYS : OPEN_EXISTING;
    HANDLE h = CreateFileA(path, access, share, NULL, create,
                           FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) {
        return MC_INVALID_HANDLE;
    }
    return (mc_handle_t)(intptr_t)h;
}

long mc_read(mc_handle_t handle, void *buf, size_t count)
{
    DWORD got = 0;
    if (!ReadFile(to_win(handle), buf, (DWORD)count, &got, NULL)) {
        return -1;
    }
    return (long)got;
}

long mc_write(mc_handle_t handle, const void *buf, size_t count)
{
    DWORD put = 0;
    if (!WriteFile(to_win(handle), buf, (DWORD)count, &put, NULL)) {
        return -1;
    }
    return (long)put;
}

long mc_seek(mc_handle_t handle, long offset, int whence)
{
    DWORD method = (whence == MC_SEEK_CUR) ? FILE_CURRENT
                 : (whence == MC_SEEK_END) ? FILE_END : FILE_BEGIN;
    DWORD pos = SetFilePointer(to_win(handle), offset, NULL, method);
    if (pos == INVALID_SET_FILE_POINTER && GetLastError() != NO_ERROR) {
        return -1;
    }
    return (long)pos;
}

long mc_size(mc_handle_t handle)
{
    DWORD size = GetFileSize(to_win(handle), NULL);
    if (size == INVALID_FILE_SIZE && GetLastError() != NO_ERROR) {
        return -1;
    }
    return (long)size;
}

int mc_close(mc_handle_t handle)
{
    return CloseHandle(to_win(handle)) ? 0 : -1;
}