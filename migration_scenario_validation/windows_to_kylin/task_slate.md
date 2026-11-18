# Task slate: windows_to_kylin

| # | Task ID | Level | Fit | Counted | Source kind | Task | Upstream |
|---:|---|---|---|---|---|---|---|
| 1 | `l1_poco_thread` | L1 | B | yes | upstream-platform-port | POCO Thread: Win32 threads -> pthreads | https://github.com/pocoproject/poco.git @ `d6bd48a94c5f` |
| 2 | `l1_poco_shared_library` | L1 | B | yes | upstream-platform-port | POCO SharedLibrary: LoadLibrary -> dlopen | https://github.com/pocoproject/poco.git @ `d6bd48a94c5f` |
| 3 | `l1_poco_file` | L1 | B | yes | upstream-platform-port | POCO File: Win32 file handles -> POSIX file descriptors | https://github.com/pocoproject/poco.git @ `d6bd48a94c5f` |
| 4 | `l1_poco_path` | L1 | B | yes | upstream-platform-port | POCO Path: Win32 path rules -> POSIX path rules | https://github.com/pocoproject/poco.git @ `d6bd48a94c5f` |
| 5 | `l1_poco_rwlock_semaphore` | L1 | B | yes | upstream-platform-port | POCO RWLock + Semaphore: Win32 primitives -> pthread primitives | https://github.com/pocoproject/poco.git @ `d6bd48a94c5f` |
| 6 | `l2_libgit2_file` | L2 | B | yes | upstream-platform-port | libgit2 file layer: Win32 mmap/realpath -> POSIX | https://github.com/libgit2/libgit2.git @ `36f7e21ad757` |
| 7 | `l2_libgit2_process` | L2 | B | yes | upstream-platform-port | libgit2 process/thread layer: Win32 process + pthread wrappers | https://github.com/libgit2/libgit2.git @ `36f7e21ad757` |
| 8 | `l2_libarchive_read_disk` | L2 | B | yes | upstream-platform-port | libarchive read_disk: Win32 traversal -> POSIX traversal | https://github.com/libarchive/libarchive.git @ `313aa1fa10b6` |
| 9 | `l2_libarchive_write_disk` | L2 | B | yes | upstream-platform-port | libarchive write_disk: Win32 restore -> POSIX restore | https://github.com/libarchive/libarchive.git @ `313aa1fa10b6` |
| 10 | `l2_curl_tls` | L2 | B | yes | upstream-platform-port | curl TLS backend: Schannel/Win32 -> OpenSSL on Kylin | https://github.com/curl/curl.git @ `7161cb17c01d` |
| 11 | `l2_opencv_highgui` | L2 | B | yes | upstream-platform-port | OpenCV highgui window backend: Win32 -> GTK | https://github.com/opencv/opencv.git @ `71d3237a093b` |
| 12 | `l2_nginx_files` | L2 | B | yes | upstream-platform-port | nginx file layer: Win32 file API -> POSIX file API | https://github.com/nginx/nginx.git @ `1be0fb0c9f9b` |
| 13 | `l2_libuv_fs` | L2 | B | yes | upstream-platform-port | libuv fs: Win32 OVERLAPPED I/O -> POSIX thread pool | https://github.com/libuv/libuv.git @ `e9f29cb98423` |
| 14 | `l2_libuv_process` | L2 | B | yes | upstream-platform-port | libuv process: Win32 CreateProcess -> POSIX fork/exec | https://github.com/libuv/libuv.git @ `e9f29cb98423` |
| 15 | `l2_libuv_thread` | L2 | B | yes | upstream-platform-port | libuv thread layer: Win32 threads -> pthreads | https://github.com/libuv/libuv.git @ `e9f29cb98423` |
| 16 | `l3_nginx_full` | L3 | B | yes | upstream-platform-port | nginx full OS layer: whole Win32 port -> Kylin/POSIX | https://github.com/nginx/nginx.git @ `1be0fb0c9f9b` |
| 17 | `l3_libgit2_full` | L3 | B | yes | upstream-platform-port | libgit2 full POSIX util layer | https://github.com/libgit2/libgit2.git @ `36f7e21ad757` |
| 18 | `l3_poco_foundation_full` | L3 | B | yes | upstream-platform-port | POCO Foundation full POSIX platform layer | https://github.com/pocoproject/poco.git @ `d6bd48a94c5f` |
| 19 | `l3_curl_build` | L3 | B | yes | upstream-platform-port | curl build system: VS projects -> CMake on Kylin | https://github.com/curl/curl.git @ `7161cb17c01d` |
| 20 | `negative_win32_eventlog` | L3 | C | yes | upstream-platform-port | Negative control: Windows Event Log channel has no equivalent | https://github.com/pocoproject/poco.git @ `d6bd48a94c5f` |

Core tasks: **20**; total packages: **20**.

