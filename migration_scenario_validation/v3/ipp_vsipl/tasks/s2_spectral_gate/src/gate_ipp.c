/* Frame windowing, magnitude profile and causal noise gate (IPP backend). */
#include "spectral_gate_internal.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

sg_state *sg_create(const sg_config *cfg)
{
    sg_state *st;

    if (!cfg || cfg->nfft < 8 || (cfg->nfft & (cfg->nfft - 1)) != 0)
        return NULL;
    if (cfg->ntrain < 1 || !(cfg->alpha > 0.0f)) return NULL;

    st = (sg_state *)calloc(1, sizeof(*st));
    if (!st) return NULL;
    st->ntrain = cfg->ntrain;
    st->alpha = cfg->alpha;
    st->window = (float *)calloc((size_t)cfg->nfft, sizeof(float));
    if (!st->window || sg_plan_build(&st->plan, cfg->nfft) != 0) {
        sg_destroy(st);
        return NULL;
    }
    sg_fill_window(st->window, cfg->nfft);
    return st;
}

void sg_destroy(sg_state *st)
{
    if (!st) return;
    sg_plan_destroy(&st->plan);
    free(st->window);
    free(st);
}

int sg_process(sg_state *st, const float *input, int n,
               float *out_mag, unsigned char *flags, sg_report *rep)
{
    int k, nbin;
    float noise_sum = 0.0f;

    if (!st || !input || !out_mag || !flags) return -1;
    if (n != st->plan.nfft) return -1;
    nbin = st->plan.nbin;

    for (k = 0; k < n; ++k) st->plan.frame[k] = input[k] * st->window[k];
    if (sg_plan_forward(&st->plan, st->plan.frame) != 0) return -1;

    for (k = 0; k < nbin; ++k) {
        const float re = st->plan.bin_re[k], im = st->plan.bin_im[k];
        out_mag[k] = sqrtf(re * re + im * im);
    }

    for (k = 0; k < nbin; ++k) {
        int lo = k - st->ntrain;
        int cnt, j;
        if (lo < 0) lo = 0;
        cnt = k - lo;
        noise_sum = 0.0f;
        for (j = lo; j < k; ++j) noise_sum += out_mag[j];
        if (cnt > 0 && noise_sum > 0.0f) {
            const float noise = noise_sum / (float)cnt;
            flags[k] = (out_mag[k] > st->alpha * noise) ? 1 : 0;
        } else {
            flags[k] = 0;
        }
    }

    if (rep) sg_fill_report(out_mag, flags, nbin, rep);
    return 0;
}