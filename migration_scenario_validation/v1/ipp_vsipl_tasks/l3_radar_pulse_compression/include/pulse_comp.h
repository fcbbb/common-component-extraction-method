/* Radar pulse compression frontend (public contract).
 *
 * One capture is `npulses` real pulses of `fft_len` samples each, laid out
 * pulse-major.  The library applies a fixed windowed-LFM matched filter to
 * every pulse, integrates the magnitudes incoherently, smooths the range
 * profile with a moving-average FIR, and reports the detections.
 *
 * The replica is defined here (not supplied by the caller) so both baseline
 * and migration build the same waveform:
 *
 *   w[i]   = 0.5*(1 - cos(2*pi*i/(N-1)))                 i = 0 .. N-1
 *   u[i]   = i - (N-1)/2
 *   r[i]   = w[i] * cos(pi * chirp_rate * u[i]^2 / N)
 *
 * computed in double and stored as float.
 *
 * For pulse p, with X_p the unscaled N-point DFT of the pulse and R the
 * unscaled DFT of the replica,
 *
 *   y_p[l] = (1/N) * sum_{k=0}^{N-1} X_p[k] * conj(R[k]) * exp(+2*pi*i*k*l/N)
 *
 * for l = 0 .. N/2 (the non-negative range lags).  The range profile is the
 * incoherent mean
 *
 *   g[l]   = (1/(npulses*N)) * sum_p | sum_k X_p[k]*conj(R[k])*exp(...) |
 *
 * and the reported profile is the causal moving average
 *
 *   profile[l] = (1/fir_len) * sum_{j=0}^{fir_len-1} g[l-j],  g[m]=0 for m<0.
 *
 * Report:
 *   noise_floor  = mean_l profile[l]
 *   threshold    = threshold_scale * noise_floor
 *   peak_value   = max_l profile[l]
 *   peak_bin     = first index of the maximum
 *   n_detections = #{ l : profile[l] >= threshold,
 *                       l == 0        or profile[l] >  profile[l-1],
 *                       l == nrange-1 or profile[l] >= profile[l+1] }
 *   first_bin, last_bin = first/last l in that set, or -1 when none
 */
#ifndef PULSE_COMP_H
#define PULSE_COMP_H

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    int fft_len;           /* power of two, >= 32 */
    int npulses;           /* >= 1 */
    int fir_len;           /* odd, 1 .. 15 */
    float chirp_rate;      /* > 0, finite */
    float threshold_scale; /* > 0, finite */
} pc_config;

typedef struct {
    float noise_floor;
    float threshold;
    float peak_value;
    int peak_bin;
    int n_detections;
    int first_bin;
    int last_bin;
} pc_report;

typedef struct pc_state pc_state;

/* NULL on a rejected configuration. */
pc_state *pc_create(const pc_config *cfg);
void pc_destroy(pc_state *st);

/* fft_len/2 + 1, or 0 for a NULL state. */
int pc_nrange(const pc_state *st);

/* Analyse one capture of n = npulses*fft_len samples.  profile has room for
 * pc_nrange() floats.  Returns npulses, or -1 on a NULL/ill-sized argument. */
int pc_process(pc_state *st, const float *signal, int n,
               float *profile, pc_report *rep);

#ifdef __cplusplus
}
#endif

#endif /* PULSE_COMP_H */