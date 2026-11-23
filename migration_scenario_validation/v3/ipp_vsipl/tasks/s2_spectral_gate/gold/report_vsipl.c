/* Report aggregation for the spectral gate (generic backend code). */
#include "spectral_gate_internal.h"

void sg_fill_report(const float *mag, const unsigned char *flags, int n,
                    sg_report *rep)
{
    float peak = -1.0f;
    float floor_sum = 0.0f;
    int peak_bin = 0;
    int detections = 0;
    int i;

    if (!rep || !mag || !flags || n <= 0) return;
    for (i = 0; i < n; ++i) {
        floor_sum += mag[i];
        if (mag[i] > peak) {
            peak = mag[i];
            peak_bin = i;
        }
        detections += flags[i] ? 1 : 0;
    }
    rep->peak = (peak < 0.0f) ? 0.0f : peak;
    rep->peak_bin = peak_bin;
    rep->detections = detections;
    rep->noise_floor = floor_sum / (float)n;
}