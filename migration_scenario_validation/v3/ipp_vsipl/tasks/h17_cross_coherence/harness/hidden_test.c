#include "cross_coherence.h"
#include <math.h>
#include <stdio.h>
int main(void){float a[16],b[16],m[9],p[9],pk,c;int i,k,bin,checks=0,fail=0;
 for(i=0;i<16;++i){a[i]=(float)(sin(.3*i)+.1);b[i]=(float)(cos(.2*i)+.2);}
 if(cross_coherence(a,b,16,m,p,&pk,&bin,&c)!=0){printf("FAIL run\n");return 1;}
 for(k=0;k<9;++k){double ar=0,ai=0,br=0,bi=0;for(i=0;i<16;++i){double w=-2*3.14159265358979323846*k*i/16;ar+=a[i]*cos(w);ai+=a[i]*sin(w);br+=b[i]*cos(w);bi+=b[i]*sin(w);}
  {double cr=ar*br+ai*bi,ci=ai*br-ar*bi;double wm=sqrt(cr*cr+ci*ci),wp=atan2(ci,cr);++checks;if(fabs(m[k]-wm)>3e-3||fabs(p[k]-wp)>3e-3)++fail;}}
 ++checks;if(pk<0||bin<0||bin>8)++fail;
 ++checks;if(cross_coherence(NULL,b,16,m,p,&pk,&bin,&c)!=-1)++fail;
 printf("SUMMARY checks=%d failures=%d\n",checks,fail);return fail?1:0;}
