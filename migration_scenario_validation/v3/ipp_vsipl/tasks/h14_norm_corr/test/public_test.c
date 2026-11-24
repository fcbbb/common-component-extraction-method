#include "norm_corr.h"
#include <stdio.h>
int main(void){float x[8]={1,2,3,4,5,6,7,8},r[8]={0,0,0,1,0,0,0,0},o[5],p;int l;
 if(norm_corr(x,r,8,-2,2,o,&p,&l)!=0)return 1;if(!(p>=0)||l<-2||l>2)return 2;puts("public_test: PASS");return 0;}
