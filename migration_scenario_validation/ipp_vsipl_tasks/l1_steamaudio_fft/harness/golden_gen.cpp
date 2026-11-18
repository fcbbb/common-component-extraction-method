// Generates the hidden case containers from the IPP build of the component.
//
// Container layout (native float32, std::complex<float> as two floats):
//   "SFFT"
//   int32 size, int32 domain (0 = Real, 1 = Complex)
//   int32 numRealSamples, int32 numComplexSamples
//   input   : numRealSamples floats (Real) or 2*numRealSamples (Complex)
//   forward : 2*numComplexSamples floats
//   inverse : same element count as input
//
// Usage: golden_gen <out-dir>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

#include "fft.h"
#include "cases.h"

int main(int argc, char** argv)
{
    const char* dir = (argc > 1) ? argv[1] : "hidden";
    char path[512];
    std::uint64_t seed = 0xC0FFEE12ULL;

    for (int ci = 0; ci < FFT_NCASES; ++ci)
    {
        const fft_case& c = fft_cases[ci];
        ipl::FFT fft(c.size, c.domain);

        const int nInFloats = (c.domain == ipl::FFTDomain::Real) ? fft.numRealSamples : 2 * fft.numRealSamples;
        std::vector<float> in(static_cast<size_t>(nInFloats));
        for (int i = 0; i < nInFloats; ++i)
        {
            in[static_cast<size_t>(i)] = fft_rand(&seed);
        }

        std::vector<ipl::complex_t> spec(static_cast<size_t>(fft.numComplexSamples));
        std::vector<float> inv(static_cast<size_t>(nInFloats));

        if (c.domain == ipl::FFTDomain::Real)
        {
            const float* x = in.data();
            fft.applyForward(x, spec.data());
            fft.applyInverse(spec.data(), inv.data());
        }
        else
        {
            const auto* x = reinterpret_cast<const ipl::complex_t*>(in.data());
            fft.applyForward(x, spec.data());
            fft.applyInverse(spec.data(), reinterpret_cast<ipl::complex_t*>(inv.data()));
        }

        snprintf(path, sizeof(path), "%s/case_%d.bin", dir, ci);
        FILE* f = fopen(path, "wb");
        if (!f) { fprintf(stderr, "cannot write %s\n", path); return 2; }
        const int domain = (c.domain == ipl::FFTDomain::Real) ? 0 : 1;
        fwrite("SFFT", 1, 4, f);
        fwrite(&c.size, sizeof(int), 1, f);
        fwrite(&domain, sizeof(int), 1, f);
        fwrite(&fft.numRealSamples, sizeof(int), 1, f);
        fwrite(&fft.numComplexSamples, sizeof(int), 1, f);
        fwrite(in.data(), sizeof(float), in.size(), f);
        fwrite(spec.data(), sizeof(float), spec.size() * 2, f);
        fwrite(inv.data(), sizeof(float), inv.size(), f);
        fclose(f);

        double maxerr = 0.0;
        for (size_t i = 0; i < inv.size(); ++i)
        {
            const double e = std::fabs(static_cast<double>(inv[i]) - static_cast<double>(in[i]));
            if (e > maxerr) maxerr = e;
        }
        printf("case %d (size=%d domain=%s): n=%d ncomp=%d roundtrip_maxerr=%.3e\n",
               ci, c.size, domain ? "complex" : "real",
               fft.numRealSamples, fft.numComplexSamples, maxerr);
    }
    return 0;
}