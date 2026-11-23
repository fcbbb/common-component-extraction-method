/* The one call sequence shared by golden_gen and hidden_test, so the baseline
 * and the candidate are driven identically. */
#ifndef FBP_OPS_H
#define FBP_OPS_H

#include <stdlib.h>
#include <string.h>

#include "fbp_filtering.h"
#include "cases.h"

static void fbp_compute(const fbp_case *c, const double *p, double *out)
{
    long dlen = fbp_datalen(c);
    long wlen = fbp_wlen(c);
    int width = fbp_width(c);
    long i;

    float *data    = (float*)malloc((size_t)dlen * sizeof(float));
    float *filter  = (float*)malloc((size_t)width * sizeof(float));
    float *weights = (float*)malloc((size_t)wlen * sizeof(float));

    for (i = 0; i < dlen; ++i) data[i] = (float)p[i];
    for (i = 0; i < width; ++i) filter[i] = (float)p[dlen + i];
    for (i = 0; i < wlen; ++i) weights[i] = (float)p[dlen + width + i];

    if (c->which == 0)
        filter_projections_avh(data, filter, weights, c->order,
                               c->num_proj, c->pix_y, c->pix_x);
    else
        filter_projections_vah(data, filter, weights, c->order,
                               c->pix_y, c->num_proj, c->pix_x);

    for (i = 0; i < dlen; ++i) out[i] = (double)data[i];

    free(data);
    free(filter);
    free(weights);
}

#endif /* FBP_OPS_H */