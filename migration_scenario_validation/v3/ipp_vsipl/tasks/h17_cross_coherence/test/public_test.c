#include "cross_coherence.h"
#include <stdio.h>
int main(void){float a[8]={1,0,0,0,0,0,0,0},b[8]={1,0,0,0,0,0,0,0},m[5],p[5],pk,c;int bin,i;
 if(cross_coherence(a,b,8,m,p,&pk,&bin,&c)!=0)return 1;for(i=0;i<5;++i)if(m[i]<0)return 2;puts("public_test: PASS");return 0;}
