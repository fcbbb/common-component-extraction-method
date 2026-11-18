/* Discrete Cosine Transform, Intel IPP backend (migration source).
 *
 * Adapted from aubio 0.4.9 src/spectral/dct_ipp.c (32-bit path only).  IPP's
 * DCT is already orthonormal, matching MATLAB's dct()/idct(), so the wrapper is
 * just the spec lifecycle: GetSize -> Malloc -> Init -> transform -> free.
 *
 * The size of the spec buffer returned by GetSize can legitimately be zero
 * (that is why the original keeps a NULL check around it); passing NULL in that
 * case is what IPP expects.
 */
#include "aubio_dct.h"

#include <ipp.h>

#include <stdlib.h>

struct _aubio_dct_t {
    unsigned int size;
    IppsDCTFwdSpec_32f *fwd;
    IppsDCTInvSpec_32f *inv;
    Ipp8u *fwd_spec;
    Ipp8u *inv_spec;
    Ipp8u *fwd_spec_buf;
    Ipp8u *inv_spec_buf;
    Ipp8u *fwd_work;
    Ipp8u *inv_work;
};

aubio_dct_t *new_aubio_dct(unsigned int size)
{
    const IppHintAlgorithm hint = ippAlgHintAccurate;
    aubio_dct_t *s;
    int spec_size = 0, spec_buf_size = 0, work_size = 0;

    if (size < 1) return NULL;

    s = (aubio_dct_t *)calloc(1, sizeof(*s));
    if (!s) return NULL;
    s->size = size;

    if (ippsDCTFwdGetSize_32f((int)size, hint, &spec_size, &spec_buf_size,
                              &work_size) != ippStsNoErr)
        goto fail;
    s->fwd_spec     = ippsMalloc_8u(spec_size);
    s->fwd_spec_buf = (spec_buf_size > 0) ? ippsMalloc_8u(spec_buf_size) : NULL;
    s->fwd_work     = ippsMalloc_8u(work_size > 0 ? work_size : 1);
    if (!s->fwd_spec || !s->fwd_work) goto fail;
    if (ippsDCTFwdInit_32f(&s->fwd, (int)size, hint, s->fwd_spec,
                           s->fwd_spec_buf) != ippStsNoErr)
        goto fail;

    if (ippsDCTInvGetSize_32f((int)size, hint, &spec_size, &spec_buf_size,
                              &work_size) != ippStsNoErr)
        goto fail;
    s->inv_spec     = ippsMalloc_8u(spec_size);
    s->inv_spec_buf = (spec_buf_size > 0) ? ippsMalloc_8u(spec_buf_size) : NULL;
    s->inv_work     = ippsMalloc_8u(work_size > 0 ? work_size : 1);
    if (!s->inv_spec || !s->inv_work) goto fail;
    if (ippsDCTInvInit_32f(&s->inv, (int)size, hint, s->inv_spec,
                           s->inv_spec_buf) != ippStsNoErr)
        goto fail;
    return s;

fail:
    del_aubio_dct(s);
    return NULL;
}

void aubio_dct_do(aubio_dct_t *s, const fvec_t *input, fvec_t *dct_output)
{
    if (!s || !input || !dct_output) return;
    (void)ippsDCTFwd_32f((const Ipp32f *)input->data, (Ipp32f *)dct_output->data,
                         s->fwd, s->fwd_work);
}

void aubio_dct_rdo(aubio_dct_t *s, const fvec_t *input, fvec_t *idct_output)
{
    if (!s || !input || !idct_output) return;
    (void)ippsDCTInv_32f((const Ipp32f *)input->data, (Ipp32f *)idct_output->data,
                         s->inv, s->inv_work);
}

void del_aubio_dct(aubio_dct_t *s)
{
    if (!s) return;
    ippsFree(s->fwd_spec);
    ippsFree(s->inv_spec);
    ippsFree(s->fwd_spec_buf);
    ippsFree(s->inv_spec_buf);
    ippsFree(s->fwd_work);
    ippsFree(s->inv_work);
    free(s);
}