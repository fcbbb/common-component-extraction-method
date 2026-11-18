/* Public test: checks the component against direct DFT references.
 *
 * Every expectation here is computed from the defining sums in double
 * precision, not from a second FFT implementation, so the test is independent
 * of the backend under test.
 */
#include "CDSPRealFFT.h"

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

using namespace r8b;

static int failures = 0;

static void check(const char *name, double err, double tol)
{
    const bool ok = (err <= tol);
    if (!ok) ++failures;
    std::printf("%-46s %-4s err=%.3e tol=%.1e\n", name, ok ? "ok" : "FAIL",
                err, tol);
}

static uint64_t rng = 0x1234567890ABCDEFULL;

static uint64_t mix()
{
    uint64_t z = (rng += 0x9E3779B97F4A7C15ULL);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}

static double rnd()
{
    return ((double)(mix() >> 11) * (1.0 / 9007199254740992.0)) - 1.0;
}

/* Perm-layout DFT of a real signal: p[0]=Re X0, p[1]=Re X(N/2),
 * p[2k]=Re Xk, p[2k+1]=Im Xk. */
static void perm_dft(const double *x, const int N, double *p)
{
    const double twopi = 6.28318530717958648;
    int k, n;

    for (k = 0; k <= N / 2; ++k) {
        double re = 0.0, im = 0.0;
        for (n = 0; n < N; ++n) {
            const double a = -twopi * (double)k * (double)n / (double)N;
            re += x[n] * std::cos(a);
            im += x[n] * std::sin(a);
        }
        if (k == 0)            p[0] = re;
        else if (k == N / 2)   p[1] = re;
        else { p[2 * k] = re; p[2 * k + 1] = im; }
    }
}

/* Unscaled inverse of a Perm block: returns N times the standard IDFT. */
static void perm_idft(const double *p, const int N, double *y)
{
    const double twopi = 6.28318530717958648;
    int n, k;

    for (n = 0; n < N; ++n) {
        double s = p[0];
        if (N >= 2) s += p[1] * std::cos(3.14159265358979324 * (double)n);
        for (k = 1; k < N / 2; ++k) {
            const double a = twopi * (double)k * (double)n / (double)N;
            s += 2.0 * (p[2 * k] * std::cos(a) - p[2 * k + 1] * std::sin(a));
        }
        y[n] = s;
    }
}

/* The same cepstrum algorithm written directly against the DFT sums. */
static void minphase_ref(double *Kernel, const int KernelLen, const int LenMult,
                         const bool DoFinalMul, double *gd)
{
    const int LenBits = getBitOccupancy(KernelLen * LenMult - 1);
    const int Len = 1 << LenBits;
    const int Len2 = Len >> 1;
    const double nzbias = 1e-300;
    std::vector<double> ip((size_t)Len, 0.0), p((size_t)Len, 0.0);
    std::vector<double> ip2((size_t)Len2 + 1, 0.0);
    int i;

    std::memcpy(&ip[0], Kernel, (size_t)KernelLen * sizeof(double));
    perm_dft(&ip[0], Len, &p[0]);

    ip2[0] = p[0];
    p[0] = std::log(std::fabs(p[0]) + nzbias);
    ip2[Len2] = p[1];
    p[1] = std::log(std::fabs(p[1]) + nzbias);

    for (i = 1; i < Len2; ++i) {
        ip2[i] = std::sqrt(p[2 * i] * p[2 * i] + p[2 * i + 1] * p[2 * i + 1]);
        p[2 * i] = std::log(ip2[i] + nzbias);
        p[2 * i + 1] = 0.0;
    }

    perm_idft(&p[0], Len, &ip[0]);

    const double m1 = 1.0 / (double)Len;
    const double m2 = -m1;

    ip[0] = 0.0;
    for (i = 1; i < Len2; ++i) ip[i] *= m1;
    ip[Len2] = 0.0;
    for (i = Len2 + 1; i < Len; ++i) ip[i] *= m2;

    perm_dft(&ip[0], Len, &p[0]);

    p[0] = ip2[0];
    p[1] = ip2[Len2];
    for (i = 1; i < Len2; ++i) {
        p[2 * i] = std::cos(p[2 * i + 1]) * ip2[i];
        p[2 * i + 1] = std::sin(p[2 * i + 1]) * ip2[i];
    }

    perm_idft(&p[0], Len, &ip[0]);

    if (DoFinalMul) {
        for (i = 0; i < KernelLen; ++i) Kernel[i] = ip[i] * m1;
    } else {
        std::memcpy(Kernel, &ip[0], (size_t)KernelLen * sizeof(double));
    }

    if (gd) *gd = calcFIRFilterGroupDelay(Kernel, KernelLen, 0.0);
}

