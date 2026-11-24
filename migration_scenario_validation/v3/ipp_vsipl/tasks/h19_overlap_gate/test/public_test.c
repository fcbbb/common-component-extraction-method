#include "overlap_gate.h"
#include <stdio.h>
int main(void){float x[16],m[9],p,n;unsigned char f[9];int b,i;for(i=0;i<16;++i)x[i]=1.0f;if(overlap_gate(x,16,1.5f,m,f,&p,&b,&n)!=0)return 1;if(!(p>=0)||!(n>=0))return 2;puts("public_test: PASS");return 0;}
