#include "window_spectrum.h"
#include <vsip.h>
#include <math.h>
#include <stdlib.h>
#ifndef WP_PI
#define WP_PI 3.14159265358979323846
#endif
int window_spectrum(const float *input, int nfft,
                    float *mag, float *peak, int *peak_bin, float *total)
{
    vsip_fft_f *plan;
    vsip_vview_f *in;
    vsip_cvview_f *out;
    int nbin, i;
    float pk = -1.0f, sum = 0.0f;
    int pb = 0;
    if (!input || !mag || nfft < 8 || (nfft & (nfft - 1)) != 0) return -1;
    nbin = nfft / 2 + 1;
    plan = vsip_rcfftop_create_f((vsip_length)nfft, 1.0f, 0, VSIP_ALG_SPACE);
    in = vsip_vcreate_f((vsip_length)nfft, VSIP_MEM_NONE);
    out = vsip_cvcreate_f((vsip_length)nbin, VSIP_MEM_NONE);
    if (!plan || !in || !out) {
        if (plan) vsip_fft_destroy_f(plan);
        if (in) vsip_valldestroy_f(in);
        if (out) vsip_cvalldestroy_f(out);
        return -1;
    }
    for (i = 0; i < nfft; ++i) {
        const double w = 0.5 * (1.0 - cos(2.0 * WP_PI * (double)i /
                                          (double)(nfft - 1)));
        vsip_vput_f(in, (vsip_index)i, input[i] * (float)w);
    }
    vsip_rcfftop_f(plan, in, out);
    for (i = 0; i < nbin; ++i) {
        const vsip_cscalar_f z = vsip_cvget_f(out, (vsip_index)i);
        const float m = sqrtf(z.r * z.r + z.i * z.i);
        mag[i] = m;
        sum += m;
        if (m > pk) { pk = m; pb = i; }
    }
    if (peak) *peak = pk;
    if (peak_bin) *peak_bin = pb;
    if (total) *total = sum;
    vsip_fft_destroy_f(plan);
    vsip_valldestroy_f(in);
    vsip_cvalldestroy_f(out);
    return 0;
}
