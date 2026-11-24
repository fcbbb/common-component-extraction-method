#include "stream_mix_fir.h"
#include <stdio.h>
int main(void){float xr[8]={1,2,3,4,5,6,7,8},xi[8]={0},nr[2]={1,1},ni[2]={0},t[1]={1},or_[8],oi[8],p,e;int ph=0,n;
 if(stream_mix_fir(xr,xi,8,nr,ni,2,&ph,t,1,2,or_,oi,8,&n,&p,&e)!=0)return 1;if(n!=4||ph!=0)return 2;puts("public_test: PASS");return 0;}
