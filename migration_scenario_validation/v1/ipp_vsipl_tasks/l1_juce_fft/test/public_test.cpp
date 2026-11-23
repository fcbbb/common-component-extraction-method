// Public self-check: the documented FFT behaviour against double-precision
// references -- order -> size mapping, complex round trip, real round trip,
// the half-spectrum + conjugate-mirror layout, and the magnitude transform.
#include "juce_FFT.h"

#include <algorithm>
#include <cmath>
#include <complex>
#include <cstdio>
#include <cstring>
#include <vector>

using juce::dsp::Complex;
using juce::dsp::FFT;

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

namespace
{
double rel(double got, double want)
{
    const double e = std::fabs(got - want);
    return (std::fabs(want) > 1.0) ? e / std::fabs(want) : e;
}

std::complex<double> dft_at(const std::vector<double>& x, int n, int k, bool inverse)
{
    const double sign = inverse ? 1.0 : -1.0;
    std::complex<double> s(0.0, 0.0);

    for (int t = 0; t < n; ++t)
    {
        const double ph = sign * 2.0 * M_PI * (double)k * (double)t / (double)n;
        s += x[(size_t)t] * std::complex<double>(std::cos(ph), std::sin(ph));
    }

    if (inverse)
        s /= (double)n;

    return s;
}

int fail_count = 0;

void check(bool cond, const char* what)
{
    if (!cond)
    {
        printf("FAIL: %s\n", what);
        ++fail_count;
    }
}
} // namespace

static void test_sizes()
{
    int bad = 0;
    for (int order = 0; order <= 6; ++order)
    {
        FFT fft(order);
        if (fft.getSize() != (1 << order))
            ++bad;
    }
    printf("  %-28s %s\n", "order -> size", bad ? "FAIL" : "PASS");
    if (bad) ++fail_count;
}

static void test_complex(int order)
{
    const int n = 1 << order;
    std::vector<Complex<float>> in((size_t)n), spec((size_t)n), back((size_t)n);
    std::vector<double> re((size_t)n), im((size_t)n);

    for (int i = 0; i < n; ++i)
    {
        in[(size_t)i] = Complex<float>((float)std::sin(0.7 * i + 0.1), (float)std::cos(0.3 * i - 0.2));
        re[(size_t)i] = in[(size_t)i].real();
        im[(size_t)i] = in[(size_t)i].imag();
    }

    FFT fft(order);
    fft.perform(in.data(), spec.data(), false);

    double worst = 0.0;
    for (int k = 0; k < n; ++k)
    {
        // Reference: DFT of the complex signal.
        std::complex<double> want(0.0, 0.0);
        for (int t = 0; t < n; ++t)
        {
            const double ph = -2.0 * M_PI * (double)k * (double)t / (double)n;
            want += std::complex<double>(re[(size_t)t], im[(size_t)t])
                    * std::complex<double>(std::cos(ph), std::sin(ph));
        }
        worst = std::max(worst, rel(spec[(size_t)k].real(), want.real()));
        worst = std::max(worst, rel(spec[(size_t)k].imag(), want.imag()));
    }
    printf("  %-28s %s maxrel=%.3e\n", "complex forward", worst < 1e-5 ? "PASS" : "FAIL", worst);
    if (!(worst < 1e-5)) ++fail_count;

    fft.perform(spec.data(), back.data(), true);
    worst = 0.0;
    for (int i = 0; i < n; ++i)
        worst = std::max(worst, std::fabs((double)back[(size_t)i].real() - re[(size_t)i]));
    printf("  %-28s %s maxerr=%.3e\n", "complex round trip", worst < 1e-5 ? "PASS" : "FAIL", worst);
    if (!(worst < 1e-5)) ++fail_count;
}

