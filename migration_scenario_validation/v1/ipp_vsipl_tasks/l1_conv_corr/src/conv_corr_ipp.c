/* 1-D convolution / correlation, Intel IPP backend (migration source).
 *
 * Three IPP 2021 details are part of the observable behaviour:
 *
 *   - ippsConvolve_32f is a full convolution: the destination has
 *     src1Len + src2Len - 1 samples.  The SAME region is therefore taken from
 *     the full result rather than computed by the library.
 *
 *   - ippsCrossCorrNorm_32f indexes its output by lag = lowLag + i and
 *     evaluates  sum(k) src1[k] * src2[k + lag]  -- the *first* argument is the
 *     one that stays in place.  The contract of dsp_correlate is the mirror
 *     image,  sum(j) h[j] * x[j + lag],  so h goes in as src1 and x as src2 and
 *     lowLag = -(nh-1) yields y[0] at lag -(nh-1) directly.
 *
 *   - IPP has no biased/unbiased switch.  The biased result comes straight out
 *     of the library; the unbiased result is divided here by the exact number
 *     of overlapping samples.
 *
 * Neither IPP call takes a stride, so the strided entry point gathers its
 * input first.
 */
#include "conv_corr.h"

#include <ipp.h>

#include <stdlib.h>

/* Full convolution of h (nh) and x (nx) into dst (nh+nx-1). */
static int conv_full_ipp(const float *h, int nh, const float *x, int nx, float *dst)
{
    int bufsize = 0;
    Ipp8u *buf;
    IppStatus st;

    if (ippsConvolveGetBufferSize(nx, nh, ipp32f, ippAlgAuto, &bufsize) != ippStsNoErr)
        return -1;
    buf = ippsMalloc_8u(bufsize > 0 ? bufsize : 1);
    if (!buf) return -1;

    st = ippsConvolve_32f(x, nx, h, nh, dst, ippAlgAuto, buf);
    ippsFree(buf);
    return (st == ippStsNoErr) ? 0 : -1;
}

static int convolve_impl(const float *h, int nh, const float *x, int nx,
                         dsp_region region, float *y)
{
    int nyfull = nh + nx - 1;
    int i;

    if (region == DSP_REGION_SAME) {
        float *full = (float *)malloc(sizeof(float) * (size_t)nyfull);
        if (!full) return -1;
        if (conv_full_ipp(h, nh, x, nx, full) != 0) { free(full); return -1; }
        for (i = 0; i < nx; ++i) y[i] = full[i + nh / 2];
        free(full);
        return 0;
    }
    return conv_full_ipp(h, nh, x, nx, y);
}

int dsp_convolve(const float *h, int nh, const float *x, int nx,
                 dsp_region region, float *y)
{
    if (!h || !x || !y || nh < 1 || nx < 1) return -1;
    if (region != DSP_REGION_FULL && region != DSP_REGION_SAME) return -1;
    return convolve_impl(h, nh, x, nx, region, y);
}

int dsp_convolve_strided(const float *h, int nh, const float *x,
                         int xstride, int offset, int nx,
                         dsp_region region, float *y)
{
    float *gathered;
    int i, rc;

    if (!h || !x || !y || nh < 1 || nx < 1 || xstride < 1 || offset < 0) return -1;
    if (region != DSP_REGION_FULL && region != DSP_REGION_SAME) return -1;

    gathered = (float *)malloc(sizeof(float) * (size_t)nx);
    if (!gathered) return -1;
    for (i = 0; i < nx; ++i) gathered[i] = x[offset + (size_t)i * (size_t)xstride];

    rc = convolve_impl(h, nh, gathered, nx, region, y);
    free(gathered);
    return rc;
}

int dsp_correlate(const float *h, int nh, const float *x, int nx,
                  dsp_corr_bias bias, float *y)
{
    int ny = nh + nx - 1;
    int bufsize = 0;
    Ipp8u *buf;
    IppStatus st;
    int i;

    if (!h || !x || !y || nh < 1 || nx < 1) return -1;
    if (bias != DSP_CORR_BIASED && bias != DSP_CORR_UNBIASED) return -1;

    if (ippsCrossCorrNormGetBufferSize(nh, nx, ny, -(nh - 1), ipp32f,
                                       ippAlgAuto, &bufsize) != ippStsNoErr)
        return -1;
    buf = ippsMalloc_8u(bufsize > 0 ? bufsize : 1);
    if (!buf) return -1;
    st = ippsCrossCorrNorm_32f(h, nh, x, nx, y, ny, -(nh - 1), ippAlgAuto, buf);
    ippsFree(buf);
    if (st != ippStsNoErr) return -1;

    if (bias == DSP_CORR_UNBIASED) {
        for (i = 0; i < ny; ++i) {
            int lag = i - (nh - 1);
            int j0 = (lag < 0) ? -lag : 0;
            int j1 = (nx - lag < nh) ? (nx - lag) : nh;
            int count = j1 - j0;
            if (count > 0) y[i] /= (float)count;
            else           y[i] = 0.0f;
        }
    }
    return 0;
}