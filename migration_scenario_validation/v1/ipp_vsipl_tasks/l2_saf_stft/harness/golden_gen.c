/* Generates the hidden case containers from the IPP baseline.
 *
 * Container layout (little endian):
 *   "SAFF"
 *   int32 op, n, win, hop, nchin, nchout, fmt, aux, payload_len, ncompare
 *   float64 payload[payload_len]
 *   float64 expected[ncompare]
 *
 * Everything is stored as float64: the baseline's float outputs are promoted
 * exactly, so replaying a float implementation reproduces the same values.
 *
 * Usage: golden_gen <out-dir>
 */
#include "saf_utility_fft.h"
#include "cases.h"
#include "saf_ops.h"

#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv)
{
    const char *dir = (argc > 1) ? argv[1] : "hidden";
    int ci;

    saf_build_cases();

    for (ci = 0; ci < SAF_NCASES; ++ci) {
        const saf_case *c = &saf_cases[ci];
        int plen = saf_payload_len(c);
        int ncomp = saf_ncompare(c);
        double *p = (double*)calloc1d(plen > 0 ? plen : 1, sizeof(double));
        double *exp = (double*)calloc1d(ncomp > 0 ? ncomp : 1, sizeof(double));
        char path[1024];
        FILE *fp;
        int hdr[10];

        saf_gen_payload(c, 0x5AF5AFULL + (uint64_t)ci * 7919ULL, p);
        saf_compute(c, p, exp);

        snprintf(path, sizeof(path), "%s/case_%d.bin", dir, ci);
        fp = fopen(path, "wb");
        if (!fp) return 2;
        hdr[0] = c->op;    hdr[1] = c->n;      hdr[2] = c->win;  hdr[3] = c->hop;
        hdr[4] = c->nchin; hdr[5] = c->nchout; hdr[6] = c->fmt; hdr[7] = c->aux;
        hdr[8] = plen;     hdr[9] = ncomp;
        fwrite("SAFF", 1, 4, fp);
        fwrite(hdr, sizeof(int), 10, fp);
        fwrite(p, sizeof(double), (size_t)plen, fp);
        fwrite(exp, sizeof(double), (size_t)ncomp, fp);
        fclose(fp);

        printf("case %3d (op=%2d n=%4d win=%4d hop=%3d ch=%d/%d fmt=%d):"
               " plen=%6d ncomp=%7d exp[0]=% .9f\n",
               ci, c->op, c->n, c->win, c->hop, c->nchin, c->nchout, c->fmt,
               plen, ncomp, exp[0]);
        free(p);
        free(exp);
    }

    printf("generated %d cases in %s\n", SAF_NCASES, dir);
    return 0;
}