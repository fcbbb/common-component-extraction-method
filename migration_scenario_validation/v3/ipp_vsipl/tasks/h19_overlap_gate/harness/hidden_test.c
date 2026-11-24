#include "overlap_gate.h"
#include <math.h>
#include <stdio.h>
int main(void){float x[16],m[9],p,n;unsigned char f[9];int i,k,b,checks=0,fail=0;double want[9],sum=0,pk=-1;for(i=0;i<16;++i)x[i]=(float)(sin(.3*i)+.2*cos(.2*i));
 for(k=0;k<9;++k){double re=0,im=0;for(i=0;i<16;++i){double w=.5*(1-cos(2*3.14159265358979323846*i/15));double a=-2*3.14159265358979323846*k*i/16;re+=x[i]*w*cos(a);im+=x[i]*w*sin(a);}want[k]=sqrt(re*re+im*im);sum+=want[k];if(want[k]>pk)pk=want[k];}
 if(overlap_gate(x,16,1.5f,m,f,&p,&b,&n)!=0){printf("FAIL run\n");return 1;}
 for(k=0;k<9;++k){++checks;if(fabs(m[k]-want[k])>3e-3)++fail;if(f[k]!=(m[k]>1.5f*(float)(sum/9)))++fail;}
 ++checks;if(fabs(p-pk)>3e-3||b<0||b>8)++fail; ++checks;if(overlap_gate(NULL,16,1.5f,m,f,&p,&b,&n)!=-1)++fail;
 printf("SUMMARY checks=%d failures=%d\n",checks,fail);return fail?1:0;}
