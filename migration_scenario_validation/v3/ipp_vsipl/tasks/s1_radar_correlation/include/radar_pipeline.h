/* Radar pulse-compression correlation layer.
 *
 * A real-valued replica is correlated with a real-valued pulse return.  The
 * public contract is split real/imaginary planes for every complex array and
 * a lag-ordered correlation output:
 *
 *     corr[k] = sum_j x[j] * conj(replica[j - k])
 *
 * with k = -(npulse-1) .. (npulse-1).  out[i] stores corr[i-(npulse-1)], so
 * i = 0 is the most negative lag and i = 2*npulse-2 is the most positive lag.
 * Out-of-range replica samples are zero.  The implementation is free to use
 * an FFT internally, but the reported order is the linear-correlation order.
 */
#ifndef RADAR_PIPELINE_H
#define RADAR_PIPELINE_H

#ifdef __cplusplus
extern "C" {
#endif

typedef struct rpc_state rpc_state;

typedef struct {
    int nfft;      /* power of two, nfft >= 2*npulse - 1 */
    int npulse;    /* replica length, >= 1 */
} rpc_config;

typedef struct {
    float peak;       /* largest |y[k]| */
    int peak_index;   /* first lag attaining it */
    float energy;     /* sum |y[k]|^2 */
} rpc_report;

/* Returns NULL for a bad configuration or allocation failure. */
rpc_state *rpc_create(const rpc_config *cfg);

void rpc_destroy(rpc_state *st);

/* The replica is copied; changing the caller's buffer afterwards has no
 * effect.  Returns 0 on success, -1 on bad arguments. */
int rpc_set_replica(rpc_state *st, const float *re, const float *im, int n);

/* Processes one return of length n == cfg.npulse.  out_re/out_im must have
 * room for 2*n-1 complex lags.  rep may be NULL.  Returns 0 or -1. */
int rpc_process(rpc_state *st,
                const float *in_re, const float *in_im, int n,
                float *out_re, float *out_im, rpc_report *rep);

#ifdef __cplusplus
}
#endif

#endif /* RADAR_PIPELINE_H */