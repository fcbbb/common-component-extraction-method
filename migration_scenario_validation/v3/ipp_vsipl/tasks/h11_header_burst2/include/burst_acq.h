/* Streaming burst acquirer ABI.
 *
 * The implementation is intentionally absent from this snapshot.  The ABI
 * and the public test define the calling convention; the reference after
 * state is in gold/.  The migrated implementation must be built on VSIPL
 * primitives and must not retain IPP symbols.
 */
#ifndef BURST_ACQ_H
#define BURST_ACQ_H

#ifdef __cplusplus
extern "C" {
#endif

typedef struct ba_state ba_state;

typedef struct {
    int nco_len;
    int decim;
    int ntaps;
    int nref;
    int nfft;
} ba_config;

typedef struct {
    float peak;
    int peak_index;
    float energy;
    int frames;
} ba_report;

ba_state *ba_create(const ba_config *cfg);
void ba_destroy(ba_state *st);

int ba_set_waveform(ba_state *st,
                    const float *nco_re, const float *nco_im,
                    const float *taps_re, const float *taps_im,
                    const float *ref_re, const float *ref_im);

int ba_push(ba_state *st,
            const float *in_re, const float *in_im, int nin,
            float *out_re, float *out_im, int out_cap,
            int *nout, ba_report *rep);

#ifdef __cplusplus
}
#endif

#endif /* BURST_ACQ_H */
