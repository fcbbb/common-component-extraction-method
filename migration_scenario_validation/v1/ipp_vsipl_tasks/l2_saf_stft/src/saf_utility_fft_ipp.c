/*
 * Copyright 2019 Leo McCormack
 *
 * Permission to use, copy, modify, and/or distribute this software for any
 * purpose with or without fee is hereby granted, provided that the above
 * copyright notice and this permission notice appear in all copies.
 *
 * THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
 * REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY
 * AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
 * INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM
 * LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR
 * OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
 * PERFORMANCE OF THIS SOFTWARE.
 */

/**
 * @file saf_utility_fft.c
 * @ingroup Utilities
 * @brief Wrappers for optimised discrete/fast Fourier transform (FFT) routines
 * @license ISC
 *
 * Extracted from
 *   Spatial_Audio_Framework/framework/modules/saf_utilities/saf_utility_fft.c
 * with the FFTW / Apple Accelerate / Intel MKL / KissFFT backends removed:
 * this is the Intel IPP backend, selected upstream with -DSAF_USE_INTEL_IPP.
 * Everything that is not backend specific (the STFT frame bookkeeping, the
 * overlap-add, the convolution helpers, the Hilbert transform) is unchanged.
 *
 * Two behaviours of this backend are load bearing and easy to get wrong:
 *   - the inverse transforms are scaled by 1/N (IPP_FFT_DIV_INV_BY_N was
 *     requested when the spec was created);
 *   - the real<->half-complex transforms exchange an array of N+2 floats
 *     holding the natural interleaved half spectrum [R0,I0,R1,I1,...], which
 *     is what this IPP build writes into the "CCS" buffer.
 */

#include "saf_utility_fft.h"
#include "saf_support.h"

#include <ipps.h>
#include <ippversion.h>
#include <ippcore.h>

/** Data structure for short-time Fourier transform */
typedef struct _saf_stft_data {
    int winsize, hopsize, fftsize, nCHin, nCHout, nBands;
    void* hFFT;
    int numOvrlpAddBlocks, bufferlength, nPrevHops;
    float* window, *insig_rect_win, *insig_win, *outsig_win;
    float** overlapAddBuffer;
    float*** prev_inhops;
    float_complex* tmp_fft;
    SAF_STFT_FDDATA_FORMAT FDformat;

}saf_stft_data;

/** Data structure for real-(half)complex FFT transforms */
typedef struct _saf_rfft_data {
    int N;
    float  Scale;
    int useKissFFT_FLAG;
    /* SAF_USE_INTEL_IPP */
    int useIPPfft_FLAG;
    int specSize, specBufferSize, bufferSize, log2n;
    IppsDFTSpec_R_32f* hDFTspec;
    IppsFFTSpec_R_32f* hFFTspec;
    Ipp8u* memSpec;
    Ipp8u* buffer;
    Ipp8u* memInit;

}saf_rfft_data;

/** Data structure for complex-complex FFT transforms */
typedef struct _saf_fft_data {
    int N;
    float  Scale;
    int useKissFFT_FLAG;
    /* SAF_USE_INTEL_IPP */
    int useIPPfft_FLAG;
    int specSize, specBufferSize, bufferSize, log2n;
    IppsDFTSpec_C_32fc* hDFTspec;
    IppsFFTSpec_C_32fc* hFFTspec;
    Ipp8u* memSpec;
    Ipp8u* buffer;
    Ipp8u* memInit;

}saf_fft_data;

/* ========================================================================== */
/*                               Misc. Functions                              */
/* ========================================================================== */

void getUniformFreqVector
(
    int fftSize,
    float fs,
    float* freqVector
)
{
    int k;
    for(k=0; k<fftSize/2+1; k++)
        freqVector[k] = (float)k * fs/(float)fftSize;
}

