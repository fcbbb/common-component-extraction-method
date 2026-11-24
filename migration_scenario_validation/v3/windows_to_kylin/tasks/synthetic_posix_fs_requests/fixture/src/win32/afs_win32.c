/*
 * Windows reference implementation of the request backend.
 *
 * Only compiled when CMake sees WIN32.  It is kept in the snapshot as the
 * reference for the target-platform implementation.
 */
#include "afs_platform.h"

#include <windows.h>
#include <winioctl.h>
#include <fcntl.h>
#include <io.h>
#include <sys/stat.h>

static int win_flags(int flags)
{
    int mode;

    switch (flags & (AFS_OPEN_READ | AFS_OPEN_WRITE)) {
    case AFS_OPEN_READ:
        mode = _O_RDONLY;
        break;
    case AFS_OPEN_WRITE:
        mode = _O_WRONLY;
        break;
    default:
        mode = _O_RDWR;
        break;
    }
    if (flags & AFS_OPEN_CREATE) {
        mode |= _O_CREAT;
    }
    if (flags & AFS_OPEN_EXCL) {
        mode |= _O_EXCL;
    }
    if (flags & AFS_OPEN_TRUNC) {
        mode |= _O_TRUNC;
    }
    return mode | _O_BINARY | _O_NOINHERIT;
}

int afs__open(afs_req *req)
{
    if (req->path == NULL || req->path[0] == '\0') {
        errno = EINVAL;
        return -1;
    }
    return _open(req->path, win_flags(req->flags), _S_IREAD | _S_IWRITE);
}

int afs__close(afs_req *req)
{
    if (req->fd < 0) {
        errno = EINVAL;
        return -1;
    }
    return _close(req->fd);
}

int afs__read(afs_req *req)
{
    __int64 saved = -1;
    long total = 0;
    unsigned i;

    if (req->fd < 0) {
        errno = EINVAL;
        return -1;
    }
    if (req->offset >= 0) {
        saved = _lseeki64(req->fd, 0, SEEK_CUR);
        if (_lseeki64(req->fd, req->offset, SEEK_SET) < 0) {
            return -1;
        }
    }
    for (i = 0; i < req->niov; i++) {
        int got = _read(req->fd, req->iov[i].iov_base,
                        (unsigned)req->iov[i].iov_len);
        if (got < 0) {
            total = -1;
            break;
        }
        total += got;
        if ((size_t)got < req->iov[i].iov_len) {
            break;
        }
    }
    if (saved >= 0) {
        _lseeki64(req->fd, saved, SEEK_SET);
    }
    return (int)total;
}

int afs__write(afs_req *req)
{
    __int64 saved = -1;
    long total = 0;
    unsigned i;

    if (req->fd < 0) {
        errno = EINVAL;
        return -1;
    }
    if (req->offset >= 0) {
        saved = _lseeki64(req->fd, 0, SEEK_CUR);
        if (_lseeki64(req->fd, req->offset, SEEK_SET) < 0) {
            return -1;
        }
    }
    for (i = 0; i < req->niov; i++) {
        int put = _write(req->fd, req->iov[i].iov_base,
                         (unsigned)req->iov[i].iov_len);
        if (put < 0) {
            total = -1;
            break;
        }
        total += put;
    }
    if (saved >= 0) {
        _lseeki64(req->fd, saved, SEEK_SET);
    }
    return (int)total;
}

int afs__stat(afs_req *req)
{
    struct _stat64 info;

    if (req->path == NULL || req->out_stat == NULL) {
        errno = EINVAL;
        return -1;
    }
    if (_stat64(req->path, &info) != 0) {
        return -1;
    }
    req->out_stat->st_mode = info.st_mode;
    req->out_stat->st_size = (off_t)info.st_size;
    req->out_stat->st_uid = info.st_uid;
    req->out_stat->st_gid = info.st_gid;
    return 0;
}

int afs__readlink(afs_req *req)
{
    HANDLE handle;
    REPARSE_DATA_BUFFER *buffer;
    DWORD returned = 0;
    wchar_t wide[MAX_PATH + 1];
    size_t length;
    int converted;

    if (req->path == NULL || req->out_buf == NULL || req->out_cap == 0) {
        errno = EINVAL;
        return -1;
    }
    length = strlen(req->path);
    if (length > MAX_PATH) {
        errno = ENAMETOOLONG;
        return -1;
    }
    mbstowcs(wide, req->path, MAX_PATH + 1);
    handle = CreateFileW(wide, 0, FILE_SHARE_READ | FILE_SHARE_WRITE,
                         NULL, OPEN_EXISTING,
                         FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_BACKUP_SEMANTICS,
                         NULL);
    if (handle == INVALID_HANDLE_VALUE) {
        errno = ENOENT;
        return -1;
    }
    if (!(GetFileAttributesW(wide) & FILE_ATTRIBUTE_REPARSE_POINT)) {
        CloseHandle(handle);
        errno = EINVAL;
        return -1;
    }
    buffer = (REPARSE_DATA_BUFFER *)malloc(MAXIMUM_REPARSE_DATA_BUFFER_SIZE);
    if (!buffer) {
        CloseHandle(handle);
        errno = ENOMEM;
        return -1;
    }
    if (!DeviceIoControl(handle, FSCTL_GET_REPARSE_POINT, NULL, 0,
                         buffer, MAXIMUM_REPARSE_DATA_BUFFER_SIZE,
                         &returned, NULL)) {
        free(buffer);
        CloseHandle(handle);
        errno = EIO;
        return -1;
    }
    converted = WideCharToMultiByte(CP_UTF8, 0,
                                    buffer->SymbolicLinkReparseBuffer.PathBuffer,
                                    buffer->SymbolicLinkReparseBuffer.PrintNameLength / 2,
                                    req->out_buf, (int)req->out_cap, NULL, NULL);
    free(buffer);
    CloseHandle(handle);
    if (converted < 0) {
        errno = EINVAL;
        return -1;
    }
    return converted;
}

int afs__temp(afs_req *req)
{
    char directory[MAX_PATH + 1];
    char name[MAX_PATH + 1];
    DWORD length;
    int fd;

    if (req->path == NULL) {
        errno = EINVAL;
        return -1;
    }
    length = GetTempPathA(MAX_PATH, directory);
    if (length == 0 || length > MAX_PATH) {
        errno = EINVAL;
        return -1;
    }
    if (GetTempFileNameA(directory, "afs", 0, name) == 0) {
        errno = EIO;
        return -1;
    }
    req->out_path = _strdup(name);
    if (!req->out_path) {
        errno = ENOMEM;
        return -1;
    }
    fd = _open(name, _O_RDWR | _O_BINARY | _O_NOINHERIT);
    if (fd < 0) {
        free(req->out_path);
        req->out_path = NULL;
        return -1;
    }
    return fd;
}