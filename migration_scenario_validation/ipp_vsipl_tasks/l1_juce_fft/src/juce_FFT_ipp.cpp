/*
  ==============================================================================

   This file is part of the JUCE framework (trimmed for this task package).

   Copyright (c) Raw Material Software Limited

   JUCE is an open source framework subject to commercial or open source
   licensing.  See the original JUCE End User Licence Agreement for terms.

   Intel Performance Primitives FFT backend, extracted from
   modules/juce_dsp/frequency/juce_FFT.cpp (JUCE 9.0.5).  The engine registry
   and the scalar fallback are not part of the task; only the IPP engine is
   kept.

  ==============================================================================
*/

#include "juce_FFT.h"

#include <ipp.h>

#include <cmath>
#include <cstring>

namespace juce::dsp
{

struct FFT::Impl
{
    static constexpr auto flag = IPP_FFT_DIV_INV_BY_N;
    static constexpr auto hint = ippAlgHintFast;

    struct IppFree
    {
        void operator() (Ipp8u* ptr) const noexcept { ippsFree (ptr); }
    };

    using IppPtr = std::unique_ptr<Ipp8u[], IppFree>;

    struct Context
    {
        IppPtr specBuf, workBuf;
        void*  specPtr = nullptr;     // IppsFFTSpec_C_32fc* or IppsFFTSpec_R_32f*

        template <typename Spec, typename GetSizeFn, typename InitFn>
        bool build (int order, GetSizeFn getSize, InitFn init)
        {
            int specSize = 0, initSize = 0, workSize = 0;

            if (getSize (order, flag, hint, &specSize, &initSize, &workSize) != ippStsNoErr)
                return false;

            IppPtr initBuf { ippsMalloc_8u (initSize) };
            specBuf = IppPtr { ippsMalloc_8u (specSize) };

            Spec* spec = nullptr;
            if (init (&spec, order, flag, hint, specBuf.get(), initBuf.get()) != ippStsNoErr)
                return false;

            specPtr = spec;
            workBuf = IppPtr { ippsMalloc_8u (workSize) };
            return true;
        }

        bool isValid() const noexcept { return specPtr != nullptr; }
    };

    Context cplx, real;
    int order = 0;
};

//==============================================================================
FFT::FFT (int order)
{
    impl = std::make_unique<Impl>();
    impl->order = order;
    size = 1 << order;

    const bool c = impl->cplx.build<IppsFFTSpec_C_32fc> (order, ippsFFTGetSize_C_32fc, ippsFFTInit_C_32fc);
    const bool r = impl->real.build<IppsFFTSpec_R_32f>  (order, ippsFFTGetSize_R_32f,  ippsFFTInit_R_32f);

    if (! c || ! r)
        impl.reset();
}

FFT::FFT (FFT&&) noexcept = default;
FFT& FFT::operator= (FFT&&) noexcept = default;
FFT::~FFT() = default;

void FFT::perform (const Complex<float>* input, Complex<float>* output, bool inverse) const noexcept
{
    if (impl == nullptr)
        return;

    auto* spec = static_cast<IppsFFTSpec_C_32fc*> (impl->cplx.specPtr);

    if (inverse)
    {
        ippsFFTInv_CToC_32fc (reinterpret_cast<const Ipp32fc*> (input),
                              reinterpret_cast<Ipp32fc*> (output),
                              spec,
                              impl->cplx.workBuf.get());
    }
    else
    {
        ippsFFTFwd_CToC_32fc (reinterpret_cast<const Ipp32fc*> (input),
                              reinterpret_cast<Ipp32fc*> (output),
                              spec,
                              impl->cplx.workBuf.get());
    }
}

void FFT::performRealOnlyForwardTransform (float* inputOutputData, bool ignoreNegativeFreqs) const noexcept
{
    if (impl == nullptr)
        return;

    ippsFFTFwd_RToCCS_32f_I (inputOutputData,
                             static_cast<IppsFFTSpec_R_32f*> (impl->real.specPtr),
                             impl->real.workBuf.get());

    if (impl->order == 0)
        return;

    auto* out = reinterpret_cast<Complex<float>*> (inputOutputData);

    if (! ignoreNegativeFreqs)
        for (auto i = size >> 1; i < size; ++i)
            out[i] = std::conj (out[size - i]);
}

void FFT::performRealOnlyInverseTransform (float* inputOutputData) const noexcept
{
    if (impl == nullptr)
        return;

    ippsFFTInv_CCSToR_32f_I (inputOutputData,
                             static_cast<IppsFFTSpec_R_32f*> (impl->real.specPtr),
                             impl->real.workBuf.get());
}

void FFT::performFrequencyOnlyForwardTransform (float* inputOutputData, bool ignoreNegativeFreqs) const noexcept
{
    if (size == 1)
        return;

    performRealOnlyForwardTransform (inputOutputData, ignoreNegativeFreqs);
    auto* out = reinterpret_cast<Complex<float>*> (inputOutputData);

    const auto limit = ignoreNegativeFreqs ? (size / 2) + 1 : size;

    for (int i = 0; i < limit; ++i)
        inputOutputData[i] = std::abs (out[i]);

    std::memset (inputOutputData + limit, 0, static_cast<size_t> (size * 2 - limit) * sizeof (float));
}

} // namespace juce::dsp