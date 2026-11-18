/* Generates the hidden case containers from the IPP baseline.
 *
 * Container layout (little endian):
 *   "R8BF"
 *   int32 op, LenBits, Len, plen, nout, KernelLen, LenMult, DoFinalMul
 *   float64 payload[plen]
 *   float64 expected[nout]
 *
 * The payload is stored as consumed by the baseline, so cases whose input has
 * to be a valid Perm block (inverse, block products) carry the baseline's own
 * forward transform output.
 *
 * Usage: golden_gen <out-dir>
 */
#include "CDSPRealFFT.h"
#include "cases.h"
#include "r8b_ops.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

static void build_payload(const r8b_case &c, std::vector<double> &payload,
                          uint64_t seed)
{
    const int Len = r8b_len(c.LenBits);
    const int plen = r8b_plen(c.op, c.LenBits, c.KernelLen);
    uint64_t s = seed;
    int i;

    payload.assign((size_t)plen, 0.0);

    if (c.op == R8_OP_MINPHASE) {
        r8b_fill_kernel(&payload[0], c.KernelLen, s);
        return;
    }

    for (i = 0; i < plen; ++i) payload[i] = r8b_rand(s);

    /* Cases that consume FFT blocks get real forward transforms. */
    switch (c.op) {
    case R8_OP_INV: {
        CDSPRealFFTKeeper k(c.LenBits);
        k->forward(&payload[0]);
        break;
    }
    case R8_OP_MUL:
    case R8_OP_MUL_I: {
        CDSPRealFFTKeeper k(c.LenBits);
        k->forward(&payload[0]);
        k->forward(&payload[(size_t)Len]);
        break;
    }
    case R8_OP_MUL_ZP: {
        CDSPRealFFTKeeper k(c.LenBits);
        k->forward(&payload[0]);
        k->forward(&payload[(size_t)Len]);
        k->convertToZP(&payload[(size_t)Len]);
        break;
    }
    default:
        break;
    }
}

int main(int argc, char **argv)
{
    const char *dir = (argc > 1) ? argv[1] : "hidden";
    int ci;

    for (ci = 0; ci < R8B_NCASES; ++ci) {
        const r8b_case &c = r8b_cases[ci];
        const int Len = r8b_len(c.LenBits);
        const int plen = r8b_plen(c.op, c.LenBits, c.KernelLen);
        const int nout = r8b_nout(c.op, c.LenBits, c.KernelLen);
        std::vector<double> payload;
        std::vector<double> expected;

        build_payload(c, payload, 0x5EED0000ULL + (uint64_t)ci * 7919ULL);
        r8b_run(c.op, c.LenBits, c.KernelLen, c.LenMult,
                c.DoFinalMul != 0, &payload[0], expected);

        if ((int)expected.size() != nout) {
            std::fprintf(stderr, "case %d: expected size mismatch\n", ci);
            return 2;
        }

        char path[1024];
        std::snprintf(path, sizeof(path), "%s/case_%d.bin", dir, ci);

        FILE *fp = std::fopen(path, "wb");
        if (!fp) {
            std::fprintf(stderr, "cannot write %s\n", path);
            return 2;
        }

        int hdr[8] = { c.op, c.LenBits, Len, plen, nout, c.KernelLen,
                       c.LenMult, c.DoFinalMul };
        std::fwrite("R8BF", 1, 4, fp);
        std::fwrite(hdr, sizeof(int), 8, fp);
        std::fwrite(&payload[0], sizeof(double), (size_t)plen, fp);
        std::fwrite(&expected[0], sizeof(double), (size_t)nout, fp);
        std::fclose(fp);

        std::printf("case %2d op=%d bits=%2d len=%5d plen=%5d nout=%5d\n",
                    ci, c.op, c.LenBits, Len, plen, nout);
    }

    return 0;
}