static void test_real(int order)
{
    const int n = 1 << order;
    std::vector<float> buf(2 * (size_t)n, 0.0f);
    std::vector<double> x((size_t)n);

    for (int i = 0; i < n; ++i)
    {
        x[(size_t)i] = std::sin(0.37 * i + 0.4) + 0.2 * std::cos(0.11 * i);
        buf[(size_t)i] = (float)x[(size_t)i];
    }

    std::vector<float> input = buf;
    FFT fft(order);

    // Full output: half spectrum followed by the conjugate mirror.
    fft.performRealOnlyForwardTransform(buf.data(), false);
    auto* out = reinterpret_cast<Complex<float>*>(buf.data());

    double worst = 0.0;
    for (int k = 0; k <= n / 2; ++k)
    {
        const std::complex<double> want = dft_at(x, n, k, false);
        worst = std::max(worst, rel(out[k].real(), want.real()));
        worst = std::max(worst, rel(out[k].imag(), want.imag()));
    }
    int mirrorBad = 0;
    for (int i = n / 2 + 1; i < n; ++i)
        if (out[i] != std::conj(out[n - i]))
            ++mirrorBad;
    printf("  %-28s %s maxrel=%.3e (mirror %s)\n", "real forward / mirror",
           (worst < 1e-5 && mirrorBad == 0) ? "PASS" : "FAIL", worst,
           mirrorBad == 0 ? "ok" : "bad");
    if (!(worst < 1e-5) || mirrorBad != 0) ++fail_count;

    // Inverse reconstructs the samples in the first half.
    fft.performRealOnlyInverseTransform(buf.data());
    worst = 0.0;
    for (int i = 0; i < n; ++i)
        worst = std::max(worst, std::fabs((double)buf[(size_t)i] - x[(size_t)i]));
    printf("  %-28s %s maxerr=%.3e\n", "real round trip", worst < 1e-5 ? "PASS" : "FAIL", worst);
    if (!(worst < 1e-5)) ++fail_count;

    // Half-only output defines the first n/2+1 complex values.
    std::vector<float> half = input;
    fft.performRealOnlyForwardTransform(half.data(), true);
    auto* hout = reinterpret_cast<Complex<float>*>(half.data());
    worst = 0.0;
    for (int k = 0; k <= n / 2; ++k)
    {
        const std::complex<double> want = dft_at(x, n, k, false);
        worst = std::max(worst, rel(hout[k].real(), want.real()));
        worst = std::max(worst, rel(hout[k].imag(), want.imag()));
    }
    printf("  %-28s %s maxrel=%.3e\n", "real forward (half)", worst < 1e-5 ? "PASS" : "FAIL", worst);
    if (!(worst < 1e-5)) ++fail_count;
}

static void test_magnitude(int order)
{
    const int n = 1 << order;

    if (n == 1)
    {
        // performFrequencyOnlyForwardTransform is a no-op at size 1.
        float one[2] = { 0.75f, -0.25f };
        FFT fft(0);
        fft.performFrequencyOnlyForwardTransform(one, false);
        printf("  %-28s %s\n", "magnitude n=1 no-op",
               (one[0] == 0.75f && one[1] == -0.25f) ? "PASS" : "FAIL");
        if (!(one[0] == 0.75f && one[1] == -0.25f)) ++fail_count;
        return;
    }

    std::vector<double> x((size_t)n);
    for (int i = 0; i < n; ++i)
        x[(size_t)i] = std::sin(0.23 * i + 0.9) - 0.4 * std::cos(0.5 * i);

    for (int variant = 0; variant < 2; ++variant)
    {
        const bool half = variant != 0;
        std::vector<float> buf(2 * (size_t)n, 3.0f);   // poison
        for (int i = 0; i < n; ++i)
            buf[(size_t)i] = (float)x[(size_t)i];

        FFT fft(order);
        fft.performFrequencyOnlyForwardTransform(buf.data(), half);

        const int limit = half ? n / 2 + 1 : n;
        double worst = 0.0;
        for (int k = 0; k < limit; ++k)
            worst = std::max(worst, rel(buf[(size_t)k], std::abs(dft_at(x, n, k, false))));

        int tailBad = 0;
        for (int i = limit; i < 2 * n; ++i)
            if (buf[(size_t)i] != 0.0f)
                ++tailBad;

        printf("  %-28s %s maxrel=%.3e (tail %s)\n",
               half ? "magnitude (half)" : "magnitude (full)",
               (worst < 1e-5 && tailBad == 0) ? "PASS" : "FAIL", worst,
               tailBad == 0 ? "zeroed" : "not zeroed");
        if (!(worst < 1e-5) || tailBad != 0) ++fail_count;
    }
}

int main()
{
    printf("public_test:\n");
    test_sizes();

    printf("  -- complex --\n");
    for (int order = 0; order <= 5; ++order)
        test_complex(order);

    printf("  -- real --\n");
    for (int order = 0; order <= 5; ++order)
        test_real(order);

    printf("  -- magnitude --\n");
    for (int order = 0; order <= 5; ++order)
        test_magnitude(order);

    printf("public_test: %s\n", fail_count ? "FAIL" : "PASS");
    return fail_count ? 1 : 0;
}