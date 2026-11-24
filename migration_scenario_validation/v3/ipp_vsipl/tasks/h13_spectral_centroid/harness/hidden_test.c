#include "spectral_centroid.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#ifndef HC_PI
#define HC_PI 3.14159265358979323846
#endif
int main(void) {
    const int sizes[]={8,16,32,64}; int s, checks=0, failures=0;
    for (s=0;s<4;++s) {
        int n=sizes[s], nb=n/2+1, i,k; float *x=malloc((size_t)n*sizeof(float));
        float c,p,t; int b; double sum=0, w=0, wantc, wp=-1; int wb=0;
        for(i=0;i<n;++i) x[i]=(float)(sin(.31*i+.2)+.25*cos(.17*i));
        for(k=0;k<nb;++k){
            double re=0,im=0;
            for(i=0;i<n;++i){
                double win=.5*(1-cos(2*HC_PI*i/(n-1)));
                double a=-2*HC_PI*k*i/n;
                re+=x[i]*win*cos(a); im+=x[i]*win*sin(a);
            }
            { double m=sqrt(re*re+im*im); sum+=m; w+=k*m; if(m>wp){wp=m;wb=k;} }
        }
        wantc=sum>0?w/sum:0;
        ++checks;
        if(spectral_centroid(x,n,&c,&p,&b,&t)!=0){printf("FAIL proc n=%d\n",n);++failures;free(x);continue;}
        ++checks;
        if(fabs(c-wantc)>3e-3*(wantc>1?wantc:1)){printf("FAIL centroid n=%d got=%g want=%g\n",n,c,wantc);++failures;}
        ++checks;
        if(b!=wb || fabs(p-wp)>3e-3*(wp>1?wp:1)){printf("FAIL peak n=%d b=%d/%d p=%g/%g\n",n,b,wb,p,wp);++failures;}
        ++checks;
        if(fabs(t-sum)>3e-3*(sum>1?sum:1)){printf("FAIL total n=%d\n",n);++failures;}
        free(x);
    }
    ++checks; if(spectral_centroid(NULL,8,NULL,NULL,NULL,NULL)!=-1) ++failures;
    ++checks; if(spectral_centroid((const float*)&s,12,(float*)&s,NULL,NULL,NULL)!=-1) ++failures;
    printf("SUMMARY checks=%d failures=%d\n",checks,failures);
    return failures?1:0;
}
