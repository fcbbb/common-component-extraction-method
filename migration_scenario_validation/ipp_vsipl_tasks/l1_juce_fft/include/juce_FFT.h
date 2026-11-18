/*
  ==============================================================================

   This file is part of the JUCE framework (trimmed for this task package).

   Copyright (c) Raw Material Software Limited

   JUCE is an open source framework subject to commercial or open source
   licensing.  See the original JUCE End User Licence Agreement for terms.

   This header keeps the public surface of juce::dsp::FFT that the migration
   task exercises: the order -> size mapping, the out-of-place complex
   transform, the in-place real transform with its CCS/mirrored layout, and
   the magnitude-only transform.

  ==============================================================================
*/

#pragma once

#include <complex>
#include <memory>

namespace juce::dsp
{

/** JUCE's Complex<T> is a std::complex<T> with a few convenience members; the
    task only needs the standard interface. */
template <typename Type>
using Complex = std::complex<Type>;

/** Performs a discrete Fourier transform of a fixed size.

    The object holds the transform plans; create one per size/direction and
    reuse it.  The number of points is 2 ^ order.
*/
class FFT
{
public:
    /** Creates a transform for 2 ^ order points. */
    explicit FFT (int order);

    ~FFT();

    FFT (FFT&&) noexcept;
    FFT& operator= (FFT&&) noexcept;

    /** Out-of-place complex transform of getSize() points.  The inverse is
        scaled by 1 / getSize(), so forward followed by inverse is the
        identity. */
    void perform (const Complex<float>* input, Complex<float>* output,
                  bool inverse) const noexcept;

    /** In-place forward transform of a block of real data.

        inputOutputData has 2 * getSize() floats; the first getSize() are the
        real samples.  On return the array holds the interleaved complex
        spectrum.  When onlyCalculateNonNegativeFrequencies is false the
        negative-frequency half is filled with the conjugate mirror of the
        positive half; when true only the first (size / 2) + 1 complex values
        are defined.
    */
    void performRealOnlyForwardTransform (float* inputOutputData,
                                          bool onlyCalculateNonNegativeFrequencies = false) const noexcept;

    /** Reverses performRealOnlyForwardTransform().  Only the first
        (size / 2) + 1 complex values are read; on return the first getSize()
        floats hold the samples. */
    void performRealOnlyInverseTransform (float* inputOutputData) const noexcept;

    /** Transforms the block and replaces it with magnitude values: getSize()
        magnitudes when onlyCalculateNonNegativeFrequencies is false, else
        (size / 2) + 1 magnitudes followed by zeros. */
    void performFrequencyOnlyForwardTransform (float* inputOutputData,
                                               bool onlyCalculateNonNegativeFrequencies = false) const noexcept;

    /** Returns the number of points this object was created for. */
    int getSize() const noexcept { return size; }

private:
    struct Impl;
    std::unique_ptr<Impl> impl;
    int size = 0;
};

} // namespace juce::dsp