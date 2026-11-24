#include "iq_metrics.h"
#include <math.h>
#include <stdio.h>
int main(void){int n=16,k,checks=0,fail=0;float i[16],q[16],g,p,pk,e;double ai=0,aq=0,cr=0,en=0,pk2=0;
 for(k=0;k<n;++k){i[k]=(float)(sin(.3*k)+.2);q[k]=(float)(.8*cos(.2*k));ai+=i[k]*i[k];aq+=q[k]*q[k];cr+=i[k]*q[k];en+=i[k]*i[k]+q[k]*q[k];if(sqrt(i[k]*i[k]+q[k]*q[k])>pk2)pk2=sqrt(i[k]*i[k]+q[k]*q[k]);}
 if(iq_metrics(i,q,n,&g,&p,&pk,&e)!=0){printf("FAIL run\n");return 1;}
 ++checks;if(fabs(g-sqrt(aq/ai))>3e-3)++fail;
 ++checks;if(fabs(p-asin(cr/sqrt(ai*aq)))>3e-3)++fail;
 ++checks;if(fabs(pk-pk2)>3e-3||fabs(e-en)>3e-3*(en>1?en:1))++fail;
 ++checks;if(iq_metrics(NULL,q,n,&g,&p,&pk,&e)!=-1)++fail;
 printf("SUMMARY checks=%d failures=%d\n",checks,fail);return fail?1:0;}
