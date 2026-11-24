/* Streaming complex burst acquirer.
 *
 * The state owns a continuous complex stream:
 *
 *   mixed[n] = input[n] * nco[n mod nco_len]
 *   filt[j]  = sum_{t=0}^{M-1} taps[t] * mixed[j*decim - t],  M = decim*ntaps
 *   y[f][k]  = sum_j z_f[j] * conj(ref[j-k])
 *
 * where z_f is the f-th consecutive frame of nref filtered samples.  The
 * first valid filtered sample is the one whose history is complete, i.e.
 * center index M; earlier centers are not emitted.
 *
 * NCO phase, FIR history and the decimated pending frame carry across
 * ba_push calls.  The caller may split the same stream into arbitrary block
 * sizes; the concatenated lag profiles must be identical.
 */
#ifndef BURST_ACQ_H
#define BURST_ACQ_H

#ifdef __cplusplus
extern "C" {
#endif

typedef struct ba_state ba_state;

typedef struct {
    int nco_len;   /* > 0 */
    int decim;     /* > 0 */
    int ntaps;     /* > 0; FIR length is decim*ntaps */
    int nref;      /* correlation frame length, >= 1 */
    int nfft;      /* power of two, >= 2*nref-1 */
} ba_config;

typedef struct {
    float peak;        /* largest |lag| over this call */
    int peak_index;    /* index in this call's concatenated lags */
    float energy;      /* sum |lag|^2 over this call */
    int frames;        /* complete lag profiles written this call */
} ba_report;

ba_state *ba_create(const ba_config *cfg);
void ba_destroy(ba_state *st);

/* Copies all waveform arrays and initializes the FIR history.  It is only
 * valid before any input has been pushed.  Returns 0 or -1. */
int ba_set_waveform(ba_state *st,
                    const float *nco_re, const float *nco_im,
                    const float *taps_re, const float *taps_im,
                    const float *ref_re, const float *ref_im);

/* Appends nin complex samples.  out_re/out_im hold out_cap complete
 * 2*nref-1 lag profiles.  If more than out_cap profiles would be produced,
 * returns -1 without consuming input or writing output.  nout receives the
 * number of profiles written.  rep is optional and aggregates this call.
 */
int ba_push(ba_state *st,
            const float *in_re, const float *in_im, int nin,
            float *out_re, float *out_im, int out_cap,
            int *nout, ba_report *rep);

#ifdef __cplusplus
}
#endif

#endif /* BURST_ACQ_H */