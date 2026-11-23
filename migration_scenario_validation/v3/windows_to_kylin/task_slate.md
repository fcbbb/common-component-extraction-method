# Task slate: windows_to_kylin

| # | Task ID | Level | Fit | Counted | Source kind | Task | Upstream |
|---:|---|---|---|---|---|---|---|
| 1 | `l2_libuv_fs` | L2 | B | no | upstream_platform_port | Migrate the libuv file-system layer to Kylin V10 SP3 | https://github.com/libuv/libuv.git @ `e9f29cb98423` |
| 2 | `l2_libuv_process` | L2 | B | no | upstream_platform_port | Migrate the libuv process layer to Kylin V10 SP3 | https://github.com/libuv/libuv.git @ `e9f29cb98423` |
| 3 | `l2_libuv_thread` | L2 | B | no | upstream_platform_port | Migrate the libuv thread layer to Kylin V10 SP3 | https://github.com/libuv/libuv.git @ `e9f29cb98423` |
| 4 | `l2_libarchive_read_disk` | L2 | B | no | upstream_platform_port | Migrate the libarchive disk reader to Kylin V10 SP3 | https://github.com/libarchive/libarchive.git @ `313aa1fa10b6` |
| 5 | `l2_libarchive_write_disk` | L2 | B | no | upstream_platform_port | Migrate the libarchive disk writer to Kylin V10 SP3 | https://github.com/libarchive/libarchive.git @ `313aa1fa10b6` |
| 6 | `v2_libgit2_util_full` | L3 | B | no | upstream_platform_port | Migrate the complete libgit2 utility layer to Kylin V10 SP3 | https://github.com/libgit2/libgit2.git @ `36f7e21ad757` |
| 7 | `v2_file` | L2 | B | yes | library_family_port | Migrate the Foundation file subsystem to Kylin V10 SP3 | https://github.com/pocoproject/poco.git @ `d6bd48a94c5f` |
| 8 | `v2_path` | L2 | B | yes | library_family_port | Migrate the Foundation path subsystem to Kylin V10 SP3 | https://github.com/pocoproject/poco.git @ `d6bd48a94c5f` |
| 9 | `v2_thread` | L2 | B | yes | library_family_port | Migrate the Foundation thread subsystem to Kylin V10 SP3 | https://github.com/pocoproject/poco.git @ `d6bd48a94c5f` |
| 10 | `v2_rwlock_semaphore` | L2 | B | yes | library_family_port | Migrate the Foundation rwlock and semaphore primitives to Kylin V10 SP3 | https://github.com/pocoproject/poco.git @ `d6bd48a94c5f` |
| 11 | `v2_shared_library` | L2 | B | no | library_family_port | Migrate the Foundation dynamic loading subsystem to Kylin V10 SP3 | https://github.com/pocoproject/poco.git @ `d6bd48a94c5f` |
| 12 | `v2_foundation_full` | L3 | B | yes | library_family_port | Migrate the Foundation platform layer to Kylin V10 SP3 | https://github.com/pocoproject/poco.git @ `d6bd48a94c5f` |
| 13 | `v2_poco_process` | L2 | B | yes | library_family_port | Migrate the Foundation process subsystem to Kylin V10 SP3 | https://github.com/pocoproject/poco.git @ `d6bd48a94c5f` |
| 14 | `negative_win32_eventlog` | L3 | C | no | upstream_platform_port | Negative control: Windows Event Log channel has no equivalent | https://github.com/pocoproject/poco.git @ `d6bd48a94c5f` |
| 15 | `v2_nginx_files` | L2 | B | yes | upstream_platform_port | Migrate the nginx file layer to Kylin V10 SP3 | https://github.com/nginx/nginx.git @ `1be0fb0c9f9b` |
| 16 | `v2_nginx_full` | L3 | B | yes | upstream_platform_port | Migrate the complete nginx OS layer to Kylin V10 SP3 | https://github.com/nginx/nginx.git @ `1be0fb0c9f9b` |
| 17 | `v2_nginx_process` | L2 | B | yes | upstream_platform_port | Migrate the nginx process layer to Kylin V10 SP3 | https://github.com/nginx/nginx.git @ `1be0fb0c9f9b` |
| 18 | `v2_nginx_thread` | L2 | B | yes | upstream_platform_port | Migrate the nginx thread pool to Kylin V10 SP3 | https://github.com/nginx/nginx.git @ `1be0fb0c9f9b` |
| 19 | `v2_curl_build` | L3 | B | yes | build_system_port | Migrate the curl build system to CMake on Kylin V10 SP3 | https://github.com/curl/curl.git @ `7161cb17c01d` |
| 20 | `v2_curl_tls` | L2 | B | no | upstream_platform_port | Migrate the curl TLS backend to Kylin V10 SP3 | https://github.com/curl/curl.git @ `7161cb17c01d` |
| 21 | `v2_curl_thread` | L2 | B | yes | upstream_platform_port | Migrate the curl threaded resolver to Kylin V10 SP3 | https://github.com/curl/curl.git @ `7161cb17c01d` |
| 22 | `v2_curl_file` | L2 | B | yes | upstream_platform_port | Migrate the curl file protocol layer to Kylin V10 SP3 | https://github.com/curl/curl.git @ `7161cb17c01d` |
| 23 | `l2_opencv_highgui` | L2 | B | no | upstream_platform_port | Migrate the OpenCV highgui backend to Kylin V10 SP3 | https://github.com/opencv/opencv.git @ `71d3237a093b` |
| 24 | `synthetic_multi_call_site` | L3 | B | no | synthetic | Synthetic multi-call-site consistency migration | synthetic://windows-to-posix/multi-call-site @ `n/a` |

Core tasks: **13**; total packages: **24**.

