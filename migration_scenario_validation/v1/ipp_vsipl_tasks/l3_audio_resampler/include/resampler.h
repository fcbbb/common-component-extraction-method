/* Streaming rational resampler + output spectrum report.
 *
 * A polyphase interpolator/decimator for audio-style sample-rate conversion,
 * followed by a periodogram of the converted stream (the "did the conversion
 * leave an image behind" measurement).
 *
 * The prototype filter is defined here, not taken from a library, so the
 * numbers are reproducible from this file alone:
 *
 *   L  = up * ntaps                          prototype length, taps
 *   c  = (L - 1) / 2                         centre, taps
 *   h[j] = 2*fc * sinc(2*fc*(j - c)) * 0.5*(1 - cos(2*pi*j/(L-1)))
 *          with sinc(x) = sin(pi*x)/(pi*x)   (1 at x = 0)
 *
 * The prototype is decomposed into `up` branches of `ntaps` taps; branch p is
 * h[p], h[p+up], ..., h[p+(ntaps-1)*up], and every branch is normalized to sum
 * to 1 so that a constant input comes out unchanged:
 *
 *   hp[p][k] = h[p + k*up] / sum_{k'} h[p + k'*up]
 *
 * The conversion contract, for output index m = 0, 1, 2, ... :
 *
 *   num   = m * down
 *   i     = num / up            (integer floor)
 *   p     = num % up
 *   y[m]  = sum_{k=0}^{ntaps-1} hp[p][k] * x[i - k]
 *
 * so output m sits at input time m*down/up and its filter window ends at input
 * sample i.  The group delay is (ntaps-1)/2 input samples.  Output m exists
 * once input sample i has been consumed and i >= ntaps-1; res_process()
 * therefore emits a number of outputs that depends only on the total input
 * consumed so far, never on how it was blocked, and the phase/history carry
 * across calls.
 *
 * res_process() returns the number of samples it wrote.  It emits nothing and
 * returns 0 when nin == 0.  If cap is smaller than res_max_out(st, nin) it
 * writes nothing and returns -1.  out has room for res_max_out() samples.
 *
 * res_spectrum() analyses the converted stream in non-overlapping frames of
 * fft_len samples (rectangular window, unscaled transform):
 *
 *   mag2[k] = (1/nframes) * sum_f |FFT(fft_len)[k]|^2,  k = 0 .. fft_len/2
 *   frames  = 1 + (n - fft_len)/fft_len   when n >= fft_len, else 0
 *   nbins   = fft_len/2 + 1
 *   power   = max_k mag2[k]
 *   power_bin = the index of the first maximum
 *   total   = sum_k mag2[k]
 *   centroid  = sum_k k*mag2[k] / total      (0 when total == 0)
 *
 * res_spectrum() returns nframes; with n < fft_len it returns 0 and leaves
 * mag2 and rep untouched.
 */
#ifndef RESAMPLER_H
#define RESAMPLER_H

typedef struct {
    int up;         /* interpolation factor, 1 .. 256 */
    int down;       /* decimation factor,      1 .. 256 */
    int ntaps;      /* taps per branch,        >= 2   */
    float cutoff;   /* prototype cutoff, cycles/sample, 0 < cutoff < 0.5 */
    int fft_len;    /* spectrum frame length, power of two >= 8 */
} res_config;

typedef struct {
    float power;     /* max_k mag2[k] */
    int power_bin;   /* index of the first maximum */
    float total;     /* sum_k mag2[k] */
    float centroid;  /* sum_k k*mag2[k] / total, 0 when total == 0 */
    int nbins;       /* fft_len/2 + 1 */
} res_report;

typedef struct res_state res_state;

res_state *res_create(const res_config *cfg);
void res_destroy(res_state *st);

/* Safe upper bound on the outputs res_process() can emit for nin new input
 * samples.  0 for a NULL state. */
int res_max_out(const res_state *st, int nin);

int res_process(res_state *st, const float *in, int nin, float *out, int cap);

int res_spectrum(res_state *st, const float *x, int n, float *mag2,
                 res_report *rep);

#endif /* RESAMPLER_H */