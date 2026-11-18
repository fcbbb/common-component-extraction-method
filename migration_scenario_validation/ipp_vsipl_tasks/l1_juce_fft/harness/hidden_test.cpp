// Hidden evaluation: replays every stored case through the candidate FFT and
// compares with the IPP-generated buffers.
//
// Usage: hidden_test <hidden-dir>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

#include "juce_FFT.h"
#include "cases.h"

using juce::dsp::Complex;
using juce::dsp::FFT;

static double rel_err(float got, float exp)
{
    const double e = std::fabs(static_cast<double>(got) - static_cast<double>(exp));
    const double scale = std::fabs(static_cast<double>(exp));
    return (scale > 1.0) ? e / scale : e;
}

int main(int argc, char** argv)
{
    const char* dir = (argc > 1) ? argv[1] : "hidden";
    char path[512];
    int ci, failures = 0;
    double worst = 0.0;

    for (ci = 0; ; ++ci)
    {
        char magic[4];
        int hdr[4];
        FILE* f;

        snprintf(path, sizeof(path), "%s/case_%d.bin", dir, ci);
        f = fopen(path, "rb");
        if (!f) break;

        if (fread(magic, 1, 4, f) != 4 || memcmp(magic, "JUCF", 4) != 0)
        {
            fprintf(stderr, "bad magic in %s\n", path);
            return 2;
        }
        if (fread(hdr, sizeof(int), 4, f) != 4)
        {
            fprintf(stderr, "bad header in %s\n", path);
            return 2;
        }

        const int order = hdr[0], op = hdr[1], n = hdr[2], ncompare = hdr[3];
        const size_t nf = 2 * static_cast<size_t>(n);

        std::vector<float> in(nf), expected(nf), got(nf);
        if (fread(in.data(), sizeof(float), nf, f) != nf ||
            fread(expected.data(), sizeof(float), nf, f) != nf)
        {
            fprintf(stderr, "short read in %s\n", path);
            return 2;
        }
        fclose(f);

        got = in;

        FFT fft(order);
        bool ok = (fft.getSize() == n);
        if (!ok)
            printf("case %d (order=%d op=%d): getSize()=%d, expected %d\n",
                   ci, order, op, fft.getSize(), n);

        if (ok)
        {
            switch (op)
            {
                case OP_COMPLEX_FWD:
                    fft.perform(reinterpret_cast<const Complex<float>*>(in.data()),
                                reinterpret_cast<Complex<float>*>(got.data()), false);
                    break;
                case OP_COMPLEX_INV:
                    fft.perform(reinterpret_cast<const Complex<float>*>(in.data()),
                                reinterpret_cast<Complex<float>*>(got.data()), true);
                    break;
                case OP_REAL_FWD:
                    fft.performRealOnlyForwardTransform(got.data(), false);
                    break;
                case OP_REAL_FWD_HALF:
                    fft.performRealOnlyForwardTransform(got.data(), true);
                    break;
                case OP_REAL_INV:
                    fft.performRealOnlyInverseTransform(got.data());
                    break;
                case OP_FREQ_ONLY:
                    fft.performFrequencyOnlyForwardTransform(got.data(), false);
                    break;
                case OP_FREQ_ONLY_HALF:
                    fft.performFrequencyOnlyForwardTransform(got.data(), true);
                    break;
                default:
                    printf("case %d: bad op %d\n", ci, op);
                    return 2;
            }
        }

        double maxerr = 0.0;
        int firstBad = -1;
        for (int i = 0; i < ncompare; ++i)
        {
            const size_t k = static_cast<size_t>(i);
            const double r = rel_err(got[k], expected[k]);
            const double absErr = std::fabs(static_cast<double>(got[k]) - static_cast<double>(expected[k]));
            if (r > maxerr) maxerr = r;
            if (r > 1e-4 && absErr > 1e-5 && firstBad < 0) firstBad = i;
        }

        if (firstBad >= 0)
        {
            printf("case %2d (order=%2d op=%d n=%4d): FAIL first at %d: got %.9g want %.9g\n",
                   ci, order, op, n, firstBad,
                   (double)got[static_cast<size_t>(firstBad)],
                   (double)expected[static_cast<size_t>(firstBad)]);
            ok = false;
        }

        printf("case %2d (order=%2d op=%d n=%4d): %s maxrel=%.3e\n",
               ci, order, op, n, ok ? "PASS" : "FAIL", maxerr);
        if (maxerr > worst) worst = maxerr;
        if (!ok) ++failures;
    }

    printf("SUMMARY cases=%d failures=%d worst_rel=%.3e\n", ci, failures, worst);
    return failures == 0 ? 0 : 1;
}