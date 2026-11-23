/* FBP projection filtering (Intel IPP backend).
 *
 * Extracted from CIL's src/Core/FBP_filtering.cpp.  The two entry points are
 * unchanged; the only edits are the ones needed to compile the file as C99:
 * aggregate literals get an explicit cast, the unused `flag` variable is kept
 * (the original declares IPP_FFT_NODIV_BY_ANY and then passes
 * IPP_FFT_DIV_FWD_BY_N anyway), and the OpenMP pragmas are gone.  Dropping
 * parallelisation cannot change the result: the `omp for` body works on one
 * independent pair of rows per iteration, and the `omp single` block runs the
 * odd tail row exactly once.
 *
 * The algorithm: FBP filters every detector row independently.  To halve the
 * transform count, two consecutive rows of a projection are packed into the
 * real and imaginary parts of one complex vector, zero padded to 2^order and
 * centred with an offset of (2^order - pix_x)/2.  The complex spectrum is
 * multiplied by the real-valued reconstruction filter and transformed back;
 * the real and imaginary parts of the result are the two filtered rows.
 */
#include "fbp_filtering.h"

#include <ipp.h>
#include <math.h>
#include <stddef.h>

int filter_projections_avh(float *data, const float *filter, const float *weights,
                           int order, long num_proj, long pix_y, long pix_x)
{
    /* set up */
    int width = 1 << order;
    int offset = (int)floor(((double)width - (double)pix_x) / 2.0);

    IppsFFTSpec_C_32fc *pSpec = 0;
    Ipp8u *pMemSpec = 0;
    Ipp8u *pMemInit = 0;

    int sizeSpec = 0;
    int sizeInit = 0;
    int sizeBuffer = 0;

    int flag = IPP_FFT_NODIV_BY_ANY;
    (void)flag;

    ippsFFTGetSize_C_32fc(order, IPP_FFT_DIV_FWD_BY_N, ippAlgHintNone,
                          &sizeSpec, &sizeInit, &sizeBuffer);
    pMemSpec = (Ipp8u*)ippMalloc(sizeSpec);
    pMemInit = (Ipp8u*)ippMalloc(sizeInit);
    ippsFFTInit_C_32fc(&pSpec, order, IPP_FFT_DIV_FWD_BY_N, ippAlgHintNone,
                       pMemSpec, pMemInit);
    ippFree(pMemInit);

    long j;
    long k = 0;
    int half_pixy = (int)(pix_y / 2);
    while (k < num_proj) {
        size_t proj_start = (size_t)k * pix_y * pix_x;
        k++;
        {
            Ipp8u *pMemBuffer = (Ipp8u*)ippMalloc(sizeBuffer);
            Ipp32fc *src = ippsMalloc_32fc(width);
            Ipp32fc *dst = ippsMalloc_32fc(width);

            float *out_ptr;
            size_t row_start;

            for (j = 0; j < half_pixy; j++) {
                row_start = (size_t)2 * j * pix_x;
                out_ptr = &data[proj_start + row_start];
                ippsMul_32f_I(weights + row_start, out_ptr, 2 * pix_x);
                ippsSet_32fc((Ipp32fc){ 0.f, 0.f }, src, width);
                ippsRealToCplx_32f(out_ptr, out_ptr + pix_x, src + offset, pix_x);
                ippsFFTFwd_CToC_32fc(src, dst, pSpec, pMemBuffer);
                ippsMul_32f32fc_I(filter, dst, width);
                ippsFFTInv_CToC_32fc(dst, src, pSpec, pMemBuffer);
                ippsCplxToReal_32fc(src + offset, out_ptr, out_ptr + pix_x, pix_x);
            }

            if (pix_y % 2) {
                row_start = (size_t)pix_y * pix_x - pix_x;
                out_ptr = &data[proj_start + row_start];

                ippsMul_32f_I(weights + row_start, out_ptr, pix_x);
                ippsSet_32fc((Ipp32fc){ 0.f, 0.f }, src, width);
                ippsRealToCplx_32f(out_ptr, NULL, src + offset, pix_x);
                ippsFFTFwd_CToC_32fc(src, dst, pSpec, pMemBuffer);
                ippsMul_32f32fc_I(filter, dst, width);
                ippsFFTInv_CToC_32fc(dst, src, pSpec, pMemBuffer);
                ippsReal_32fc(src + offset, out_ptr, pix_x);
            }
            ippFree(src);
            ippFree(dst);
            ippFree(pMemBuffer);
        }
    }

    ippFree(pMemSpec);
    return 0;
}

