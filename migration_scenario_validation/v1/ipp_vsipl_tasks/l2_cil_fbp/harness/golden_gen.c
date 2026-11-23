/* Generates the hidden case containers from the IPP baseline.
 *
 * Container layout (little endian):
 *   "FBPF"
 *   int32 which, order, num_proj, pix_y, pix_x, payload_len, ncompare
 *   float64 payload[payload_len]      (data | filter | weights)
 *   float64 expected[ncompare]
 *
 * Usage: golden_gen <out-dir>
 */
#include "fbp_filtering.h"
#include "cases.h"
#include "fbp_ops.h"

#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv)
{
    const char *dir = (argc > 1) ? argv[1] : "hidden";
    int ci;

    fbp_build_cases();

    for (ci = 0; ci < FBP_NCASES; ++ci) {
        const fbp_case *c = &fbp_cases[ci];
        long plen = fbp_payload_len(c);
        long ncomp = fbp_ncompare(c);
        double *p = (double*)calloc((size_t)plen, sizeof(double));
        double *exp = (double*)calloc((size_t)ncomp, sizeof(double));
        char path[1024];
        FILE *fp;
        int hdr[7];

        fbp_gen_payload(c, 0xF8B0ULL + (uint64_t)ci * 7919ULL, p);
        fbp_compute(c, p, exp);

        snprintf(path, sizeof(path), "%s/case_%d.bin", dir, ci);
        fp = fopen(path, "wb");
        if (!fp) return 2;
        hdr[0] = c->which; hdr[1] = c->order;
        hdr[2] = (int)c->num_proj; hdr[3] = (int)c->pix_y; hdr[4] = (int)c->pix_x;
        hdr[5] = (int)plen;  hdr[6] = (int)ncomp;
        fwrite("FBPF", 1, 4, fp);
        fwrite(hdr, sizeof(int), 7, fp);
        fwrite(p, sizeof(double), (size_t)plen, fp);
        fwrite(exp, sizeof(double), (size_t)ncomp, fp);
        fclose(fp);

        printf("case %2d (%s order=%d proj=%ld y=%ld x=%ld): plen=%6ld "
               "ncomp=%7ld exp[0]=% .9f\n",
               ci, c->which ? "vah" : "avh", c->order,
               c->num_proj, c->pix_y, c->pix_x, plen, ncomp, exp[0]);
        free(p);
        free(exp);
    }

    printf("generated %d cases in %s\n", FBP_NCASES, dir);
    return 0;
}