void fftconv
(
    float* x,
    float* h,
    int x_len,
    int h_len,
    int nCH,
    float* y
)
{
    int i, y_len, fftSize, nBins;
    float* h0, *x0, *y0;
    float_complex* H, *X, *Y;
    void* hfft;

    /* prep */
    y_len = x_len + h_len - 1;
    fftSize =  (int)((float)nextpow2(y_len)+0.5f);
    nBins = fftSize/2+1;
    h0 = calloc1d(fftSize, sizeof(float));
    x0 = calloc1d(fftSize, sizeof(float));
    y0 = malloc1d(fftSize * sizeof(float));
    H = malloc1d(nBins*sizeof(float_complex));
    X = malloc1d(nBins*sizeof(float_complex));
    Y = malloc1d(nBins*sizeof(float_complex));
    saf_rfft_create(&hfft, fftSize);

    /* apply convolution per channel */
    for(i=0; i<nCH; i++){
        /* zero pad to avoid circular convolution artefacts, prior to fft */
        memcpy(h0, &h[i*h_len], h_len*sizeof(float));
        memcpy(x0, &x[i*x_len], x_len*sizeof(float));
        saf_rfft_forward(hfft, x0, X);
        saf_rfft_forward(hfft, h0, H);

        /* multiply the two spectra */
        utility_cvvmul(X, H, nBins, Y);

        /* ifft, truncate and store to output */
        saf_rfft_backward(hfft, Y, y0);
        memcpy(&y[i*y_len], y0, y_len*sizeof(float));
    }

    /* tidy up */
    saf_rfft_destroy(&hfft);
    free(h0);
    free(x0);
    free(y0);
    free(H);
    free(X);
    free(Y);
}

void fftfilt
(
    float* x,
    float* h,
    int x_len,
    int h_len,
    int nCH,
    float* y
)
{
    int i;
    float* y_tmp;

    y_tmp = malloc1d(nCH*(x_len+h_len-1)*sizeof(float));
    fftconv(x, h, x_len, h_len, nCH, y_tmp);
    for(i=0; i<nCH; i++)
        memcpy(&y[i*x_len], &y_tmp[i*(x_len+h_len-1)], x_len*sizeof(float));
    free(y_tmp);
}

void hilbert
(
    float_complex* x,
    int x_len,
    float_complex* y
)
{
    int i;
    float_complex *xfft, *h, *xhfft;
    void* hfft;

    saf_fft_create(&hfft, x_len);
    xfft = malloc1d(x_len*sizeof(float_complex));
    h = malloc1d(x_len*sizeof(float_complex));
    xhfft = malloc1d(x_len*sizeof(float_complex));

    /* Forward fft */
    saf_fft_forward(hfft, x, xfft);

    /* define vector h */
    memset(h, 0, sizeof(float_complex)*x_len);
    if(x_len % 2 == 0){
        /* even */
        h[0] = cmplxf(1.0f, 0.0f);
        h[x_len/2] = cmplxf(1.0f, 0.0f);
        for(i=1;i<x_len/2;i++)
            h[i] = cmplxf(2.0f, 0.0f);
    }
    else{
        saf_assert(x_len % 2 == 0, "Uneven lengths are not supported by saf_fft");
        /* odd */
        h[0] = cmplxf(1.0f, 0.0f);
        for(i=1;i<(x_len+1)/2;i++)
            h[i] = cmplxf(2.0f, 0.0f);
    }

    /* apply h, and ifft */
    utility_cvvmul(xfft, h, x_len, xhfft);
    saf_fft_backward(hfft, xhfft, y);

    /* tidy up */
    saf_fft_destroy(&hfft);
    free(xfft);
    free(h);
    free(xhfft);
}

/* ========================================================================== */
/*                     Short-time Fourier Transform (STFT)                    */
/* ========================================================================== */

