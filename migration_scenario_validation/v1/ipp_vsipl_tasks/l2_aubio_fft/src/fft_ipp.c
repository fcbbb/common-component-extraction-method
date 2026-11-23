/*
  Copyright (C) 2003-2013 Paul Brossier <piem@aubio.org>

  This file is part of aubio.

  aubio is free software: you can redistribute it and/or modify it under the
  terms of the GNU General Public License as published by the Free Software
  Foundation, either version 3 of the License, or (at your option) any later
  version.

  Intel IPP backend, extracted from aubio 0.4.9 src/spectral/fft.c.
*/

#include "aubio_fft.h"

#include <ipp.h>

#include <math.h>
#include <stdlib.h>
#include <string.h>

#define PI 3.14159265358979323846

struct _aubio_fft_t {
  uint_t winsize;
  uint_t fft_size;
  smpl_t *in;
  smpl_t *out;
  Ipp8u *memSpec;
  Ipp8u *memInit;
  Ipp8u *memBuffer;
  IppsFFTSpec_R_32f *fftSpec;
  Ipp32fc *complexOut;
  fvec_t *compspec;
};

static fvec_t *new_fvec_internal(uint_t length)
{
  fvec_t *s = (fvec_t *)calloc(1, sizeof(fvec_t));
  if (!s) return NULL;
  s->length = length;
  s->data = (smpl_t *)calloc(length, sizeof(smpl_t));
  if (!s->data) { free(s); return NULL; }
  return s;
}

static void del_fvec_internal(fvec_t *s)
{
  if (!s) return;
  free(s->data);
  free(s);
}

static int aubio_is_power_of_two(uint_t a)
{
  return (a > 0 && (a & (a - 1)) == 0);
}

static int aubio_power_of_two_order(uint_t a)
{
  int order = 0;
  while ((uint_t)(1u << order) < a) order++;
  return order;
}

aubio_fft_t *new_aubio_fft(uint_t winsize)
{
  const IppHintAlgorithm qualityHint = ippAlgHintAccurate;
  const int flags = IPP_FFT_NODIV_BY_ANY; /* we're scaling manually afterwards */
  int order = aubio_power_of_two_order(winsize);
  int sizeSpec, sizeInit, sizeBuffer;
  IppStatus status;
  aubio_fft_t *s;

  if ((int)winsize < 2) {
    return NULL;
  }
  if (winsize <= 4 || aubio_is_power_of_two(winsize) != 1) {
    return NULL;
  }

  s = (aubio_fft_t *)calloc(1, sizeof(aubio_fft_t));
  if (!s) return NULL;

  status = ippsFFTGetSize_R_32f(order, flags, qualityHint,
      &sizeSpec, &sizeInit, &sizeBuffer);
  if (status != ippStsNoErr) goto beach;

  s->fft_size = s->winsize = winsize;
  s->compspec = new_fvec_internal(winsize);
  s->in = (smpl_t *)calloc(winsize, sizeof(smpl_t));
  s->out = (smpl_t *)calloc(winsize, sizeof(smpl_t));
  if (!s->compspec || !s->in || !s->out) goto beach;

  s->memSpec = ippsMalloc_8u(sizeSpec);
  /* IPP reports a zero-sized work buffer for the smallest orders; passing a
     NULL buffer pointer is the documented way to say "none needed". */
  if (sizeBuffer > 0) {
    s->memBuffer = ippsMalloc_8u(sizeBuffer);
  }
  if (sizeInit > 0) {
    s->memInit = ippsMalloc_8u(sizeInit);
  }
  s->complexOut = ippsMalloc_32fc(s->fft_size / 2 + 1);
  if (!s->memSpec || (sizeBuffer > 0 && !s->memBuffer) || !s->complexOut)
    goto beach;

  status = ippsFFTInit_R_32f(&s->fftSpec, order, flags, qualityHint,
      s->memSpec, s->memInit);
  if (status != ippStsNoErr) goto beach;

  return s;

beach:
  del_aubio_fft(s);
  return NULL;
}

void del_aubio_fft(aubio_fft_t *s)
{
  if (!s) return;
  ippsFree(s->memSpec);
  ippsFree(s->memInit);
  ippsFree(s->memBuffer);
  ippsFree(s->complexOut);
  del_fvec_internal(s->compspec);
  free(s->in);
  free(s->out);
  free(s);
}

void aubio_fft_do(aubio_fft_t *s, const fvec_t *input, cvec_t *spectrum)
{
  aubio_fft_do_complex(s, input, s->compspec);
  aubio_fft_get_spectrum(s->compspec, spectrum);
}

void aubio_fft_rdo(aubio_fft_t *s, const cvec_t *spectrum, fvec_t *output)
{
  aubio_fft_get_realimag(spectrum, s->compspec);
  aubio_fft_rdo_complex(s, s->compspec, output);
}

