/* Time-domain FIR filter bank (HPEC TDFIR kernel, reduced).
 *
 * A bank of `nfilters` FIR filters, each with `ntaps` coefficients, is applied
 * to a continuous input stream. Output is interleaved by filter:
 *
 *     out[m * n + i] = filter_m applied to in[i]
 *
 * The bank is block based: every tdfir_process() call consumes exactly `block`
 * samples. Consecutive calls continue the same stream, so filter state must be
 * preserved between calls.
 */
#ifndef TDFIR_H
#define TDFIR_H

#ifdef __cplusplus
extern "C" {
#endif

typedef struct tdfir_bank tdfir_bank;

/* Create a bank of `nfilters` FIR filters, each with `ntaps` coefficients.
 * `taps` holds nfilters*ntaps coefficients, filter-major.
 * `block` is the largest n a single tdfir_process() call may use.
 * Returns NULL on invalid arguments or allocation failure. */
tdfir_bank *tdfir_create(const float *taps, int ntaps, int nfilters, int block);

void tdfir_destroy(tdfir_bank *b);

/* Filter exactly `block` samples and write nfilters*block outputs.
 * Returns 0 on success, -1 on invalid arguments. */
int tdfir_process(tdfir_bank *b, const float *in, float *out, int n);

#ifdef __cplusplus
}
#endif

#endif /* TDFIR_H */