/* Largest absolute difference, normalised by the peak of the reference. */
static double max_rel(const std::vector<double> &got,
                      const std::vector<double> &want)
{
    double peak = 0.0, worst = 0.0;
    size_t i;
    for (i = 0; i < want.size(); ++i) peak = std::fmax(peak, std::fabs(want[i]));
    if (peak < 1.0) peak = 1.0;
    for (i = 0; i < want.size(); ++i)
        worst = std::fmax(worst, std::fabs(got[i] - want[i]) / peak);
    return worst;
}

static void check_forward(const int LenBits)
{
    const int N = 1 << LenBits;
    std::vector<double> x((size_t)N), ref((size_t)N), got((size_t)N);
    char name[64];
    int i;

    for (i = 0; i < N; ++i) x[i] = rnd();
    perm_dft(&x[0], N, &ref[0]);

    {
        CDSPRealFFTKeeper k(LenBits);
        got = x;
        k->forward(&got[0]);
    }

    std::snprintf(name, sizeof(name), "forward vs direct DFT (N=%d)", N);
    check(name, max_rel(got, ref), 1e-11);
}

static void check_inverse(const int LenBits)
{
    const int N = 1 << LenBits;
    std::vector<double> x((size_t)N), p((size_t)N), ref((size_t)N), got((size_t)N);
    char name[64];
    int i;

    for (i = 0; i < N; ++i) x[i] = rnd();
    perm_dft(&x[0], N, &p[0]);
    perm_idft(&p[0], N, &ref[0]);

    {
        CDSPRealFFTKeeper k(LenBits);
        got = p;
        k->inverse(&got[0]);
    }

    std::snprintf(name, sizeof(name), "inverse vs direct IDFT (N=%d)", N);
    check(name, max_rel(got, ref), 1e-11);
}

static void check_roundtrip(const int LenBits)
{
    const int N = 1 << LenBits;
    std::vector<double> x((size_t)N), got((size_t)N);
    double m = 0.0;
    char name[64];
    int i;

    for (i = 0; i < N; ++i) x[i] = rnd();

    {
        CDSPRealFFTKeeper k(LenBits);
        m = k->getInvMulConst();
        got = x;
        k->forward(&got[0]);
        k->inverse(&got[0]);
        for (i = 0; i < N; ++i) got[i] *= m;
    }

    std::snprintf(name, sizeof(name), "forward+inverse*InvMulConst (N=%d)", N);
    check(name, max_rel(got, x), 1e-12);
    std::snprintf(name, sizeof(name), "InvMulConst == 1/N (N=%d)", N);
    check(name, std::fabs(m - 1.0 / (double)N), 0.0);
}

static void check_multiply(const int LenBits)
{
    const int N = 1 << LenBits;
    std::vector<double> a((size_t)N), b((size_t)N), ref((size_t)N);
    std::vector<double> out((size_t)N), inplace((size_t)N);
    char name[64];
    int i;

    for (i = 0; i < N; ++i) a[i] = rnd();
    for (i = 0; i < N; ++i) b[i] = rnd();

    {
        CDSPRealFFTKeeper k(LenBits);
        std::vector<double> pa = a, pb = b;
        k->forward(&pa[0]);
        k->forward(&pb[0]);

        ref[0] = pa[0] * pb[0];
        ref[1] = pa[1] * pb[1];
        for (i = 1; i < N / 2; ++i) {
            ref[2 * i]     = pa[2 * i] * pb[2 * i] - pa[2 * i + 1] * pb[2 * i + 1];
            ref[2 * i + 1] = pa[2 * i] * pb[2 * i + 1] + pa[2 * i + 1] * pb[2 * i];
        }

        k->multiplyBlocks(&pa[0], &pb[0], &out[0]);
        inplace = pb;
        k->multiplyBlocks(&pa[0], &inplace[0]);
    }

    std::snprintf(name, sizeof(name), "multiplyBlocks out-of-place (N=%d)", N);
    check(name, max_rel(out, ref), 1e-12);
    std::snprintf(name, sizeof(name), "multiplyBlocks in-place (N=%d)", N);
    check(name, max_rel(inplace, ref), 1e-12);
}

