/* Private state shared by the lag-correlation stages. */
#ifndef STREAM_LAG_INTERNAL_H
#define STREAM_LAG_INTERNAL_H

#include "stream_lag.h"

typedef struct {
    void *fwd;
    void *inv;
    int nfft;
    float *time_re;
    float *time_im;
    float *freq_re;
    float *freq_im;
    void *scratch;
} sc_plan;

struct sc_state {
    sc_plan plan;
    int nref;
    float *ref_spec_re;
    float *ref_spec_im;
    float *prod_re;
    float *prod_im;

    float *pending_re;
    float *pending_im;
    int pending_n;
    int pending_cap;
};

int sc_plan_build(sc_plan *p, int nfft);
void sc_plan_destroy(sc_plan *p);

/* Split-complex time data in, split-complex natural-order frequency data out. */
int sc_plan_forward(sc_plan *p, const float *re, const float *im);

/* Split-complex frequency data in, split-complex time data out.
 * The inverse is normalized by 1/nfft. */
int sc_plan_inverse(sc_plan *p, float *re, float *im);

void sc_report_fill(const float *re, const float *im, int n, sc_report *rep);

/* Correlates one complete nref frame and writes exactly 2*nref-1 lags. */
int sc_process_frame(sc_state *st,
                     const float *frame_re, const float *frame_im,
                     float *out_re, float *out_im);

#endif /* STREAM_LAG_INTERNAL_H */