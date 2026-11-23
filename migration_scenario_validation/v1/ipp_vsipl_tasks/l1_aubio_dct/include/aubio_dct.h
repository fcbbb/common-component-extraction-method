/* Discrete Cosine Transform, orthonormal DCT-II / DCT-III.
 *
 * API and semantics follow aubio 0.4.9 (src/spectral/dct.h, GPL-2.0+),
 * trimmed to the pieces this package needs: aubio's fvec_t types and the four
 * entry points.  Equivalent to MATLAB/Octave dct()/idct() and to
 * scipy.fftpack.dct(x, norm='ortho')/idct(x, norm='ortho'):
 *
 *     X[k] = c_k * sum(n=0..N-1) x[n] cos(pi*k*(2n+1)/(2N))
 *     x[n] = sum(k=0..N-1) c_k * X[k] cos(pi*k*(2n+1)/(2N))
 *     c_0 = sqrt(1/N), c_k = sqrt(2/N) for k > 0
 *
 * Both fvecs handed to the transform calls must hold at least `size` samples;
 * the length fields are not consulted, exactly as in aubio.
 */
#ifndef AUBIO_DCT_H
#define AUBIO_DCT_H

#ifdef __cplusplus
extern "C" {
#endif

typedef float smpl_t;

typedef struct {
    unsigned int length;
    smpl_t *data;
} fvec_t;

typedef struct _aubio_dct_t aubio_dct_t;

/* Returns NULL when size < 1 (or on allocation failure). */
aubio_dct_t *new_aubio_dct(unsigned int size);

void aubio_dct_do(aubio_dct_t *s, const fvec_t *input, fvec_t *dct_output);
void aubio_dct_rdo(aubio_dct_t *s, const fvec_t *input, fvec_t *idct_output);

/* NULL is ignored. */
void del_aubio_dct(aubio_dct_t *s);

#ifdef __cplusplus
}
#endif

#endif /* AUBIO_DCT_H */