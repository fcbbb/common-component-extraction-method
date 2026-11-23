/* Hidden evaluation: replays every stored case through the candidate fft and
 * compares with the IPP-generated buffers.
 *
 * Phase values are compared modulo 2*pi (they are angles in -pi..pi; a small
 * numerical difference around the -pi/pi seam must not count as a failure).
 *
 * Usage: hidden_test <hidden-dir>
 */
#include "aubio_fft.h"
#include "cases.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

static int is_phase_slot(int op, int m, int idx)
{
    if (op != FFT_GET_SPECTRUM) return 0;
    return (idx % (2 * m)) >= m;
}

static double slot_error(int phase, float got, float exp)
{
    if (phase) {
        double d = (double)got - (double)exp;
        d -= 2.0 * M_PI * floor(d / (2.0 * M_PI) + 0.5);
        return fabs(d);
    } else {
        double e = fabs((double)got - (double)exp);
        double s = fabs((double)exp);
        return (s > 1.0) ? e / s : e;
    }
}

int main(int argc, char **argv)
{
    const char *dir = (argc > 1) ? argv[1] : "hidden";
    char path[512];
    int ci, failures = 0;
    double worst = 0.0;

    for (ci = 0; ; ++ci) {
        char magic[4];
        int hdr[6];
        FILE *f;
        int n, op, nframes, m, ncompare;
        float *payload = NULL, *expected = NULL, *got = NULL;
        int payload_len;
        int ok = 1;
        double maxerr = 0.0;
        int firstBad = -1;
        aubio_fft_t *s = NULL;

        snprintf(path, sizeof(path), "%s/case_%d.bin", dir, ci);
        f = fopen(path, "rb");
        if (!f) break;
        if (fread(magic, 1, 4, f) != 4 || memcmp(magic, "AUBF", 4) != 0) {
            fprintf(stderr, "bad magic in %s\n", path);
            return 2;
        }
        if (fread(hdr, sizeof(int), 6, f) != 6) {
            fprintf(stderr, "bad header in %s\n", path);
            return 2;
        }
        n = hdr[0]; op = hdr[1]; nframes = hdr[2]; m = hdr[3]; ncompare = hdr[4];

        if (op == FFT_INVALID) {
            s = new_aubio_fft((uint_t)n);
            fclose(f);
            ok = (s == NULL);
            if (!ok) {
                printf("case %2d (n=%4d invalid): FAIL new_aubio_fft did not return NULL\n", ci, n);
                del_aubio_fft(s);
                ++failures;
            } else {
                printf("case %2d (n=%4d invalid): PASS\n", ci, n);
            }
            continue;
        }

        payload_len = (op == FFT_GET_REALIMAG) ? 2 * m : nframes * n;
        payload = (float *)malloc(sizeof(float) * (size_t)payload_len);
        expected = (float *)malloc(sizeof(float) * (size_t)(ncompare > 0 ? ncompare : 1));
        got = (float *)calloc((size_t)(ncompare > 0 ? ncompare : 1), sizeof(float));
        if (!payload || !expected || !got) return 2;
        if (fread(payload, sizeof(float), (size_t)payload_len, f) != (size_t)payload_len ||
            fread(expected, sizeof(float), (size_t)ncompare, f) != (size_t)ncompare) {
            fprintf(stderr, "short read in %s\n", path);
            return 2;
        }
        fclose(f);

        if (op == FFT_GET_REALIMAG) {
            fvec_t comp;
            cvec_t spec;
            comp.length = (uint_t)n;
            comp.data = got;
            spec.length = (uint_t)m;
            spec.norm = payload;
            spec.phas = payload + m;
            aubio_fft_get_realimag(&spec, &comp);
        } else {
            int fr;
            float *frame = (float *)malloc(sizeof(float) * (size_t)n);
            fvec_t fin, fout, fcomp;
            cvec_t spec;
            if (!frame) return 2;
            fin.length = (uint_t)n; fin.data = frame;
            fout.length = (uint_t)n; fout.data = got;
            fcomp.length = (uint_t)n; fcomp.data = NULL;
            spec.length = (uint_t)m; spec.norm = NULL; spec.phas = NULL;

            s = new_aubio_fft((uint_t)n);
            if (!s) {
                printf("case %2d (n=%4d op=%d): FAIL new_aubio_fft returned NULL\n", ci, n, op);
                ++failures;
                free(frame); free(payload); free(expected); free(got);
                continue;
            }

            for (fr = 0; fr < nframes; ++fr) {
                memcpy(frame, payload + (size_t)fr * n, sizeof(float) * (size_t)n);
                switch (op) {
                    case FFT_DO_COMPLEX:
                        fcomp.data = got + (size_t)fr * n;
                        aubio_fft_do_complex(s, &fin, &fcomp);
                        break;
                    case FFT_GET_SPECTRUM:
                        spec.norm = got + (size_t)fr * 2 * m;
                        spec.phas = spec.norm + m;
                        aubio_fft_do(s, &fin, &spec);
                        break;
                    case FFT_ROUNDTRIP_NORMPHAS:
                        spec.norm = (float *)malloc(sizeof(float) * (size_t)m);
                        spec.phas = (float *)malloc(sizeof(float) * (size_t)m);
                        if (!spec.norm || !spec.phas) return 2;
                        aubio_fft_do(s, &fin, &spec);
                        aubio_fft_rdo(s, &spec, &fout);
                        free(spec.norm); free(spec.phas);
                        break;
                    case FFT_ROUNDTRIP_COMPLEX:
                        fcomp.data = (float *)malloc(sizeof(float) * (size_t)n);
                        if (!fcomp.data) return 2;
                        aubio_fft_do_complex(s, &fin, &fcomp);
                        aubio_fft_rdo_complex(s, &fcomp, &fout);
                        free(fcomp.data);
                        break;
                }
            }
            del_aubio_fft(s);
            free(frame);
        }

        {
            int i;
            for (i = 0; i < ncompare; ++i) {
                const int ph = is_phase_slot(op, m, i);
                const double r = slot_error(ph, got[i], expected[i]);
                if (r > maxerr) maxerr = r;
                if (r > 1e-4 && firstBad < 0) firstBad = i;
            }
        }

        if (firstBad >= 0) {
            printf("case %2d (n=%4d op=%d): FAIL first at %d: got %.9g want %.9g\n",
                   ci, n, op, firstBad, (double)got[firstBad], (double)expected[firstBad]);
            ok = 0;
        }
        printf("case %2d (n=%4d op=%d frames=%d): %s maxerr=%.3e\n",
               ci, n, op, nframes, ok ? "PASS" : "FAIL", maxerr);
        if (maxerr > worst) worst = maxerr;
        if (!ok) ++failures;

        free(payload);
        free(expected);
        free(got);
    }

    printf("SUMMARY cases=%d failures=%d worst_rel=%.3e\n", ci, failures, worst);
    return failures == 0 ? 0 : 1;
}