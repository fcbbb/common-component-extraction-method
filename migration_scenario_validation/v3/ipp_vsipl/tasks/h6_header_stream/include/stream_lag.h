/* Header-only streaming correlation ABI.  The implementation is absent from
 * this snapshot; the reference after state is gold/. */
#ifndef STREAM_LAG_H
#define STREAM_LAG_H
#ifdef __cplusplus
extern "C" {
#endif
typedef struct sc_state sc_state;
typedef struct { int nfft; int nref; } sc_config;
typedef struct { float peak; int peak_index; float energy; } sc_report;
sc_state *sc_create(const sc_config *cfg);
void sc_destroy(sc_state *st);
int sc_set_reference(sc_state *st, const float *re, const float *im);
int sc_process(sc_state *st, const float *in_re, const float *in_im, int nin,
               float *out_re, float *out_im, int out_cap,
               int *nout, sc_report *rep);
#ifdef __cplusplus
}
#endif
#endif
