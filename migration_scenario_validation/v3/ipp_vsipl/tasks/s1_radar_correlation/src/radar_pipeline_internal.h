/* Private state shared by the correlation stages.
 *
 * The two backends keep their own opaque plan objects in fwd/inv; time and
 * frequency work arrays are plain split-float planes so the stage boundary is
 * independent of the backend.
 */
#ifndef RADAR_PIPELINE_INTERNAL_H
#define RADAR_PIPELINE_INTERNAL_H

#include "radar_pipeline.h"

typedef struct {
    void *fwd;
    void *inv;
    int nfft;
    float *time_re;
    float *time_im;
    float *freq_re;
    float *freq_im;
    void *scratch;      /* backend-private interleaved work area */
} rpc_plan;

struct rpc_state {
    rpc_plan plan;
    int npulse;
    float *rep_spec_re;
    float *rep_spec_im;
    float *prod_re;
    float *prod_im;
};

int rpc_plan_build(rpc_plan *p, int nfft);
void rpc_plan_destroy(rpc_plan *p);

/* Input is split complex time data of length p->nfft; output is split
 * complex frequency data in natural order. */
int rpc_plan_forward(rpc_plan *p, const float *re, const float *im);

/* Input is split complex frequency data; output is split complex time data.
 * The inverse must be normalized by 1/nfft. */
int rpc_plan_inverse(rpc_plan *p, float *re, float *im);

void rpc_profile_fill(const float *re, const float *im, int n,
                      rpc_report *rep);

#endif /* RADAR_PIPELINE_INTERNAL_H */