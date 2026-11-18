/* Public self-check: summary statistics against the definitions written out
 * here in double precision, for one contiguous and one decimated window, plus
 * the argument-checking contract.
 */
#include "stats.h"

#include <math.h>
#include <stdio.h>

#define NC 128
#define NS 37

static double ref_stddev(const double *x, int n)
{
    double m = 0.0, ss = 0.0;
    int i;
    for (i = 0; i < n; ++i) m += x[i];
    m /= (double)n;
    for (i = 0; i < n; ++i) ss += (x[i] - m) * (x[i] - m);
    return (n > 1) ? sqrt(ss / (double)(n - 1)) : 0.0;
}

static int check_summary(const dsp_summary *s,
                         double dot, double norm, double mean, double sd,
                         double vmax, double vmin, const char *tag)
{
    static const char *names[6] = { "dot", "norm", "mean", "stddev", "vmax", "vmin" };
    const double got[6] = { s->dot, s->norm, s->mean, s->stddev, s->vmax, s->vmin };
    const double want[6] = { dot, norm, mean, sd, vmax, vmin };
    int i, fail = 0;

    for (i = 0; i < 6; ++i) {
        double e = fabs(got[i] - want[i]);
        double rel = (fabs(want[i]) > 1.0) ? e / fabs(want[i]) : e;
        if (!(rel <= 1e-4 || e <= 1e-5)) {
            printf("FAIL %s: %s got %.9g want %.9g (err %.3e)\n",
                   tag, names[i], got[i], want[i], e);
            fail = 1;
        }
    }
    return fail;
}

int main(void)
{
    float a[NC], b[NC];
    double wa[NC], dot = 0.0, ss = 0.0, mean = 0.0, sd;
    double vmax = -INFINITY, vmin = INFINITY;
    dsp_summary s;
    int i, fail = 0;

    /* --- contiguous window --------------------------------------------- */
    for (i = 0; i < NC; ++i) {
        a[i] = (float)(0.5 * sin(0.11 * i) + 0.3 * cos(0.37 * i));
        b[i] = (float)(0.2 * cos(0.07 * i) - 0.4 * sin(0.23 * i));
        wa[i] = (double)a[i];
        dot += wa[i] * (double)b[i];
        ss  += wa[i] * wa[i];
        mean += wa[i];
        if (wa[i] > vmax) vmax = wa[i];
        if (wa[i] < vmin) vmin = wa[i];
    }
    mean /= (double)NC;
    sd = ref_stddev(wa, NC);

    if (dsp_summary_compute(a, b, NC, &s) != 0) {
        printf("FAIL: dsp_summary_compute returned non-zero\n");
        return 1;
    }
    fail |= check_summary(&s, dot, sqrt(ss), mean, sd, vmax, vmin, "contiguous");

    /* --- decimated window: a at 1 + 2i, b at 1 + 3i --------------------- */
    {
        enum { LEN = 4 + 3 * (NS - 1) + 1 };
        float ab[LEN], bb[LEN];
        double xa[NS], dot2 = 0.0, ss2 = 0.0, mean2 = 0.0, sd2;
        double mx = -INFINITY, mn = INFINITY;

        for (i = 0; i < LEN; ++i) {
            ab[i] = (float)(0.1 * i - 2.0);
            bb[i] = (float)(0.05 * i + 0.5);
        }
        for (i = 0; i < NS; ++i) {
            xa[i] = (double)ab[1 + 2 * i];
            dot2 += xa[i] * (double)bb[1 + 3 * i];
            ss2  += xa[i] * xa[i];
            mean2 += xa[i];
            if (xa[i] > mx) mx = xa[i];
            if (xa[i] < mn) mn = xa[i];
        }
        mean2 /= (double)NS;
        sd2 = ref_stddev(xa, NS);

        if (dsp_summary_compute_strided(ab, 2, bb, 3, 1, NS, &s) != 0) {
            printf("FAIL: dsp_summary_compute_strided returned non-zero\n");
            return 1;
        }
        fail |= check_summary(&s, dot2, sqrt(ss2), mean2, sd2, mx, mn, "strided");
    }

    /* --- single sample: stddev is 0 ------------------------------------ */
    {
        float one[2] = { 7.0f, 0.0f };
        float two[2] = { 2.0f, 0.0f };
        dsp_summary s1;
        if (dsp_summary_compute(one, two, 1, &s1) != 0) {
            printf("FAIL: n=1 rejected\n");
            fail = 1;
        } else if (fabs(s1.stddev) > 0.0 || s1.mean != 7.0f || s1.vmax != 7.0f ||
                   s1.vmin != 7.0f || s1.dot != 14.0f || s1.norm != 7.0f) {
            printf("FAIL: n=1 summary wrong (dot=%.9g norm=%.9g mean=%.9g sd=%.9g)\n",
                   (double)s1.dot, (double)s1.norm, (double)s1.mean, (double)s1.stddev);
            fail = 1;
        }
    }

    /* --- argument contract --------------------------------------------- */
    if (dsp_summary_compute(a, b, 0, &s) != -1 ||
        dsp_summary_compute(NULL, b, NC, &s) != -1 ||
        dsp_summary_compute(a, b, NC, NULL) != -1 ||
        dsp_summary_compute_strided(a, 0, b, 1, 0, NC, &s) != -1 ||
        dsp_summary_compute_strided(a, 1, b, 1, -1, NC, &s) != -1) {
        printf("FAIL: invalid arguments were not rejected\n");
        fail = 1;
    }

    printf("public_test: %s\n", fail ? "FAIL" : "PASS");
    return fail;
}