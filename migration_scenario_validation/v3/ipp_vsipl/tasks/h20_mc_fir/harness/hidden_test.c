#include "mc_fir.h"
#include <math.h>
#include <stdio.h>
int main(void){int n=12,nt=4,i,t,outn=n-nt+1,checks=0,fail=0;float x0[12],x1[12],h[4],y0[12],y1[12],p,e;double pk=-1,en=0;
 for(i=0;i<n;++i){x0[i]=(float)(sin(.3*i)+.2);x1[i]=(float)(cos(.2*i));}
 for(t=0;t<nt;++t)h[t]=(float)(cos(.4*t)+.1);
 if(mc_fir(x0,x1,h,n,nt,y0,y1,&p,&e)!=0){printf("FAIL run\n");return 1;}
 for(i=0;i<outn;++i){double a=0,b=0;for(t=0;t<nt;++t){a+=h[t]*x0[i+t];b+=h[t]*x1[i+t];}++checks;if(fabs(y0[i]-a)>3e-3||fabs(y1[i]-b)>3e-3)++fail;en+=a*a+b*b;if(sqrt(a*a+b*b)>pk)pk=sqrt(a*a+b*b);}
 ++checks;if(fabs(p-pk)>3e-3||fabs(e-en)>3e-3*(en>1?en:1))++fail;
 ++checks;if(mc_fir(NULL,x1,h,n,nt,y0,y1,&p,&e)!=-1)++fail;
 printf("SUMMARY checks=%d failures=%d\n",checks,fail);return fail?1:0;}
