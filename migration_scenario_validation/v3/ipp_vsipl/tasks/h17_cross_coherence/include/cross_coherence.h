#ifndef CROSS_COHERENCE_H
#define CROSS_COHERENCE_H
#ifdef __cplusplus
extern "C" {
#endif
int cross_coherence(const float *a, const float *b, int nfft,
                    float *mag, float *phase, float *peak, int *bin,
                    float *coherence);
#ifdef __cplusplus
}
#endif
#endif
