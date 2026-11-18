/* Comms demodulator frontend (Intel IPP backend).
 *
 * Synthetic component in the style of a software-defined-radio receive chain:
 * a complex NCO mixer, a decimating complex FIR and per-block magnitude /
 * power statistics.  Every stage is a straight vector operation, which is why
 * the IPP version reads as a sequence of one-line calls.
 *
 *   stage        IPP
 *   split in     ippsRealToCplx_32f
 *   mix          ippsMul_32fc
 *   merge back   ippsCplxToReal_32fc
 *   FIR          ippsDotProd_32f (4 real dot products per complex output)
 *   |x|          ippsMagnitude_32fc
 *   power        ippsSqr_32f + ippsSum_32f
 *   peak         ippsMaxIndx_32f
 *   buffers      ippsMalloc_8u / ippFree
 *
 * The NCO table is kept interleaved so that the mix segment is a single
 * ippsMul_32fc call; the history and the taps are kept as split planes
 * because the FIR is four real dot products.
 */
#include "demod_frontend.h"

#include <ipp.h>

#include <string.h>

struct dem_state {
    int nco_len;
    int decim;
    int ntaps;
    int T;              /* decim * ntaps */

    Ipp32fc *nco;       /* nco_len entries, interleaved */

    float *taps_re;
    float *taps_im;

    int ph;             /* current NCO phase */
    long gtotal;        /* input samples consumed */
    long jnext;         /* next decimation instant to try */

    float *xre;         /* mixed-signal history, split planes */
    float *xim;
    int cap;            /* allocated length of xre/xim */
    int hfill;          /* valid samples in the history */
    long base;          /* global index of xre[0] */

    Ipp32fc *mixbuf;
    int mixcap;
};

static void *dem_alloc(size_t bytes)
{
    if (bytes == 0) bytes = 1;
    return ippsMalloc_8u((int)bytes);
}

static int dem_reserve_history(dem_state *st, int need)
{
    int ncap;
    float *nre;
    float *nim;

    if (need <= st->cap) return 0;

    ncap = st->cap > 0 ? st->cap : 64;
    while (ncap < need) ncap *= 2;

    nre = (float *)dem_alloc((size_t)ncap * sizeof(float));
    nim = (float *)dem_alloc((size_t)ncap * sizeof(float));
    if (!nre || !nim) {
        if (nre) ippFree(nre);
        if (nim) ippFree(nim);
        return -1;
    }

    if (st->hfill > 0) {
        memcpy(nre, st->xre, (size_t)st->hfill * sizeof(float));
        memcpy(nim, st->xim, (size_t)st->hfill * sizeof(float));
    }
    if (st->xre) ippFree(st->xre);
    if (st->xim) ippFree(st->xim);
    st->xre = nre;
    st->xim = nim;
    st->cap = ncap;

    return 0;
}

static int dem_reserve_mix(dem_state *st, int need)
{
    if (need <= st->mixcap) return 0;

    if (st->mixbuf) ippFree(st->mixbuf);
    st->mixbuf = (Ipp32fc *)dem_alloc((size_t)need * sizeof(Ipp32fc));
    st->mixcap = st->mixbuf ? need : 0;

    return st->mixbuf ? 0 : -1;
}

dem_state *dem_create(const dem_config *cfg,
                      const float *nco_re, const float *nco_im,
                      const float *taps_re, const float *taps_im)
{
    dem_state *st;
    int k;

    if (!cfg || !nco_re || !nco_im || !taps_re || !taps_im) return 0;
    if (cfg->nco_len <= 0 || cfg->decim <= 0 || cfg->ntaps <= 0) return 0;

    st = (dem_state *)dem_alloc(sizeof(dem_state));
    if (!st) return 0;
    memset(st, 0, sizeof(*st));

    st->nco_len = cfg->nco_len;
    st->decim = cfg->decim;
    st->ntaps = cfg->ntaps;
    st->T = cfg->decim * cfg->ntaps;

    st->nco = (Ipp32fc *)dem_alloc((size_t)st->nco_len * sizeof(Ipp32fc));
    st->taps_re = (float *)dem_alloc((size_t)st->T * sizeof(float));
    st->taps_im = (float *)dem_alloc((size_t)st->T * sizeof(float));

    if (!st->nco || !st->taps_re || !st->taps_im) {
        dem_destroy(st);
        return 0;
    }

    ippsRealToCplx_32f(nco_re, nco_im, st->nco, st->nco_len);
    /* The dot product walks the window in increasing time, so the taps are
     * stored time-reversed: that turns
     *     sum_i rev[i] * x[center - T + 1 + i]
     * into the contract  sum_t h[t] * x[center - t]. */
    for (k = 0; k < st->T; ++k) {
        st->taps_re[k] = taps_re[st->T - 1 - k];
        st->taps_im[k] = taps_im[st->T - 1 - k];
    }

    return st;
}

