/* Hidden evaluation: replays every stored case through the candidate
 * implementation and compares with the buffers produced by the IPP baseline.
 *
 * Each case is graded relative to its own peak magnitude (rtol 1e-4), because
 * the unscaled transforms and the STFT overlap-add all produce values whose
 * absolute float32 round-off scales with the signal level of the case.
 *
 * Usage: hidden_test <hidden-dir>
 */
#include "saf_utility_fft.h"
#include "cases.h"
#include "saf_ops.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv)
{
    const char *dir = (argc > 1) ? argv[1] : "hidden";
    int ci, failures = 0;
    double worst = 0.0;

    for (ci = 0; ; ++ci) {
        char path[1024];
        FILE *fp;
        char magic[4];
        int hdr[10];
        saf_case c;
        int plen, ncomp, i;
        double *p, *exp, *got, scale = 0.0, maxerr = 0.0;
        int firstBad = -1;
        double rtol = 1.0e-4;

        snprintf(path, sizeof(path), "%s/case_%d.bin", dir, ci);
        fp = fopen(path, "rb");
        if (!fp) break;

        if (fread(magic, 1, 4, fp) != 4 || memcmp(magic, "SAFF", 4) != 0) {
            fprintf(stderr, "bad magic in %s\n", path);
            return 2;
        }
        if (fread(hdr, sizeof(int), 10, fp) != 10) {
            fprintf(stderr, "bad header in %s\n", path);
            return 2;
        }
        memset(&c, 0, sizeof(c));
        c.op = hdr[0]; c.n = hdr[1]; c.win = hdr[2]; c.hop = hdr[3];
        c.nchin = hdr[4]; c.nchout = hdr[5]; c.fmt = hdr[6]; c.aux = hdr[7];
        plen = hdr[8];
        ncomp = hdr[9];

        p   = (double*)calloc1d(plen > 0 ? (size_t)plen : 1, sizeof(double));
        exp = (double*)calloc1d(ncomp > 0 ? (size_t)ncomp : 1, sizeof(double));
        got = (double*)calloc1d(ncomp > 0 ? (size_t)ncomp : 1, sizeof(double));

        if (fread(p, sizeof(double), (size_t)plen, fp) != (size_t)plen ||
            fread(exp, sizeof(double), (size_t)ncomp, fp) != (size_t)ncomp) {
            fprintf(stderr, "short read in %s\n", path);
            return 2;
        }
        fclose(fp);

        saf_compute(&c, p, got);

        for (i = 0; i < ncomp; ++i) {
            double a = fabs(exp[i]);
            if (a > scale) scale = a;
        }
        if (scale < 1.0) scale = 1.0;

        for (i = 0; i < ncomp; ++i) {
            double r = fabs(got[i] - exp[i]) / scale;
            if (r > maxerr) maxerr = r;
            if (r > rtol && firstBad < 0) firstBad = i;
        }

        if (firstBad >= 0) {
            printf("case %3d (op=%2d n=%4d win=%4d hop=%3d ch=%d/%d fmt=%d): "
                   "FAIL first at %d: got %.12g want %.12g\n",
                   ci, c.op, c.n, c.win, c.hop, c.nchin, c.nchout, c.fmt,
                   firstBad, got[firstBad], exp[firstBad]);
            ++failures;
        } else {
            printf("case %3d (op=%2d n=%4d win=%4d hop=%3d ch=%d/%d fmt=%d): "
                   "PASS maxerr=%.3e\n",
                   ci, c.op, c.n, c.win, c.hop, c.nchin, c.nchout, c.fmt, maxerr);
        }
        if (maxerr > worst) worst = maxerr;

        free(p);
        free(exp);
        free(got);
    }

    printf("SUMMARY cases=%d failures=%d worst_rel=%.3e\n", ci, failures, worst);
    return failures == 0 ? 0 : 1;
}