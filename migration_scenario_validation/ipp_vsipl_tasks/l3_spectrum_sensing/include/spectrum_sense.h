/* Spectrum sensing frontend: Welch periodogram plus an energy detector.
 *
 * One sensor object owns an FFT plan and a Hann window of fft_len samples.
 * A capture is cut into frames of fft_len samples every frame_step samples;
 * every frame is windowed, transformed, squared and averaged into a single
 * power spectral density.  The detector then reports the noise floor (the mean
 * of the density), the peak, and how many bins sit above
 * thr_scale * noise_floor.
 *
 *   window      w[i] = 0.5 * (1 - cos(2*pi*i/(N-1)))   i = 0 .. N-1
 *   frames      f    = 0 .. nframes-1, frame f starts at x[f*frame_step]
 *   density     psd[k] = (1/nframes) * sum_f |FFT_N(w * x_f)[k]|^2
 *                      k = 0 .. N/2
 *   report      noise_floor = mean(psd)
 *               peak_power  = max(psd), peak_bin = its first index
 *               threshold   = thr_scale * noise_floor
 *               occ_bins    = #{ k : psd[k] >= threshold }
 *               occupancy   = occ_bins / (N/2 + 1)
 *
 * The transform is unscaled, exactly as IPP's IPP_FFT_NODIV_BY_ANY produces
 * it; nothing in this component normalises by N.
 */
#ifndef SPECTRUM_SENSE_H
#define SPECTRUM_SENSE_H

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    int fft_len;      /* N, power of two, >= 8 */
    int frame_step;   /* hop between consecutive frames, > 0 */
    float thr_scale;  /* detector threshold = thr_scale * noise_floor, > 0 */
} sens_config;

typedef struct {
    float noise_floor;
    float peak_power;
    int peak_bin;
    int occ_bins;
    float occupancy;
} sens_report;

typedef struct sens_state sens_state;

/* NULL for a NULL config, an fft_len that is not a power of two or is below 8,
 * a non-positive frame_step, or a non-positive thr_scale. */
sens_state *sens_create(const sens_config *cfg);

void sens_destroy(sens_state *st);

/* Number of bins in a density, N/2 + 1 (0 when st is NULL). */
int sens_nbin(const sens_state *st);

/* Analyses one capture of n samples.  The caller supplies psd with room for
 * sens_nbin() floats.  Returns the number of frames averaged; returns 0 and
 * writes nothing when n < fft_len, and -1 on a NULL argument. */
int sens_analyze(sens_state *st, const float *x, int n,
                 float *psd, sens_report *rep);

#ifdef __cplusplus
}
#endif

#endif /* SPECTRUM_SENSE_H */