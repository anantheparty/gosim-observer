#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>

// Incidence is stored once per start/field. Program and duration only reference
// the shared physical coefficient bank. No per-action edge arrays are formed.
extern "C" void price_shared(int n, int nf, int na, int nd,
 const int32_t* offset,const int32_t* target,const uint8_t* fiber,
 const int32_t* field_start,const int32_t* af,const uint8_t* ad,const uint8_t* ap,
 const double* factor,const uint8_t* band,const uint8_t* eligible,
 const double* weight,const double* mult,double mismatch,
 const double* best,const double* sigma,const double* time_cost,const uint8_t* allowed,
 double* residual,int32_t* witness,double* bestgain) {
 for(int i=0;i<n;i++){witness[i]=-1;bestgain[i]=0.;}
 for(int a=0;a<na;a++) {
  if(!allowed[a]){residual[a]=-std::numeric_limits<double>::infinity();continue;}
  int f=af[a],s=field_start[f],d=ad[a],p=ap[a];
  int64_t bank=((int64_t)s*nd+d)*n;
  double cell[64]={0.};
  for(int k=offset[f];k<offset[f+1];k++) {
   int i=target[k]; if(!eligible[bank+i])continue;
   double score=weight[i]*factor[bank+i]*(band[bank+i]==p?mult[p]:mismatch);
   double gain=std::max(0.,score-best[i]);
   if(gain>bestgain[i]){bestgain[i]=gain;witness[i]=a;}
   cell[fiber[k]]=std::max(cell[fiber[k]],gain-sigma[i]);
  }
  double sum=-time_cost[a]; for(int f2=0;f2<nf;f2++)sum+=cell[f2];
  residual[a]=sum;
 }
}
extern "C" void compress_intervals(int na,int ng,const double* values,
 const int32_t* group,const uint8_t* allowed,int32_t* winner) {
 for(int j=0;j<ng;j++)winner[j]=-1;
 for(int a=0;a<na;a++)if(allowed[a]) {
  int j=group[a],old=winner[j];
  if(old<0 || values[a]>values[old])winner[j]=a;
 }
}
