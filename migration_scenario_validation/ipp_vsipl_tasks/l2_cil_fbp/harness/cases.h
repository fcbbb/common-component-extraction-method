/* Case table shared by the golden generator and the hidden test. */
#ifndef FBP_CASES_H
#define FBP_CASES_H

#include <stdint.h>
#include <string.h>

typedef struct {
    int which;          /* 0 = filter_projections_avh, 1 = filter_projections_vah */
    int order;          /* transform length is 2^order */
    long num_proj;
    long pix_y;
    long pix_x;
} fbp_case;

static int fbp_width(const fbp_case *c) { return 1 << c->order; }
static long fbp_datalen(const fbp_case *c) { return c->num_proj * c->pix_y * c->pix_x; }
static long fbp_wlen(const fbp_case *c) { return c->pix_y * c->pix_x; }
static long fbp_payload_len(const fbp_case *c)
{
    return fbp_datalen(c) + fbp_width(c) + fbp_wlen(c);
}
static long fbp_ncompare(const fbp_case *c) { return fbp_datalen(c); }

/* The first five cases take the angle-major (avh) layout, the last five the
 * vertical-major (vah) one.  Each group covers an even/odd row count, a
 * single-projection block and a short transform. */
#define FBP_NCASES 10
static fbp_case fbp_cases[FBP_NCASES];

static void fbp_build_cases(void)
{
    int k = 0;

    /* avh: data is [num_proj][pix_y][pix_x] */
    fbp_cases[k].which = 0; fbp_cases[k].order = 6;
    fbp_cases[k].num_proj = 10; fbp_cases[k].pix_y = 16; fbp_cases[k].pix_x = 32; ++k;

    fbp_cases[k].which = 0; fbp_cases[k].order = 6;   /* odd pix_y: tail row */
    fbp_cases[k].num_proj = 7;  fbp_cases[k].pix_y = 15; fbp_cases[k].pix_x = 20; ++k;

    fbp_cases[k].which = 0; fbp_cases[k].order = 6;   /* single projection */
    fbp_cases[k].num_proj = 1;  fbp_cases[k].pix_y = 20; fbp_cases[k].pix_x = 24; ++k;

    fbp_cases[k].which = 0; fbp_cases[k].order = 5;
    fbp_cases[k].num_proj = 5;  fbp_cases[k].pix_y = 8;  fbp_cases[k].pix_x = 12; ++k;

    fbp_cases[k].which = 0; fbp_cases[k].order = 6;   /* pix_y = 1: only the tail */
    fbp_cases[k].num_proj = 4;  fbp_cases[k].pix_y = 1;  fbp_cases[k].pix_x = 32; ++k;

    /* vah: data is [pix_y][num_proj][pix_x] */
    fbp_cases[k].which = 1; fbp_cases[k].order = 6;
    fbp_cases[k].num_proj = 10; fbp_cases[k].pix_y = 16; fbp_cases[k].pix_x = 32; ++k;

    fbp_cases[k].which = 1; fbp_cases[k].order = 6;   /* odd num_proj: tail row */
    fbp_cases[k].num_proj = 11; fbp_cases[k].pix_y = 16; fbp_cases[k].pix_x = 32; ++k;

    fbp_cases[k].which = 1; fbp_cases[k].order = 6;   /* single projection */
    fbp_cases[k].num_proj = 1;  fbp_cases[k].pix_y = 9;  fbp_cases[k].pix_x = 24; ++k;

    fbp_cases[k].which = 1; fbp_cases[k].order = 5;
    fbp_cases[k].num_proj = 8;  fbp_cases[k].pix_y = 8;  fbp_cases[k].pix_x = 12; ++k;

    fbp_cases[k].which = 1; fbp_cases[k].order = 6;   /* single column block */
    fbp_cases[k].num_proj = 32; fbp_cases[k].pix_y = 1;  fbp_cases[k].pix_x = 32; ++k;
}

/* ------------------------------------------------------------------------- */
/*                            Input generation                              */
/* ------------------------------------------------------------------------- */

static inline double fbp_rand(uint64_t *s)
{
    uint64_t z = (*s += 0x9E3779B97F4A7C15ULL);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return ((double)((z ^ (z >> 31)) >> 11) / 9007199254740992.0) * 2.0 - 1.0;
}

/* payload = data[data_len], filter[2^order], weights[pix_y*pix_x] */
static void fbp_gen_payload(const fbp_case *c, uint64_t seed, double *p)
{
    long len = fbp_payload_len(c), i;
    long dlen = fbp_datalen(c);
    long wlen = fbp_wlen(c);
    int width = fbp_width(c);

    for (i = 0; i < dlen; ++i) p[i] = fbp_rand(&seed);

    /* The reconstruction filter is a smooth, low-pass response in the CIL
     * sense (DC at index 0, positive frequencies, then negative ones), not
     * white noise: a band-limited filter keeps the filtered rows in the same
     * dynamic range as the input and makes a layout error obvious instead of
     * hiding it under a random spectrum. */
    {
        double cutoff = 0.5 + 0.5 * (fbp_rand(&seed) + 1.0) * 0.5;   /* 0.5 .. 1.0 */
        int k;
        for (k = 0; k < width; ++k) {
            double f = (k <= width / 2) ? (double)k / (double)(width / 2)
                                        : (double)(width - k) / (double)(width / 2);
            p[dlen + k] = (f <= cutoff) ? (1.0 - 0.5 * f) * (1.0 + 0.1 * fbp_rand(&seed)) : 0.0;
        }
    }

    for (i = 0; i < wlen; ++i)
        p[dlen + width + i] = 0.5 + 0.5 * (fbp_rand(&seed) + 1.0);
}

#endif /* FBP_CASES_H */