void dem_destroy(dem_state *st)
{
    if (!st) return;

    if (st->nco) ippFree(st->nco);
    if (st->taps_re) ippFree(st->taps_re);
    if (st->taps_im) ippFree(st->taps_im);
    if (st->xre) ippFree(st->xre);
    if (st->xim) ippFree(st->xim);
    if (st->mixbuf) ippFree(st->mixbuf);
    ippFree(st);
}

int dem_process(dem_state *st,
                const float *in_re, const float *in_im, int nin,
                float *out_re, float *out_im)
{
    int produced = 0;
    int done = 0;
    long j;

    if (!st || nin <= 0) return 0;
    if (!in_re || !in_im || !out_re || !out_im) return 0;

    if (dem_reserve_history(st, st->hfill + nin) != 0) return 0;
    if (dem_reserve_mix(st, nin) != 0) return 0;

    /* Mix the block against the NCO, in segments that do not cross a table
     * wrap.  The result goes straight into the history planes. */
    while (done < nin) {
        int seg = st->nco_len - st->ph;

        if (seg > nin - done) seg = nin - done;

        ippsRealToCplx_32f(in_re + done, in_im + done, st->mixbuf, seg);
        ippsMul_32fc(st->mixbuf, st->nco + st->ph, st->mixbuf, seg);
        ippsCplxToReal_32fc(st->mixbuf,
                            st->xre + st->hfill + done,
                            st->xim + st->hfill + done, seg);

        st->ph += seg;
        if (st->ph >= st->nco_len) st->ph -= st->nco_len;
        done += seg;
    }

    st->hfill += nin;
    st->gtotal += nin;

    /* Produce every decimation instant whose window is fully available. */
    j = st->jnext;
    for (;;) {
        const long center = j * (long)st->decim; /* global index of x[j*M] */
        const long li = center - st->base;       /* its local index */
        const float *xr;
        const float *xi;
        Ipp32f rr, ri, ir, ii;

        if (li > (long)st->hfill - 1) break;     /* need more input */
        if (center < (long)(st->T - 1)) {        /* window not deep enough */
            ++j;
            continue;
        }

        xr = st->xre + (li - (st->T - 1));
        xi = st->xim + (li - (st->T - 1));

        ippsDotProd_32f(st->taps_re, xr, st->T, &rr);
        ippsDotProd_32f(st->taps_im, xi, st->T, &ri);
        ippsDotProd_32f(st->taps_re, xi, st->T, &ir);
        ippsDotProd_32f(st->taps_im, xr, st->T, &ii);

        out_re[produced] = (float)(rr - ri);
        out_im[produced] = (float)(ir + ii);

        ++produced;
        ++j;
    }
    st->jnext = j;

    /* Keep only the last T-1 samples. */
    if (st->T > 1 && st->hfill > st->T - 1) {
        const int drop = st->hfill - (st->T - 1);

        memmove(st->xre, st->xre + drop, (size_t)(st->T - 1) * sizeof(float));
        memmove(st->xim, st->xim + drop, (size_t)(st->T - 1) * sizeof(float));
        st->base += drop;
        st->hfill = st->T - 1;
    }

    return produced;
}

void dem_stats(const float *re, const float *im, int n,
               float *mag, float *mean_power, float *peak, int *peak_index)
{
    Ipp32fc *iq;
    float *mbuf;
    float *sq;
    float mx = 0.0f;
    int mi = 0;
    void *pool;

    if (!re || !im || n <= 0) {
        if (mean_power) *mean_power = 0.0f;
        if (peak) *peak = 0.0f;
        if (peak_index) *peak_index = 0;
        return;
    }

    /* One allocation holds the interleaved copy, a magnitude plane (used only
     * when the caller passed no buffer) and the squares. */
    pool = dem_alloc((size_t)n * (sizeof(Ipp32fc) + 3 * sizeof(float)));
    if (!pool) return;

    iq = (Ipp32fc *)pool;
    mbuf = (float *)((char *)pool + (size_t)n * sizeof(Ipp32fc));
    sq = mbuf + n;
    if (mag) mbuf = mag;

    ippsRealToCplx_32f(re, im, iq, n);
    ippsMagnitude_32fc(iq, mbuf, n);
    ippsSqr_32f(mbuf, sq, n);
    ippsMaxIndx_32f(mbuf, n, &mx, &mi);

    {
        float sum = 0.0f;

        ippsSum_32f(sq, n, &sum, ippAlgHintFast);
        if (mean_power) *mean_power = sum / (float)n;
    }

    if (peak) *peak = mx;
    if (peak_index) *peak_index = mi;

    ippFree(pool);
}