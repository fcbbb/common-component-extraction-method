#include "corr2d.h"
#include <stdio.h>
int main(void){float xr[4]={1,2,3,4},xi[4]={0},hr[4]={0,0,0,1},hi[4]={0},or_[9],oi[9];
 if(corr2d(xr,xi,2,2,hr,hi,or_,oi)!=0)return 1;if(!(or_[8]>=0))return 2;puts("public_test: PASS");return 0;}
