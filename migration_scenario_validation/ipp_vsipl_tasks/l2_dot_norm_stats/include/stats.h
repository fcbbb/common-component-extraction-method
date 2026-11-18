/* Public API: one-pass summary statistics over a window of a stream.
 *
 * The window is described by an offset and a stride so that callers can take
 * decimated slices out of interleaved buffers without copying them.  IPP has
 * no strided vector primitives, VSIPL does (vsip_vbind_f).
 */
#ifndef DSP_STATS_H
#define DSP_STATS_H

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    float dot;      /* sum_i a[i] * b[i]                       */
    float norm;     /* sqrt(sum_i a[i]^2)                      */
    float mean;     /* mean of a                               */
    float stddev;   /* sample standard deviation of a (n-1)    */
    float vmax;     /* largest sample of a                     */
    float vmin;     /* smallest sample of a                    */
} dsp_summary;

/* Contiguous window: a[0..n), b[0..n).  Equivalent to the strided form with
 * astride = bstride = 1 and offset = 0. */
int dsp_summary_compute(const float *a, const float *b, int n, dsp_summary *out);

/* Strided window: sample i is a[offset + i*astride], b[offset + i*bstride].
 *
 * astride/bstride must be >= 1 and offset >= 0; both buffers must be large
 * enough to cover offset + (n-1)*stride.  Returns 0 on success, -1 on any
 * invalid argument (NULL pointer, n < 1, stride < 1, offset < 0). */
int dsp_summary_compute_strided(const float *a, int astride,
                                const float *b, int bstride,
                                int offset, int n, dsp_summary *out);

#ifdef __cplusplus
}
#endif

#endif /* DSP_STATS_H */