/* Hidden evaluation: replays every stored case through the candidate
 * implementation and compares with the buffers produced by the IPP baseline.
 *
 * Comparison is relative to the peak magnitude of the expected buffer,
 * floored at 1.0.  The group delay that calcMinPhaseTransform() reports is
 * compared with an absolute tolerance instead: it is a finite difference of
 * two nearly equal phases, so it amplifies the last bits of the transform by
 * several orders of magnitude and carries no extra information about the
 * kernel itself.
 *
 * Usage: hidden_test <hidden-dir>
 */
#include "CDSPRealFFT.h"
#include "cases.h"
#include "r8b_ops.h"

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

static const double RTOL = 1.0e-9;
static const double GD_ATOL = 1.0e-2;

int main(int argc, char **argv)
{
    if (argc < 2) {
        std::fprintf(stderr, "usage: hidden_test <hidden-dir>\n");
        return 2;
    }

    const char *dir = argv[1];
    int ci;
    int failures = 0;
    double worst = 0.0;
    double worst_gd = 0.0;

    for (ci = 0; ci < R8B_NCASES; ++ci) {
        char path[1024];
        std::snprintf(path, sizeof(path), "%s/case_%d.bin", dir, ci);

        FILE *fp = std::fopen(path, "rb");
        if (!fp) {
            std::fprintf(stderr, "case %d: cannot open %s\n", ci, path);
            ++failures;
            continue;
        }

        char magic[4];
        int hdr[8];
        if (std::fread(magic, 1, 4, fp) != 4 ||
            std::memcmp(magic, "R8BF", 4) != 0 ||
            std::fread(hdr, sizeof(int), 8, fp) != 8) {
            std::fprintf(stderr, "case %d: bad header\n", ci);
            std::fclose(fp);
            ++failures;
            continue;
        }

        const int op = hdr[0];
        const int LenBits = hdr[1];
        const int plen = hdr[3];
        const int nout = hdr[4];
        const int KernelLen = hdr[5];
        const int LenMult = hdr[6];
        const int DoFinalMul = hdr[7];

        std::vector<double> payload((size_t)(plen > 0 ? plen : 1), 0.0);
        std::vector<double> expected((size_t)(nout > 0 ? nout : 1), 0.0);

        if (std::fread(&payload[0], sizeof(double), (size_t)plen, fp)
                != (size_t)plen ||
            std::fread(&expected[0], sizeof(double), (size_t)nout, fp)
                != (size_t)nout) {
            std::fprintf(stderr, "case %d: short read\n", ci);
            std::fclose(fp);
            ++failures;
            continue;
        }
        std::fclose(fp);

        std::vector<double> got;
        r8b_run(op, LenBits, KernelLen, LenMult, DoFinalMul != 0,
                &payload[0], got);

        if ((int)got.size() != nout) {
            std::printf("case %2d op=%2d bits=%2d  size mismatch\n",
                        ci, op, LenBits);
            ++failures;
            continue;
        }

        double peak = 0.0;
        int i;
        for (i = 0; i < nout; ++i) {
            const double a = std::fabs(expected[(size_t)i]);
            if (a > peak) peak = a;
        }
        if (peak < 1.0) peak = 1.0;

        const int hasDelay = (op == R8_OP_MINPHASE);
        double cworst = 0.0;
        int bad = 0;

        for (i = 0; i < nout; ++i) {
            const double d = std::fabs(got[(size_t)i] - expected[(size_t)i]);

            if (hasDelay && i == nout - 1) {
                if (d > GD_ATOL) {
                    if (bad < 3)
                        std::printf("  delay: got %.17g want %.17g\n",
                                    got[(size_t)i], expected[(size_t)i]);
                    ++bad;
                }
                if (d > worst_gd) worst_gd = d;
            } else {
                const double r = d / peak;
                if (r > cworst) cworst = r;
                if (r > RTOL) {
                    if (bad < 3)
                        std::printf("  [%d] got %.17g want %.17g rel %.3e\n",
                                    i, got[(size_t)i], expected[(size_t)i], r);
                    ++bad;
                }
            }
        }

        if (cworst > worst) worst = cworst;
        const bool ok = (bad == 0);
        if (!ok) ++failures;

        std::printf("case %2d op=%2d bits=%2d len=%5d  worst_rel=%.3e  %s\n",
                    ci, op, LenBits, 1 << LenBits, cworst,
                    ok ? "ok" : "FAIL");
    }

    std::printf("SUMMARY cases=%d failures=%d worst_rel=%.3e worst_gd_abs=%.3e\n",
                R8B_NCASES, failures, worst, worst_gd);

    return (failures == 0) ? 0 : 1;
}