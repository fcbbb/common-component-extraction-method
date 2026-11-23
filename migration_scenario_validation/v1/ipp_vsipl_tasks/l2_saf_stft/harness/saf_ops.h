/* Shared driver: runs one case through the public SAF FFT API.
 *
 * Both the golden generator and the hidden test call compute() so that the
 * sequence of API calls is identical on the two sides; only the comparison
 * differs.  Nothing here reaches past the published interface -- it is the
 * same code a user of the component would write.
 */
#ifndef SAF_OPS_H
#define SAF_OPS_H

#include "saf_utility_fft.h"
#include "cases.h"

#include <stdlib.h>
#include <string.h>

static int saf_fd_chmax(const saf_case *c)
{
    return (c->nchin > c->nchout) ? c->nchin : c->nchout;
}

/* The frequency-domain buffers are sized for the larger channel count: the
 * forward transform writes nCHin channels even when the handle was created
 * with fewer outputs. */
static float_complex*** saf_fd_alloc(const saf_case *c)
{
    int d0, d1, d2;
    saf_fd_dims(c, saf_fd_chmax(c), &d0, &d1, &d2);
    return (float_complex***)calloc3d(d0, d1, d2, sizeof(float_complex));
}

static float** saf_td_alloc(int nch, int len)
{
    return (float**)calloc2d(nch, len, sizeof(float));
}

static void saf_load_td(float **td, int nch, int len, const double *p, int offset)
{
    int ch, i;
    for (ch = 0; ch < nch; ++ch)
        for (i = 0; i < len; ++i)
            td[ch][i] = (float)p[offset + ch * len + i];
}

static void saf_dump_td(float **td, int nch, int len, double *out)
{
    int ch, i;
    for (ch = 0; ch < nch; ++ch)
        for (i = 0; i < len; ++i)
            out[ch * len + i] = (double)td[ch][i];
}

static void saf_load_cplx(const double *p, int n, float_complex *z)
{
    int i;
    for (i = 0; i < n; ++i) z[i] = cmplxf((float)p[2 * i], (float)p[2 * i + 1]);
}

static void saf_dump_cplx(const float_complex *z, int n, double *out)
{
    int i;
    for (i = 0; i < n; ++i) {
        out[2 * i]     = (double)crealf(z[i]);
        out[2 * i + 1] = (double)cimagf(z[i]);
    }
}

