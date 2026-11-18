/* -*- c-basic-offset: 4 indent-tabs-mode: nil -*-  vi:set ts=8 sts=4 sw=4: */

/*
    Rubber Band Library
    An audio time-stretching and pitch-shifting library.
    Copyright 2007-2024 Particular Programs Ltd.

    This program is free software; you can redistribute it and/or
    modify it under the terms of the GNU General Public License as
    published by the Free Software Foundation; either version 2 of the
    License, or (at your option) any later version.  See the file
    COPYING included with this distribution for more information.

    Extracted from src/common/FFT.cpp: the Intel IPP backend, the
    built-in direct-DFT fallback, and the FFT wrapper that dispatches
    between them.  The other backends (FFTW, KissFFT, vDSP, Sleef,
    builtin) are not part of this component.
*/

#include "FFT.h"

#include <ipps.h>
#include <ippversion.h>

#include <cmath>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <map>
#include <set>
#include <string>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

namespace RubberBand {

class FFTImpl
{
public:
    virtual ~FFTImpl() { }

    virtual FFT::Precisions getSupportedPrecisions() const = 0;

    virtual int getSize() const = 0;

    virtual void initFloat() = 0;
    virtual void initDouble() = 0;

    virtual void forward(const double *BQ_R__ realIn, double *BQ_R__ realOut, double *BQ_R__ imagOut) = 0;
    virtual void forwardInterleaved(const double *BQ_R__ realIn, double *BQ_R__ complexOut) = 0;
    virtual void forwardPolar(const double *BQ_R__ realIn, double *BQ_R__ magOut, double *BQ_R__ phaseOut) = 0;
    virtual void forwardMagnitude(const double *BQ_R__ realIn, double *BQ_R__ magOut) = 0;

    virtual void forward(const float *BQ_R__ realIn, float *BQ_R__ realOut, float *BQ_R__ imagOut) = 0;
    virtual void forwardInterleaved(const float *BQ_R__ realIn, float *BQ_R__ complexOut) = 0;
    virtual void forwardPolar(const float *BQ_R__ realIn, float *BQ_R__ magOut, float *BQ_R__ phaseOut) = 0;
    virtual void forwardMagnitude(const float *BQ_R__ realIn, float *BQ_R__ magOut) = 0;

    virtual void inverse(const double *BQ_R__ realIn, const double *BQ_R__ imagIn, double *BQ_R__ realOut) = 0;
    virtual void inverseInterleaved(const double *BQ_R__ complexIn, double *BQ_R__ realOut) = 0;
    virtual void inversePolar(const double *BQ_R__ magIn, const double *BQ_R__ phaseIn, double *BQ_R__ realOut) = 0;
    virtual void inverseCepstral(const double *BQ_R__ magIn, double *BQ_R__ cepOut) = 0;

    virtual void inverse(const float *BQ_R__ realIn, const float *BQ_R__ imagIn, float *BQ_R__ realOut) = 0;
    virtual void inverseInterleaved(const float *BQ_R__ complexIn, float *BQ_R__ realOut) = 0;
    virtual void inversePolar(const float *BQ_R__ magIn, const float *BQ_R__ phaseIn, float *BQ_R__ realOut) = 0;
    virtual void inverseCepstral(const float *BQ_R__ magIn, float *BQ_R__ cepOut) = 0;
};

namespace FFTs {

class D_IPP : public FFTImpl
{
public:
    D_IPP(int size) :
        m_size(size), m_fspec(0), m_dspec(0),
        m_fspecbuf(0), m_dspecbuf(0), m_fbuf(0), m_dbuf(0),
        m_fpacked(0), m_fspare(0), m_dpacked(0), m_dspare(0)
    {
        for (int i = 0; ; ++i) {
            if (m_size & (1 << i)) {
                m_order = i;
                break;
            }
        }
    }

    ~D_IPP() {
        if (m_fspec) {
#if (IPP_VERSION_MAJOR >= 9)
            ippsFree(m_fspecbuf);
#else
            ippsFFTFree_R_32f(m_fspec);
#endif
            ippsFree(m_fbuf);
            ippsFree(m_fpacked);
            ippsFree(m_fspare);
        }
        if (m_dspec) {
#if (IPP_VERSION_MAJOR >= 9)
            ippsFree(m_dspecbuf);
#else
            ippsFFTFree_R_64f(m_dspec);
#endif
            ippsFree(m_dbuf);
            ippsFree(m_dpacked);
            ippsFree(m_dspare);
        }
    }

