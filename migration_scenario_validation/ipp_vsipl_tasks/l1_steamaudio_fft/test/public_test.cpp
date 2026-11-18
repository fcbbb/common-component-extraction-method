// Public self-check: impulse response, round trip, and the documented
// rounding of the transform size.  No golden data involved.
#include <cmath>
#include <cstdio>
#include <vector>

#include "fft.h"

int main()
{
    int fail = 0;

    // 1. size rounding
    {
        ipl::FFT f(100, ipl::FFTDomain::Real);
        if (f.numRealSamples != 128 || f.numComplexSamples != 65)
        {
            printf("FAIL: size 100 -> n=%d ncomp=%d, expected 128/65\n",
                   f.numRealSamples, f.numComplexSamples);
            fail = 1;
        }
    }

    // 2. impulse -> flat spectrum (unnormalised forward transform)
    {
        ipl::FFT f(64, ipl::FFTDomain::Real);
        std::vector<float> x(64, 0.0f);
        std::vector<ipl::complex_t> spec(33);
        x[0] = 1.0f;
        f.applyForward(x.data(), spec.data());
        for (int k = 0; k < 33; ++k)
        {
            if (std::fabs(spec[k].real() - 1.0f) > 1e-5f || std::fabs(spec[k].imag()) > 1e-5f)
            {
                printf("FAIL: impulse spectrum[%d] = (%f, %f)\n", k,
                       static_cast<double>(spec[k].real()), static_cast<double>(spec[k].imag()));
                fail = 1;
                break;
            }
        }
    }

    // 3. real round trip (inverse must scale by 1/N)
    {
        ipl::FFT f(256, ipl::FFTDomain::Real);
        std::vector<float> x(256), y(256);
        std::vector<ipl::complex_t> spec(129);
        for (int i = 0; i < 256; ++i)
            x[i] = std::sin(0.07f * i) + 0.4f * std::cos(0.31f * i);
        f.applyForward(x.data(), spec.data());
        f.applyInverse(spec.data(), y.data());
        double maxerr = 0.0;
        for (int i = 0; i < 256; ++i)
            maxerr = std::max(maxerr, static_cast<double>(std::fabs(y[i] - x[i])));
        if (maxerr > 1e-5)
        {
            printf("FAIL: real round trip maxerr=%g\n", maxerr);
            fail = 1;
        }
    }

    // 4. complex round trip
    {
        ipl::FFT f(64, ipl::FFTDomain::Complex);
        std::vector<ipl::complex_t> x(64), y(64), spec(64);
        for (int i = 0; i < 64; ++i)
            x[i] = ipl::complex_t(std::sin(0.13f * i), std::cos(0.21f * i));
        f.applyForward(x.data(), spec.data());
        f.applyInverse(spec.data(), y.data());
        double maxerr = 0.0;
        for (int i = 0; i < 64; ++i)
            maxerr = std::max(maxerr, static_cast<double>(std::abs(y[i] - x[i])));
        if (maxerr > 1e-5)
        {
            printf("FAIL: complex round trip maxerr=%g\n", maxerr);
            fail = 1;
        }
    }

    printf("public_test: %s\n", fail ? "FAIL" : "PASS");
    return fail;
}