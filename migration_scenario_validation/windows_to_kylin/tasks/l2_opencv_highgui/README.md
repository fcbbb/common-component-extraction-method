# l2_opencv_highgui — OpenCV highgui window backend: Win32 -> GTK

- **Scenario**: `windows_to_kylin`
- **Level**: `L2`  **Fit**: `B`
- **Source**: https://github.com/opencv/opencv.git @ `71d3237a093b60a27601c20e9ee6c3e52154e8b1`
- **License**: Apache-2.0
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

The GTK window backend was removed.  Reimplement
`modules/highgui/src/window_gtk.cpp` so that the backend-facing
functions declared in `modules/highgui/src/window.hpp` behave as on
Windows: named windows, imshow, waitKey/waitKeyEx, trackbars, mouse and
keyboard callbacks, window resizing and destruction, and the
`cvGetWindowHandle`/`cvGetWindowName` contract.

The hidden test runs the upstream highgui test binary under Xvfb with
GTK, so no physical display is required.

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
cmake -S . -B {build} -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DBUILD_LIST=core,imgproc,imgcodecs,highgui,ts -DWITH_GTK=ON -DWITH_QT=OFF -DBUILD_TESTS=ON -DBUILD_PERF_TESTS=OFF -DBUILD_EXAMPLES=OFF -DBUILD_opencv_python3=OFF && cmake --build {build} -j4
```

## Hidden tests

```bash
cd {build} && timeout 900 xvfb-run -a ./bin/opencv_test_highgui --gtest_filter=Highgui_GUI.*
```

## Gold

Gold kind: `implementation`.  The reference files are listed in `provenance.json` and are **not** part of the agent-visible `work/` tree.
