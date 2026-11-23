/* Public tests: the visible half of the evaluation.
 *
 * These compare the two entry points against a double-precision direct DFT and
 * against the identity that the filter pair implies (forward scaled by 1/N,
 * inverse unscaled), so a wrong packing order, a wrong transform scale or a
 * missing weight multiplication all fail loudly.
 */
#include "fbp_filtering.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

#define CHECK(cond, msg) do { \
    if (!(cond)) { printf("FAIL %s\n", msg); ++failures; } \
    else         { printf("ok   %s\n", msg); } \
} while (0)

static int failures = 0;

static double peak(const double *v, long n)
{
    long i;
    double p = 0.0;
    for (i = 0; i < n; ++i) if (fabs(v[i]) > p) p = fabs(v[i]);
    return p > 1.0 ? p : 1.0;
}

/* Filters one pair of rows through a direct DFT: two rows of nx samples are
 * packed as the real and imaginary parts of one centred complex vector, the
 * spectrum is scaled by 1/N (IPP's IPP_FFT_DIV_FWD_BY_N), multiplied by the
 * real filter, and transformed back without a scale.  ia / wa_im may be NULL,
 * which means the imaginary part is zero (the odd tail row). */
static void ref_filter_pair(const double *ra, const double *ia,
                            const double *wa_re, const double *wa_im,
                            const double *filt, int nx, int width, int offset,
                            double *ra_out, double *ia_out)
{
    double *xr = (double*)calloc((size_t)width, sizeof(double));
    double *xi = (double*)calloc((size_t)width, sizeof(double));
    double *yr = (double*)calloc((size_t)width, sizeof(double));
    double *yi = (double*)calloc((size_t)width, sizeof(double));
    int t, k, i;

    for (i = 0; i < nx; ++i) {
        xr[offset + i] = ra[i] * wa_re[i];
        xi[offset + i] = ia ? ia[i] * wa_im[i] : 0.0;
    }

    /* forward, scaled by 1/width */
    for (k = 0; k < width; ++k) {
        double re = 0.0, im = 0.0;
        for (t = 0; t < width; ++t) {
            double a = -2.0 * M_PI * (double)k * (double)t / (double)width;
            double c = cos(a), s = sin(a);
            re += xr[t] * c - xi[t] * s;
            im += xr[t] * s + xi[t] * c;
        }
        yr[k] = re * filt[k] / (double)width;
        yi[k] = im * filt[k] / (double)width;
    }

    /* inverse, unscaled */
    for (t = 0; t < width; ++t) {
        double re = 0.0, im = 0.0;
        for (k = 0; k < width; ++k) {
            double a = +2.0 * M_PI * (double)k * (double)t / (double)width;
            double c = cos(a), s = sin(a);
            re += yr[k] * c - yi[k] * s;
            im += yr[k] * s + yi[k] * c;
        }
        xr[t] = re;
        xi[t] = im;
    }

    for (i = 0; i < nx; ++i) {
        ra_out[i] = xr[offset + i];
        if (ia_out) ia_out[i] = xi[offset + i];
    }

    free(xr); free(xi); free(yr); free(yi);
}

static void check_identity(int which)
{
    const long np = 3, ny = 4, nx = 8;
    const int order = 4, width = 1 << order;
    const long dlen = np * ny * nx, wlen = ny * nx;
    float *data = (float*)malloc(sizeof(float) * dlen);
    float *work = (float*)malloc(sizeof(float) * dlen);
    float *filter = (float*)malloc(sizeof(float) * width);
    float *weights = (float*)malloc(sizeof(float) * wlen);
    double *ref = (double*)malloc(sizeof(double) * dlen);
    long i;
    int k, bad = 0;

    for (i = 0; i < dlen; ++i) data[i] = (float)((double)((i * 37) % 101) / 50.0 - 1.0);
    for (k = 0; k < width; ++k) filter[k] = 1.0f;
    for (i = 0; i < wlen; ++i) weights[i] = 0.5f + (float)((i * 13) % 17) / 20.0f;

    /* With an all-ones filter the forward 1/N and the unscaled inverse cancel,
     * so the result is just the weighted input. */
    for (i = 0; i < dlen; ++i) ref[i] = (double)data[i];
    if (which == 0) {
        /* avh: weights are [pix_y][pix_x], the same rows in every projection */
        for (i = 0; i < dlen; ++i) ref[i] *= (double)weights[i % (ny * nx)];
    } else {
        /* vah: data is [pix_y][num_proj][pix_x], one weights row per block */
        for (i = 0; i < dlen; ++i)
            ref[i] *= (double)weights[(i / (np * nx)) * nx + (i % nx)];
    }

    memcpy(work, data, sizeof(float) * dlen);
    if (which == 0)
        filter_projections_avh(work, filter, weights, order, np, ny, nx);
    else
        filter_projections_vah(work, filter, weights, order, ny, np, nx);

    for (i = 0; i < dlen; ++i)
        if (fabs((double)work[i] - ref[i]) > 1.0e-4 * peak(ref, dlen)) ++bad;
    CHECK(bad == 0, which == 0
        ? "avh with an all-ones filter is the weighted input"
        : "vah with an all-ones filter is the weighted input");

    free(data); free(work); free(filter); free(weights); free(ref);
}

