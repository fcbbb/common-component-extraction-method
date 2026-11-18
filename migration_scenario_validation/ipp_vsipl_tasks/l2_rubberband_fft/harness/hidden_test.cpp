/* Hidden evaluation: replays every stored case through the candidate FFT and
 * compares with the buffers produced by the IPP baseline.
 *
 * Phase slots (second half of an RB_FWD_POLAR expectation) are compared
 * modulo 2*pi.  Phase comparisons are absolute (radians).
 *
 * Usage: hidden_test <hidden-dir>
 */
#include "FFT.h"
#include "cases.h"

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

using namespace RubberBand;

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

static double slot_error(int phase, double got, double want, double &absErr)
{
    absErr = std::fabs(got - want);
    if (phase) {
        double d = got - want;
        d -= 2.0 * M_PI * std::floor(d / (2.0 * M_PI) + 0.5);
        absErr = std::fabs(d);
        return absErr;
    }
    double s = std::fabs(want);
    return (s > 1.0) ? absErr / s : absErr;
}

static bool compute(FFT &f, int op, int prec,
                    const std::vector<double> &payload, int n,
                    std::vector<double> &got)
{
    const int hs1 = rb_bins(n);
    std::vector<float> inF((size_t)n), reF((size_t)hs1), imF((size_t)hs1);
    std::vector<double> inD((size_t)n), reD((size_t)hs1), imD((size_t)hs1);
    std::vector<float> intF((size_t)(n + 2)), outF((size_t)n);
    std::vector<double> intD((size_t)(n + 2)), outD((size_t)n);

    if (op <= RB_FWD_MAG) {
        for (int i = 0; i < n; ++i) {
            inF[i] = (float)payload[i];
            inD[i] = payload[i];
        }
    }

    switch (op) {

    case RB_FWD:
        if (prec == 0) {
            f.forward(inF.data(), reF.data(), imF.data());
            for (int k = 0; k < hs1; ++k) {
                got[k] = reF[k];
                got[hs1 + k] = imF[k];
            }
        } else {
            f.forward(inD.data(), reD.data(), imD.data());
            for (int k = 0; k < hs1; ++k) {
                got[k] = reD[k];
                got[hs1 + k] = imD[k];
            }
        }
        return true;

    case RB_FWD_INTERLEAVED:
        if (prec == 0) {
            f.forwardInterleaved(inF.data(), intF.data());
            for (int k = 0; k < n + 2; ++k) got[k] = intF[k];
        } else {
            f.forwardInterleaved(inD.data(), intD.data());
            for (int k = 0; k < n + 2; ++k) got[k] = intD[k];
        }
        return true;

    case RB_FWD_POLAR:
        if (prec == 0) {
            f.forwardPolar(inF.data(), reF.data(), imF.data());
            for (int k = 0; k < hs1; ++k) {
                got[k] = reF[k];
                got[hs1 + k] = imF[k];
            }
        } else {
            f.forwardPolar(inD.data(), reD.data(), imD.data());
            for (int k = 0; k < hs1; ++k) {
                got[k] = reD[k];
                got[hs1 + k] = imD[k];
            }
        }
        return true;

    case RB_FWD_MAG:
        if (prec == 0) {
            f.forwardMagnitude(inF.data(), reF.data());
            for (int k = 0; k < hs1; ++k) got[k] = reF[k];
        } else {
            f.forwardMagnitude(inD.data(), reD.data());
            for (int k = 0; k < hs1; ++k) got[k] = reD[k];
        }
        return true;

    case RB_INV:
        for (int k = 0; k < hs1; ++k) {
            reF[k] = (float)payload[k];
            imF[k] = (float)payload[hs1 + k];
            reD[k] = payload[k];
            imD[k] = payload[hs1 + k];
        }
        if (prec == 0) {
            f.inverse(reF.data(), imF.data(), outF.data());
            for (int i = 0; i < n; ++i) got[i] = outF[i];
        } else {
            f.inverse(reD.data(), imD.data(), outD.data());
            for (int i = 0; i < n; ++i) got[i] = outD[i];
        }
        return true;

    case RB_INV_INTERLEAVED:
        for (int k = 0; k < n + 2; ++k) {
            intF[k] = (float)payload[k];
            intD[k] = payload[k];
        }
        if (prec == 0) {
            f.inverseInterleaved(intF.data(), outF.data());
            for (int i = 0; i < n; ++i) got[i] = outF[i];
        } else {
            f.inverseInterleaved(intD.data(), outD.data());
            for (int i = 0; i < n; ++i) got[i] = outD[i];
        }
        return true;

    case RB_INV_POLAR:
        for (int k = 0; k < hs1; ++k) {
            reF[k] = (float)payload[k];
            imF[k] = (float)payload[hs1 + k];
            reD[k] = payload[k];
            imD[k] = payload[hs1 + k];
        }
        if (prec == 0) {
            f.inversePolar(reF.data(), imF.data(), outF.data());
            for (int i = 0; i < n; ++i) got[i] = outF[i];
        } else {
            f.inversePolar(reD.data(), imD.data(), outD.data());
            for (int i = 0; i < n; ++i) got[i] = outD[i];
        }
        return true;

    case RB_INV_CEPSTRAL:
        for (int k = 0; k < hs1; ++k) {
            reF[k] = (float)payload[k];
            reD[k] = payload[k];
        }
        if (prec == 0) {
            f.inverseCepstral(reF.data(), outF.data());
            for (int i = 0; i < n; ++i) got[i] = outF[i];
        } else {
            f.inverseCepstral(reD.data(), outD.data());
            for (int i = 0; i < n; ++i) got[i] = outD[i];
        }
        return true;
    }

    return false;
}

