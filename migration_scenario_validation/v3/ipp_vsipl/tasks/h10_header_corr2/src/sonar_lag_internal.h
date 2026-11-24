/* Private state shared by the lag-correlation stages. */
#ifndef SONAR_LAG_INTERNAL_H
#define SONAR_LAG_INTERNAL_H

#include "sonar_lag.h"

typedef struct {
    void *fwd;
    void *inv;
    int nfft;
    float *time_re;
    float *time_im;
    float *freq_re;
    float *freq_im;
    void *scratch;
} sl_plan;

struct sl_state {
    sl_plan plan;
    int nref;
    float *ref_spec_re;
    float *ref_spec_im;
    float *prod_re;
    float *prod_im;
};

int sl_plan_build(sl_plan *p, int nfft);
void sl_plan_destroy(sl_plan *p);

/* Split-complex time data in, split-complex natural-order frequency data out. */
int sl_plan_forward(sl_plan *p, const float *re, const float *im);

/* Split-complex frequency data in, split-complex time data out.
 * The inverse is normalized by 1/nfft. */
int sl_plan_inverse(sl_plan *p, float *re, float *im);

void sl_report_fill(const float *re, const float *im, int n, sl_report *rep);

#endif /* SONAR_LAG_INTERNAL_H */