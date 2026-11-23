/* Generates the hidden case containers from the IPP baseline.
 *
 * Container layout (little endian, native float32):
 *   "STAT"
 *   int32 n, astride, bstride, offset, nan_index
 *   int32 alen, blen
 *   float32 a[alen]
 *   float32 b[blen]
 *   float32 expected[6]   dot, norm, mean, stddev, vmax, vmin
 *   uint8   mask[6]       1 = field not compared (ambiguous/unstable)
 *
 * The only masked field today is stddev on the NaN case: ippsStdDev_32f
 * returns 0 when the window contains NaN, which is not a meaningful value to
 * reproduce, so the hidden test scores that case on the other five fields.
 *
 * Usage: golden_gen <out-dir>
 */
#include "stats.h"
#include "cases.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv)
{
    const char *dir = (argc > 1) ? argv[1] : "hidden";
    char path[512];
    unsigned long long seed = 0xA11CE5ULL;
    int ci;

    for (ci = 0; ci < STATS_NCASES; ++ci) {
        const stats_case *c = &stats_cases[ci];
        int alen = stats_base_len(c->n, c->astride, c->offset);
        int blen = stats_base_len(c->n, c->bstride, c->offset);
        float *a = (float *)malloc(sizeof(float) * (size_t)alen);
        float *b = (float *)malloc(sizeof(float) * (size_t)blen);
        float expected[STATS_NFIELDS];
        unsigned char mask[STATS_NFIELDS] = { 0, 0, 0, 0, 0, 0 };
        dsp_summary s;
        FILE *f;

        if (!a || !b) return 2;
        stats_make_inputs(c, seed + (unsigned long long)ci * 7919ULL, a, alen, b, blen);

        memset(&s, 0, sizeof(s));
        if (dsp_summary_compute_strided(a, c->astride, b, c->bstride,
                                        c->offset, c->n, &s) != 0) {
            fprintf(stderr, "case %d: compute failed\n", ci);
            return 2;
        }
        expected[0] = s.dot;
        expected[1] = s.norm;
        expected[2] = s.mean;
        expected[3] = s.stddev;
        expected[4] = s.vmax;
        expected[5] = s.vmin;

        if (c->nan_index >= 0) mask[3] = 1;

        snprintf(path, sizeof(path), "%s/case_%d.bin", dir, ci);
        f = fopen(path, "wb");
        if (!f) { fprintf(stderr, "cannot write %s\n", path); return 2; }
        fwrite("STAT", 1, 4, f);
        fwrite(&c->n, sizeof(int), 1, f);
        fwrite(&c->astride, sizeof(int), 1, f);
        fwrite(&c->bstride, sizeof(int), 1, f);
        fwrite(&c->offset, sizeof(int), 1, f);
        fwrite(&c->nan_index, sizeof(int), 1, f);
        fwrite(&alen, sizeof(int), 1, f);
        fwrite(&blen, sizeof(int), 1, f);
        fwrite(a, sizeof(float), (size_t)alen, f);
        fwrite(b, sizeof(float), (size_t)blen, f);
        fwrite(expected, sizeof(float), STATS_NFIELDS, f);
        fwrite(mask, 1, STATS_NFIELDS, f);
        fclose(f);

        printf("case %d (n=%d astride=%d bstride=%d offset=%d nan=%d): "
               "dot=%.4f norm=%.4f mean=%.4f sd=%.4f max=%.4f min=%.4f\n",
               ci, c->n, c->astride, c->bstride, c->offset, c->nan_index,
               (double)expected[0], (double)expected[1], (double)expected[2],
               (double)expected[3], (double)expected[4], (double)expected[5]);
        free(a); free(b);
    }
    return 0;
}