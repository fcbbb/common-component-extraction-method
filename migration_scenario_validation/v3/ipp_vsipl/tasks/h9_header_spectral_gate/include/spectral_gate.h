/* Header-only spectral gate ABI.  Implementation absent; gold/ is the
 * reference after state. */
#ifndef SPECTRAL_GATE_H
#define SPECTRAL_GATE_H
#ifdef __cplusplus
extern "C" {
#endif
typedef struct sg_state sg_state;
typedef struct { int nfft; int ntrain; float alpha; } sg_config;
typedef struct { float peak; int peak_bin; int detections; float noise_floor; } sg_report;
sg_state *sg_create(const sg_config *cfg);
void sg_destroy(sg_state *st);
int sg_process(sg_state *st, const float *input, int n,
               float *out_mag, unsigned char *flags, sg_report *rep);
#ifdef __cplusplus
}
#endif
#endif