    int getSize() const {
        return m_size;
    }

    FFT::Precisions
    getSupportedPrecisions() const {
        return FFT::SinglePrecision | FFT::DoublePrecision;
    }

    void initFloat() {
        if (m_fspec) return;
#if (IPP_VERSION_MAJOR >= 9)
        int specSize, specBufferSize, bufferSize;
        ippsFFTGetSize_R_32f(m_order, IPP_FFT_NODIV_BY_ANY, ippAlgHintFast,
                             &specSize, &specBufferSize, &bufferSize);
        m_fspecbuf = ippsMalloc_8u(specSize);
        Ipp8u *tmp = ippsMalloc_8u(specBufferSize);
        m_fbuf = ippsMalloc_8u(bufferSize);
        m_fpacked = ippsMalloc_32f(m_size + 2);
        m_fspare = ippsMalloc_32f(m_size / 2 + 1);
        ippsFFTInit_R_32f(&m_fspec,
                          m_order, IPP_FFT_NODIV_BY_ANY, ippAlgHintFast,
                          m_fspecbuf, tmp);
        ippsFree(tmp);
#else
        int specSize, specBufferSize, bufferSize;
        ippsFFTGetSize_R_32f(m_order, IPP_FFT_NODIV_BY_ANY, ippAlgHintFast,
                             &specSize, &specBufferSize, &bufferSize);
        m_fbuf = ippsMalloc_8u(bufferSize);
        m_fpacked = ippsMalloc_32f(m_size + 2);
        m_fspare = ippsMalloc_32f(m_size / 2 + 1);
        ippsFFTInitAlloc_R_32f(&m_fspec, m_order, IPP_FFT_NODIV_BY_ANY,
                               ippAlgHintFast);
#endif
    }

    void initDouble() {
        if (m_dspec) return;
#if (IPP_VERSION_MAJOR >= 9)
        int specSize, specBufferSize, bufferSize;
        ippsFFTGetSize_R_64f(m_order, IPP_FFT_NODIV_BY_ANY, ippAlgHintFast,
                             &specSize, &specBufferSize, &bufferSize);
        m_dspecbuf = ippsMalloc_8u(specSize);
        Ipp8u *tmp = ippsMalloc_8u(specBufferSize);
        m_dbuf = ippsMalloc_8u(bufferSize);
        m_dpacked = ippsMalloc_64f(m_size + 2);
        m_dspare = ippsMalloc_64f(m_size / 2 + 1);
        ippsFFTInit_R_64f(&m_dspec,
                          m_order, IPP_FFT_NODIV_BY_ANY, ippAlgHintFast,
                          m_dspecbuf, tmp);
        ippsFree(tmp);
#else
        int specSize, specBufferSize, bufferSize;
        ippsFFTGetSize_R_64f(m_order, IPP_FFT_NODIV_BY_ANY, ippAlgHintFast,
                             &specSize, &specBufferSize, &bufferSize);
        m_dbuf = ippsMalloc_8u(bufferSize);
        m_dpacked = ippsMalloc_64f(m_size + 2);
        m_dspare = ippsMalloc_64f(m_size / 2 + 1);
        ippsFFTInitAlloc_R_64f(&m_dspec, m_order, IPP_FFT_NODIV_BY_ANY,
                               ippAlgHintFast);
#endif
    }

    void packFloat(const float *BQ_R__ re, const float *BQ_R__ im) {
        int index = 0;
        const int hs = m_size/2;
        for (int i = 0; i <= hs; ++i) {
            m_fpacked[index++] = re[i];
            index++;
        }
        index = 0;
        if (im) {
            for (int i = 0; i <= hs; ++i) {
                index++;
                m_fpacked[index++] = im[i];
            }
        } else {
            for (int i = 0; i <= hs; ++i) {
                index++;
                m_fpacked[index++] = 0.f;
            }
        }
    }

    void packDouble(const double *BQ_R__ re, const double *BQ_R__ im) {
        int index = 0;
        const int hs = m_size/2;
        for (int i = 0; i <= hs; ++i) {
            m_dpacked[index++] = re[i];
            index++;
        }
        index = 0;
        if (im) {
            for (int i = 0; i <= hs; ++i) {
                index++;
                m_dpacked[index++] = im[i];
            }
        } else {
            for (int i = 0; i <= hs; ++i) {
                index++;
                m_dpacked[index++] = 0.0;
            }
        }
    }

