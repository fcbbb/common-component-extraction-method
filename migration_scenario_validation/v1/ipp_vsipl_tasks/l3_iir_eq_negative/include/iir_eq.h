/* Cascaded biquad equaliser (32-bit float, streaming).
 *
 * `sos` holds `nsections` second-order sections, 5 coefficients each:
 *
 *     {b0, b1, b2, a1, a2}
 *
 * with a0 = 1, i.e. each section computes
 *
 *     y[n] = b0*x[n] + b1*x[n-1] + b2*x[n-2] - a1*y[n-1] - a2*y[n-2]
 *
 * Sections are applied in order.  Processing is block based: each call
 * consumes exactly `block` samples and continues the previous stream, so the
 * filter state persists between calls.
 */
#ifndef IIR_EQ_H
#define IIR_EQ_H

#ifdef __cplusplus
extern "C" {
#endif

typedef struct iir_eq iir_eq;

/* nsections >= 1, block >= 1, sos not NULL. Returns NULL on invalid input. */
iir_eq *iir_eq_create(const float *sos, int nsections, int block);

void iir_eq_destroy(iir_eq *eq);

/* Filter exactly `block` samples into out[0..n-1]. Returns 0, or -1 on
 * invalid arguments. */
int iir_eq_process(iir_eq *eq, const float *in, float *out, int n);

#ifdef __cplusplus
}
#endif

#endif /* IIR_EQ_H */