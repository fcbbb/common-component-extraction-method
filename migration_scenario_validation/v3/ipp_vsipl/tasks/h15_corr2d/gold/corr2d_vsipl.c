#include "corr2d.h"
int corr2d(const float *x_re, const float *x_im, int rows, int cols,
           const float *ref_re, const float *ref_im,
           float *out_re, float *out_im)
{
    int kr, kc, i, j, orow, ocol;
    if (!x_re || !x_im || !ref_re || !ref_im || !out_re || !out_im ||
        rows < 1 || cols < 1) return -1;
    for (kr = -(rows - 1); kr <= rows - 1; ++kr) {
        for (kc = -(cols - 1); kc <= cols - 1; ++kc) {
            float sr = 0.0f, si = 0.0f;
            for (i = 0; i < rows; ++i) {
                for (j = 0; j < cols; ++j) {
                    const int qr = i - kr, qc = j - kc;
                    float hr, hi;
                    if (qr < 0 || qr >= rows || qc < 0 || qc >= cols) continue;
                    hr = ref_re[qr * cols + qc];
                    hi = ref_im[qr * cols + qc];
                    sr += x_re[i * cols + j] * hr +
                          x_im[i * cols + j] * hi;
                    si += x_im[i * cols + j] * hr -
                          x_re[i * cols + j] * hi;
                }
            }
            orow = kr + rows - 1;
            ocol = kc + cols - 1;
            out_re[orow * (2 * cols - 1) + ocol] = sr;
            out_im[orow * (2 * cols - 1) + ocol] = si;
        }
    }
    return 0;
}