    void unpackFloat(float *re, float *BQ_R__ im) { // re may be equal to m_fpacked
        int index = 0;
        const int hs = m_size/2;
        if (im) {
            for (int i = 0; i <= hs; ++i) {
                index++;
                im[i] = m_fpacked[index++];
            }
        }
        index = 0;
        for (int i = 0; i <= hs; ++i) {
            re[i] = m_fpacked[index++];
            index++;
        }
    }

    void unpackDouble(double *re, double *BQ_R__ im) { // re may be equal to m_dpacked
        int index = 0;
        const int hs = m_size/2;
        if (im) {
            for (int i = 0; i <= hs; ++i) {
                index++;
                im[i] = m_dpacked[index++];
            }
        }
        index = 0;
        for (int i = 0; i <= hs; ++i) {
            re[i] = m_dpacked[index++];
            index++;
        }
    }

    void forward(const double *BQ_R__ realIn, double *BQ_R__ realOut, double *BQ_R__ imagOut) {
        if (!m_dspec) initDouble();
        ippsFFTFwd_RToCCS_64f(realIn, m_dpacked, m_dspec, m_dbuf);
        unpackDouble(realOut, imagOut);
    }

    void forwardInterleaved(const double *BQ_R__ realIn, double *BQ_R__ complexOut) {
        if (!m_dspec) initDouble();
        ippsFFTFwd_RToCCS_64f(realIn, complexOut, m_dspec, m_dbuf);
    }

    void forwardPolar(const double *BQ_R__ realIn, double *BQ_R__ magOut, double *BQ_R__ phaseOut) {
        if (!m_dspec) initDouble();
        ippsFFTFwd_RToCCS_64f(realIn, m_dpacked, m_dspec, m_dbuf);
        unpackDouble(m_dpacked, m_dspare);
        ippsCartToPolar_64f(m_dpacked, m_dspare, magOut, phaseOut, m_size/2+1);
    }

    void forwardMagnitude(const double *BQ_R__ realIn, double *BQ_R__ magOut) {
        if (!m_dspec) initDouble();
        ippsFFTFwd_RToCCS_64f(realIn, m_dpacked, m_dspec, m_dbuf);
        unpackDouble(m_dpacked, m_dspare);
        ippsMagnitude_64f(m_dpacked, m_dspare, magOut, m_size/2+1);
    }

    void forward(const float *BQ_R__ realIn, float *BQ_R__ realOut, float *BQ_R__ imagOut) {
        if (!m_fspec) initFloat();
        ippsFFTFwd_RToCCS_32f(realIn, m_fpacked, m_fspec, m_fbuf);
        unpackFloat(realOut, imagOut);
    }

    void forwardInterleaved(const float *BQ_R__ realIn, float *BQ_R__ complexOut) {
        if (!m_fspec) initFloat();
        ippsFFTFwd_RToCCS_32f(realIn, complexOut, m_fspec, m_fbuf);
    }

    void forwardPolar(const float *BQ_R__ realIn, float *BQ_R__ magOut, float *BQ_R__ phaseOut) {
        if (!m_fspec) initFloat();
        ippsFFTFwd_RToCCS_32f(realIn, m_fpacked, m_fspec, m_fbuf);
        unpackFloat(m_fpacked, m_fspare);
        ippsCartToPolar_32f(m_fpacked, m_fspare, magOut, phaseOut, m_size/2+1);
    }

    void forwardMagnitude(const float *BQ_R__ realIn, float *BQ_R__ magOut) {
        if (!m_fspec) initFloat();
        ippsFFTFwd_RToCCS_32f(realIn, m_fpacked, m_fspec, m_fbuf);
        unpackFloat(m_fpacked, m_fspare);
        ippsMagnitude_32f(m_fpacked, m_fspare, magOut, m_size/2+1);
    }

    void inverse(const double *BQ_R__ realIn, const double *BQ_R__ imagIn, double *BQ_R__ realOut) {
        if (!m_dspec) initDouble();
        packDouble(realIn, imagIn);
        ippsFFTInv_CCSToR_64f(m_dpacked, realOut, m_dspec, m_dbuf);
    }

    void inverseInterleaved(const double *BQ_R__ complexIn, double *BQ_R__ realOut) {
        if (!m_dspec) initDouble();
        ippsFFTInv_CCSToR_64f(complexIn, realOut, m_dspec, m_dbuf);
    }