static void check_zp(const int LenBits)
{
    const int N = 1 << LenBits;
    std::vector<double> a((size_t)N), b((size_t)N), ref((size_t)N), got((size_t)N);
    char name[64];
    int i;

    for (i = 0; i < N; ++i) a[i] = rnd();
    for (i = 0; i < N; ++i) b[i] = rnd();

    {
        CDSPRealFFTKeeper k(LenBits);
        std::vector<double> pa = a, pb = b;
        k->forward(&pa[0]);
        k->forward(&pb[0]);
        k->convertToZP(&pb[0]);

        for (i = 0; i < N; ++i) ref[i] = pa[i] * pb[i];

        got = pa;
        k->multiplyBlocksZP(&pb[0], &got[0]);

        /* convertToZP must duplicate the real part into the imaginary slot */
        int bad = 0;
        for (i = 1; i < N / 2; ++i)
            if (pb[2 * i + 1] != pb[2 * i]) ++bad;
        char zname[64];
        std::snprintf(zname, sizeof(zname),
                      "convertToZP p[2k+1]=p[2k] (N=%d)", N);
        check(zname, (double)bad, 0.0);
    }

    std::snprintf(name, sizeof(name), "multiplyBlocksZP (N=%d)", N);
    check(name, max_rel(got, ref), 1e-12);
}

static void check_nyquist(const int LenBits)
{
    const int N = 1 << LenBits;
    std::vector<double> x((size_t)N), ref((size_t)N), got((size_t)N);
    const double v = 1.75;
    char name[64];
    int i;

    for (i = 0; i < N; ++i) x[i] = rnd();
    perm_dft(&x[0], N, &ref[0]);
    ref[1] = v;

    {
        CDSPRealFFTKeeper k(LenBits);
        got = x;
        k->forward(&got[0]);
        CDSPRealFFT::setBinNyquist(&got[0], v);
    }

    std::snprintf(name, sizeof(name), "setBinNyquist (N=%d)", N);
    check(name, max_rel(got, ref), 1e-11);
}

static void check_minphase(const int KernelLen, const int LenMult,
                           const bool DoFinalMul)
{
    std::vector<double> ker((size_t)KernelLen), ref((size_t)KernelLen);
    double gd_ref = 0.0, gd_got = 0.0;
    char name[64];
    int i;

    /* A smooth, well-conditioned kernel: X(w) has no near-null bins. */
    ker[0] = 1.0;
    for (i = 1; i < KernelLen; ++i)
        ker[i] = 0.4 * (double)((i & 1) ? 1 : -1) / (double)(i + 1) + 0.02 * rnd();

    ref = ker;
    minphase_ref(&ref[0], KernelLen, LenMult, DoFinalMul, &gd_ref);
    calcMinPhaseTransform(&ker[0], KernelLen, LenMult, DoFinalMul, &gd_got);

    std::snprintf(name, sizeof(name),
                  "calcMinPhaseTransform vs direct DFT (n=%d m=%d)",
                  KernelLen, LenMult);
    check(name, max_rel(ker, ref), 1e-9);

    std::snprintf(name, sizeof(name), "calcMinPhaseTransform DC group delay");
    check(name, std::fabs(gd_got - gd_ref), 1e-2);
}

static void check_keeper()
{
    std::vector<double> x((size_t)64), a((size_t)64), b((size_t)64);
    int i;

    for (i = 0; i < 64; ++i) x[i] = rnd();

    {
        CDSPRealFFTKeeper k(6);
        a = x;
        k->forward(&a[0]);
    }
    {
        CDSPRealFFTKeeper k(6);
        b = x;
        k->forward(&b[0]);
    }

    check("keeper reuse gives the same transform", max_rel(a, b), 0.0);

    CDSPRealFFTKeeper k;
    k.init(5);
    const bool got5 = (k->getLen() == 32);
    k.init(6);
    const bool got6 = (k->getLen() == 64);
    k.reset();
    check("keeper init/reset switch lengths", (got5 && got6) ? 0.0 : 1.0, 0.0);
}

int main()
{
    check_forward(4);
    check_forward(6);
    check_inverse(4);
    check_inverse(8);
    check_roundtrip(6);
    check_multiply(5);
    check_zp(6);
    check_nyquist(6);
    check_minphase(24, 2, true);
    check_minphase(40, 4, false);
    check_keeper();

    if (failures == 0) {
        std::printf("PASS: 0 failure(s)\n");
        return 0;
    }

    std::printf("FAIL: %d failure(s)\n", failures);
    return 1;
}