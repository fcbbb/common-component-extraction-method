#include "spectral_centroid.h"
#include <vsip.h>
#include <math.h>
#ifndef SC_PI
#define SC_PI 3.14159265358979323846
#endif
int spectral_centroid(const float *input, int nfft,
                      float *centroid, float *peak, int *peak_bin,
                      float *total)
{
    vsip_fft_f *fft;
    vsip_vview_f *time;
    vsip_cvview_f *spec;
    int nbin, k, pb = 0;
    float pk = -1.0f, sum = 0.0f, weighted = 0.0f;
    if (!input || !centroid || nfft < 8 || (nfft & (nfft - 1)) != 0)
        return -1;
    nbin = nfft / 2 + 1;
    fft = vsip_rcfftop_create_f((vsip_length)nfft, 1.0f, 0, VSIP_ALG_SPACE);
    time = vsip_vcreate_f((vsip_length)nfft, VSIP_MEM_NONE);
    spec = vsip_cvcreate_f((vsip_length)nbin, VSIP_MEM_NONE);
    if (!fft || !time || !spec) {
        if (fft) vsip_fft_destroy_f(fft);
        if (time) vsip_valldestroy_f(time);
        if (spec) vsip_cvalldestroy_f(spec);
        return -1;
    }
    for (k = 0; k < nfft; ++k) {
        const double w = 0.5 * (1.0 - cos(2.0 * SC_PI * k / (nfft - 1)));
        vsip_vput_f(time, (vsip_index)k, input[k] * (float)w);
    }
    vsip_rcfftop_f(fft, time, spec);
    for (k = 0; k < nbin; ++k) {
        const vsip_cscalar_f z = vsip_cvget_f(spec, (vsip_index)k);
        const float m = sqrtf(z.r * z.r + z.i * z.i);
        sum += m;
        weighted += (float)k * m;
        if (m > pk) { pk = m; pb = k; }
    }
    *centroid = sum > 0.0f ? weighted / sum : 0.0f;
    if (peak) *peak = pk < 0.0f ? 0.0f : pk;
    if (peak_bin) *peak_bin = pb;
    if (total) *total = sum;
    vsip_fft_destroy_f(fft);
    vsip_valldestroy_f(time);
    vsip_cvalldestroy_f(spec);
    return 0;
}
