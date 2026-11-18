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
 * @file saf_utility_fft.h
 * @brief Wrappers for optimised discrete/fast Fourier transform (FFT) routines
 * @license ISC
 *
 * Extracted from the Spatial_Audio_Framework: the public declarations are the
 * upstream ones, the doxygen prose is trimmed, and the dependency on
 * saf_utility_complex.h is replaced by the C99 complex type in saf_support.h.
 */

#ifndef SAF_FFT_H_INCLUDED
#define SAF_FFT_H_INCLUDED

#include "saf_support.h"

#ifdef __cplusplus
extern "C" {
#endif /* __cplusplus */

/** Options for how the frequency domain data is permuted when using saf_stft */
typedef enum {
    SAF_STFT_BANDS_CH_TIME, /**< nBands x nChannels x nTimeHops */
    SAF_STFT_TIME_CH_BANDS  /**< nTimeHops x nChannels x nBands */

}SAF_STFT_FDDATA_FORMAT;

/* ========================================================================== */
/*                               Misc. Functions                              */
/* ========================================================================== */

/** Calculates the frequencies (in Hz) of uniformly spaced bins. */
void getUniformFreqVector(int fftSize,
                          float fs,
                          float* freqVector);

/** FFT-based convolution of signal 'x' with filter 'h' (zero padded). */
void fftconv(float* x,
             float* h,
             int x_len,
             int h_len,
             int nCH,
             float* y);

/** FFT-based convolution for FIR filters; only the first x_len samples. */
void fftfilt(float* x,
             float* h,
             int x_len,
             int h_len,
             int nCH,
             float* y);

/** Computes the discrete-time analytic signal via the Hilbert transform. */
void hilbert(float_complex* x,
             int x_len,
             float_complex* y);


/* ========================================================================== */
/*                     Short-time Fourier Transform (STFT)                    */
/* ========================================================================== */

/** Creates an instance of saf_stft. */
void saf_stft_create(void ** const phSTFT,
                     int winsize,
                     int hopsize,
                     int nCHin,
                     int nCHout,
                     SAF_STFT_FDDATA_FORMAT FDformat);

/** Destroys an instance of saf_stft. */
void saf_stft_destroy(void ** const phSTFT);

/** Performs the forward-STFT operation for the current frame. */
void saf_stft_forward(void * const hSTFT,
                      float** dataTD,
                      int framesize,
                      float_complex*** dataFD);

/** Performs the backward-STFT operation for the current frame. */
void saf_stft_backward(void * const hSTFT,
                       float_complex*** dataFD,
                       int framesize,
                       float** dataTD);

/** Flushes the internal buffers with zeros. */
void saf_stft_flushBuffers(void * const hSTFT);

/** Changes the number of input/output channels. */
void saf_stft_channelChange(void * const hSTFT,
                            int new_nCHin,
                            int new_nCHout);


/* ========================================================================== */
/*                Real<->Half-Complex (Conjugate-Symmetric) FFT               */
/* ========================================================================== */

/** Creates an instance of saf_rfft; real<->half-complex FFT. */
void saf_rfft_create(void ** const phFFT,
                     int N);

/** Destroys an instance of saf_rfft. */
void saf_rfft_destroy(void ** const phFFT);

/** Performs the forward-FFT operation (real to half-complex). */
void saf_rfft_forward(void * const hFFT,
                      float* inputTD,
                      float_complex* outputFD);

/** Performs the backward-FFT operation (half-complex to real). */
void saf_rfft_backward(void * const hFFT,
                       float_complex* inputFD,
                       float* outputTD);


/* ========================================================================== */
/*                            Complex<->Complex FFT                           */
/* ========================================================================== */

/** Creates an instance of saf_fft; complex<->complex FFT. */
void saf_fft_create(void ** const phFFT,
                    int N);

/** Destroys an instance of saf_fft. */
void saf_fft_destroy(void ** const phFFT);

/** Performs the forward-FFT operation (complex to complex). */
void saf_fft_forward(void * const hFFT,
                     float_complex* inputTD,
                     float_complex* outputFD);

/** Performs the backward-FFT operation (complex to complex). */
void saf_fft_backward(void * const hFFT,
                      float_complex* inputFD,
                      float_complex* outputTD);

#ifdef __cplusplus
}/* extern "C" */
#endif /* __cplusplus */

#endif /* SAF_FFT_H_INCLUDED */