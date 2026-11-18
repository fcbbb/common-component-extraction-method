/* Hidden evaluation: replays every stored case through the candidate
 * implementation and compares with the buffers produced by the IPP baseline.
 * Each case is graded relative to its own peak magnitude (floored at 1.0).
 *
 * Usage: hidden_test <hidden-dir>
 */
#include "fbp_filtering.h"
#include "cases.h"
#include "fbp_ops.h"

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
        int hdr[7];
        fbp_case c;
        long plen, ncomp, i;
        double *p, *exp, *got, scale = 0.0, maxerr = 0.0;
        long firstBad = -1;
        double rtol = 1.0e-4;

        snprintf(path, sizeof(path), "%s/case_%d.bin", dir, ci);
        fp = fopen(path, "rb");
        if (!fp) break;

        if (fread(magic, 1, 4, fp) != 4 || memcmp(magic, "FBPF", 4) != 0) {
            fprintf(stderr, "bad magic in %s\n", path);
            return 2;
        }
        if (fread(hdr, sizeof(int), 7, fp) != 7) {
            fprintf(stderr, "bad header in %s\n", path);
            return 2;
        }
        c.which = hdr[0]; c.order = hdr[1];
        c.num_proj = hdr[2]; c.pix_y = hdr[3]; c.pix_x = hdr[4];
        plen = hdr[5];
        ncomp = hdr[6];

        p   = (double*)calloc((size_t)plen, sizeof(double));
        exp = (double*)calloc((size_t)ncomp, sizeof(double));
        got = (double*)calloc((size_t)ncomp, sizeof(double));

        if (fread(p, sizeof(double), (size_t)plen, fp) != (size_t)plen ||
            fread(exp, sizeof(double), (size_t)ncomp, fp) != (size_t)ncomp) {
            fprintf(stderr, "short read in %s\n", path);
            return 2;
        }
        fclose(fp);

        fbp_compute(&c, p, got);

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
            printf("case %2d (%s order=%d proj=%ld y=%ld x=%ld): FAIL first at "
                   "%ld: got %.12g want %.12g\n",
                   ci, c.which ? "vah" : "avh", c.order,
                   c.num_proj, c.pix_y, c.pix_x, firstBad,
                   got[firstBad], exp[firstBad]);
            ++failures;
        } else {
            printf("case %2d (%s order=%d proj=%ld y=%ld x=%ld): PASS maxerr=%.3e\n",
                   ci, c.which ? "vah" : "avh", c.order,
                   c.num_proj, c.pix_y, c.pix_x, maxerr);
        }
        if (maxerr > worst) worst = maxerr;

        free(p);
        free(exp);
        free(got);
    }

    printf("SUMMARY cases=%d failures=%d worst_rel=%.3e\n", ci, failures, worst);
    return failures == 0 ? 0 : 1;
}