    void inversePolar(const double *BQ_R__ magIn, const double *BQ_R__ phaseIn, double *BQ_R__ realOut) {
        if (!m_dspec) initDouble();
        ippsPolarToCart_64f(magIn, phaseIn, realOut, m_dspare, m_size/2+1);
        packDouble(realOut, m_dspare); // to m_dpacked
        ippsFFTInv_CCSToR_64f(m_dpacked, realOut, m_dspec, m_dbuf);
    }

    void inverseCepstral(const double *BQ_R__ magIn, double *BQ_R__ cepOut) {
        if (!m_dspec) initDouble();
        const int hs1 = m_size/2 + 1;
        ippsCopy_64f(magIn, m_dspare, hs1);
        ippsAddC_64f_I(0.000001, m_dspare, hs1);
        ippsLn_64f_I(m_dspare, hs1);
        packDouble(m_dspare, 0);
        ippsFFTInv_CCSToR_64f(m_dpacked, cepOut, m_dspec, m_dbuf);
    }

    void inverse(const float *BQ_R__ realIn, const float *BQ_R__ imagIn, float *BQ_R__ realOut) {
        if (!m_fspec) initFloat();
        packFloat(realIn, imagIn);
        ippsFFTInv_CCSToR_32f(m_fpacked, realOut, m_fspec, m_fbuf);
    }

    void inverseInterleaved(const float *BQ_R__ complexIn, float *BQ_R__ realOut) {
        if (!m_fspec) initFloat();
        ippsFFTInv_CCSToR_32f(complexIn, realOut, m_fspec, m_fbuf);
    }

    void inversePolar(const float *BQ_R__ magIn, const float *BQ_R__ phaseIn, float *BQ_R__ realOut) {
        if (!m_fspec) initFloat();
        ippsPolarToCart_32f(magIn, phaseIn, realOut, m_fspare, m_size/2+1);
        packFloat(realOut, m_fspare); // to m_fpacked
        ippsFFTInv_CCSToR_32f(m_fpacked, realOut, m_fspec, m_fbuf);
    }

    void inverseCepstral(const float *BQ_R__ magIn, float *BQ_R__ cepOut) {
        if (!m_fspec) initFloat();
        const int hs1 = m_size/2 + 1;
        ippsCopy_32f(magIn, m_fspare, hs1);
        ippsAddC_32f_I(0.000001f, m_fspare, hs1);
        ippsLn_32f_I(m_fspare, hs1);
        packFloat(m_fspare, 0);
        ippsFFTInv_CCSToR_32f(m_fpacked, cepOut, m_fspec, m_fbuf);
    }

private:
    const int m_size;
    int m_order;
    IppsFFTSpec_R_32f *m_fspec;
    IppsFFTSpec_R_64f *m_dspec;
    Ipp8u *m_fspecbuf;
    Ipp8u *m_dspecbuf;
    Ipp8u *m_fbuf;
    Ipp8u *m_dbuf;
    float *m_fpacked;
    float *m_fspare;
    double *m_dpacked;
    double *m_dspare;
};

/* Direct DFT fallback, used for sizes the compiled-in FFT backends do not
 * support (odd sizes, and powers of two below 4).  Unchanged from the
 * original FFT.cpp.
 */
class D_DFT : public FFTImpl
{
private:
    template <typename T>
    class DFT
    {
    public:
        DFT(int size) : m_size(size), m_bins(size/2 + 1) {

            m_sin = allocate_channels<double>(m_size, m_size);
            m_cos = allocate_channels<double>(m_size, m_size);

            for (int i = 0; i < m_size; ++i) {
                for (int j = 0; j < m_size; ++j) {
                    double arg = (double(i) * double(j) * M_PI * 2.0) / m_size;
                    m_sin[i][j] = sin(arg);
                    m_cos[i][j] = cos(arg);
                }
            }

            m_tmp = allocate_channels<double>(2, m_size);
        }

        ~DFT() {
            deallocate_channels(m_tmp, 2);
            deallocate_channels(m_sin, m_size);
            deallocate_channels(m_cos, m_size);
        }

        void forward(const T *BQ_R__ realIn, T *BQ_R__ realOut, T *BQ_R__ imagOut) {
            for (int i = 0; i < m_bins; ++i) {
                double re = 0.0, im = 0.0;
                for (int j = 0; j < m_size; ++j) re += realIn[j] * m_cos[i][j];
                for (int j = 0; j < m_size; ++j) im -= realIn[j] * m_sin[i][j];
                realOut[i] = T(re);
                imagOut[i] = T(im);
            }
        }