void saf_stft_create
(
    void ** const phSTFT,
    int winsize,
    int hopsize,
    int nCHin,
    int nCHout,
    SAF_STFT_FDDATA_FORMAT FDformat
)
{
    *phSTFT = malloc1d(sizeof(saf_stft_data));
    saf_stft_data *h = (saf_stft_data*)(*phSTFT);

    h->nCHin = nCHin;
    h->nCHout = nCHout;
    h->winsize = winsize;
    h->hopsize = hopsize;
    h->nBands = winsize+1;
    h->FDformat = FDformat;

    /* set-up FFT */
    h->fftsize = 2*winsize;
    saf_rfft_create(&(h->hFFT), h->fftsize);
    h->insig_rect_win = calloc1d(h->fftsize, sizeof(float));
    h->insig_win = calloc1d(h->fftsize, sizeof(float));

    /* Intermediate buffers */
    h->tmp_fft = malloc1d(h->nBands * sizeof(float_complex));
    h->outsig_win = malloc1d(h->fftsize*sizeof(float));
    h->nPrevHops = winsize/hopsize-1;
    if (h->nPrevHops>0)
        h->prev_inhops = (float***)calloc3d(h->nPrevHops, nCHin, hopsize, sizeof(float));
    else
        h->prev_inhops = NULL;

    /* Windowing function */
    if(winsize==hopsize)
        h->window = NULL;
    else{
        h->window = malloc1d(winsize*sizeof(float));
        getWindowingFunction(WINDOWING_FUNCTION_HANN, winsize, h->window);
    }

    /* Overlap-add buffer */
    h->numOvrlpAddBlocks = winsize/hopsize;
    h->bufferlength = h->numOvrlpAddBlocks * (h->fftsize);
    h->overlapAddBuffer = (float**)calloc2d(nCHout, h->bufferlength, sizeof(float));
}

void saf_stft_destroy
(
    void ** const phSTFT
)
{
    saf_stft_data *h = (saf_stft_data*)(*phSTFT);
    if(h!=NULL){
        saf_rfft_destroy(&(h->hFFT));
        free(h->window);
        free(h->overlapAddBuffer);
        free(h->insig_rect_win);
        free(h->insig_win);
        free(h->tmp_fft);
        free(h->prev_inhops);
        free(h);
        h=NULL;
        *phSTFT = NULL;
    }
}

void saf_stft_forward
(
    void * const hSTFT,
    float** dataTD,
    int framesize,
    float_complex*** dataFD

)
{
    saf_stft_data *h = (saf_stft_data*)(hSTFT);
    int ch, j, nHops, t, band, idx, hIdx;

    saf_assert(framesize % h->hopsize == 0, "framesize must be multiple of hopsize");
    nHops = framesize/h->hopsize;

    /* For linear time-invariant (LTI) operation (i.e. no previous hops are
     * required) */
    if(h->winsize==h->hopsize){
        for (t = 0; t<nHops; t++){
            for(ch=0; ch < h->nCHin; ch++){
                /* Window input signal (Rectangular) */
                memcpy(h->insig_rect_win, &dataTD[ch][t*(h->hopsize)], h->winsize*sizeof(float));

                /* Apply FFT and copy data to output dataFD buffer */
                switch(h->FDformat){
                    case SAF_STFT_TIME_CH_BANDS:
                        saf_rfft_forward(h->hFFT, h->insig_rect_win, dataFD[t][ch]);
                        break;

                    case SAF_STFT_BANDS_CH_TIME:
                        saf_rfft_forward(h->hFFT, h->insig_rect_win, h->tmp_fft);
                        for(band=0; band<h->nBands; band++)
                            dataFD[band][ch][t] = h->tmp_fft[band];
                        break;
                }
            }
        }
    }
    /* For oversampled TF transforms */
    else{
        idx = 0;
        for (t = 0; t<nHops; t++){
            for(ch=0; ch < h->nCHin; ch++){
                hIdx = 0;
                /* Window input signal */
                while (hIdx < h->winsize){
                    memcpy(&(h->insig_rect_win[hIdx]), h->prev_inhops[0][ch], h->hopsize*sizeof(float));
                    for(j=0; j< h->nPrevHops-1; j++)
                        memcpy(h->prev_inhops[j][ch], h->prev_inhops[j+1][ch], h->hopsize*sizeof(float));
                    memcpy(h->prev_inhops[h->nPrevHops-1][ch], &dataTD[ch][idx], h->hopsize*sizeof(float));
                    hIdx += h->hopsize;
                }
                utility_svvmul(h->insig_rect_win, h->window, h->winsize, h->insig_win);

                /* Apply FFT and copy data to output dataFD buffer */
                switch(h->FDformat){
                    case SAF_STFT_TIME_CH_BANDS:
                        saf_rfft_forward(h->hFFT, h->insig_win, dataFD[t][ch]);
                        break;

                    case SAF_STFT_BANDS_CH_TIME:
                        saf_rfft_forward(h->hFFT, h->insig_win, h->tmp_fft);
                        for(band=0; band<h->nBands; band++)
                            dataFD[band][ch][t] = h->tmp_fft[band];
                        break;
                }
            }
            idx += h->hopsize;
        }
    }
}

