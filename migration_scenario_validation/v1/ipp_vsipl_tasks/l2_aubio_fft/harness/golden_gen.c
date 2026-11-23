/* Generates the hidden case containers from the IPP baseline.
 *
 * Container layout (little endian, native float32):
 *   "AUBF"
 *   int32 winsize, op, nframes, m, ncompare, circ
 *   float32 payload[]   (in[0..ncompare_input-1]; absent for FFT_INVALID)
 *   float32 expected[ncompare]
 *
 * Usage: golden_gen <out-dir>
 */
#include "aubio_fft.h"
#include "cases.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void fill_frame(float *x, int n, uint64_t seed)
{
    uint64_t st = seed;
    int i;
    for (i = 0; i < n; ++i)
        x[i] = aubio_fft_rand(&st);
}

int main(int argc, char **argv)
{
    const char *dir = (argc > 1) ? argv[1] : "hidden";
    char path[512];
    uint64_t seed = 0xA0B10F17ULL;
    int ci;

    for (ci = 0; ci < AUBIO_FFT_NCASES; ++ci) {
        const aubio_fft_case *c = &aubio_fft_cases[ci];
        const int n = c->winsize;
        const int m = n / 2 + 1;
        const int nframes = (c->nframes > 0) ? c->nframes : 0;
        const int ncompare = aubio_fft_ncompare(c->op, n, nframes);
        const int circ = aubio_fft_circular(c->op);
        float *payload = NULL, *expected = NULL;
        int payload_len = 0;
        int f;
        FILE *fp;
        aubio_fft_t *s = NULL;

        if (c->op == FFT_INVALID) {
            s = new_aubio_fft((uint_t)n);
            if (s != NULL) {
                fprintf(stderr, "case %d: new_aubio_fft(%d) did not return NULL\n", ci, n);
                del_aubio_fft(s);
                return 2;
            }
            fp = fopen((snprintf(path, sizeof(path), "%s/case_%d.bin", dir, ci), path), "wb");
            if (!fp) return 2;
            {
                int hdr[6] = { n, c->op, nframes, m, 0, 0 };
                fwrite("AUBF", 1, 4, fp);
                fwrite(hdr, sizeof(int), 6, fp);
            }
            fclose(fp);
            printf("case %2d (n=%4d invalid): new_aubio_fft -> NULL\n", ci, n);
            continue;
        }

        payload_len = (c->op == FFT_GET_REALIMAG) ? 2 * m : nframes * n;
        payload = (float *)malloc(sizeof(float) * (size_t)payload_len);
        expected = (float *)malloc(sizeof(float) * (size_t)ncompare);
        if (!payload || !expected) return 2;

        s = new_aubio_fft((uint_t)n);
        if (!s) {
            fprintf(stderr, "case %d: new_aubio_fft(%d) failed\n", ci, n);
            return 2;
        }

        if (c->op == FFT_GET_REALIMAG) {
            float *compdata = (float *)malloc(sizeof(float) * (size_t)n);
            float *phas = (float *)malloc(sizeof(float) * (size_t)m);
            fvec_t fin, comp;
            cvec_t spec;

            if (!compdata || !phas) return 2;

            fin.length = (uint_t)n; fin.data = payload;
            comp.length = (uint_t)n; comp.data = compdata;
            spec.length = (uint_t)m; spec.norm = payload; spec.phas = phas;

            fill_frame(payload, n, seed + (uint64_t)ci * 7919ULL);
            aubio_fft_do_complex(s, &fin, &comp);
            aubio_fft_get_spectrum(&comp, &spec);

            /* payload = norm[m] followed by phas[m] */
            memcpy(payload + m, phas, sizeof(float) * (size_t)m);

            aubio_fft_get_realimag(&spec, &comp);
            memcpy(expected, compdata, sizeof(float) * (size_t)n);

            free(compdata);
            free(phas);
        } else {
            float *frame = (float *)malloc(sizeof(float) * (size_t)n);
            fvec_t fin, fout, fcomp;
            cvec_t spec;
            if (!frame) return 2;
            fin.length = (uint_t)n; fin.data = frame;
            fout.length = (uint_t)n; fout.data = expected;
            fcomp.length = (uint_t)n; fcomp.data = NULL;
            spec.length = (uint_t)m; spec.norm = NULL; spec.phas = NULL;

            for (f = 0; f < nframes; ++f) {
                fill_frame(frame, n, seed + (uint64_t)ci * 7919ULL + (uint64_t)f * 104729ULL);
                memcpy(payload + (size_t)f * n, frame, sizeof(float) * (size_t)n);

                switch (c->op) {
                    case FFT_DO_COMPLEX:
                        fcomp.data = expected + (size_t)f * n;
                        aubio_fft_do_complex(s, &fin, &fcomp);
                        break;
                    case FFT_GET_SPECTRUM:
                        spec.norm = expected + (size_t)f * 2 * m;
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
            free(frame);
        }

        del_aubio_fft(s);

        fp = fopen((snprintf(path, sizeof(path), "%s/case_%d.bin", dir, ci), path), "wb");
        if (!fp) return 2;
        {
            int hdr[6] = { n, c->op, nframes, m, ncompare, circ };
            fwrite("AUBF", 1, 4, fp);
            fwrite(hdr, sizeof(int), 6, fp);
        }
        fwrite(payload, sizeof(float), (size_t)payload_len, fp);
        fwrite(expected, sizeof(float), (size_t)ncompare, fp);
        fclose(fp);

        printf("case %2d (n=%4d op=%d frames=%d): exp[0]=% .6f exp[1]=% .6f\n",
               ci, n, c->op, nframes, (double)expected[0],
               ncompare > 1 ? (double)expected[1] : 0.0);

        free(payload);
        free(expected);
    }
    return 0;
}