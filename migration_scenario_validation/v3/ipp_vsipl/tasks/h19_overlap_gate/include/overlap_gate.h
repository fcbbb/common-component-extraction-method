#ifndef OVERLAP_GATE_H
#define OVERLAP_GATE_H
#ifdef __cplusplus
extern "C" {
#endif
int overlap_gate(const float *input, int nfft, float alpha,
                 float *mag, unsigned char *flags, float *peak,
                 int *peak_bin, float *noise);
#ifdef __cplusplus
}
#endif
#endif
