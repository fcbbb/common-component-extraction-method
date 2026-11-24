/* Header-only correlation ABI.  The implementation is absent from this
 * snapshot; the reference after state is gold/. */
#ifndef SONAR_LAG_H
#define SONAR_LAG_H
#ifdef __cplusplus
extern "C" {
#endif
typedef struct sl_state sl_state;
typedef struct { int nfft; int nref; } sl_config;
typedef struct { float peak; int peak_index; float energy; } sl_report;
sl_state *sl_create(const sl_config *cfg);
void sl_destroy(sl_state *st);
int sl_set_reference(sl_state *st, const float *re, const float *im);
int sl_process(sl_state *st, const float *in_re, const float *in_im,
               float *out_re, float *out_im, sl_report *rep);
#ifdef __cplusplus
}
#endif
#endif
