#ifndef IQ_METRICS_H
#define IQ_METRICS_H
#ifdef __cplusplus
extern "C" {
#endif
int iq_metrics(const float *i, const float *q, int n,
               float *gain, float *phase, float *peak, float *energy);
#ifdef __cplusplus
}
#endif
#endif