void aubio_fft_do_complex(aubio_fft_t *s, const fvec_t *input, fvec_t *compspec)
{
  uint_t i;

  for (i = 0; i < s->winsize; i++) {
    s->in[i] = input->data[i];
  }

  ippsFFTFwd_RToCCS_32f(s->in, (Ipp32f *)s->complexOut, s->fftSpec,
      s->memBuffer);

  /* convert complex buffer to [ r0, r1, ..., rN, iN-1, .., i2, i1] */
  compspec->data[0] = s->complexOut[0].re;
  compspec->data[s->fft_size / 2] = s->complexOut[s->fft_size / 2].re;
  for (i = 1; i < s->fft_size / 2; i++) {
    compspec->data[i] = s->complexOut[i].re;
    compspec->data[s->fft_size - i] = s->complexOut[i].im;
  }
}

void aubio_fft_rdo_complex(aubio_fft_t *s, const fvec_t *compspec, fvec_t *output)
{
  uint_t i;

  /* convert from real imag [ r0, 0, ..., rN, iN-1, .., i2, i1, iN-1]
   * to complex format */
  s->complexOut[0].re = compspec->data[0];
  s->complexOut[0].im = 0;
  s->complexOut[s->fft_size / 2].re = compspec->data[s->fft_size / 2];
  s->complexOut[s->fft_size / 2].im = 0.0;
  for (i = 1; i < s->fft_size / 2; i++) {
    s->complexOut[i].re = compspec->data[i];
    s->complexOut[i].im = compspec->data[s->fft_size - i];
  }

  ippsFFTInv_CCSToR_32f((const Ipp32f *)s->complexOut, output->data,
      s->fftSpec, s->memBuffer);

  ippsMulC_32f(output->data, 1.0 / s->winsize, output->data, s->fft_size);
}

void aubio_fft_get_spectrum(const fvec_t *compspec, cvec_t *spectrum)
{
  aubio_fft_get_phas(compspec, spectrum);
  aubio_fft_get_norm(compspec, spectrum);
}

void aubio_fft_get_realimag(const cvec_t *spectrum, fvec_t *compspec)
{
  aubio_fft_get_imag(spectrum, compspec);
  aubio_fft_get_real(spectrum, compspec);
}

void aubio_fft_get_phas(const fvec_t *compspec, cvec_t *spectrum)
{
  uint_t i;

  if (compspec->data[0] < 0) {
    spectrum->phas[0] = PI;
  } else {
    spectrum->phas[0] = 0.;
  }

  /* convert from real imag  [ r0, r1, ..., rN, iN-1, ..., i2, i1, i0]
   *                     to  [ r0, r1, ..., rN, i0, i1, i2, ..., iN-1] */
  for (i = 1; i < spectrum->length / 2; i++) {
    smpl_t tmp = compspec->data[compspec->length - i];
    compspec->data[compspec->length - i] = compspec->data[spectrum->length + i - 1];
    compspec->data[spectrum->length + i - 1] = tmp;
  }

  ippsAtan2_32f_A21(compspec->data + spectrum->length,
      compspec->data + 1, spectrum->phas + 1, spectrum->length - 1);

  /* revert the imaginary part back again */
  for (i = 1; i < spectrum->length / 2; i++) {
    smpl_t tmp = compspec->data[spectrum->length + i - 1];
    compspec->data[spectrum->length + i - 1] = compspec->data[compspec->length - i];
    compspec->data[compspec->length - i] = tmp;
  }

  if (compspec->data[compspec->length / 2] < 0) {
    spectrum->phas[spectrum->length - 1] = PI;
  } else {
    spectrum->phas[spectrum->length - 1] = 0.;
  }
}

void aubio_fft_get_norm(const fvec_t *compspec, cvec_t *spectrum)
{
  uint_t i = 0;

  spectrum->norm[0] = fabsf(compspec->data[0]);
  for (i = 1; i < spectrum->length - 1; i++) {
    spectrum->norm[i] = sqrtf(compspec->data[i] * compspec->data[i]
        + compspec->data[compspec->length - i]
        * compspec->data[compspec->length - i]);
  }
  spectrum->norm[spectrum->length - 1] =
      fabsf(compspec->data[compspec->length / 2]);
}

void aubio_fft_get_imag(const cvec_t *spectrum, fvec_t *compspec)
{
  uint_t i;
  for (i = 1; i < (compspec->length + 1) / 2; i++) {
    compspec->data[compspec->length - i] =
        spectrum->norm[i] * sinf(spectrum->phas[i]);
  }
}

void aubio_fft_get_real(const cvec_t *spectrum, fvec_t *compspec)
{
  uint_t i;
  for (i = 0; i < compspec->length / 2 + 1; i++) {
    compspec->data[i] = spectrum->norm[i] * cosf(spectrum->phas[i]);
  }
}