void saf_stft_backward
(
    void * const hSTFT,
    float_complex*** dataFD,
    int framesize,
    float** dataTD
)
{
    saf_stft_data *h = (saf_stft_data*)(hSTFT);
    int t, ch, nHops, band;

    saf_assert(framesize % h->hopsize == 0, "framesize must be multiple of hopsize");
    nHops = framesize/h->hopsize;

    for (t = 0; t<nHops; t++){
        for(ch=0; ch < h->nCHout; ch++){
            /* Shift data down */
            memcpy(h->overlapAddBuffer[ch], h->overlapAddBuffer[ch] + h->hopsize, (h->numOvrlpAddBlocks-1)*(h->hopsize)*sizeof(float));

            /* Append with zeros */
            memset(h->overlapAddBuffer[ch] + (h->numOvrlpAddBlocks-1)*(h->hopsize), 0, h->hopsize*sizeof(float));

            /* Apply inverse FFT */
            switch(h->FDformat){
                case SAF_STFT_TIME_CH_BANDS:
                    saf_rfft_backward(h->hFFT, dataFD[t][ch], h->outsig_win);
                    break;
                case SAF_STFT_BANDS_CH_TIME:
                    for(band=0; band<h->nBands; band++)
                        h->tmp_fft[band] = dataFD[band][ch][t];
                    saf_rfft_backward(h->hFFT, h->tmp_fft, h->outsig_win);
                    break;
            }

            /* Overlap-Add 1:hopsize to output buffer */
            saf_saxpy(h->fftsize, 1.0f, h->outsig_win, 1, h->overlapAddBuffer[ch], 1);
            memcpy(dataTD[ch] + t*(h->hopsize), h->overlapAddBuffer[ch], h->hopsize*sizeof(float));
        }
    }
}

void saf_stft_flushBuffers
(
    void * const hSTFT
)
{
    saf_stft_data *h = (saf_stft_data*)(hSTFT);
    if(h->nPrevHops > 0)
        memset(FLATTEN3D(h->prev_inhops), 0, h->nPrevHops * (h->nCHin) * (h->hopsize) * sizeof(float));
    memset(FLATTEN2D(h->overlapAddBuffer), 0, h->nCHout * (h->bufferlength) * sizeof(float));
}

void saf_stft_channelChange
(
    void * const hSTFT,
    int new_nCHin,
    int new_nCHout
)
{
    saf_stft_data *h = (saf_stft_data*)(hSTFT);
    int i, ch;

    if(new_nCHin != h->nCHin && h->nPrevHops > 0){
        /* Reallocate memory while retaining previous values (which will be
         * truncated if new_nCHin < nCHin) */
        h->prev_inhops = (float***)realloc3d_r((void***)h->prev_inhops, h->nPrevHops, new_nCHin, h->hopsize,
                                               h->nPrevHops, h->nCHin, h->hopsize, sizeof(float));
        /* Zero new channels if new_nCHin > nCHin */
        for(i=0; i< h->nPrevHops; i++)
            for(ch=h->nCHin; ch<new_nCHin; ch++)
                memset(h->prev_inhops[i][ch], 0, h->hopsize * sizeof(float));

        h->nCHin = new_nCHin;
    }

    if(new_nCHout != h->nCHout){
        /* Reallocate memory while retaining previous values (which will be
         * truncated if new_nCHout < nCHout) */
        h->overlapAddBuffer = (float**)realloc2d_r((void**)h->overlapAddBuffer, new_nCHout, h->bufferlength,
                                                   h->nCHout, h->bufferlength, sizeof(float));
        /* Zero new channels if new_nCHout > nCHout */
        for(ch=h->nCHout; ch<new_nCHout; ch++)
            memset(h->overlapAddBuffer[ch], 0, h->bufferlength * sizeof(float));

        h->nCHout = new_nCHout;
    }
}


