/* Public API: HPEC-style dB magnitude kernel.
 *
 * Converts a split real/imaginary pair into a dB scale, clamping the magnitude
 * to a floor before the logarithm so that zeros and near-zeros stay finite.
 */
#ifndef VEC_DB_MAG_H
#define VEC_DB_MAG_H

#ifdef __cplusplus
extern "C" {
#endif

/* out[i] = 20*log10(max(|x[i]|, floor_mag)) + offset, where
 * |x[i]| = sqrt(re[i]^2 + im[i]^2).
 *
 * floor_mag must be > 0.  Returns 0 on success, -1 for NULL pointers, n < 1
 * or floor_mag <= 0. */
int vec_db_mag(const float *re, const float *im, int n,
               float floor_mag, float offset, float *out);

#ifdef __cplusplus
}
#endif

#endif /* VEC_DB_MAG_H */