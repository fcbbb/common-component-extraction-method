/* Streaming spectral gate.
 *
 * Each call filters one nfft-sample real frame with a symmetric Hann window,
 * computes the one-sided real spectrum (nfft/2+1 natural complex bins), forms
 * a magnitude profile, estimates the local noise floor from the ntrain bins to
 * the left of each bin, and flags bins above alpha * noise.
 *
 * Bin k of `out_mag` is |X[k]| for k = 0 .. nfft/2.  The transform is
 * unscaled: a unit DC frame has magnitude 1 at bin 0, not nfft.
 */
#ifndef SPECTRAL_GATE_H
#define SPECTRAL_GATE_H

#ifdef __cplusplus
extern "C" {
#endif

typedef struct sg_state sg_state;

typedef struct {
    int nfft;      /* even power of two, >= 8 */
    int ntrain;    /* causal noise-window length, >= 1 */
    float alpha;   /* detection multiplier, > 0 */
} sg_config;

typedef struct {
    float peak;
    int peak_bin;
    int detections;
    float noise_floor;
} sg_report;

sg_state *sg_create(const sg_config *cfg);
void sg_destroy(sg_state *st);

/* Returns 0 on success, -1 on bad arguments.  out_mag has nfft/2+1 floats;
 * flags has nfft/2+1 bytes. */
int sg_process(sg_state *st, const float *input, int n,
               float *out_mag, unsigned char *flags, sg_report *rep);

#ifdef __cplusplus
}
#endif

#endif /* SPECTRAL_GATE_H */