/* Generates the hidden case containers from the IPP baseline.
 *
 * Container layout (little endian):
 *   "RBBF"
 *   int32 size, op, prec, ncompare
 *   float64 payload[payload_len]
 *   float64 expected[ncompare]
 *
 * Everything is stored as float64: for prec=0 the baseline's float outputs
 * are promoted exactly, so replaying a float implementation reproduces the
 * same values.
 *
 * Usage: golden_gen <out-dir>
 */
#include "FFT.h"
#include "cases.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

using namespace RubberBand;

int main(int argc, char **argv)
{
    const std::string dir = (argc > 1) ? argv[1] : "hidden";
    uint64_t seed = 0x7B0FF7ULL;
    int ci;

    for (ci = 0; ci < RB_NCASES; ++ci) {
        const rb_case &c = rb_cases[ci];
        const int size = c.size;
        const int op = c.op;
        const int prec = c.prec;
        const int hs1 = rb_bins(size);
        const int plen = rb_payload_len(op, size);
        const int ncomp = rb_ncompare(op, size);
        const int n = size;

        std::vector<double> payload((size_t)(plen > 0 ? plen : 1), 0.0);
        std::vector<double> expected((size_t)(ncomp > 0 ? ncomp : 1), 0.0);

        char path[1024];
        std::snprintf(path, sizeof(path), "%s/case_%d.bin", dir.c_str(), ci);

        if (op == RB_NULL_ARG) {
            FILE *fp = std::fopen(path, "wb");
            if (!fp) return 2;
            int hdr[4] = { size, op, prec, 0 };
            std::fwrite("RBBF", 1, 4, fp);
            std::fwrite(hdr, sizeof(int), 4, fp);
            std::fclose(fp);
            std::printf("case %3d (n=%4d op=%d prec=%d): null-argument probe\n",
                        ci, size, op, prec);
            continue;
        }

        FFT f(size);

        std::vector<double> in((size_t)n);
        for (int i = 0; i < n; ++i) in[i] = rb_rand(&seed);

        std::vector<float> inf((size_t)n), reF((size_t)hs1), imF((size_t)hs1);
        std::vector<double> reD((size_t)hs1), imD((size_t)hs1);
        std::vector<float> outF((size_t)(n + 2)), intF((size_t)(n + 2));
        std::vector<double> outD((size_t)(n + 2)), intD((size_t)(n + 2));
        std::vector<float> sockF((size_t)n);
        std::vector<double> sockD((size_t)n);

        for (int i = 0; i < n; ++i) inf[i] = (float)in[i];

        switch (op) {

        case RB_FWD:
            std::memcpy(payload.data(), in.data(), sizeof(double) * (size_t)n);
            if (prec == 0) {
                f.forward(inf.data(), reF.data(), imF.data());
                for (int k = 0; k < hs1; ++k) {
                    expected[k] = reF[k];
                    expected[hs1 + k] = imF[k];
                }
            } else {
                f.forward(in.data(), reD.data(), imD.data());
                for (int k = 0; k < hs1; ++k) {
                    expected[k] = reD[k];
                    expected[hs1 + k] = imD[k];
                }
            }
            break;

        case RB_FWD_INTERLEAVED:
            std::memcpy(payload.data(), in.data(), sizeof(double) * (size_t)n);
            if (prec == 0) {
                f.forwardInterleaved(inf.data(), intF.data());
                for (int k = 0; k < n + 2; ++k) expected[k] = intF[k];
            } else {
                f.forwardInterleaved(in.data(), intD.data());
                for (int k = 0; k < n + 2; ++k) expected[k] = intD[k];
            }
            break;

        case RB_FWD_POLAR:
            std::memcpy(payload.data(), in.data(), sizeof(double) * (size_t)n);
            if (prec == 0) {
                f.forwardPolar(inf.data(), reF.data(), imF.data());
                for (int k = 0; k < hs1; ++k) {
                    expected[k] = reF[k];
                    expected[hs1 + k] = imF[k];
                }
            } else {
                f.forwardPolar(in.data(), reD.data(), imD.data());
                for (int k = 0; k < hs1; ++k) {
                    expected[k] = reD[k];
                    expected[hs1 + k] = imD[k];
                }
            }
            break;

        case RB_FWD_MAG:
            std::memcpy(payload.data(), in.data(), sizeof(double) * (size_t)n);
            if (prec == 0) {
                f.forwardMagnitude(inf.data(), reF.data());
                for (int k = 0; k < hs1; ++k) expected[k] = reF[k];
            } else {
                f.forwardMagnitude(in.data(), reD.data());
                for (int k = 0; k < hs1; ++k) expected[k] = reD[k];
            }
            break;

        case RB_INV:
            if (prec == 0) {
                f.forward(inf.data(), reF.data(), imF.data());
                for (int k = 0; k < hs1; ++k) {
                    payload[k] = reF[k];
                    payload[hs1 + k] = imF[k];
                }
                f.inverse(reF.data(), imF.data(), outF.data());
                for (int i = 0; i < n; ++i) expected[i] = outF[i];
            } else {
                f.forward(in.data(), reD.data(), imD.data());
                for (int k = 0; k < hs1; ++k) {
                    payload[k] = reD[k];
                    payload[hs1 + k] = imD[k];
                }
                f.inverse(reD.data(), imD.data(), outD.data());
                for (int i = 0; i < n; ++i) expected[i] = outD[i];
            }
            break;

        case RB_INV_INTERLEAVED:
            if (prec == 0) {
                f.forward(inf.data(), reF.data(), imF.data());
                for (int k = 0; k < hs1; ++k) {
                    intF[2 * k] = reF[k];
                    intF[2 * k + 1] = imF[k];
                }
                for (int k = 0; k < n + 2; ++k) payload[k] = intF[k];
                f.inverseInterleaved(intF.data(), outF.data());
                for (int i = 0; i < n; ++i) expected[i] = outF[i];
            } else {
                f.forward(in.data(), reD.data(), imD.data());
                for (int k = 0; k < hs1; ++k) {
                    intD[2 * k] = reD[k];
                    intD[2 * k + 1] = imD[k];
                }
                for (int k = 0; k < n + 2; ++k) payload[k] = intD[k];
                f.inverseInterleaved(intD.data(), outD.data());
                for (int i = 0; i < n; ++i) expected[i] = outD[i];
            }
            break;

        case RB_INV_POLAR:
            if (prec == 0) {
                f.forwardPolar(inf.data(), reF.data(), imF.data());
                for (int k = 0; k < hs1; ++k) {
                    payload[k] = reF[k];
                    payload[hs1 + k] = imF[k];
                }
                f.inversePolar(reF.data(), imF.data(), outF.data());
                for (int i = 0; i < n; ++i) expected[i] = outF[i];
            } else {
                f.forwardPolar(in.data(), reD.data(), imD.data());
                for (int k = 0; k < hs1; ++k) {
                    payload[k] = reD[k];
                    payload[hs1 + k] = imD[k];
                }
                f.inversePolar(reD.data(), imD.data(), outD.data());
                for (int i = 0; i < n; ++i) expected[i] = outD[i];
            }
            break;

        case RB_INV_CEPSTRAL:
            if (prec == 0) {
                f.forwardMagnitude(inf.data(), reF.data());
                for (int k = 0; k < hs1; ++k) payload[k] = reF[k];
                f.inverseCepstral(reF.data(), sockF.data());
                for (int i = 0; i < n; ++i) expected[i] = sockF[i];
            } else {
                f.forwardMagnitude(in.data(), reD.data());
                for (int k = 0; k < hs1; ++k) payload[k] = reD[k];
                f.inverseCepstral(reD.data(), sockD.data());
                for (int i = 0; i < n; ++i) expected[i] = sockD[i];
            }
            break;
        }

        FILE *fp = std::fopen(path, "wb");
        if (!fp) return 2;
        int hdr[4] = { size, op, prec, ncomp };
        std::fwrite("RBBF", 1, 4, fp);
        std::fwrite(hdr, sizeof(int), 4, fp);
        std::fwrite(payload.data(), sizeof(double), (size_t)plen, fp);
        std::fwrite(expected.data(), sizeof(double), (size_t)ncomp, fp);
        std::fclose(fp);

        std::printf("case %3d (n=%4d op=%d prec=%d): exp[0]=% .9f exp[1]=% .9f\n",
                    ci, size, op, prec, expected[0],
                    ncomp > 1 ? expected[1] : 0.0);
    }

    std::printf("generated %d cases in %s\n", RB_NCASES, dir.c_str());
    return 0;
}