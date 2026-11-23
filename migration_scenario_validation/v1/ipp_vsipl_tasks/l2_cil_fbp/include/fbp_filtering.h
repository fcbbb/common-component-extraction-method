/* FBP projection filtering, as published by CIL.
 *
 * Lifted verbatim (signatures and semantics) from
 *   src/Core/include/FBP_filtering.h
 * of the Core Imaging Library, minus the IPP / OpenMP / C++ includes: the
 * header only has to describe the two entry points the Python wrapper calls.
 */
#ifndef FBP_FILTERING_H
#define FBP_FILTERING_H

#ifdef __cplusplus
extern "C" {
#endif

/* data is [num_proj][pix_y][pix_x], weights is [pix_y][pix_x],
 * filter is 2^order long (the frequency response of the reconstruction
 * filter, index 0 = DC).  Filters the projections in place. */
int filter_projections_avh(float *data, const float *filter, const float *weights,
                           int order, long num_proj, long pix_y, long pix_x);

/* data is [pix_y][num_proj][pix_x], weights is [pix_y][pix_x],
 * filter is 2^order long.  Same operation, with the acquisition data stored
 * angle-major. */
int filter_projections_vah(float *data, const float *filter, const float *weights,
                           int order, long pix_y, long num_proj, long pix_x);

#ifdef __cplusplus
}
#endif

#endif /* FBP_FILTERING_H */