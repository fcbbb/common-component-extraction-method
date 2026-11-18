/* Public API: apply a symmetric analysis window to a signal.
 *
 * All four windows are the classic symmetric definitions over n samples, with
 * the phase 2*pi*i/(n-1):
 *
 *   HANN      w[i] = 0.5 - 0.5*cos(t)
 *   HAMMING   w[i] = 0.54 - 0.46*cos(t)
 *   BLACKMAN  w[i] = (0.5 + a/2) - 0.5*cos(t) - (a/2)*cos(2t),  a = param
 *   KAISER    w[i] = I0(b*sqrt(1-(2i/(n-1)-1)^2)) / I0(b),      b = param*(n-1)/2
 *
 * The Kaiser parameter is given in samples (beta = param*(n-1)/2), which is
 * IPP's convention, not the raw beta used by most textbook formulas.
 *
 * n must be >= 3 for HANN, HAMMING and BLACKMAN; KAISER also accepts n == 1
 * (window value 1) and n == 2.  param is ignored by HANN and HAMMING, is the
 * Blackman cosine coefficient for BLACKMAN and must satisfy
 * param*(n-1)/2 <= 38 for KAISER (larger values are rejected: the Bessel
 * argument would overflow single precision -- IPP reports these as
 * ippStsHugeWinErr, "Kaiser window is too big").
 */
#ifndef WIN_GEN_H
#define WIN_GEN_H

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    WIN_HANN = 0,
    WIN_HAMMING = 1,
    WIN_BLACKMAN = 2,
    WIN_KAISER = 3
} win_type;

/* out[i] = in[i] * w[i].  Returns 0 on success, -1 on invalid arguments
 * (NULL pointers, n out of range for the chosen window, negative Kaiser
 * parameter or an unknown window type). */
int win_apply(win_type type, float param, const float *in, float *out, int n);

#ifdef __cplusplus
}
#endif

#endif /* WIN_GEN_H */