/* ========================================================================== */
/*                Real<->Half-Complex (Conjugate-Symmetric) FFT               */
/* ========================================================================== */

void saf_rfft_create
(
    void ** const phFFT,
    int N
)
{
    *phFFT = malloc1d(sizeof(saf_rfft_data));
    saf_rfft_data *h = (saf_rfft_data*)(*phFFT);

    h->N = N;
    h->Scale = 1.0f/(float)N; /* output scaling after ifft */
    saf_assert(N>=2 && ISEVEN(N), "Only even (non zero) FFT sizes are supported");
    h->useKissFFT_FLAG = 0;

    /* Use ippsFFT if N is 2^x, otherwise, use ippsDFT */
    if((int)(log2f((float)N)+1.0f) == (int)(log2f((float)N))){
        h->useIPPfft_FLAG = 1;
        h->log2n = (int)(log2f((float)N)+0.1f);
        ippsFFTGetSize_R_32f(h->log2n, IPP_FFT_DIV_INV_BY_N, ippAlgHintNone, &(h->specSize), &(h->specBufferSize), &(h->bufferSize));
        h->hFFTspec = NULL;
        h->memSpec = (Ipp8u*) ippMalloc(h->specSize);
        h->buffer  = (Ipp8u*) ippMalloc(h->bufferSize);
        h->memInit = (Ipp8u*) ippMalloc(h->specBufferSize);
        ippsFFTInit_R_32f(&(h->hFFTspec), h->log2n, IPP_FFT_DIV_INV_BY_N, ippAlgHintNone, h->memSpec, h->memInit);
    }
    else{
        h->useIPPfft_FLAG = 0;
        ippsDFTGetSize_R_32f(N, IPP_FFT_DIV_INV_BY_N, ippAlgHintNone, &(h->specSize), &(h->specBufferSize), &(h->bufferSize));
        h->hDFTspec = (IppsDFTSpec_R_32f*) ippMalloc(h->specSize);
        h->buffer  = (Ipp8u*) ippMalloc(h->bufferSize);
        h->memInit = (Ipp8u*) ippMalloc(h->specBufferSize);
        ippsDFTInit_R_32f(N, IPP_FFT_DIV_INV_BY_N, ippAlgHintNone, h->hDFTspec, h->memInit);
    }
    if (h->memInit)
        ippFree(h->memInit);
}

void saf_rfft_destroy
(
    void ** const phFFT
)
{
    saf_rfft_data *h = (saf_rfft_data*)(*phFFT);
    if(h!=NULL){
        if(h->useIPPfft_FLAG){
            if(h->memSpec)
                ippFree(h->memSpec);
        }
        else {
            if(h->hDFTspec)
                ippFree(h->hDFTspec);
        }
        if(h->buffer)
            ippFree(h->buffer);

        free(h);
        h = NULL;
        *phFFT = NULL;
    }
}

void saf_rfft_forward
(
    void * const hFFT,
    float* inputTD,
    float_complex* outputFD
)
{
    saf_rfft_data *h = (saf_rfft_data*)(hFFT);

    if(h->useIPPfft_FLAG)
        ippsFFTFwd_RToCCS_32f((Ipp32f*)inputTD, (Ipp32f*)outputFD, h->hFFTspec, h->buffer);
    else
        ippsDFTFwd_RToCCS_32f((Ipp32f*)inputTD, (Ipp32f*)outputFD, h->hDFTspec, h->buffer);
}

void saf_rfft_backward
(
    void * const hFFT,
    float_complex* inputFD,
    float* outputTD
)
{
    saf_rfft_data *h = (saf_rfft_data*)(hFFT);

    if(h->useIPPfft_FLAG)
        ippsFFTInv_CCSToR_32f((Ipp32f*)inputFD, (Ipp32f*)outputTD, h->hFFTspec, h->buffer);
    else
        ippsDFTInv_CCSToR_32f((Ipp32f*)inputFD, (Ipp32f*)outputTD, h->hDFTspec, h->buffer);
}