/* Runs one avh case with a band-limited filter and compares against the
 * direct DFT. */
static void check_avh_dft(long np, long ny, long nx, int order)
{
    const int width = 1 << order;
    const int offset = (int)((width - nx) / 2);
    const long dlen = np * ny * nx, wlen = ny * nx;
    float *data = (float*)malloc(sizeof(float) * dlen);
    float *work = (float*)malloc(sizeof(float) * dlen);
    float *filter = (float*)malloc(sizeof(float) * width);
    float *weights = (float*)malloc(sizeof(float) * wlen);
    double *ref = (double*)malloc(sizeof(double) * dlen);
    double *fd = (double*)malloc(sizeof(double) * width);
    double *ra = (double*)malloc(sizeof(double) * nx);
    double *ia = (double*)malloc(sizeof(double) * nx);
    double *wa = (double*)malloc(sizeof(double) * nx);
    double *wb = (double*)malloc(sizeof(double) * nx);
    double *oa = (double*)malloc(sizeof(double) * nx);
    double *ob = (double*)malloc(sizeof(double) * nx);
    long i, p;
    int k;
    double scale;
    char msg[160];

    for (i = 0; i < dlen; ++i) data[i] = (float)(sin(0.13 * (double)i) + 0.4 * cos(0.07 * (double)i));
    for (k = 0; k < width; ++k) filter[k] = (float)(1.0 - 0.4 * (double)k / (double)width);
    for (k = 0; k < width; ++k) fd[k] = (double)filter[k];
    for (i = 0; i < wlen; ++i) weights[i] = (float)(0.7 + 0.2 * (double)(i % 5));

    /* reference: filter every projection independently, two rows at a time */
    for (p = 0; p < np; ++p) {
        long base = p * ny * nx;
        long r;
        for (r = 0; r + 1 < ny; r += 2) {
            for (i = 0; i < nx; ++i) {
                ra[i] = (double)data[base + r * nx + i];
                ia[i] = (double)data[base + (r + 1) * nx + i];
                wa[i] = (double)weights[r * nx + i];
                wb[i] = (double)weights[(r + 1) * nx + i];
            }
            ref_filter_pair(ra, ia, wa, wb, fd, (int)nx, width, offset, oa, ob);
            for (i = 0; i < nx; ++i) {
                ref[base + r * nx + i] = oa[i];
                ref[base + (r + 1) * nx + i] = ob[i];
            }
        }
        if (ny % 2) {
            r = ny - 1;
            for (i = 0; i < nx; ++i) {
                ra[i] = (double)data[base + r * nx + i];
                wa[i] = (double)weights[r * nx + i];
            }
            ref_filter_pair(ra, NULL, wa, NULL, fd, (int)nx, width, offset, oa, NULL);
            for (i = 0; i < nx; ++i) ref[base + r * nx + i] = oa[i];
        }
    }

    memcpy(work, data, sizeof(float) * dlen);
    filter_projections_avh(work, filter, weights, order, np, ny, nx);

    scale = peak(ref, dlen);
    k = 0;
    for (i = 0; i < dlen; ++i)
        if (fabs((double)work[i] - ref[i]) > 2.0e-4 * scale) ++k;
    snprintf(msg, sizeof(msg),
             "avh (np=%ld ny=%ld nx=%ld order=%d) matches the direct DFT", np, ny, nx, order);
    CHECK(k == 0, msg);

    free(data); free(work); free(filter); free(weights); free(ref); free(fd);
    free(ra); free(ia); free(wa); free(wb); free(oa); free(ob);
}

