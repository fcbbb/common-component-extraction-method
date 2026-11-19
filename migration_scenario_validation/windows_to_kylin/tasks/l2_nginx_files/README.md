# l2_nginx_files — nginx file layer: Win32 file API -> POSIX file API

- **Scenario**: `windows_to_kylin`
- **Level**: `L2`
- **Source**: https://github.com/nginx/nginx.git @ `1be0fb0c9f9bc3489c7b40576efd6afe6b2eccd5`
- **License**: BSD-2-Clause
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

`src/os/unix/ngx_files.c` was removed while the Win32 file layer and
`src/os/unix/ngx_files.h` stay visible.  Reimplement the file primitives used by the whole server, including
timestamps, directory iteration, path canonicalisation and the ngx_errno mapping.

## Workspace

`work/` is materialized by `prepare.sh`. The evaluator-only gold and hidden fixtures are not part of `work/`.