/* ========================================================================== */
/*                            Complex<->Complex FFT                           */
/* ========================================================================== */

void saf_fft_create
(
    void ** const phFFT,
    int N
)
{
    *phFFT = malloc1d(sizeof(saf_fft_data));
    saf_fft_data *h = (saf_fft_data*)(*phFFT);

    h->N = N;
    h->Scale = 1.0f/(float)N; /* output scaling after ifft */
    saf_assert(N>=2, "Only even (non zero) FFT sizes are supported");
    h->useKissFFT_FLAG = 0;

    /* Use ippsFFT if N is 2^x, otherwise, use ippsDFT */
    if((int)(log2f((float)N) + 1.0f) == (int)(log2f((float)N))){
        h->useIPPfft_FLAG = 1;
        h->log2n = (int)(log2f((float)N)+0.1f);
        ippsFFTGetSize_C_32fc(h->log2n, IPP_FFT_DIV_INV_BY_N, ippAlgHintNone, &(h->specSize), &(h->specBufferSize), &(h->bufferSize));
        h->hFFTspec = NULL;
        h->memSpec = (Ipp8u*)ippMalloc(h->specSize);
        h->buffer  = (Ipp8u*)ippMalloc(h->bufferSize);
        h->memInit = (Ipp8u*)ippMalloc(h->specBufferSize);
        ippsFFTInit_C_32fc(&(h->hFFTspec), h->log2n, IPP_FFT_DIV_INV_BY_N, ippAlgHintNone, h->memSpec, h->memInit);
    }
    else{
        h->useIPPfft_FLAG = 0;
        ippsDFTGetSize_C_32fc(N, IPP_FFT_DIV_INV_BY_N, ippAlgHintNone, &(h->specSize), &(h->specBufferSize), &(h->bufferSize));
        h->hDFTspec = (IppsDFTSpec_C_32fc*)ippMalloc(h->specSize);
        h->buffer  = (Ipp8u*)ippMalloc(h->bufferSize);
        h->memInit = (Ipp8u*)ippMalloc(h->specBufferSize);
        ippsDFTInit_C_32fc(N, IPP_FFT_DIV_INV_BY_N, ippAlgHintNone, h->hDFTspec, h->memInit);
    }
    if (h->memInit)
        ippFree(h->memInit);
}

void saf_fft_destroy
(
    void ** const phFFT
)
{
    saf_fft_data *h = (saf_fft_data*)(*phFFT);

    if(h!=NULL){
        if(h->useIPPfft_FLAG){
            if(h->memSpec)
                ippFree(h->memSpec);
        }
        else {
            if(h->hDFTspec)
                ippFree(h->hDFTspec);
        }
        if (h->buffer)
            ippFree(h->buffer);

        free(h);
        h = NULL;
        *phFFT = NULL;
    }
}

void saf_fft_forward
(
    void * const hFFT,
    float_complex* inputTD,
    float_complex* outputFD
)
{
    saf_fft_data *h = (saf_fft_data*)(hFFT);

    if(h->useIPPfft_FLAG)
        ippsFFTFwd_CToC_32fc((Ipp32fc*)inputTD, (Ipp32fc*)outputFD, h->hFFTspec, h->buffer);
    else
        ippsDFTFwd_CToC_32fc((Ipp32fc*)inputTD, (Ipp32fc*)outputFD, h->hDFTspec, h->buffer);
}

void saf_fft_backward
(
    void * const hFFT,
    float_complex* inputFD,
    float_complex* outputTD
)
{
    saf_fft_data *h = (saf_fft_data*)(hFFT);

    if(h->useIPPfft_FLAG)
        ippsFFTInv_CToC_32fc((Ipp32fc*)inputFD, (Ipp32fc*)outputTD, h->hFFTspec, h->buffer);
    else
        ippsDFTInv_CToC_32fc((Ipp32fc*)inputFD, (Ipp32fc*)outputTD, h->hDFTspec, h->buffer);
}