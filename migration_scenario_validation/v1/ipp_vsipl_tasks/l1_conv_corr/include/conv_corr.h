/* 1-D convolution and normalized cross-correlation.
 *
 * Sign conventions and index ranges are part of the contract; both are easy to
 * get backwards when a library numbers its lags differently.
 */
#ifndef CONV_CORR_H
#define CONV_CORR_H

/* Which part of the full convolution to return. */
typedef enum {
    DSP_REGION_FULL = 0,   /* nh + nx - 1 samples                       */
    DSP_REGION_SAME = 1    /* nx samples, starting at full[nh/2]        */
} dsp_region;

/* Normalisation for the correlation. */
typedef enum {
    DSP_CORR_BIASED   = 0, /* raw overlap sum                           */
    DSP_CORR_UNBIASED = 1  /* divided by the number of overlapping pairs */
} dsp_corr_bias;

/*
 * dsp_convolve
 *     full[i] = sum(j = 0..nh-1) h[j] * x[i-j],     i = 0 .. nh+nx-2
 *     DSP_REGION_FULL writes full[0 .. nh+nx-2] into y.
 *     DSP_REGION_SAME writes full[i + nh/2] for i = 0 .. nx-1 into y
 *     (integer division; for an odd kernel this is the usual centre tap).
 *
 * dsp_convolve_strided
 *     Same output as dsp_convolve, but the input is read as
 *         x[k] == xbuf[offset + k*xstride],  k = 0 .. nx-1.
 *
 * dsp_correlate
 *     y[i] = sum(j = 0..nh-1) h[j] * x[j + i - (nh-1)],  i = 0 .. nh+nx-2
 *     That is, y[0] is lag -(nh-1) and y[nh+nx-2] is lag nx-1.
 *     DSP_CORR_BIASED leaves the sum as is; DSP_CORR_UNBIASED divides it by
 *     the overlap count, i.e. by the number of j in [0, nh) for which
 *     j+i-(nh-1) is in [0, nx).  The kernel may be longer than the data.
 *
 * All three return 0 on success and -1 on invalid arguments: a NULL buffer,
 * nh < 1, nx < 1, xstride < 1, offset < 0, or an unknown enumerator.
 */
int dsp_convolve(const float *h, int nh, const float *x, int nx,
                 dsp_region region, float *y);

int dsp_convolve_strided(const float *h, int nh, const float *x,
                         int xstride, int offset, int nx,
                         dsp_region region, float *y);

int dsp_correlate(const float *h, int nh, const float *x, int nx,
                  dsp_corr_bias bias, float *y);

#endif /* CONV_CORR_H */