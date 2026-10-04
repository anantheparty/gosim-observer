// CPU arithmetic fusion only. Geometry/candidate/tie semantics live in Python.
#include <cstdint>
#include <cmath>
#include <algorithm>
extern "C" void fine_values(
 const int64_t *times, int D, const int64_t *idx, int N, const int32_t *fiber, int F, int G,
 const double *up, const double *k, const double *scores, const double *factors,
 const double *weight, const double *mult, const uint8_t *missing,
 const double *rr, const double *rt, const double *rd, const double *ub, const double *urgency,
 const uint8_t *membership, double req_threshold, double uniform_threshold, double req_penalty,
 double safety, double focus_reward, int focus_left, double focus_threshold, double focus_deadline,
 double *value, double *cells, double *eligible_cells, uint8_t *allowed, uint8_t *eligible, int64_t *winner, int64_t *ewinner) {
 std::fill(cells, cells+D*3*F, 0.);
 std::fill(eligible_cells,eligible_cells+D*3*F,-INFINITY);
 if(winner)std::fill(winner,winner+D*3*F,-1);
 if(ewinner)std::fill(ewinner,ewinner+D*3*F,-1);
 for(int d=0;d<D;d++) for(int j=0;j<N;j++) {
  int64_t i=idx[j];double t=static_cast<double>(times[d]);
  double raw=std::min(1.,t*k[i]);double robust=std::min(1.,t*k[i]/safety);
  bool a=t<=up[i]; bool fe=membership && membership[i] && robust+1e-10>=focus_threshold && t<=focus_deadline;
  if(allowed)allowed[d*N+j]=a;
  if(eligible)eligible[d*N+j]=fe;
  double terminal=(missing[i] && robust+1e-10>=req_threshold) * req_penalty;
  terminal += (factors[i]<uniform_threshold && robust+1e-10>=uniform_threshold) * ub[i];
  terminal += (rr[i]>0 && robust+1e-10>=rt[i] && t<=rd[i]) * rr[i];
  if(membership)terminal -= fe*(focus_reward/focus_left);
  for(int p=0;p<3;p++) {
   double science=std::max(0.,weight[i]*raw*mult[p*G+i]-scores[i]);
   double v=a?(science+terminal)*urgency[i]:-INFINITY;
   if(value)value[(d*3+p)*N+j]=v;
   int cell=(d*3+p)*F+fiber[j];
   if(v>cells[cell]) {cells[cell]=v;if(winner)winner[cell]=i;}
   if(fe && v>eligible_cells[cell]) {eligible_cells[cell]=v;if(ewinner)ewinner[cell]=i;}
  }
 }
}
extern "C" void coarse_cells(int C,int N,int F,const int32_t *fiber,const uint8_t *valid,
 const double *value,const uint8_t *target_allowed,const uint8_t *target_eligible,
 double *cells,double *eligible_cells) {
 std::fill(cells,cells+C*3*F,0.);
 if(target_eligible)std::fill(eligible_cells,eligible_cells+C*3*F,-INFINITY);
 for(int c=0;c<C;c++)for(int j=0;j<N;j++) {
  if(!valid[c*N+j] || !target_allowed[j])continue;
  int f=fiber[c*N+j];
  for(int p=0;p<3;p++) {
   int cell=(c*3+p)*F+f;double v=value[p*N+j];
   cells[cell]=std::max(cells[cell],v);
   if(target_eligible && target_eligible[j])eligible_cells[cell]=std::max(eligible_cells[cell],v);
  }
 }
}
