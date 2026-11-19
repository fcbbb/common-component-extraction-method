# l2_opencv_highgui — OpenCV highgui window backend: Win32 -> GTK

- **Scenario**: `windows_to_kylin`
- **Level**: `L2`
- **Source**: https://github.com/opencv/opencv.git @ `71d3237a093b60a27601c20e9ee6c3e52154e8b1`
- **License**: Apache-2.0
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

The target GUI backend was removed.  Reimplement
`modules/highgui/src/window_gtk.cpp` so that the backend-facing
functions declared in `modules/highgui/src/window.hpp` behave as on
Windows: named windows, imshow, waitKey/waitKeyEx, trackbars, mouse and
keyboard callbacks, window resizing and destruction, and the
`cvGetWindowHandle`/`cvGetWindowName` contract.

## Workspace

`work/` is materialized by `prepare.sh`. The evaluator-only gold and hidden fixtures are not part of `work/`.
