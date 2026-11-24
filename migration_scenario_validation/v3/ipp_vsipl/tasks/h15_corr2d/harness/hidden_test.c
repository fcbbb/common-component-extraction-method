#include "corr2d.h"
#include <math.h>
#include <stdio.h>
int main(void){int R=3,C=4,i,j,kr,kc,checks=0,fail=0;float xr[12],xi[12],hr[12],hi[12],or_[35],oi[35];
 for(i=0;i<12;++i){xr[i]=(float)(sin(.3*i)+.2);xi[i]=(float)(cos(.4*i));hr[i]=(float)(sin(.2*i+.1));hi[i]=(float)(cos(.25*i));}
 if(corr2d(xr,xi,R,C,hr,hi,or_,oi)!=0){printf("FAIL run\n");return 1;}
 for(kr=-(R-1);kr<=R-1;++kr)for(kc=-(C-1);kc<=C-1;++kc){double sr=0,si=0;int orow=kr+R-1,ocol=kc+C-1;
  for(i=0;i<R;++i)for(j=0;j<C;++j){int qr=i-kr,qc=j-kc;if(qr<0||qr>=R||qc<0||qc>=C)continue;
   sr+=xr[i*C+j]*hr[qr*C+qc]+xi[i*C+j]*hi[qr*C+qc];
   si+=xi[i*C+j]*hr[qr*C+qc]-xr[i*C+j]*hi[qr*C+qc];}
  ++checks;if(fabs(or_[orow*(2*C-1)+ocol]-sr)>3e-3||fabs(oi[orow*(2*C-1)+ocol]-si)>3e-3){printf("FAIL kr=%d kc=%d\n",kr,kc);++fail;}}
 ++checks;if(corr2d(NULL,xr,R,C,hr,hi,or_,oi)!=-1)++fail;
 printf("SUMMARY checks=%d failures=%d\n",checks,fail);return fail?1:0;}