        void forwardInterleaved(const T *BQ_R__ realIn, T *BQ_R__ complexOut) {
            for (int i = 0; i < m_bins; ++i) {
                double re = 0.0, im = 0.0;
                for (int j = 0; j < m_size; ++j) re += realIn[j] * m_cos[i][j];
                for (int j = 0; j < m_size; ++j) im -= realIn[j] * m_sin[i][j];
                complexOut[i*2] = T(re);
                complexOut[i*2 + 1] = T(im);
            }
        }

        void forwardPolar(const T *BQ_R__ realIn, T *BQ_R__ magOut, T *BQ_R__ phaseOut) {
            forward(realIn, magOut, phaseOut); // temporarily
            for (int i = 0; i < m_bins; ++i) {
                T re = magOut[i], im = phaseOut[i];
                c_magphase(magOut + i, phaseOut + i, re, im);
            }
        }

        void forwardMagnitude(const T *BQ_R__ realIn, T *BQ_R__ magOut) {
            for (int i = 0; i < m_bins; ++i) {
                double re = 0.0, im = 0.0;
                for (int j = 0; j < m_size; ++j) re += realIn[j] * m_cos[i][j];
                for (int j = 0; j < m_size; ++j) im -= realIn[j] * m_sin[i][j];
                magOut[i] = T(sqrt(re * re + im * im));
            }
        }

        void inverse(const T *BQ_R__ realIn, const T *BQ_R__ imagIn, T *BQ_R__ realOut) {
            for (int i = 0; i < m_bins; ++i) {
                m_tmp[0][i] = realIn[i];
                m_tmp[1][i] = imagIn[i];
            }
            for (int i = m_bins; i < m_size; ++i) {
                m_tmp[0][i] = realIn[m_size - i];
                m_tmp[1][i] = -imagIn[m_size - i];
            }
            for (int i = 0; i < m_size; ++i) {
                double re = 0.0;
                const double *const cos = m_cos[i];
                const double *const sin = m_sin[i];
                for (int j = 0; j < m_size; ++j) re += m_tmp[0][j] * cos[j];
                for (int j = 0; j < m_size; ++j) re -= m_tmp[1][j] * sin[j];
                realOut[i] = T(re);
            }
        }

        void inverseInterleaved(const T *BQ_R__ complexIn, T *BQ_R__ realOut) {
            for (int i = 0; i < m_bins; ++i) {
                m_tmp[0][i] = complexIn[i*2];
                m_tmp[1][i] = complexIn[i*2+1];
            }
            for (int i = m_bins; i < m_size; ++i) {
                m_tmp[0][i] = complexIn[(m_size - i) * 2];
                m_tmp[1][i] = -complexIn[(m_size - i) * 2 + 1];
            }
            for (int i = 0; i < m_size; ++i) {
                double re = 0.0;
                const double *const cos = m_cos[i];
                const double *const sin = m_sin[i];
                for (int j = 0; j < m_size; ++j) re += m_tmp[0][j] * cos[j];
                for (int j = 0; j < m_size; ++j) re -= m_tmp[1][j] * sin[j];
                realOut[i] = T(re);
            }
        }

        void inversePolar(const T *BQ_R__ magIn, const T *BQ_R__ phaseIn, T *BQ_R__ realOut) {
            T *complexIn = allocate<T>(m_bins * 2);
            v_polar_to_cartesian_interleaved(complexIn, magIn, phaseIn, m_bins);
            inverseInterleaved(complexIn, realOut);
            deallocate(complexIn);
        }

        void inverseCepstral(const T *BQ_R__ magIn, T *BQ_R__ cepOut) {
            T *complexIn = allocate_and_zero<T>(m_bins * 2);
            for (int i = 0; i < m_bins; ++i) {
                complexIn[i*2] = T(log(magIn[i] + 0.000001));
            }
            inverseInterleaved(complexIn, cepOut);
            deallocate(complexIn);
        }

    private:
        const int m_size;
        const int m_bins;
        double **m_sin;
        double **m_cos;
        double **m_tmp;
    };

public:
    D_DFT(int size) : m_size(size), m_double(0), m_float(0) { }

    ~D_DFT() {
        delete m_double;
        delete m_float;
    }

