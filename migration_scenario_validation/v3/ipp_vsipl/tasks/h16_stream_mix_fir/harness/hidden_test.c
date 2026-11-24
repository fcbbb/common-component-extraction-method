#include "stream_mix_fir.h"
#include <math.h>
#include <stdio.h>
int main(void){float xr[10],xi[10],nr[3]={1,.5f,-.5f},ni[3]={0,.2f,.3f},t[1]={1},or_[10],oi[10],p,e;int ph=0,n,i,checks=0,fail=0;
 for(i=0;i<10;++i){xr[i]=(float)(sin(.3*i)+.2);xi[i]=(float)(cos(.2*i));}
 if(stream_mix_fir(xr,xi,10,nr,ni,3,&ph,t,1,2,or_,oi,10,&n,&p,&e)!=0){printf("FAIL run\n");return 1;}
 ++checks;if(n!=5||ph!=1)++fail;
 {float pr=0,pi=0;for(i=0;i<10;++i){int q=i%3;float rr=xr[i]*nr[q]-xi[i]*ni[q],ii=xr[i]*ni[q]+xi[i]*nr[q];if((i+1)%2==0){int j=(i+1)/2-1;if(fabs(or_[j]-rr)>3e-4||fabs(oi[j]-ii)>3e-4)++fail;}}
  (void)pr;(void)pi;}
 ++checks;if(stream_mix_fir(NULL,xi,10,nr,ni,3,&ph,t,1,2,or_,oi,10,&n,&p,&e)!=-1)++fail;
 printf("SUMMARY checks=%d failures=%d\n",checks,fail);return fail?1:0;}
