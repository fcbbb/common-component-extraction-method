// Hidden evaluation: forward and inverse transforms of the component under
// test are compared against the IPP-generated golden spectra.
//
// Usage: hidden_test <hidden-dir>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

#include "fft.h"

static int read_i32(FILE* f, int* v) { return fread(v, sizeof(*v), 1, f) == 1; }

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
        int size, domain, n, ncomp;
        std::vector<float> in, gspec, ginv;
        FILE* f;

        snprintf(path, sizeof(path), "%s/case_%d.bin", dir, ci);
        f = fopen(path, "rb");
        if (!f) break;
        if (fread(magic, 1, 4, f) != 4 || memcmp(magic, "SFFT", 4) != 0)
        {
            fprintf(stderr, "bad magic in %s\n", path); return 2;
        }
        if (!read_i32(f, &size) || !read_i32(f, &domain) ||
            !read_i32(f, &n) || !read_i32(f, &ncomp))
        {
            fprintf(stderr, "bad header in %s\n", path); return 2;
        }

        const bool isReal = (domain == 0);
        const size_t nIn = isReal ? static_cast<size_t>(n) : 2 * static_cast<size_t>(n);
        in.resize(nIn);
        gspec.resize(2 * static_cast<size_t>(ncomp));
        ginv.resize(nIn);
        if (fread(in.data(), sizeof(float), in.size(), f) != in.size() ||
            fread(gspec.data(), sizeof(float), gspec.size(), f) != gspec.size() ||
            fread(ginv.data(), sizeof(float), ginv.size(), f) != ginv.size())
        {
            fprintf(stderr, "short read in %s\n", path); return 2;
        }
        fclose(f);

        std::vector<float> gotSpec(gspec.size(), 0.0f), gotInv(ginv.size(), 0.0f);
        double maxFwd = 0.0, maxInv = 0.0;
        bool ok = true;

        {
            ipl::FFT fft(size, isReal ? ipl::FFTDomain::Real : ipl::FFTDomain::Complex);
            if (fft.numRealSamples != n || fft.numComplexSamples != ncomp)
            {
                printf("case %d: size mismatch (n=%d/%d ncomp=%d/%d)\n",
                       ci, fft.numRealSamples, n, fft.numComplexSamples, ncomp);
                ++failures;
                continue;
            }

            if (isReal)
            {
                fft.applyForward(in.data(), reinterpret_cast<ipl::complex_t*>(gotSpec.data()));
                fft.applyInverse(reinterpret_cast<const ipl::complex_t*>(gspec.data()), gotInv.data());
            }
            else
            {
                fft.applyForward(reinterpret_cast<const ipl::complex_t*>(in.data()),
                                 reinterpret_cast<ipl::complex_t*>(gotSpec.data()));
                fft.applyInverse(reinterpret_cast<const ipl::complex_t*>(gspec.data()),
                                 reinterpret_cast<ipl::complex_t*>(gotInv.data()));
            }
        }

        for (size_t i = 0; i < gspec.size(); ++i)
        {
            const double r = rel_err(gotSpec[i], gspec[i]);
            if (r > maxFwd) maxFwd = r;
            if (r > 1e-3 && std::fabs(gotSpec[i] - gspec[i]) > 1e-4) ok = false;
        }
        for (size_t i = 0; i < ginv.size(); ++i)
        {
            const double r = rel_err(gotInv[i], ginv[i]);
            if (r > maxInv) maxInv = r;
            if (r > 1e-3 && std::fabs(gotInv[i] - ginv[i]) > 1e-4) ok = false;
        }

        printf("case %d (size=%d domain=%s n=%d ncomp=%d): %s "
               "fwd_maxrel=%.3e inv_maxrel=%.3e\n",
               ci, size, isReal ? "real" : "complex", n, ncomp,
               ok ? "PASS" : "FAIL", maxFwd, maxInv);
        if (maxFwd > worst) worst = maxFwd;
        if (maxInv > worst) worst = maxInv;
        if (!ok) ++failures;
    }

    printf("SUMMARY cases=%d failures=%d worst_rel=%.3e\n", ci, failures, worst);
    return failures == 0 ? 0 : 1;
}