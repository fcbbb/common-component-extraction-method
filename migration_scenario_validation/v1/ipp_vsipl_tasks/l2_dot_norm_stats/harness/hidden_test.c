/* Hidden evaluation: runs the summary statistics over the stored windows and
 * compares every field with the IPP-generated values.
 *
 * Usage: hidden_test <hidden-dir>
 */
#include "stats.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int get_i32(FILE *f, int *v) { return fread(v, sizeof(*v), 1, f) == 1; }

static int field_ok(double got, double exp)
{
    double e, rel;
    if (isnan(exp) || isnan(got)) return isnan(exp) && isnan(got);
    if (isinf(exp) || isinf(got)) return got == exp;
    e = fabs(got - exp);
    rel = (fabs(exp) > 1.0) ? e / fabs(exp) : e;
    return rel <= 1e-4 || e <= 1e-5;
}

int main(int argc, char **argv)
{
    const char *dir = (argc > 1) ? argv[1] : "hidden";
    char path[512];
    int ci, failures = 0;
    double worst = 0.0;
    static const char *names[6] = { "dot", "norm", "mean", "stddev", "vmax", "vmin" };

    for (ci = 0; ; ++ci) {
        char magic[4];
        int n, astride, bstride, offset, nan_index, alen, blen;
        float *a = NULL, *b = NULL;
        float exp[6];
        unsigned char mask[6];
        dsp_summary s;
        FILE *f;
        int i, ok = 1, rc;
        double maxerr = 0.0;

        snprintf(path, sizeof(path), "%s/case_%d.bin", dir, ci);
        f = fopen(path, "rb");
        if (!f) break;
        if (fread(magic, 1, 4, f) != 4 || memcmp(magic, "STAT", 4) != 0) {
            fprintf(stderr, "bad magic in %s\n", path); return 2;
        }
        if (!get_i32(f, &n) || !get_i32(f, &astride) || !get_i32(f, &bstride) ||
            !get_i32(f, &offset) || !get_i32(f, &nan_index) ||
            !get_i32(f, &alen) || !get_i32(f, &blen)) {
            fprintf(stderr, "bad header in %s\n", path); return 2;
        }
        a = (float *)malloc(sizeof(float) * (size_t)alen);
        b = (float *)malloc(sizeof(float) * (size_t)blen);
        if (!a || !b) return 2;
        if (fread(a, sizeof(float), (size_t)alen, f) != (size_t)alen ||
            fread(b, sizeof(float), (size_t)blen, f) != (size_t)blen ||
            fread(exp, sizeof(float), 6, f) != 6 ||
            fread(mask, 1, 6, f) != 6) {
            fprintf(stderr, "short read in %s\n", path); return 2;
        }
        fclose(f);

        memset(&s, 0, sizeof(s));
        if (offset == 0 && astride == 1 && bstride == 1)
            rc = dsp_summary_compute(a, b, n, &s);
        else
            rc = dsp_summary_compute_strided(a, astride, b, bstride, offset, n, &s);
        if (rc != 0) {
            printf("case %d (n=%d): compute returned %d\n", ci, n, rc);
            ++failures;
            free(a); free(b);
            continue;
        }

        {
            double got[6], want[6];
            got[0] = s.dot;   got[1] = s.norm;   got[2] = s.mean;
            got[3] = s.stddev; got[4] = s.vmax;  got[5] = s.vmin;
            for (i = 0; i < 6; ++i) want[i] = exp[i];

            for (i = 0; i < 6; ++i) {
                double e, rel;
                if (mask[i]) continue;
                e = fabs(got[i] - want[i]);
                rel = (fabs(want[i]) > 1.0) ? e / fabs(want[i]) : e;
                if (!isnan(rel) && rel > maxerr) maxerr = rel;
                if (!field_ok(got[i], want[i])) {
                    printf("case %d (n=%d astride=%d bstride=%d offset=%d): "
                           "%s got %.9g want %.9g\n",
                           ci, n, astride, bstride, offset, names[i],
                           got[i], want[i]);
                    ok = 0;
                }
            }
        }

        printf("case %d (n=%d astride=%d bstride=%d offset=%d nan=%d): %s maxrel=%.3e\n",
               ci, n, astride, bstride, offset, nan_index,
               ok ? "PASS" : "FAIL", maxerr);
        if (maxerr > worst) worst = maxerr;
        if (!ok) ++failures;
        free(a); free(b);
    }

    printf("SUMMARY cases=%d failures=%d worst_rel=%.3e\n", ci, failures, worst);
    return failures == 0 ? 0 : 1;
}