/* Real power spectrum, VSIPL backend (reference after state). */
#include "power_spectrum.h"

#include <vsip.h>

int power_spectrum(const float *input, int nfft, float *power,
                   float *peak, int *peak_bin, float *total_power)
{
    vsip_fft_f *fft;
    vsip_vview_f *time, *pview;
    vsip_cvview_f *spec;
    float p = 0.0f, total = 0.0f;
    int nbin, k, pbin = 0, rc = -1;

    if (!input || !power || nfft < 8 || (nfft & (nfft - 1)) != 0) return -1;
    nbin = nfft / 2 + 1;
    fft = vsip_rcfftop_create_f((vsip_length)nfft, 1.0f, 0, VSIP_ALG_SPACE);
    time = vsip_vcreate_f((vsip_length)nfft, VSIP_MEM_NONE);
    spec = vsip_cvcreate_f((vsip_length)nbin, VSIP_MEM_NONE);
    pview = vsip_vcreate_f((vsip_length)nbin, VSIP_MEM_NONE);
    if (!fft || !time || !spec || !pview) goto done;

    vsip_vcopyfrom_user_f((vsip_scalar_f *)(void *)input, time);
    vsip_rcfftop_f(fft, time, spec);
    vsip_vcmagsq_f(spec, pview);
    vsip_vcopyto_user_f(pview, power);

    for (k = 0; k < nbin; ++k) {
        total += power[k];
        if (power[k] > p) { p = power[k]; pbin = k; }
    }
    if (peak) *peak = p;
    if (peak_bin) *peak_bin = pbin;
    if (total_power) *total_power = total;
    rc = 0;

done:
    if (fft) vsip_fft_destroy_f(fft);
    if (time) vsip_valldestroy_f(time);
    if (spec) vsip_cvalldestroy_f(spec);
    if (pview) vsip_valldestroy_f(pview);
    return rc;
}