int filter_projections_vah(float *data, const float *filter, const float *weights,
                           int order, long pix_y, long num_proj, long pix_x)
{
    /* set up */
    int width = 1 << order;
    int offset = (int)floor(((double)width - (double)pix_x) / 2.0);

    IppsFFTSpec_C_32fc *pSpec = 0;
    Ipp8u *pMemSpec = 0;
    Ipp8u *pMemInit = 0;

    int sizeSpec = 0;
    int sizeInit = 0;
    int sizeBuffer = 0;

    int flag = IPP_FFT_NODIV_BY_ANY;
    (void)flag;

    ippsFFTGetSize_C_32fc(order, IPP_FFT_DIV_FWD_BY_N, ippAlgHintNone,
                          &sizeSpec, &sizeInit, &sizeBuffer);
    pMemSpec = (Ipp8u*)ippMalloc(sizeSpec);
    pMemInit = (Ipp8u*)ippMalloc(sizeInit);
    ippsFFTInit_C_32fc(&pSpec, order, IPP_FFT_DIV_FWD_BY_N, ippAlgHintNone,
                       pMemSpec, pMemInit);
    ippFree(pMemInit);

    long j;
    long k = 0;
    int half_proj = (int)(num_proj / 2);
    while (k < pix_y) {
        size_t col_start = (size_t)k * num_proj * pix_x;
        const float *weights_ptr = &weights[(size_t)k * pix_x];
        k++;
        {
            Ipp8u *pMemBuffer = (Ipp8u*)ippMalloc(sizeBuffer);
            Ipp32fc *src = ippsMalloc_32fc(width);
            Ipp32fc *dst = ippsMalloc_32fc(width);

            float *out_ptr;
            size_t row_start;

            for (j = 0; j < half_proj; j++) {
                row_start = (size_t)2 * j * pix_x;
                out_ptr = &data[col_start + row_start];
                ippsMul_32f_I(weights_ptr, out_ptr, pix_x);
                ippsMul_32f_I(weights_ptr, out_ptr + pix_x, pix_x);

                ippsSet_32fc((Ipp32fc){ 0.f, 0.f }, src, width);
                ippsRealToCplx_32f(out_ptr, out_ptr + pix_x, src + offset, pix_x);
                ippsFFTFwd_CToC_32fc(src, dst, pSpec, pMemBuffer);
                ippsMul_32f32fc_I(filter, dst, width);
                ippsFFTInv_CToC_32fc(dst, src, pSpec, pMemBuffer);
                ippsCplxToReal_32fc(src + offset, out_ptr, out_ptr + pix_x, pix_x);
            }

            if (num_proj % 2) {
                row_start = (size_t)num_proj * pix_x - pix_x;
                out_ptr = &data[col_start + row_start];
                ippsMul_32f_I(weights_ptr, out_ptr, pix_x);
                ippsSet_32fc((Ipp32fc){ 0.f, 0.f }, src, width);
                ippsRealToCplx_32f(out_ptr, NULL, src + offset, pix_x);
                ippsFFTFwd_CToC_32fc(src, dst, pSpec, pMemBuffer);
                ippsMul_32f32fc_I(filter, dst, width);
                ippsFFTInv_CToC_32fc(dst, src, pSpec, pMemBuffer);
                ippsReal_32fc(src + offset, out_ptr, pix_x);
            }
            ippFree(src);
            ippFree(dst);
            ippFree(pMemBuffer);
        }
    }

    ippFree(pMemSpec);
    return 0;
}