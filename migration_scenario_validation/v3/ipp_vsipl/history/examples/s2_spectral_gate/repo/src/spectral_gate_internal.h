#ifndef SPECTRAL_GATE_INTERNAL_H
#define SPECTRAL_GATE_INTERNAL_H

#include "spectral_gate.h"

typedef struct {
    void *plan;
    int nfft;
    int nbin;
    float *frame;
    float *bin_re;
    float *bin_im;
    void *scratch;
} sg_plan;

struct sg_state {
    sg_plan plan;
    int ntrain;
    float alpha;
    float *window;
};

int sg_plan_build(sg_plan *p, int nfft);
void sg_plan_destroy(sg_plan *p);
int sg_plan_forward(sg_plan *p, const float *input);
void sg_fill_window(float *window, int n);
void sg_fill_report(const float *mag, const unsigned char *flags, int n,
                    sg_report *rep);

#endif /* SPECTRAL_GATE_INTERNAL_H */