    int getSize() const {
        return m_size;
    }

    FFT::Precisions
    getSupportedPrecisions() const {
        return FFT::DoublePrecision;
    }

    void initFloat() {
        if (!m_float) {
            m_float = new DFT<float>(m_size);
        }
    }

    void initDouble() {
        if (!m_double) {
            m_double = new DFT<double>(m_size);
        }
    }

    void forward(const double *BQ_R__ realIn, double *BQ_R__ realOut, double *BQ_R__ imagOut) {
        initDouble();
        m_double->forward(realIn, realOut, imagOut);
    }

    void forwardInterleaved(const double *BQ_R__ realIn, double *BQ_R__ complexOut) {
        initDouble();
        m_double->forwardInterleaved(realIn, complexOut);
    }

    void forwardPolar(const double *BQ_R__ realIn, double *BQ_R__ magOut, double *BQ_R__ phaseOut) {
        initDouble();
        m_double->forwardPolar(realIn, magOut, phaseOut);
    }

    void forwardMagnitude(const double *BQ_R__ realIn, double *BQ_R__ magOut) {
        initDouble();
        m_double->forwardMagnitude(realIn, magOut);
    }

    void forward(const float *BQ_R__ realIn, float *BQ_R__ realOut, float *BQ_R__ imagOut) {
        initFloat();
        m_float->forward(realIn, realOut, imagOut);
    }

    void forwardInterleaved(const float *BQ_R__ realIn, float *BQ_R__ complexOut) {
        initFloat();
        m_float->forwardInterleaved(realIn, complexOut);
    }

    void forwardPolar(const float *BQ_R__ realIn, float *BQ_R__ magOut, float *BQ_R__ phaseOut) {
        initFloat();
        m_float->forwardPolar(realIn, magOut, phaseOut);
    }

    void forwardMagnitude(const float *BQ_R__ realIn, float *BQ_R__ magOut) {
        initFloat();
        m_float->forwardMagnitude(realIn, magOut);
    }

    void inverse(const double *BQ_R__ realIn, const double *BQ_R__ imagIn, double *BQ_R__ realOut) {
        initDouble();
        m_double->inverse(realIn, imagIn, realOut);
    }

    void inverseInterleaved(const double *BQ_R__ complexIn, double *BQ_R__ realOut) {
        initDouble();
        m_double->inverseInterleaved(complexIn, realOut);
    }

    void inversePolar(const double *BQ_R__ magIn, const double *BQ_R__ phaseIn, double *BQ_R__ realOut) {
        initDouble();
        m_double->inversePolar(magIn, phaseIn, realOut);
    }

    void inverseCepstral(const double *BQ_R__ magIn, double *BQ_R__ cepOut) {
        initDouble();
        m_double->inverseCepstral(magIn, cepOut);
    }

    void inverse(const float *BQ_R__ realIn, const float *BQ_R__ imagIn, float *BQ_R__ realOut) {
        initFloat();
        m_float->inverse(realIn, imagIn, realOut);
    }

    void inverseInterleaved(const float *BQ_R__ complexIn, float *BQ_R__ realOut) {
        initFloat();
        m_float->inverseInterleaved(complexIn, realOut);
    }

    void inversePolar(const float *BQ_R__ magIn, const float *BQ_R__ phaseIn, float *BQ_R__ realOut) {
        initFloat();
        m_float->inversePolar(magIn, phaseIn, realOut);
    }