static void saf_compute(const saf_case *c, const double *p, double *out)
{
    int i, framesize = saf_framesize(c), inlen = saf_inlen(c);

    switch (c->op) {

    case SAF_OP_RFFT_FWD: {
        void *h;
        float *in  = (float*)malloc1d((size_t)c->n * sizeof(float));
        float_complex *X = (float_complex*)malloc1d((size_t)(c->n / 2 + 1) * sizeof(float_complex));
        for (i = 0; i < c->n; ++i) in[i] = (float)p[i];
        saf_rfft_create(&h, c->n);
        saf_rfft_forward(h, in, X);
        for (i = 0; i < c->n + 2; ++i) out[i] = (double)((float*)X)[i];
        saf_rfft_destroy(&h);
        free(in);
        free(X);
        break;
    }

    case SAF_OP_RFFT_BWD: {
        void *h;
        float_complex *X = (float_complex*)malloc1d((size_t)(c->n / 2 + 1) * sizeof(float_complex));
        float *y = (float*)malloc1d((size_t)c->n * sizeof(float));
        for (i = 0; i < c->n + 2; ++i) ((float*)X)[i] = (float)p[i];
        saf_rfft_create(&h, c->n);
        saf_rfft_backward(h, X, y);
        for (i = 0; i < c->n; ++i) out[i] = (double)y[i];
        saf_rfft_destroy(&h);
        free(X);
        free(y);
        break;
    }

    case SAF_OP_RFFT_ROUND: {
        void *h;
        float *in = (float*)malloc1d((size_t)c->n * sizeof(float));
        float_complex *X = (float_complex*)malloc1d((size_t)(c->n / 2 + 1) * sizeof(float_complex));
        float *y = (float*)malloc1d((size_t)c->n * sizeof(float));
        for (i = 0; i < c->n; ++i) in[i] = (float)p[i];
        saf_rfft_create(&h, c->n);
        saf_rfft_forward(h, in, X);
        saf_rfft_backward(h, X, y);
        for (i = 0; i < c->n; ++i) out[i] = (double)y[i];
        saf_rfft_destroy(&h);
        free(in);
        free(X);
        free(y);
        break;
    }

    case SAF_OP_CFFT_FWD:
    case SAF_OP_CFFT_BWD:
    case SAF_OP_CFFT_ROUND: {
        void *h;
        float_complex *x = (float_complex*)malloc1d((size_t)c->n * sizeof(float_complex));
        float_complex *y = (float_complex*)malloc1d((size_t)c->n * sizeof(float_complex));
        float_complex *z = (float_complex*)malloc1d((size_t)c->n * sizeof(float_complex));
        saf_load_cplx(p, c->n, x);
        saf_fft_create(&h, c->n);
        if (c->op == SAF_OP_CFFT_FWD) {
            saf_fft_forward(h, x, y);
            saf_dump_cplx(y, c->n, out);
        } else if (c->op == SAF_OP_CFFT_BWD) {
            saf_fft_backward(h, x, y);
            saf_dump_cplx(y, c->n, out);
        } else {
            saf_fft_forward(h, x, y);
            saf_fft_backward(h, y, z);
            saf_dump_cplx(z, c->n, out);
        }
        saf_fft_destroy(&h);
        free(x);
        free(y);
        free(z);
        break;
    }

    case SAF_OP_STFT_FWD: {
        void *h;
        float **td = saf_td_alloc(c->nchin, inlen);
        float_complex ***fd = saf_fd_alloc(c);
        saf_load_td(td, c->nchin, inlen, p, 0);
        saf_stft_create(&h, c->win, c->hop, c->nchin, c->nchout, (SAF_STFT_FDDATA_FORMAT)c->fmt);
        saf_stft_forward(h, td, framesize, fd);
        saf_fd_to_linear(c, fd, c->nchin, out);
        saf_stft_destroy(&h);
        break;
    }

    case SAF_OP_STFT_BWD: {
        void *h;
        float **td = saf_td_alloc(c->nchout, framesize);
        float_complex ***fd = saf_fd_alloc(c);
        saf_fd_from_linear(c, p, fd, c->nchout);
        saf_stft_create(&h, c->win, c->hop, c->nchin, c->nchout, (SAF_STFT_FDDATA_FORMAT)c->fmt);
        saf_stft_backward(h, fd, framesize, td);
        saf_dump_td(td, c->nchout, framesize, out);
        saf_stft_destroy(&h);
        break;
    }

    case SAF_OP_STFT_ROUND: {
        void *h;
        float **td = saf_td_alloc(c->nchout, framesize);
        float **in = saf_td_alloc(c->nchin, inlen);
        float_complex ***fd = saf_fd_alloc(c);
        saf_load_td(in, c->nchin, inlen, p, 0);
        saf_stft_create(&h, c->win, c->hop, c->nchin, c->nchout, (SAF_STFT_FDDATA_FORMAT)c->fmt);
        saf_stft_forward(h, in, framesize, fd);
        saf_stft_backward(h, fd, framesize, td);
        saf_dump_td(td, c->nchout, framesize, out);
        saf_stft_destroy(&h);
        break;
    }

    case SAF_OP_STFT_STATEFUL:
    case SAF_OP_STFT_FLUSH: {
        void *h;
        float **td = saf_td_alloc(c->nchout, framesize);
        float **in = saf_td_alloc(c->nchin, inlen);
        float_complex ***fd = saf_fd_alloc(c);
        saf_load_td(in, c->nchin, inlen, p, 0);
        saf_stft_create(&h, c->win, c->hop, c->nchin, c->nchout, (SAF_STFT_FDDATA_FORMAT)c->fmt);
        saf_stft_forward(h, in, framesize, fd);
        saf_stft_backward(h, fd, framesize, td);
        saf_dump_td(td, c->nchout, framesize, out);
        if (c->op == SAF_OP_STFT_FLUSH)
            saf_stft_flushBuffers(h);
        saf_stft_backward(h, fd, framesize, td);
        saf_dump_td(td, c->nchout, framesize, out + c->nchout * framesize);
        saf_stft_destroy(&h);
        break;
    }

    case SAF_OP_STFT_CHCHANGE: {
        void *h;
        float **td = saf_td_alloc(2, framesize);
        float **in2 = saf_td_alloc(2, inlen);
        float **in1 = saf_td_alloc(1, inlen);
        float_complex ***fd = saf_fd_alloc(c);
        saf_load_td(in2, 2, inlen, p, 0);
        saf_load_td(in1, 1, inlen, p, 2 * inlen);
        saf_stft_create(&h, c->win, c->hop, 2, 2, (SAF_STFT_FDDATA_FORMAT)c->fmt);
        saf_stft_forward(h, in2, framesize, fd);
        saf_stft_backward(h, fd, framesize, td);
        saf_stft_channelChange(h, 1, 1);
        saf_stft_forward(h, in1, framesize, fd);
        saf_stft_backward(h, fd, framesize, td);
        saf_dump_td(td, 1, framesize, out);
        saf_stft_destroy(&h);
        break;
    }

    case SAF_OP_FFTCONV:
    case SAF_OP_FFTFILT: {
        int x_len = c->n, h_len = c->aux, nch = c->nchin;
        int ylen = (c->op == SAF_OP_FFTCONV) ? (x_len + h_len - 1) : x_len;
        float *x  = (float*)malloc1d((size_t)nch * (size_t)x_len * sizeof(float));
        float *hh = (float*)malloc1d((size_t)nch * (size_t)h_len * sizeof(float));
        float *y  = (float*)malloc1d((size_t)nch * (size_t)(x_len + h_len) * sizeof(float));
        int ch, j;
        for (ch = 0; ch < nch; ++ch) {
            for (j = 0; j < x_len; ++j)
                x[ch * x_len + j] = (float)p[ch * (x_len + h_len) + j];
            for (j = 0; j < h_len; ++j)
                hh[ch * h_len + j] = (float)p[ch * (x_len + h_len) + x_len + j];
        }
        if (c->op == SAF_OP_FFTCONV)
            fftconv(x, hh, x_len, h_len, nch, y);
        else
            fftfilt(x, hh, x_len, h_len, nch, y);
        for (ch = 0; ch < nch; ++ch)
            for (j = 0; j < ylen; ++j) out[ch * ylen + j] = (double)y[ch * ylen + j];
        free(x);
        free(hh);
        free(y);
        break;
    }

    case SAF_OP_HILBERT: {
        float_complex *x = (float_complex*)malloc1d((size_t)c->n * sizeof(float_complex));
        float_complex *y = (float_complex*)malloc1d((size_t)c->n * sizeof(float_complex));
        saf_load_cplx(p, c->n, x);
        hilbert(x, c->n, y);
        saf_dump_cplx(y, c->n, out);
        free(x);
        free(y);
        break;
    }

    case SAF_OP_FREQVEC: {
        float *fv = (float*)malloc1d((size_t)(c->n / 2 + 1) * sizeof(float));
        getUniformFreqVector(c->n, (float)c->aux, fv);
        for (i = 0; i < c->n / 2 + 1; ++i) out[i] = (double)fv[i];
        free(fv);
        break;
    }

    default:
        break;
    }
}

#endif /* SAF_OPS_H */