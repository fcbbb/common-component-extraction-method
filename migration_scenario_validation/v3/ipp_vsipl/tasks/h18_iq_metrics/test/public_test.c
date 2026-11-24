#include "iq_metrics.h"
#include <stdio.h>
int main(void){float i[4]={1,1,1,1},q[4]={1,1,1,1},g,p,pk,e;if(iq_metrics(i,q,4,&g,&p,&pk,&e)!=0)return 1;if(!(g>=0)||!(pk>=0))return 2;puts("public_test: PASS");return 0;}
