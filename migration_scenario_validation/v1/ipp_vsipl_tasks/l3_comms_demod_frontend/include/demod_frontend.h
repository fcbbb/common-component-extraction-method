/* Comms demodulator frontend: NCO mixer, decimating complex FIR, block
 * statistics.
 *
 * The component is streaming: dem_process() may be called with any block size
 * and the NCO phase and the FIR history carry over between calls, so the
 * concatenation of the outputs does not depend on how the input was split.
 *
 * All arrays are split into real and imaginary planes (no interleaving).
 */
#ifndef DEMOD_FRONTEND_H
#define DEMOD_FRONTEND_H

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    int nco_len;   /* number of entries in the NCO table, > 0 */
    int decim;     /* decimation factor M, > 0 */
    int ntaps;     /* FIR taps per decimation phase, > 0;
                      the total filter length is decim * ntaps */
} dem_config;

typedef struct dem_state dem_state;

/* Creates the frontend.  nco_re/nco_im hold nco_len entries; taps_re/taps_im
 * hold decim*ntaps entries, indexed by the filter tap t = 0 .. T-1 with
 * T = decim*ntaps.  Every array is copied.  Returns NULL on a bad
 * configuration or an allocation failure. */
dem_state *dem_create(const dem_config *cfg,
                      const float *nco_re, const float *nco_im,
                      const float *taps_re, const float *taps_im);

void dem_destroy(dem_state *st);

/* Processes nin complex samples and writes the decimated baseband samples to
 * out_re/out_im.  Returns the number of complex samples written, which is the
 * number of decimation instants that have become complete with this call
 * (0 is a normal result for a short block).  out_* must have room for
 * floor(nin / decim) + 1 samples.
 *
 * Baseband sample j is produced when all of its taps are available:
 *     y[j] = sum_{t=0}^{T-1} h[t] * x[j*M - t]      (x is the mixed signal)
 * for j*M >= T-1 and j*M < (samples consumed so far). */
int dem_process(dem_state *st,
                const float *in_re, const float *in_im, int nin,
                float *out_re, float *out_im);

/* Block statistics over n complex samples: |x| into mag (may be NULL), the
 * mean power sum(|x|^2)/n, the peak magnitude and the index of the first
 * sample that reaches it.  All output pointers are optional except that mag
 * and the scalars are independent. */
void dem_stats(const float *re, const float *im, int n,
               float *mag, float *mean_power, float *peak, int *peak_index);

#ifdef __cplusplus
}
#endif

#endif /* DEMOD_FRONTEND_H */