/* Passive-sonar lag-profile correlation.
 *
 * A complex baseband reference is correlated against one complex input frame.
 * The public contract uses split real/imaginary planes and a lag-ordered
 * output:
 *
 *     y[k] = sum_j x[j] * conj(ref[j - k])
 *
 * for k = -(nref-1) .. (nref-1).  Out-of-range reference samples are zero.
 * out[i] stores y[i-(nref-1)], so i = 0 is the most negative lag and
 * i = 2*nref-2 is the most positive lag.
 *
 * The reference FFT length is caller-selected.  It must be a power of two and
 * at least 2*nref-1, so that the linear correlation does not fold.
 */
#ifndef SONAR_LAG_H
#define SONAR_LAG_H

#ifdef __cplusplus
extern "C" {
#endif

typedef struct sl_state sl_state;

typedef struct {
    int nfft;   /* power of two, >= 2*nref - 1 */
    int nref;   /* reference length, >= 1 */
} sl_config;

typedef struct {
    float peak;        /* largest |y[i]| */
    int peak_index;    /* output index of the first peak */
    float energy;      /* sum |y[i]|^2 over the 2*nref-1 lags */
} sl_report;

/* Returns NULL for an invalid configuration or allocation failure. */
sl_state *sl_create(const sl_config *cfg);

void sl_destroy(sl_state *st);

/* Copies the reference and precomputes its spectrum.  The caller may reuse or
 * free re/im immediately after this call.  Returns 0, or -1 on bad arguments.
 */
int sl_set_reference(sl_state *st, const float *re, const float *im);

/* Correlates one input frame of st->nref complex samples.  out_re/out_im must
 * have room for 2*nref-1 complex lags.  rep may be NULL.  Returns 0 or -1. */
int sl_process(sl_state *st,
               const float *in_re, const float *in_im,
               float *out_re, float *out_im, sl_report *rep);

#ifdef __cplusplus
}
#endif

#endif /* SONAR_LAG_H */