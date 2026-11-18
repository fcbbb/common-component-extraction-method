/* Frequency-domain FIR filter (overlap-save).
 *
 * The filter is designed once from a tap vector and then applied to buffers of
 * any length; the transform length is fixed at creation time.
 */
#ifndef FDFIR_H
#define FDFIR_H

typedef struct fdfir fdfir;

/*
 * fdfir_create
 *     taps/ntaps   filter kernel, ntaps >= 1
 *     nfft         transform length: a power of two with nfft >= ntaps.
 *                  The overlap-save block is nfft - ntaps + 1 samples.
 *     Returns NULL on invalid arguments (NULL taps, ntaps < 1, nfft not a
 *     power of two, nfft < ntaps).
 *
 * fdfir_apply
 *     y[i] = sum(j = 0..ntaps-1) taps[j] * x[i-j],  i = 0 .. nx-1,
 *     with x[k] = 0 for k < 0.  This is the causal (streaming) convention, not
 *     the "same" slice of the full convolution.  x and y must not overlap.
 *     Buffers of any length are accepted, including nx < block.
 *     Returns 0 on success, -1 on invalid arguments (NULL handle/buffers,
 *     nx < 1).
 *
 * fdfir_destroy
 *     Releases the handle; NULL is ignored.
 */
fdfir *fdfir_create(const float *taps, int ntaps, int nfft);
int fdfir_apply(fdfir *f, const float *x, int nx, float *y);
void fdfir_destroy(fdfir *f);

#endif /* FDFIR_H */