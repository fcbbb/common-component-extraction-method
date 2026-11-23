# l2_opencv_highgui — Migrate the OpenCV highgui backend to Kylin V10 SP3

- **Scenario**: `windows_to_kylin`
- **Level**: `L2`  **Fit**: `B`
- **Task family**: `v3` (`opencv_highgui`, `pattern`)
- **Frozen library**: `v3/windows_to_kylin/library/manifest.json`
- **Source**: https://github.com/opencv/opencv.git @ `71d3237a093b60a27601c20e9ee6c3e52154e8b1`
- **License**: Apache-2.0
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

OpenCV is being moved from Windows to Kylin V10 SP3.  The
target-platform highgui backend has not been written yet.

Reimplement the window backend behind the existing highgui
interface: named windows, image display, key waiting, trackbars,
mouse and keyboard callbacks, window resizing and destruction,
and the window-handle and window-name queries.  The Win32 backend,
the shared headers and the callers stay visible as the reference.

Scope: the GUI backend only; do not change the public API or the
build configuration.  Deliverable: `libopencv_highgui.a`, built
by the repository CMake entry with the platform windowing backend enabled.

Target environment: Kylin V10 SP3, x86_64, GCC 13.3, CMake
3.16.5.

## Workspace

```bash
bash prepare.sh       # materialize work/ (network + git)
cd work
```

The target-platform implementation has been removed.  Keep the public
headers and the Windows source as reference; implement the missing
platform layer and make the hidden tests pass.

## Build

```bash
cmake -S . -B {build} -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DBUILD_LIST=core,imgproc,imgcodecs,highgui,ts -DWITH_GTK=ON -DWITH_QT=OFF -DBUILD_TESTS=ON -DBUILD_PERF_TESTS=OFF -DBUILD_EXAMPLES=OFF -DBUILD_opencv_python3=OFF && cmake --build {build} -j2
```
