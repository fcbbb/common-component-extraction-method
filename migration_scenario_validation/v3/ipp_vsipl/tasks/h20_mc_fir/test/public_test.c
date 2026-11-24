#include "mc_fir.h"
#include <stdio.h>
int main(void){float x0[4]={1,0,0,0},x1[4]={1,1,1,1},t[2]={1,1},y0[3],y1[3],p,e;if(mc_fir(x0,x1,t,4,2,y0,y1,&p,&e)!=0)return 1;if(!(p>=0)||!(e>=0))return 2;puts("public_test: PASS");return 0;}
