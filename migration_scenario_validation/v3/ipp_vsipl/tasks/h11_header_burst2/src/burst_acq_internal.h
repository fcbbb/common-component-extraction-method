/* Private state shared by the burst-acquirer stages. */
#ifndef BURST_ACQ_INTERNAL_H
#define BURST_ACQ_INTERNAL_H

#include "burst_acq.h"

typedef struct {
    void *fwd;
    void *inv;
    int nfft;
    float *time_re;
    float *time_im;
    float *freq_re;
    float *freq_im;
    void *scratch;
} ba_plan;

struct ba_state {
    ba_config cfg;
    int M;                 /* decim * ntaps */

    float *nco_re;
    float *nco_im;
    float *taps_re;
    float *taps_im;
    float *ref_re;
    float *ref_im;
    int ready;

    /* Gold backend: FFT plan and reference spectrum. */
    ba_plan plan;
    float *ref_spec_re;
    float *ref_spec_im;
    float *prod_re;
    float *prod_im;

    /* Source backend: opaque IPP FIR state. */
    void *ipp_fir;

    /* Continuous input/mixer state. */
    int nco_phase;
    long input_seen;

    /* Last M mixed samples in ascending time order. */
    float *hist_re;
    float *hist_im;
    int hfill;

    /* Decimated samples waiting to complete nref-sized frames. */
    float *dec_re;
    float *dec_im;
    int dec_n;
    int dec_cap;
};

int ba_plan_build(ba_plan *p, int nfft);
void ba_plan_destroy(ba_plan *p);
int ba_plan_forward(ba_plan *p, const float *re, const float *im);
int ba_plan_inverse(ba_plan *p, float *re, float *im);

int ba_correlate_frame(ba_state *st,
                       const float *frame_re, const float *frame_im,
                       float *out_re, float *out_im);

#endif /* BURST_ACQ_INTERNAL_H */