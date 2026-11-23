/*
  Copyright (C) 2003-2013 Paul Brossier <piem@aubio.org>

  This file is part of aubio (trimmed for this task package).

  aubio is free software: you can redistribute it and/or modify it under the
  terms of the GNU General Public License as published by the Free Software
  Foundation, either version 3 of the License, or (at your option) any later
  version.

  This header keeps the public surface of aubio 0.4.9's src/spectral/fft.h.
*/

#ifndef AUBIO_FFT_H
#define AUBIO_FFT_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>

typedef uint32_t uint_t;
typedef float smpl_t;

/** real-valued buffer */
typedef struct {
  uint_t length;  /**< length of buffer */
  smpl_t *data;   /**< data vector of length ::fvec_t.length */
} fvec_t;

/** spectral buffer: length = (fft size)/2 + 1 */
typedef struct {
  uint_t length;  /**< length of buffer = (requested length)/2 + 1 */
  smpl_t *norm;   /**< norm array of size ::cvec_t.length */
  smpl_t *phas;   /**< phase array of size ::cvec_t.length */
} cvec_t;

/** FFT object */
typedef struct _aubio_fft_t aubio_fft_t;

/** create new FFT computation object
 *
 *  \param size length of the FFT; must be a power of two greater than 4
 */
aubio_fft_t *new_aubio_fft(uint_t size);

/** delete FFT object */
void del_aubio_fft(aubio_fft_t *s);

/** compute forward FFT
 *
 *  \param s fft object
 *  \param input input signal
 *  \param spectrum output spectrum (norm and phase)
 */
void aubio_fft_do(aubio_fft_t *s, const fvec_t *input, cvec_t *spectrum);

/** compute backward (inverse) FFT
 *
 *  \param s fft object
 *  \param spectrum input spectrum (norm and phase)
 *  \param output output signal
 */
void aubio_fft_rdo(aubio_fft_t *s, const cvec_t *spectrum, fvec_t *output);

/** compute forward FFT, real/imaginary output
 *
 *  The complex spectrum is packed as
 *  [ r0, r1, ..., rN/2, iN/2-1, ..., i2, i1 ].
 */
void aubio_fft_do_complex(aubio_fft_t *s, const fvec_t *input, fvec_t *compspec);

/** compute backward (inverse) FFT from real/imaginary input */
void aubio_fft_rdo_complex(aubio_fft_t *s, const fvec_t *compspec, fvec_t *output);

/** convert real/imaginary spectrum to norm/phase spectrum */
void aubio_fft_get_spectrum(const fvec_t *compspec, cvec_t *spectrum);

/** convert norm/phase spectrum to real/imaginary spectrum */
void aubio_fft_get_realimag(const cvec_t *spectrum, fvec_t *compspec);

/** compute phase spectrum from real/imaginary parts */
void aubio_fft_get_phas(const fvec_t *compspec, cvec_t *spectrum);

/** compute norm spectrum from real/imaginary parts */
void aubio_fft_get_norm(const fvec_t *compspec, cvec_t *spectrum);

/** compute imaginary part from the norm/phase cvec */
void aubio_fft_get_imag(const cvec_t *spectrum, fvec_t *compspec);

/** compute real part from the norm/phase cvec */
void aubio_fft_get_real(const cvec_t *spectrum, fvec_t *compspec);

#ifdef __cplusplus
}
#endif

#endif /* AUBIO_FFT_H */