    void inverseCepstral(const float *BQ_R__ magIn, float *BQ_R__ cepOut) {
        initFloat();
        m_float->inverseCepstral(magIn, cepOut);
    }

private:
    int m_size;
    DFT<double> *m_double;
    DFT<float> *m_float;
};

} /* end namespace FFTs */

enum SizeConstraint {
    SizeConstraintNone           = 0x0,
    SizeConstraintEven           = 0x1,
    SizeConstraintPowerOfTwo     = 0x2,
    SizeConstraintEvenPowerOfTwo = 0x3 // i.e. 0x1 | 0x2. Excludes size 1 obvs
};

typedef std::map<std::string, SizeConstraint> ImplMap;

static std::string defaultImplementation;

static ImplMap
getImplementationDetails()
{
    ImplMap impls;

#ifdef HAVE_IPP
    impls["ipp"] = SizeConstraintEvenPowerOfTwo;
#endif

    impls["dft"] = SizeConstraintNone;

    return impls;
}

static std::string
pickImplementation(int size)
{
    ImplMap impls = getImplementationDetails();

    bool isPowerOfTwo = !(size & (size-1));
    bool isEven = !(size & 1);

    if (defaultImplementation != "") {
        ImplMap::const_iterator itr = impls.find(defaultImplementation);
        if (itr != impls.end()) {
            if (((itr->second & SizeConstraintPowerOfTwo) && !isPowerOfTwo) ||
                ((itr->second & SizeConstraintEven) && !isEven)) {
                // fall through to the preference list
            } else {
                return defaultImplementation;
            }
        } else {
            std::cerr << "WARNING: bqfft: Default implementation \""
                      << defaultImplementation << "\" is not compiled in"
                      << std::endl;
        }
    }

    std::string preference[] = {
        "ipp", "dft"
    };

    for (int i = 0; i < int(sizeof(preference)/sizeof(preference[0])); ++i) {
        ImplMap::const_iterator itr = impls.find(preference[i]);
        if (itr != impls.end()) {
            if ((itr->second & SizeConstraintPowerOfTwo) &&
                // out of an abundance of caution we don't attempt to
                // use power-of-two implementations with size 2
                // either, as they may involve a half-half
                // complex-complex underneath (which would end up with
                // size 0)
                (!isPowerOfTwo || size < 4)) {
                continue;
            }
            if ((itr->second & SizeConstraintEven) && !isEven) {
                continue;
            }
            return preference[i];
        }
    }

    std::cerr << "WARNING: bqfft: No compiled-in implementation supports size "
              << size << ", falling back to slow DFT" << std::endl;

    return "dft";
}

std::set<std::string>
FFT::getImplementations()
{
    ImplMap impls = getImplementationDetails();
    std::set<std::string> toReturn;
    for (ImplMap::const_iterator i = impls.begin(); i != impls.end(); ++i) {
        toReturn.insert(i->first);
    }
    return toReturn;
}

std::string
FFT::getDefaultImplementation()
{
    return defaultImplementation;
}

void
FFT::setDefaultImplementation(std::string i)
{
    if (i == "") {
        defaultImplementation = i;
        return;
    }
    ImplMap impls = getImplementationDetails();
    ImplMap::const_iterator itr = impls.find(i);
    if (itr == impls.end()) {
        std::cerr << "WARNING: bqfft: setDefaultImplementation: "
                  << "requested implementation \"" << i
                  << "\" is not compiled in" << std::endl;
    } else {
        defaultImplementation = i;
    }
}

FFT::FFT(int size, int debugLevel) :
    d(0)
{
    if (size < 2) {
        throw InvalidSize;
    }

    std::string impl = pickImplementation(size);

    if (debugLevel > 0) {
        std::cerr << "FFT::FFT(" << size << "): using implementation: "
                  << impl << std::endl;
    }

    if (impl == "ipp") {
#ifdef HAVE_IPP
        d = new FFTs::D_IPP(size);
#endif
    } else if (impl == "dft") {
        d = new FFTs::D_DFT(size);
    }

    if (!d) {
        std::cerr << "FFT::FFT(" << size << "): ERROR: implementation "
                  << impl << " is not compiled in" << std::endl;
        throw InvalidImplementation;
    }
}

FFT::~FFT()
{
    delete d;
}

#define CHECK_NOT_NULL(x) \
    if (!(x)) { \
        std::cerr << "FFT: ERROR: Null argument " #x << std::endl;  \
        throw NullArgument; \
    }

void
FFT::forward(const double *BQ_R__ realIn, double *BQ_R__ realOut, double *BQ_R__ imagOut)
{
    CHECK_NOT_NULL(realIn);
    CHECK_NOT_NULL(realOut);
    CHECK_NOT_NULL(imagOut);
    d->forward(realIn, realOut, imagOut);
}

void
FFT::forwardInterleaved(const double *BQ_R__ realIn, double *BQ_R__ complexOut)
{
    CHECK_NOT_NULL(realIn);
    CHECK_NOT_NULL(complexOut);
    d->forwardInterleaved(realIn, complexOut);
}

void
FFT::forwardPolar(const double *BQ_R__ realIn, double *BQ_R__ magOut, double *BQ_R__ phaseOut)
{
    CHECK_NOT_NULL(realIn);
    CHECK_NOT_NULL(magOut);
    CHECK_NOT_NULL(phaseOut);
    d->forwardPolar(realIn, magOut, phaseOut);
}

void
FFT::forwardMagnitude(const double *BQ_R__ realIn, double *BQ_R__ magOut)
{
    CHECK_NOT_NULL(realIn);
    CHECK_NOT_NULL(magOut);
    d->forwardMagnitude(realIn, magOut);
}

void
FFT::forward(const float *BQ_R__ realIn, float *BQ_R__ realOut, float *BQ_R__ imagOut)
{
    CHECK_NOT_NULL(realIn);
    CHECK_NOT_NULL(realOut);
    CHECK_NOT_NULL(imagOut);
    d->forward(realIn, realOut, imagOut);
}

void
FFT::forwardInterleaved(const float *BQ_R__ realIn, float *BQ_R__ complexOut)
{
    CHECK_NOT_NULL(realIn);
    CHECK_NOT_NULL(complexOut);
    d->forwardInterleaved(realIn, complexOut);
}

void
FFT::forwardPolar(const float *BQ_R__ realIn, float *BQ_R__ magOut, float *BQ_R__ phaseOut)
{
    CHECK_NOT_NULL(realIn);
    CHECK_NOT_NULL(magOut);
    CHECK_NOT_NULL(phaseOut);
    d->forwardPolar(realIn, magOut, phaseOut);
}

void
FFT::forwardMagnitude(const float *BQ_R__ realIn, float *BQ_R__ magOut)
{
    CHECK_NOT_NULL(realIn);
    CHECK_NOT_NULL(magOut);
    d->forwardMagnitude(realIn, magOut);
}

void
FFT::inverse(const double *BQ_R__ realIn, const double *BQ_R__ imagIn, double *BQ_R__ realOut)
{
    CHECK_NOT_NULL(realIn);
    CHECK_NOT_NULL(imagIn);
    CHECK_NOT_NULL(realOut);
    d->inverse(realIn, imagIn, realOut);
}

void
FFT::inverseInterleaved(const double *BQ_R__ complexIn, double *BQ_R__ realOut)
{
    CHECK_NOT_NULL(complexIn);
    CHECK_NOT_NULL(realOut);
    d->inverseInterleaved(complexIn, realOut);
}

void
FFT::inversePolar(const double *BQ_R__ magIn, const double *BQ_R__ phaseIn, double *BQ_R__ realOut)
{
    CHECK_NOT_NULL(magIn);
    CHECK_NOT_NULL(phaseIn);
    CHECK_NOT_NULL(realOut);
    d->inversePolar(magIn, phaseIn, realOut);
}

void
FFT::inverseCepstral(const double *BQ_R__ magIn, double *BQ_R__ cepOut)
{
    CHECK_NOT_NULL(magIn);
    CHECK_NOT_NULL(cepOut);
    d->inverseCepstral(magIn, cepOut);
}

void
FFT::inverse(const float *BQ_R__ realIn, const float *BQ_R__ imagIn, float *BQ_R__ realOut)
{
    CHECK_NOT_NULL(realIn);
    CHECK_NOT_NULL(imagIn);
    CHECK_NOT_NULL(realOut);
    d->inverse(realIn, imagIn, realOut);
}

void
FFT::inverseInterleaved(const float *BQ_R__ complexIn, float *BQ_R__ realOut)
{
    CHECK_NOT_NULL(complexIn);
    CHECK_NOT_NULL(realOut);
    d->inverseInterleaved(complexIn, realOut);
}

void
FFT::inversePolar(const float *BQ_R__ magIn, const float *BQ_R__ phaseIn, float *BQ_R__ realOut)
{
    CHECK_NOT_NULL(magIn);
    CHECK_NOT_NULL(phaseIn);
    CHECK_NOT_NULL(realOut);
    d->inversePolar(magIn, phaseIn, realOut);
}

void
FFT::inverseCepstral(const float *BQ_R__ magIn, float *BQ_R__ cepOut)
{
    CHECK_NOT_NULL(magIn);
    CHECK_NOT_NULL(cepOut);
    d->inverseCepstral(magIn, cepOut);
}

void
FFT::initFloat()
{
    d->initFloat();
}

void
FFT::initDouble()
{
    d->initDouble();
}

int
FFT::getSize() const
{
    return d->getSize();
}

FFT::Precisions
FFT::getSupportedPrecisions() const
{
    return d->getSupportedPrecisions();
}

} /* end namespace RubberBand */