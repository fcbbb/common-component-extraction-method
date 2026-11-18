/* Public self-check for the extracted rubberband FFT component.
 *
 * Deliberately small: exercises every entry point against a direct
 * double-precision DFT computed here, for a handful of sizes covering both
 * the power-of-two backend and the built-in DFT fallback.  No hidden data is
 * used.
 */
#include "FFT.h"

#include <cmath>
#include <cstdio>
#include <vector>

using namespace RubberBand;

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

static double slot_error(int phase, double got, double want)
{
    double d = std::fabs(got - want);
    if (phase) {
        d = got - want;
        d -= 2.0 * M_PI * std::floor(d / (2.0 * M_PI) + 0.5);
        d = std::fabs(d);
        return d;
    }
    double s = std::fabs(want);
    return (s > 1.0) ? d / s : d;
}

static void dft(const std::vector<double> &x,
                std::vector<double> &re, std::vector<double> &im)
{
    const int n = (int)x.size();
    for (int k = 0; k <= n / 2; ++k) {
        double sr = 0.0, si = 0.0;
        for (int t = 0; t < n; ++t) {
            double a = -2.0 * M_PI * (double)k * (double)t / (double)n;
            sr += x[t] * std::cos(a);
            si += x[t] * std::sin(a);
        }
        re[k] = sr;
        im[k] = si;
    }
}

template <typename T>
static int check_size(int n, const char *tag)
{
    const int hs1 = n / 2 + 1;
    std::vector<double> xd((size_t)n), re((size_t)hs1), im((size_t)hs1);
    std::vector<double> mag((size_t)hs1), ph((size_t)hs1);
    std::vector<double> gotRe((size_t)hs1), gotIm((size_t)hs1);
    std::vector<double> gotA((size_t)hs1), gotB((size_t)hs1);
    std::vector<double> out((size_t)n), inter((size_t)(n + 2)), cep((size_t)n);
    std::vector<T> x((size_t)n), tin((size_t)(n + 2)), tout((size_t)n);
    std::vector<T> tA((size_t)hs1), tB((size_t)hs1);

    for (int i = 0; i < n; ++i) {
        xd[i] = 0.8 * std::sin(0.37 * i) + 0.3 * std::cos(0.11 * i * i) - 0.2;
        x[i] = (T)xd[i];
    }
    dft(xd, re, im);
    for (int k = 0; k < hs1; ++k) {
        mag[k] = std::hypot(re[k], im[k]);
        ph[k] = std::atan2(im[k], re[k]);
    }

    int fail = 0;
    double worst = 0.0;
    double s = 0.0;

    FFT f(n);

    /* forward */
    f.forward(x.data(), tA.data(), tB.data());
    for (int k = 0; k < hs1; ++k) {
        s = slot_error(0, tA[k], re[k]); if (s > worst) worst = s;
        s = slot_error(0, tB[k], im[k]); if (s > worst) worst = s;
    }

    /* forwardInterleaved */
    f.forwardInterleaved(x.data(), tin.data());
    for (int k = 0; k < hs1; ++k) {
        s = slot_error(0, tin[2*k], re[k]); if (s > worst) worst = s;
        s = slot_error(0, tin[2*k+1], im[k]); if (s > worst) worst = s;
    }

    /* forwardPolar / forwardMagnitude */
    f.forwardPolar(x.data(), tA.data(), tB.data());
    for (int k = 0; k < hs1; ++k) {
        s = slot_error(0, tA[k], mag[k]); if (s > worst) worst = s;
        s = slot_error(1, tB[k], ph[k]); if (s > worst) worst = s;
    }
    f.forwardMagnitude(x.data(), tA.data());
    for (int k = 0; k < hs1; ++k) {
        s = slot_error(0, tA[k], mag[k]); if (s > worst) worst = s;
    }

    /* inverse round trip: unscaled forward + unscaled inverse = n * x */
    f.forward(x.data(), tA.data(), tB.data());
    f.inverse(tA.data(), tB.data(), tout.data());
    for (int i = 0; i < n; ++i) {
        s = slot_error(0, tout[i], n * xd[i]); if (s > worst) worst = s;
    }

    /* inverseInterleaved round trip */
    f.forwardInterleaved(x.data(), tin.data());
    f.inverseInterleaved(tin.data(), tout.data());
    for (int i = 0; i < n; ++i) {
        s = slot_error(0, tout[i], n * xd[i]); if (s > worst) worst = s;
    }

    /* inversePolar round trip */
    f.forwardPolar(x.data(), tA.data(), tB.data());
    f.inversePolar(tA.data(), tB.data(), tout.data());
    for (int i = 0; i < n; ++i) {
        s = slot_error(0, tout[i], n * xd[i]); if (s > worst) worst = s;
    }

    /* inverseCepstral against the direct formula */
    f.forwardMagnitude(x.data(), tA.data());
    {
        std::vector<double> c((size_t)n);
        for (int k = 0; k < hs1; ++k) {
            c[k] = std::log((double)tA[k] + 0.000001);
        }
        for (int k = hs1; k < n; ++k) c[k] = c[n - k];
        for (int t = 0; t < n; ++t) {
            double acc = 0.0;
            for (int k = 0; k < n; ++k) {
                acc += c[k] * std::cos(2.0 * M_PI * k * t / n);
            }
            out[t] = acc;
        }
        f.inverseCepstral(tA.data(), tout.data());
        for (int t = 0; t < n; ++t) {
            s = slot_error(0, tout[t], out[t]); if (s > worst) worst = s;
        }
    }

    const double tol = (sizeof(T) == sizeof(float)) ? 1.0e-4 : 1.0e-10;
    if (!(worst <= tol)) fail = 1;
    std::printf("  n=%4d %-6s: %s worst=%.3e\n", n, tag,
                fail ? "FAIL" : "PASS", worst);
    return fail;
}

int main()
{
    int fail = 0;

    std::printf("constructor / argument checks\n");
    for (int bad = 0; bad <= 1; ++bad) {
        bool ok = false;
        try {
            FFT f(bad);
        } catch (FFT::Exception e) {
            ok = (e == FFT::InvalidSize);
        }
        std::printf("  size %d: %s\n", bad, ok ? "PASS (InvalidSize)" : "FAIL");
        if (!ok) fail = 1;
    }
    {
        bool ok = false;
        try {
            FFT f(8);
            std::vector<float> a(5), b(5);
            f.forward((const float *)0, a.data(), b.data());
        } catch (FFT::Exception e) {
            ok = (e == FFT::NullArgument);
        }
        std::printf("  null argument: %s\n", ok ? "PASS (NullArgument)" : "FAIL");
        if (!ok) fail = 1;
    }

    std::printf("transform checks against a direct DFT\n");
    fail |= check_size<float>(4, "float");
    fail |= check_size<float>(8, "float");
    fail |= check_size<float>(16, "float");
    fail |= check_size<double>(4, "double");
    fail |= check_size<double>(12, "double");
    fail |= check_size<double>(100, "double");

    std::printf(fail ? "PUBLIC_TEST=FAIL\n" : "PUBLIC_TEST=PASS\n");
    return fail ? 1 : 0;
}