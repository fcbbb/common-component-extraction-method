#include "norm_corr.h"
#include <math.h>
#include <stdio.h>
int main(void){int n=16,lm=-4,lx=4;float x[16],r[16],o[9],p;int i,k,pl,checks=0,fail=0;
 for(i=0;i<n;++i){x[i]=(float)(sin(.3*i)+.2*cos(.7*i));r[i]=(float)(cos(.2*i)+.1*sin(.5*i));}
 if(norm_corr(x,r,n,lm,lx,o,&p,&pl)!=0){printf("FAIL run\n");return 1;}
 for(k=lm;k<=lx;++k){double dot=0,ex=0,er=0,want;int j0=k<0?-k:0,j1=k>0?n-k:n;
  for(i=0;i<n;++i){ex+=x[i]*x[i];er+=r[i]*r[i];}
  for(i=j0;i<j1;++i)dot+=x[i]*r[i+k];want=dot/sqrt(ex*er);
  ++checks;if(fabs(o[k-lm]-want)>3e-4){printf("FAIL lag=%d got=%g want=%g\n",k,o[k-lm],want);++fail;}
 }
 ++checks;if(p<0||pl<lm||pl>lx)++fail;
 ++checks;if(norm_corr(NULL,r,n,lm,lx,o,&p,&pl)!=-1)++fail;
 printf("SUMMARY checks=%d failures=%d\n",checks,fail);return fail?1:0;}
