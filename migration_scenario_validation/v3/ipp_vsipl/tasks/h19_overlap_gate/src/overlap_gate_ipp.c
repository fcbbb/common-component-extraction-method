#include "overlap_gate.h"
#include <ipp.h>
#include <math.h>
#include <stdlib.h>
int overlap_gate(const float *input, int nfft, float alpha,
                 float *mag, unsigned char *flags, float *peak,
                 int *peak_bin, float *noise)
{
    IppsFFTSpec_R_32f *spec = NULL; Ipp8u *mem=NULL,*init=NULL,*work=NULL; Ipp32f *packed=NULL,*frame=NULL;
    int order=0,ss=0,is=0,ws=0,nb,k,rc=-1,pb=0; float pk=-1,sum=0;
    if(!input||!mag||!flags||nfft<8||(nfft&(nfft-1))||!(alpha>0))return -1;
    nb=nfft/2+1; while((1<<order)<nfft)++order;
    if(ippsFFTGetSize_R_32f(order,IPP_FFT_NODIV_BY_ANY,ippAlgHintNone,&ss,&is,&ws)!=ippStsNoErr)goto done;
    mem=ippsMalloc_8u(ss);init=ippsMalloc_8u(is?is:1);work=ippsMalloc_8u(ws?ws:1);
    packed=ippsMalloc_32f(nfft+2);frame=ippsMalloc_32f(nfft);
    if(!mem||!init||!work||!packed||!frame)goto done;
    if(ippsFFTInit_R_32f(&spec,order,IPP_FFT_NODIV_BY_ANY,ippAlgHintNone,mem,init)!=ippStsNoErr)goto done;
    for(k=0;k<nfft;++k){double w=.5*(1-cos(2*3.14159265358979323846*k/(nfft-1)));frame[k]=input[k]*(float)w;}
    if(ippsFFTFwd_RToCCS_32f(frame,packed,spec,work)!=ippStsNoErr)goto done;
    for(k=0;k<nb;++k){float re=packed[k],im=(k==0||k==nfft/2)?0:packed[nfft-k];mag[k]=sqrtf(re*re+im*im);sum+=mag[k];if(mag[k]>pk){pk=mag[k];pb=k;}}
    for(k=0;k<nb;++k)flags[k]=mag[k]>alpha*(sum/nb)?1:0;
    if(peak)*peak=pk;if(peak_bin)*peak_bin=pb;if(noise)*noise=sum/nb;rc=0;
done: ippsFree(mem);ippsFree(init);ippsFree(work);ippsFree(packed);ippsFree(frame);return rc;
}
