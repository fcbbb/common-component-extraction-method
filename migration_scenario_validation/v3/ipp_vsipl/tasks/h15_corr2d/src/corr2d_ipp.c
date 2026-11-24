#include "corr2d.h"
#include <ipp.h>
int corr2d(const float *x_re, const float *x_im, int rows, int cols,
           const float *ref_re, const float *ref_im,
           float *out_re, float *out_im)
{
    int kr, kc;
    if (!x_re || !x_im || !ref_re || !ref_im || !out_re || !out_im ||
        rows < 1 || cols < 1) return -1;
    for (kr = -(rows - 1); kr <= rows - 1; ++kr) {
        for (kc = -(cols - 1); kc <= cols - 1; ++kc) {
            float dot = 0.0f, cross = 0.0f, sr = 0.0f, si = 0.0f;
            int i, j, orow = kr + rows - 1, ocol = kc + cols - 1;
            for (i = 0; i < rows; ++i) {
                for (j = 0; j < cols; ++j) {
                    int qr = i - kr, qc = j - kc;
                    if (qr < 0 || qr >= rows || qc < 0 || qc >= cols) continue;
                    /* IPP dot products over the same 2D offset are expressed
                     * as one-dimensional gathers into temporary rows. */
                    ippsDotProd_32f(x_re + i * cols + j,
                                    ref_re + qr * cols + qc, 1, &dot);
                    ippsDotProd_32f(x_im + i * cols + j,
                                    ref_im + qr * cols + qc, 1, &cross);
                    sr += dot + cross;
                    ippsDotProd_32f(x_im + i * cols + j,
                                    ref_re + qr * cols + qc, 1, &dot);
                    ippsDotProd_32f(x_re + i * cols + j,
                                    ref_im + qr * cols + qc, 1, &cross);
                    si += dot - cross;
                }
            }
            out_re[orow * (2 * cols - 1) + ocol] = sr;
            out_im[orow * (2 * cols - 1) + ocol] = si;
        }
    }
    return 0;
}