/* Same for the vertical-major layout: data is [pix_y][num_proj][pix_x] and
 * one weights row of pix_x entries applies to every projection of a block. */
static void check_vah_dft(long np, long ny, long nx, int order)
{
    const int width = 1 << order;
    const int offset = (int)((width - nx) / 2);
    const long dlen = np * ny * nx, wlen = ny * nx;
    float *data = (float*)malloc(sizeof(float) * dlen);
    float *work = (float*)malloc(sizeof(float) * dlen);
    float *filter = (float*)malloc(sizeof(float) * width);
    float *weights = (float*)malloc(sizeof(float) * wlen);
    double *ref = (double*)malloc(sizeof(double) * dlen);
    double *fd = (double*)malloc(sizeof(double) * width);
    double *ra = (double*)malloc(sizeof(double) * nx);
    double *ia = (double*)malloc(sizeof(double) * nx);
    double *wa = (double*)malloc(sizeof(double) * nx);
    double *wb = (double*)malloc(sizeof(double) * nx);
    double *oa = (double*)malloc(sizeof(double) * nx);
    double *ob = (double*)malloc(sizeof(double) * nx);
    long i, col;
    int k;
    double scale;
    char msg[160];

    for (i = 0; i < dlen; ++i) data[i] = (float)(cos(0.11 * (double)i) - 0.3 * sin(0.05 * (double)i));
    for (k = 0; k < width; ++k) filter[k] = (float)(0.5 + 0.5 * cos(M_PI * (double)k / (double)width));
    for (k = 0; k < width; ++k) fd[k] = (double)filter[k];
    for (i = 0; i < wlen; ++i) weights[i] = (float)(0.6 + 0.3 * (double)(i % 3));

    for (col = 0; col < ny; ++col) {
        long base = col * np * nx;
        long r;
        for (r = 0; r + 1 < np; r += 2) {
            for (i = 0; i < nx; ++i) {
                ra[i] = (double)data[base + r * nx + i];
                ia[i] = (double)data[base + (r + 1) * nx + i];
                wa[i] = (double)weights[col * nx + i];
                wb[i] = (double)weights[col * nx + i];
            }
            ref_filter_pair(ra, ia, wa, wb, fd, (int)nx, width, offset, oa, ob);
            for (i = 0; i < nx; ++i) {
                ref[base + r * nx + i] = oa[i];
                ref[base + (r + 1) * nx + i] = ob[i];
            }
        }
        if (np % 2) {
            r = np - 1;
            for (i = 0; i < nx; ++i) {
                ra[i] = (double)data[base + r * nx + i];
                wa[i] = (double)weights[col * nx + i];
            }
            ref_filter_pair(ra, NULL, wa, NULL, fd, (int)nx, width, offset, oa, NULL);
            for (i = 0; i < nx; ++i) ref[base + r * nx + i] = oa[i];
        }
    }

    memcpy(work, data, sizeof(float) * dlen);
    filter_projections_vah(work, filter, weights, order, ny, np, nx);

    scale = peak(ref, dlen);
    k = 0;
    for (i = 0; i < dlen; ++i)
        if (fabs((double)work[i] - ref[i]) > 2.0e-4 * scale) ++k;
    snprintf(msg, sizeof(msg),
             "vah (np=%ld ny=%ld nx=%ld order=%d) matches the direct DFT", np, ny, nx, order);
    CHECK(k == 0, msg);

    free(data); free(work); free(filter); free(weights); free(ref); free(fd);
    free(ra); free(ia); free(wa); free(wb); free(oa); free(ob);
}

int main(void)
{
    check_identity(0);
    check_identity(1);
    check_avh_dft(2, 4, 6, 4);
    check_avh_dft(1, 3, 4, 3);       /* odd pix_y: tail row */
    check_avh_dft(2, 1, 4, 3);       /* pix_y = 1: only the tail row */
    check_vah_dft(4, 2, 6, 4);
    check_vah_dft(3, 1, 4, 3);       /* odd num_proj, single column block */
    check_vah_dft(2, 3, 5, 4);       /* odd pix_x */

    printf("%s: %d failure(s)\n", failures ? "FAIL" : "PASS", failures);
    return failures == 0 ? 0 : 1;
}