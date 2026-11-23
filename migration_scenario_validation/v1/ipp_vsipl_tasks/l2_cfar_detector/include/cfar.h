/* Cell-averaging CFAR detector (HPEC CFAR kernel, reduced).
 *
 * `mag2` holds n non-negative samples (magnitude squared) of one range or
 * Doppler line.  For every cell the noise level is the mean of the training
 * cells on both sides, excluding `nguard` guard cells next to the cell under
 * test.  A cell is flagged when
 *
 *     mag2[i] > alpha * noise[i],    alpha = N0 * (pfa^(-1/N0) - 1),
 *
 * with N0 = 2 * ntrain (the design number of training cells) and pfa the
 * requested probability of false alarm.  At the edges fewer training cells are
 * available and the mean is taken over whatever is valid; if no training cell
 * is valid the cell is never flagged.
 */
#ifndef CFAR_H
#define CFAR_H

#ifdef __cplusplus
extern "C" {
#endif

typedef struct cfar_state cfar_state;

/* nguard >= 0, ntrain >= 1, 0 < pfa < 1.  Returns NULL on invalid arguments. */
cfar_state *cfar_create(int nguard, int ntrain, float pfa);

void cfar_destroy(cfar_state *s);

/* Process n cells in place into flags[0..n-1] (each 0 or 1).
 * Returns the number of detections, or -1 on invalid arguments. */
int cfar_detect(cfar_state *s, const float *mag2, int n, unsigned char *flags);

#ifdef __cplusplus
}
#endif

#endif /* CFAR_H */