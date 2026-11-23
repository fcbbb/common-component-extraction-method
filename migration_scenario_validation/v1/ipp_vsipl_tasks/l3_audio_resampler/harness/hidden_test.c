/* Hidden evaluation: replays every stored conversion session through the
 * candidate resampler and compares the converted stream and its periodogram
 * with the buffers produced by the IPP baseline.
 *
 * The stream and the spectral magnitudes are compared peak-relative with the
 * peak as the scale; the bin count and the peak bin are compared exactly.  All
 * comparisons are written as `!(r <= tol)` so that a NaN counts as a failure.
 *
 * Usage: hidden_test <hidden-dir>
 */
#include "resampler.h"
#include "cases.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const double RTOL = 1.0e-5;

/* `total` and `centroid` are aggregates over the whole frame, and adding nbin
 * floats carries an order-dependent rounding of O(nbin*eps) -- about 3e-5 for
 * the 257-bin frames here, observed at 1.4e-5 between two correct kernels.  A
 * sum that has to agree with a reference cannot be held to the element-wise
 * tolerance, but a scaling mistake still shows up far above this. */
static const double RTOL_SUM = 1.0e-4;

int main(int argc, char **argv)
{
    const char *dir;
    int failures = 0;
    int ci;
    double worst = 0.0;

    if (argc < 2) {
        fprintf(stderr, "usage: hidden_test <hidden-dir>\n");
        return 2;
    }
    dir = argv[1];

    for (ci = 0; ci < RES_NCASES; ++ci) {
        char path[1024];
        int hdr[8];
        int up, down, ntaps, fft_len, nin, nout, block, nbin;
        double cutoff;
        double *dx, *dy, *dmag2, *dstats;
        float *fx, *fy, *fout, *fmag2;
        res_config cfg;
        res_state *st;
        res_report rep;
        int pos, wpos = 0, bad = 0, frames, i;
        double cworst = 0.0;
        double ypeak = 1.0, mpeak = 1.0;
        FILE *fp;

        snprintf(path, sizeof(path), "%s/case_%d.bin", dir, ci);
        fp = fopen(path, "rb");
        if (!fp) {
            fprintf(stderr, "case %d: cannot open %s\n", ci, path);
            ++failures;
            continue;
        }

        {
            char magic[4];

            if (fread(magic, 1, 4, fp) != 4 || memcmp(magic, "RSPL", 4) != 0 ||
                fread(hdr, sizeof(int), 8, fp) != 8 ||
                fread(&cutoff, sizeof(double), 1, fp) != 1) {
                fprintf(stderr, "case %d: bad header\n", ci);
                fclose(fp);
                ++failures;
                continue;
            }
        }

        up = hdr[0]; down = hdr[1]; ntaps = hdr[2]; fft_len = hdr[3];
        nin = hdr[4]; nout = hdr[5]; block = hdr[6]; nbin = hdr[7];

        dx = (double *)calloc((size_t)nin, sizeof(double));
        dy = (double *)calloc((size_t)(nout > 0 ? nout : 1), sizeof(double));
        dmag2 = (double *)calloc((size_t)nbin, sizeof(double));
        dstats = (double *)calloc(4, sizeof(double));
        fx = (float *)calloc((size_t)nin, sizeof(float));
        fy = (float *)calloc((size_t)(nout > 0 ? nout : 1), sizeof(float));
        fout = (float *)calloc((size_t)(nout > 0 ? nout : 1), sizeof(float));
        fmag2 = (float *)calloc((size_t)nbin, sizeof(float));

        if (!dx || !dy || !dmag2 || !dstats || !fx || !fy || !fout || !fmag2) {
            fprintf(stderr, "case %d: out of memory\n", ci);
            return 2;
        }

        if (fread(dx, sizeof(double), (size_t)nin, fp) != (size_t)nin ||
            fread(dy, sizeof(double), (size_t)nout, fp) != (size_t)nout ||
            fread(dmag2, sizeof(double), (size_t)nbin, fp) != (size_t)nbin ||
            fread(dstats, sizeof(double), 4, fp) != 4) {
            fprintf(stderr, "case %d: short read\n", ci);
            fclose(fp);
            ++failures;
            continue;
        }
        fclose(fp);

        for (i = 0; i < nin; ++i) fx[i] = (float)dx[i];
        for (i = 0; i < nout; ++i) {
            if (fabs(dy[i]) > ypeak) ypeak = fabs(dy[i]);
        }
        for (i = 0; i < nbin; ++i) {
            if (fabs(dmag2[i]) > mpeak) mpeak = fabs(dmag2[i]);
        }

        cfg.up = up;
        cfg.down = down;
        cfg.ntaps = ntaps;
        cfg.cutoff = (float)cutoff;
        cfg.fft_len = fft_len;

        st = res_create(&cfg);
        if (!st) {
            printf("case %d: res_create failed\n", ci);
            ++failures;
            continue;
        }

        for (pos = 0; pos < nin; pos += block) {
            int n = block;
            int got;

            if (pos + n > nin) n = nin - pos;
            got = res_process(st, fx + pos, n, fout, res_max_out(st, n));
            if (got < 0) {
                printf("case %d: res_process failed at input %d\n", ci, pos);
                ++bad;
                break;
            }
            if (wpos + got <= nout) {
                memcpy(fy + wpos, fout, (size_t)got * sizeof(float));
            }
            wpos += got;
        }

        if (bad == 0 && wpos != nout) {
            printf("case %d: converted %d samples, expected %d\n",
                   ci, wpos, nout);
            ++bad;
        }

        if (bad == 0) {
            double r;

            for (i = 0; i < nout; ++i) {
                r = fabs((double)fy[i] - dy[i]) / ypeak;
                if (!(r <= cworst)) cworst = r;
                if (!(r <= RTOL)) {
                    if (bad < 3) printf("  y[%d] rel %.3e\n", i, r);
                    ++bad;
                }
            }

            frames = res_spectrum(st, fy, nout, fmag2, &rep);
            if (frames <= 0) {
                printf("case %d: res_spectrum returned %d\n", ci, frames);
                ++bad;
            } else {
                if (rep.nbins != nbin) {
                    printf("  nbins got %d want %d\n", rep.nbins, nbin);
                    ++bad;
                }
                for (i = 0; i < nbin; ++i) {
                    r = fabs((double)fmag2[i] - dmag2[i]) / mpeak;
                    if (!(r <= cworst)) cworst = r;
                    if (!(r <= RTOL)) {
                        if (bad < 3) printf("  mag2[%d] rel %.3e\n", i, r);
                        ++bad;
                    }
                }

                r = fabs((double)rep.power - dstats[0]) / mpeak;
                if (!(r <= cworst)) cworst = r;
                if (!(r <= RTOL)) {
                    if (bad < 3) printf("  power rel %.3e\n", r);
                    ++bad;
                }

                r = fabs((double)rep.total - dstats[2]) / mpeak;
                if (!(r <= cworst)) cworst = r;
                if (!(r <= RTOL_SUM)) {
                    if (bad < 3) printf("  total rel %.3e\n", r);
                    ++bad;
                }

                r = fabs((double)rep.centroid - dstats[3]) / (double)nbin;
                if (!(r <= cworst)) cworst = r;
                if (!(r <= RTOL_SUM)) {
                    if (bad < 3) printf("  centroid rel %.3e\n", r);
                    ++bad;
                }

                if (rep.power_bin != (int)dstats[1]) {
                    if (bad < 3)
                        printf("  power_bin got %d want %d\n",
                               rep.power_bin, (int)dstats[1]);
                    ++bad;
                }
            }
        }

        if (cworst > worst) worst = cworst;
        if (bad) ++failures;

        printf("case %d: %3d/%3d taps=%2d fft=%4d nin=%4d block=%3d -> %4d  "
               "worst_rel=%.3e  %s\n",
               ci, up, down, ntaps, fft_len, nin, block, nout, cworst,
               bad ? "FAIL" : "ok");

        res_destroy(st);
        free(dx); free(dy); free(dmag2); free(dstats);
        free(fx); free(fy); free(fout); free(fmag2);
    }

    printf("SUMMARY cases=%d failures=%d worst_rel=%.3e\n",
           RES_NCASES, failures, worst);

    return failures ? 1 : 0;
}