int main(int argc, char **argv)
{
    const std::string dir = (argc > 1) ? argv[1] : "hidden";
    int ci, failures = 0;
    double worst = 0.0;

    for (ci = 0; ; ++ci) {
        char path[1024];
        std::snprintf(path, sizeof(path), "%s/case_%d.bin", dir.c_str(), ci);

        FILE *fp = std::fopen(path, "rb");
        if (!fp) break;

        char magic[4];
        int hdr[4];
        if (std::fread(magic, 1, 4, fp) != 4 || std::memcmp(magic, "RBBF", 4) != 0) {
            std::fprintf(stderr, "bad magic in %s\n", path);
            return 2;
        }
        if (std::fread(hdr, sizeof(int), 4, fp) != 4) {
            std::fprintf(stderr, "bad header in %s\n", path);
            return 2;
        }
        const int size = hdr[0];
        const int op = hdr[1];
        const int prec = hdr[2];
        const int ncomp = hdr[3];
        const int plen = rb_payload_len(op, size);

        if (op == RB_NULL_ARG) {
            std::fclose(fp);
            bool ok = false;
            try {
                FFT f(size);
                std::vector<float> re((size_t)rb_bins(size)), im((size_t)rb_bins(size));
                std::vector<double> red((size_t)rb_bins(size)), imd((size_t)rb_bins(size));
                try {
                    if (prec == 0) f.forward((const float *)0, re.data(), im.data());
                    else f.forward((const double *)0, red.data(), imd.data());
                } catch (FFT::Exception e) {
                    ok = (e == FFT::NullArgument);
                }
            } catch (...) {
                ok = false;
            }
            std::printf("case %3d (n=%4d null-arg prec=%d): %s\n",
                        ci, size, prec, ok ? "PASS" : "FAIL");
            if (!ok) ++failures;
            continue;
        }

        std::vector<double> payload((size_t)(plen > 0 ? plen : 1), 0.0);
        std::vector<double> expected((size_t)(ncomp > 0 ? ncomp : 1), 0.0);
        std::vector<double> got((size_t)(ncomp > 0 ? ncomp : 1), 0.0);

        if (std::fread(payload.data(), sizeof(double), (size_t)plen, fp) != (size_t)plen ||
            std::fread(expected.data(), sizeof(double), (size_t)ncomp, fp) != (size_t)ncomp) {
            std::fprintf(stderr, "short read in %s\n", path);
            return 2;
        }
        std::fclose(fp);

        bool ok = true;
        try {
            FFT f(size);
            ok = compute(f, op, prec, payload, size, got);
            if (!ok) {
                std::printf("case %3d (n=%4d op=%d prec=%d): FAIL unsupported op\n",
                            ci, size, op, prec);
                ++failures;
                continue;
            }
        } catch (FFT::Exception e) {
            std::printf("case %3d (n=%4d op=%d prec=%d): FAIL threw exception %d\n",
                        ci, size, op, prec, (int)e);
            ++failures;
            continue;
        }

        /* The inverse transforms of a length-1024 spectrum produce values of
         * order 1000 with float32 roundoff around 1e-4 absolute, so each case
         * is graded relative to its own peak magnitude.  Phase slots are
         * angles and use a fixed absolute tolerance instead. */
        const double rtol = (prec == 0) ? 1.0e-4 : 1.0e-9;
        const double phase_tol = (prec == 0) ? 1.0e-4 : 1.0e-9;
        double scale = 1.0;
        for (int i = 0; i < ncomp; ++i) {
            if (!rb_is_phase_slot(op, size, i)) {
                double a = std::fabs(expected[i]);
                if (a > scale) scale = a;
            }
        }
        double maxerr = 0.0;
        int firstBad = -1;
        for (int i = 0; i < ncomp; ++i) {
            double absErr = 0.0;
            const int ph = rb_is_phase_slot(op, size, i);
            slot_error(ph, got[i], expected[i], absErr);
            const double r = ph ? absErr : absErr / scale;
            const double limit = ph ? phase_tol : rtol;
            if (r > maxerr) maxerr = r;
            if (r > limit && firstBad < 0) firstBad = i;
        }

        if (firstBad >= 0) {
            std::printf("case %3d (n=%4d op=%d prec=%d): FAIL first at %d: "
                        "got %.12g want %.12g\n",
                        ci, size, op, prec, firstBad,
                        got[firstBad], expected[firstBad]);
            ok = false;
        }
        std::printf("case %3d (n=%4d op=%d prec=%d): %s maxerr=%.3e\n",
                    ci, size, op, prec, ok ? "PASS" : "FAIL", maxerr);
        if (maxerr > worst) worst = maxerr;
        if (!ok) ++failures;
    }

    std::printf("SUMMARY cases=%d failures=%d worst_rel=%.3e\n", ci, failures, worst);
    return failures == 0 ? 0 : 1;
}