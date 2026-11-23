/* Wideband complex channelizer.
 *
 * A complex NCO mixes the input stream, then a decimating complex FIR
 * produces one output every `decim` mixed samples:
 *
 *   m[n] = x[n] * nco[n mod nco_len]
 *   y[j] = sum_{t=0}^{T-1} h[t] * m[j*decim - t],  T = decim*ntaps
 *
 * The state is streaming: NCO phase, FIR history and the next output index
 * carry over between wc_process calls, so splitting the same input into
 * different block sizes must not change the concatenated output.
 *
 * All complex arrays are split into real and imaginary planes.
 */
#ifndef CHANNELIZER_H
#define CHANNELIZER_H

#ifdef __cplusplus
extern "C" {
#endif

typedef struct wc_state wc_state;

typedef struct {
    int nco_len;  /* > 0 */
    int decim;    /* > 0 */
    int ntaps;    /* > 0; total filter length is decim*ntaps */
} wc_config;

typedef struct {
    float mean_power;
    float peak;
    int peak_index;
} wc_report;

wc_state *wc_create(const wc_config *cfg,
                    const float *nco_re, const float *nco_im,
                    const float *taps_re, const float *taps_im);
void wc_destroy(wc_state *st);

/* Processes nin complex samples.  out_re/out_im must hold at least
 * floor(nin / decim) + 1 complex samples.  Returns produced count, or -1 on
 * bad arguments. */
int wc_process(wc_state *st,
               const float *in_re, const float *in_im, int nin,
               float *out_re, float *out_im, wc_report *rep);

#ifdef __cplusplus
}
#endif

#endif /* CHANNELIZER_H */