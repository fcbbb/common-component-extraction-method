/* Streaming complex lag-profile correlation.
 *
 * A complex baseband reference is correlated against a continuous complex
 * input stream.  The stream is cut into consecutive, non-overlapping frames
 * of exactly nref samples; each complete frame produces the lag-ordered
 * correlation
 *
 *     y[k] = sum_j x[j] * conj(ref[j - k])
 *
 * for k = -(nref-1) .. (nref-1).  out[i] stores y[i-(nref-1)], so i = 0 is
 * the most negative lag and i = 2*nref-2 is the most positive lag.
 * Out-of-range reference samples are zero.
 *
 * Frames that straddle a process call are retained in the state.  Splitting
 * the same stream into different call sizes must not change the concatenated
 * output.  The reference FFT length is caller-selected; it must be a power of
 * two and at least 2*nref-1 so the linear correlation does not fold.
 */
#ifndef STREAM_LAG_H
#define STREAM_LAG_H

#ifdef __cplusplus
extern "C" {
#endif

typedef struct sc_state sc_state;

typedef struct {
    int nfft;   /* power of two, >= 2*nref - 1 */
    int nref;   /* frame/reference length, >= 1 */
} sc_config;

typedef struct {
    float peak;        /* largest |y[i]| over this call */
    int peak_index;    /* index in this call's concatenated output */
    float energy;      /* sum |y[i]|^2 over this call's output */
} sc_report;

/* Returns NULL for an invalid configuration or allocation failure. */
sc_state *sc_create(const sc_config *cfg);

void sc_destroy(sc_state *st);

/* Copies the reference and precomputes its spectrum.  The caller may reuse or
 * free re/im immediately after this call.  It is an error to replace the
 * reference while a partial frame is pending.  Returns 0 or -1. */
int sc_set_reference(sc_state *st, const float *re, const float *im);

/* Appends nin complex samples to the stream and emits one complete
 * 2*nref-1 lag profile for every complete nref-sample frame.  out_re/out_im
 * have room for out_cap complete profiles.  If the call would need more than
 * out_cap profiles it returns -1 without consuming input or writing output.
 * nout receives the number of profiles written.  rep may be NULL; when
 * non-NULL it aggregates all profiles emitted by this call.  Returns 0 or -1.
 */
int sc_process(sc_state *st,
               const float *in_re, const float *in_im, int nin,
               float *out_re, float *out_im, int out_cap,
               int *nout, sc_report *rep);

#ifdef __cplusplus
}
#endif

#endif /* STREAM_LAG_H */