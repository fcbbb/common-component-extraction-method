// Generates the hidden case containers from the IPP build of the component.
//
// Container layout (little endian, native float32):
//   "JUCF"
//   int32 order, op, n, ncompare
//   float32 in[2*n]
//   float32 expected[2*n]
//
// Only the first ncompare floats of `expected` are part of the contract:
//   complex transforms   -> 2*n
//   real forward (full)  -> 2*n   (half spectrum + conjugate mirror)
//   real forward (half)  -> n + 2 (the (n/2 + 1) complex values IPP writes)
//   real inverse         -> n
//   frequency only       -> 2*n   (magnitudes followed by zeros)
//
// Input generation per op:
//   complex      : 2*n random floats (n complex values)
//   real forward : n random samples, the rest zero
//   real inverse : n random samples, transformed forward first, so the stored
//                  input is a genuine conjugate-symmetric spectrum
//   frequency    : n random samples, the rest zero
//
// Usage: golden_gen <out-dir>
#include <cmath>
#include <complex>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

#include "juce_FFT.h"
#include "cases.h"

using juce::dsp::Complex;
using juce::dsp::FFT;

int main(int argc, char** argv)
{
    const char* dir = (argc > 1) ? argv[1] : "hidden";
    char path[512];
    std::uint64_t seed = 0x4A554345ULL;

    for (int ci = 0; ci < JUCE_NCASES; ++ci)
    {
        const juce_case& c = juce_cases[ci];
        const int n = 1 << c.order;
        const size_t nf = 2 * static_cast<size_t>(n);

        FFT fft(c.order);
        if (fft.getSize() != n)
        {
            fprintf(stderr, "case %d: getSize()=%d, expected %d\n", ci, fft.getSize(), n);
            return 2;
        }

        std::vector<float> in(nf, 0.0f);
        std::vector<float> expected(nf, 0.0f);

        for (int i = 0; i < n; ++i)
            in[static_cast<size_t>(i)] = juce_rand(&seed);
        if (c.op == OP_COMPLEX_FWD || c.op == OP_COMPLEX_INV)
            for (int i = n; i < 2 * n; ++i)
                in[static_cast<size_t>(i)] = juce_rand(&seed);

        expected = in;

        switch (c.op)
        {
            case OP_COMPLEX_FWD:
                fft.perform(reinterpret_cast<const Complex<float>*>(in.data()),
                            reinterpret_cast<Complex<float>*>(expected.data()), false);
                break;
            case OP_COMPLEX_INV:
                fft.perform(reinterpret_cast<const Complex<float>*>(in.data()),
                            reinterpret_cast<Complex<float>*>(expected.data()), true);
                break;
            case OP_REAL_FWD:
                fft.performRealOnlyForwardTransform(expected.data(), false);
                break;
            case OP_REAL_FWD_HALF:
                fft.performRealOnlyForwardTransform(expected.data(), true);
                break;
            case OP_REAL_INV:
                // Forward first so the stored input is a real spectrum.
                fft.performRealOnlyForwardTransform(in.data(), false);
                expected = in;
                fft.performRealOnlyInverseTransform(expected.data());
                break;
            case OP_FREQ_ONLY:
                fft.performFrequencyOnlyForwardTransform(expected.data(), false);
                break;
            case OP_FREQ_ONLY_HALF:
                fft.performFrequencyOnlyForwardTransform(expected.data(), true);
                break;
            default:
                fprintf(stderr, "case %d: bad op %d\n", ci, c.op);
                return 2;
        }

        snprintf(path, sizeof(path), "%s/case_%d.bin", dir, ci);
        FILE* f = fopen(path, "wb");
        if (!f) { fprintf(stderr, "cannot write %s\n", path); return 2; }

        const int hdr[4] = { c.order, c.op, n, juce_ncompare(c.op, n) };
        fwrite("JUCF", 1, 4, f);
        fwrite(hdr, sizeof(int), 4, f);
        fwrite(in.data(), sizeof(float), nf, f);
        fwrite(expected.data(), sizeof(float), nf, f);
        fclose(f);

        printf("case %2d (order=%2d op=%d n=%4d): exp[0]=% .6f exp[1]=% .6f exp[n/2]=% .6f\n",
               ci, c.order, c.op, n, (double)expected[0], (double)expected[1],
               (double)expected[static_cast<size_t>(n / 2)]);
    }
    return 0;
}