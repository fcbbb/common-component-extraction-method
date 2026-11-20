# l3_nginx_full — nginx full OS layer: whole Win32 port -> Kylin/POSIX

- **Scenario**: `windows_to_kylin`
- **Level**: `L3`
- **Source**: https://github.com/nginx/nginx.git @ `1be0fb0c9f9bc3489c7b40576efd6afe6b2eccd5`
- **License**: BSD-2-Clause
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

This is the whole-server variant: `src/os/unix/` has been removed as a
directory, not one file.  Rebuild nginx's operating-system layer for
Kylin from the Windows implementation and the rest of the tree:
  - process model, daemonisation, signals and master/worker channels;
  - event loop, timers, accept/connect/read/write/sendfile;
  - file, directory, shared memory, atomics, errno and time;
  - configuration-time detection in auto/ must still produce a working
    `objs/nginx`.

## Workspace

`work/` is materialized by `prepare.sh`. The evaluator-only gold and hidden fixtures are not part of `work/`.
