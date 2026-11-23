/* Sequencer shared by the golden generator and the hidden test: runs one case
 * from cases.h against whatever CDSPRealFFT implementation is linked in. */
#ifndef R8B_OPS_H
#define R8B_OPS_H

#include "CDSPRealFFT.h"
#include "cases.h"

#include <algorithm>
#include <vector>

using namespace r8b;

static inline void r8b_run(const int op, const int LenBits,
                           const int KernelLen, const int LenMult,
                           const bool DoFinalMul, const double *payload,
                           std::vector<double> &out)
{
    const int Len = r8b_len(LenBits);
    const int nout = r8b_nout(op, LenBits, KernelLen);

    out.assign((size_t)nout, 0.0);

    switch (op) {

    case R8_OP_FWD: {
        CDSPRealFFTKeeper k(LenBits);
        std::copy(payload, payload + Len, out.begin());
        k->forward(&out[0]);
        break;
    }

    case R8_OP_INV: {
        CDSPRealFFTKeeper k(LenBits);
        std::copy(payload, payload + Len, out.begin());
        k->inverse(&out[0]);
        break;
    }

    case R8_OP_ROUNDTRIP: {
        CDSPRealFFTKeeper k(LenBits);
        const double m = k->getInvMulConst();
        int i;
        std::copy(payload, payload + Len, out.begin());
        k->forward(&out[0]);
        k->inverse(&out[0]);
        for (i = 0; i < Len; ++i) out[i] *= m;
        break;
    }

    case R8_OP_MUL: {
        CDSPRealFFTKeeper k(LenBits);
        std::vector<double> a(payload, payload + Len);
        std::vector<double> b(payload + Len, payload + 2 * Len);
        k->forward(&a[0]);
        k->forward(&b[0]);
        k->multiplyBlocks(&a[0], &b[0], &out[0]);
        break;
    }

    case R8_OP_MUL_I: {
        CDSPRealFFTKeeper k(LenBits);
        std::vector<double> a(payload, payload + Len);
        std::vector<double> b(payload + Len, payload + 2 * Len);
        k->forward(&a[0]);
        k->forward(&b[0]);
        k->multiplyBlocks(&a[0], &b[0]);
        std::copy(b.begin(), b.end(), out.begin());
        break;
    }

    case R8_OP_MUL_ZP: {
        /* The payload already holds a forward block and its zero-phase
         * counterpart. */
        CDSPRealFFTKeeper k(LenBits);
        std::vector<double> ker(payload + Len, payload + 2 * Len);
        std::copy(payload, payload + Len, out.begin());
        k->multiplyBlocksZP(&ker[0], &out[0]);
        break;
    }

    case R8_OP_ZP: {
        CDSPRealFFTKeeper k(LenBits);
        std::copy(payload, payload + Len, out.begin());
        k->forward(&out[0]);
        k->convertToZP(&out[0]);
        break;
    }

    case R8_OP_NYQ: {
        CDSPRealFFTKeeper k(LenBits);
        std::copy(payload, payload + Len, out.begin());
        k->forward(&out[0]);
        CDSPRealFFT::setBinNyquist(&out[0], payload[Len]);
        break;
    }

    case R8_OP_MINPHASE: {
        std::vector<double> ker(payload, payload + KernelLen);
        double gd = 0.0;
        calcMinPhaseTransform(&ker[0], KernelLen, LenMult,
                              DoFinalMul, &gd);
        std::copy(ker.begin(), ker.end(), out.begin());
        out[(size_t)KernelLen] = gd;
        break;
    }

    case R8_OP_KEEPER: {
        /* Two keepers of the same length in sequence: the second one must get
         * the object the first one gave back to the pool. */
        {
            CDSPRealFFTKeeper k(LenBits);
            std::copy(payload, payload + Len, out.begin());
            k->forward(&out[0]);
        }
        {
            CDSPRealFFTKeeper k(LenBits);
            std::vector<double> tmp(payload, payload + Len);
            k->forward(&tmp[0]);
            std::copy(tmp.begin(), tmp.end(), out.begin() + Len);
        }
        break;
    }

    default:
        break;
    }
}

#endif /* R8B_OPS_H */