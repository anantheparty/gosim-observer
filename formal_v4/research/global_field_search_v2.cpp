// Global spherical pointing boxes, target/fibre compatibility and matching bound.
// The bound applies to the frozen public utility model, not to final season score.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <queue>
#include <vector>

namespace {
constexpr double pi=3.14159265358979323846, rad=pi/180., inf=1e100;
struct Target {
  double alt,az,s,c,k,up,score,factor,w,urg,req,rr,rt,rd,ub,upper,tx,ty;
  std::array<double,3> mult;
  bool focus;
};
struct Node {
  double al,ah,zl,zh,bound;
  std::vector<int> ids;
  std::vector<unsigned> masks;
  int serial;
};
struct Order { bool operator()(Node const&a,Node const&b)const {
  return a.bound==b.bound ? a.serial>b.serial : a.bound<b.bound;
}};
struct Proposal {double rate,alt,az;};
struct Result {
  double rate=0.,total=0.,alt=0.,az=0.;
  int duration=0,program=0;
  std::array<int,16> chosen;
  Result(){chosen.fill(-1);}
};
struct Engine {
  int n,side,nf,tmin,tmax,limit,keep,serial=0,roots=0,visited=0,pruned=0,evaluations=0,matchings=0;
  double pitch,glass,safety,reqthr,reqpen,unithr,incumbent,focusreward,focusthr,focusdeadline;
  int focusleft;
  double offset_alt=0.,offset_az=0.;
  long long root_pool_entries=0,root_full_entries=0;
  int improvements=0;
  Result best_action;
  std::vector<Target> targets;
  std::vector<Proposal> proposals;
  double eps=1e-10;

  static std::pair<double,double> wave(double C,double D,double l,double h) {
    double a=C*std::cos(l)+D*std::sin(l),b=C*std::cos(h)+D*std::sin(h);
    double low=std::min(a,b),high=std::max(a,b),p=std::atan2(D,C);
    for(int k=-2;k<=2;k++) for(int j=0;j<2;j++) {
      double x=p+k*2*pi+j*pi;
      if(l<=x&&x<=h) {double v=C*std::cos(x)+D*std::sin(x);low=std::min(low,v);high=std::max(high,v);}
    }
    return {low-2e-14,high+2e-14};
  }
  unsigned mask(Target const&t,Node const&b) const {
    double radius=std::atan(side*pitch/std::sqrt(2.)*rad);
    if(t.alt<b.al-radius-1e-12||t.alt>b.ah+radius+1e-12)return 0;
    auto cc=wave(1.,0.,t.az-b.zh,t.az-b.zl);
    auto ss=wave(0.,1.,t.az-b.zh,t.az-b.zl);
    double A0=t.c*cc.first,A1=t.c*cc.second;
    auto q0=wave(A0,t.s,b.al,b.ah),q1=wave(A1,t.s,b.al,b.ah);
    double half=side*pitch/2*rad;
    double qfield=1./std::sqrt(1+2*half*half);
    double ql=std::max(qfield,q0.first),qh=q1.second;
    if(qh<qfield-2e-13)return 0;
    auto nn0=wave(t.s,-A1,b.al,b.ah),nn1=wave(t.s,-A0,b.al,b.ah);
    double n0=nn0.first,n1=nn1.second,e0=t.c*ss.first,e1=t.c*ss.second;
    auto ratio=[&](double x0,double x1) {
      return std::make_pair(x0/(x0>=0?qh:ql)/rad,x1/(x1>=0?ql:qh)/rad);
    };
    auto rn=ratio(n0,n1),re=ratio(e0,e1);
    double h=glass/2-.008;
    unsigned result=0;
    for(int r=0;r<side;r++) {
      double cr=(r-(side-1)/2.)*pitch;
      if(rn.second<cr-h-1e-9||rn.first>cr+h+1e-9)continue;
      for(int c=0;c<side;c++) {
        double ce=(c-(side-1)/2.)*pitch;
        if(re.second>=ce-h-1e-9&&re.first<=ce+h+1e-9) result|=1u<<(r*side+c);
      }
    }
    return result;
  }
  // Hungarian: nf fibres, distinct targets plus empty dummy choices.
  double matching(Node const&b) {
    matchings++;
    int m=b.ids.size()+nf;
    std::vector<double>u(nf+1),v(m+1),minv(m+1);
    std::vector<int>p(m+1),way(m+1);
    std::vector<unsigned char> used(m+1);
    for(int row=1;row<=nf;row++) {
      p[0]=row;int j0=0;
      std::fill(minv.begin(),minv.end(),inf);std::fill(used.begin(),used.end(),0);
      do {
        used[j0]=1;int i0=p[j0],j1=0;double delta=inf;
        for(int j=1;j<=m;j++)if(!used[j]) {
          double cost=(j<=(int)b.ids.size()&&(b.masks[j-1]&(1u<<(i0-1)))) ? -targets[b.ids[j-1]].upper:0.;
          double cur=cost-u[i0]-v[j];
          if(cur<minv[j]){minv[j]=cur;way[j]=j0;}
          if(minv[j]<delta){delta=minv[j];j1=j;}
        }
        for(int j=0;j<=m;j++)if(used[j]){u[p[j]]+=delta;v[j]-=delta;}else minv[j]-=delta;
        j0=j1;
      }while(p[j0]!=0);
      do{int j1=way[j0];p[j0]=p[j1];j0=j1;}while(j0);
    }
    return v[0]+1e-8;
  }
  bool bound(Node &b,std::vector<int> const&pool) {
    std::array<double,16> cells{};
    std::vector<double> tops;
    double ac=(b.al+b.ah)/2,zc=(b.zl+b.zh)/2;
    double radius=std::atan(side*pitch/std::sqrt(2.)*rad)+(b.ah-b.al)/2+std::cos(b.al)*(b.zh-b.zl)/2;
    double cosine=radius>=pi?-1.:std::cos(radius);
    double vx=std::cos(ac)*std::cos(zc),vy=std::cos(ac)*std::sin(zc),vz=std::sin(ac);
    for(int i:pool) {
      auto const&t=targets[i];
      double dot=t.tx*vx+t.ty*vy+t.s*vz;
      if(dot<cosine-1e-12)continue;
      unsigned f=mask(targets[i],b);
      if(!f)continue;
      b.ids.push_back(i);b.masks.push_back(f);tops.push_back(targets[i].upper);
      for(int j=0;j<nf;j++)if(f&(1u<<j))cells[j]=std::max(cells[j],targets[i].upper);
    }
    if(b.ids.empty())return false;
    double sum=0;for(int j=0;j<nf;j++)sum+=cells[j];
    std::sort(tops.begin(),tops.end(),std::greater<double>());
    double top=0;for(int j=0;j<std::min(nf,(int)tops.size());j++)top+=tops[j];
    b.bound=std::min(sum,top)+1e-8;
    if(b.bound<=incumbent+eps){pruned++;return false;}
    b.bound=std::min(b.bound,matching(b));
    if(b.bound<=incumbent+eps){pruned++;return false;}
    b.serial=serial++;return true;
  }
  int classify(Target const&t,double a,double z) const {
    double A=t.c*std::cos(t.az-z),q=A*std::cos(a)+t.s*std::sin(a);
    if(q<=0)return -1;
    double x=t.c*std::sin(t.az-z)/q/rad,y=(-A*std::sin(a)+t.s*std::cos(a))/q/rad;
    int r=(int)std::floor(y/pitch+side/2.),c=(int)std::floor(x/pitch+side/2.);
    if(r<0||r>=side||c<0||c>=side)return -1;
    double cr=(r-(side-1)/2.)*pitch,ce=(c-(side-1)/2.)*pitch,h=glass/2-.008;
    if(std::abs(y-cr)>h||std::abs(x-ce)>h)return -1;
    return r*side+c;
  }
  Result evaluate(Node const&b,double a,double z) {
    evaluations++;
    Result best;
    double cmd_alt=std::round((a/rad-offset_alt)*1e7)/1e7;
    double cmd_az=std::fmod(std::fmod(z/rad-offset_az,360.)+360.,360.);
    cmd_az=std::fmod(std::round(cmd_az*1e7)/1e7,360.);
    if(cmd_alt<0||cmd_alt>90)return best;
    a=(cmd_alt+offset_alt)*rad;z=std::fmod(cmd_az+offset_az+720.,360.)*rad;
    if(a<0||a>pi/2)return best;
    std::vector<int> ids,fs,ds{tmin,tmax};
    auto add=[&](double d){if(std::isfinite(d))ds.push_back(std::max(tmin,std::min(tmax,(int)std::min(1e9,d))));};
    for(int d:{300,600,900,1200,1800,2400,3600})add(d);
    auto threshold=[&](double f,double k){double first=std::ceil(std::max(0.,f-eps)*safety/k);add(first-1);add(first);add(first+1);};
    for(int i:b.ids) {
      int f=classify(targets[i],a,z);if(f<0)continue;
      ids.push_back(i);fs.push_back(f);auto const&t=targets[i];
      add(std::floor(1./t.k));add(std::ceil(1./t.k));add(std::floor(t.up));add(std::floor(t.up)+1);
      if(t.req)threshold(reqthr,t.k);
      if(t.factor<unithr)threshold(unithr,t.k);
      if(t.rr>0){threshold(t.rt,t.k);add(std::floor(t.rd));add(std::floor(t.rd)+1);}
      if(t.focus&&focusleft>0){threshold(focusthr,t.k);add(std::floor(focusdeadline));add(std::floor(focusdeadline)+1);}
    }
    if(ids.empty())return best;
    std::sort(ds.begin(),ds.end());ds.erase(std::unique(ds.begin(),ds.end()),ds.end());
    double maximum_rate=0;
    for(int d:ds)for(int program=0;program<3;program++) {
      std::array<double,16> cells{},ecells;ecells.fill(-inf);
      std::array<int,16> winners,ewinners;winners.fill(-1);ewinners.fill(-1);
      for(int j=0;j<(int)ids.size();j++) {
        auto const&t=targets[ids[j]];if(d>t.up)continue;
        double raw=std::min(1.,d*t.k),robust=std::min(1.,d*t.k/safety);
        double terminal=(t.req&&robust+eps>=reqthr?reqpen:0.)+(t.factor<unithr&&robust+eps>=unithr?t.ub:0.)
             +(t.rr>0&&robust+eps>=t.rt&&d<=t.rd?t.rr:0.);
        bool eligible=focusleft>0&&t.focus&&robust+eps>=focusthr&&d<=focusdeadline;
        if(eligible)terminal-=focusreward/focusleft;
        double value=(std::max(0.,t.w*raw*t.mult[program]-t.score)+terminal)*t.urg;
        int f=fs[j];if(value>cells[f]){cells[f]=value;winners[f]=ids[j];}
        if(eligible&&value>ecells[f]){ecells[f]=value;ewinners[f]=ids[j];}
      }
      double total=0;for(int f=0;f<nf;f++)total+=cells[f];
      std::array<int,16> order;for(int f=0;f<nf;f++)order[f]=f;
      int force=0;
      if(focusleft>0) {
        std::array<double,16>cost;int count=0;
        for(int f=0;f<nf;f++){cost[f]=cells[f]-ecells[f];if(ecells[f]>-inf/2)count++;}
        std::sort(order.begin(),order.begin()+nf,[&](int x,int y){return cost[x]==cost[y]?x<y:cost[x]<cost[y];});
        int q=std::min(focusleft,nf);
        if(focusleft<=nf&&count>=focusleft){
          double c=0;for(int j=0;j<q;j++)c+=cost[order[j]];
          double full=total+focusreward-c;
          if(full>=total-1e-10)force=focusleft;
          total=std::max(total,full);
        }else for(int j=0;j<q;j++){
          double gain=std::max(0.,focusreward/focusleft-cost[order[j]]);total+=gain;if(gain>0)force++;
        }
      }
      double rate=total/d;maximum_rate=std::max(maximum_rate,rate);
      double tolerance=1e-10*std::max(1.,maximum_rate);
      if(best.duration==0||best.rate<maximum_rate-tolerance||(rate>=maximum_rate-tolerance&&total>best.total)) {
        best.rate=rate;best.total=total;best.duration=d;best.program=program;best.alt=a/rad;best.az=z/rad;best.chosen=winners;
        for(int j=0;j<force;j++)best.chosen[order[j]]=ewinners[order[j]];
      }
    }
    return best;
  }
  void propose(double rate,double a,double z) {
    if(rate<=incumbent+eps)return;
    double ad=a/rad,zd=z/rad;
    for(auto &p:proposals)if(std::abs(ad-p.alt)<.015&&std::abs(zd-p.az)*std::max(.035,std::cos(a))<.015) {
      if(rate>p.rate)p={rate,ad,zd};return;
    }
    proposals.push_back({rate,ad,zd});
    std::sort(proposals.begin(),proposals.end(),[](Proposal const&a,Proposal const&b){return a.rate>b.rate;});
    if((int)proposals.size()>keep)proposals.resize(keep);
  }
  void search(double alo,double ahi) {
    std::priority_queue<Node,std::vector<Node>,Order> heap;
    std::vector<int>all;for(int i=0;i<n;i++)if(targets[i].upper>1e-12)all.push_back(i);
    std::sort(all.begin(),all.end(),[&](int x,int y){return targets[x].alt==targets[y].alt?x<y:targets[x].alt<targets[y].alt;});
    double fieldradius=std::atan(side*pitch/std::sqrt(2.)*rad);
    for(double a=alo;a<ahi;a+=4*rad) {
      double ah=std::min(ahi,a+4*rad);
      auto lower=std::lower_bound(all.begin(),all.end(),a-fieldradius-1e-12,[&](int x,double alt){return targets[x].alt<alt;});
      auto upper=std::upper_bound(all.begin(),all.end(),ah+fieldradius+1e-12,[&](double alt,int x){return alt<targets[x].alt;});
      std::vector<int> pool(lower,upper);
      // Preserve public catalogue order for equal target-utility winners.
      std::sort(pool.begin(),pool.end());
      for(double z=0;z<2*pi-1e-12;z+=8*rad) {
        root_pool_entries+=pool.size();root_full_entries+=all.size();
        Node b{a,ah,z,std::min(2*pi,z+8*rad),0};
        if(bound(b,pool)){roots++;heap.push(std::move(b));}
      }
    }
    while(!heap.empty()&&visited<limit) {
      Node b=heap.top();heap.pop();
      if(b.bound<=incumbent+eps){pruned++;continue;}
      visited++;
      double a=(b.al+b.ah)/2,z=(b.zl+b.zh)/2;
      Result candidate=evaluate(b,a,z);
      if(candidate.rate>incumbent+eps){incumbent=candidate.rate;best_action=candidate;improvements++;}
      double aw=b.ah-b.al,zw=(b.zh-b.zl)*std::max(.035,std::cos(a));
      if(std::max(aw,zw)<.008*rad)continue;
      for(int j=0;j<2;j++) {
        Node c=b;c.ids.clear();c.masks.clear();
        if(aw>=zw){if(j)c.al=a;else c.ah=a;}else{if(j)c.zl=z;else c.zh=z;}
        if(bound(c,b.ids))heap.push(std::move(c));
      }
    }
  }
};
}

// data columns: alt,az,k,up,score,factor,weight,urgency,reqmissing,
// rr,rt,rd,uniformbonus,upper,mult0,mult1,mult2,focusmembership.
Engine make_engine(int n,const double*data,const double*cfg) {
    Engine e;e.n=n;e.side=(int)cfg[0];e.nf=e.side*e.side;
    e.pitch=cfg[1];e.glass=cfg[2];e.tmin=(int)cfg[3];e.tmax=(int)cfg[4];e.safety=cfg[5];
    e.reqthr=cfg[6];e.reqpen=cfg[7];e.unithr=cfg[8];e.incumbent=cfg[9];e.limit=(int)cfg[10];e.keep=(int)cfg[11];
    e.focusleft=(int)cfg[12];e.focusreward=cfg[13];e.focusthr=cfg[14];e.focusdeadline=cfg[15];
    e.offset_alt=cfg[18];e.offset_az=cfg[19];
    for(int i=0;i<n;i++) {
      const double*d=data+18*i;Target t;
      t.alt=d[0]*rad;t.az=d[1]*rad;t.s=std::sin(t.alt);t.c=std::cos(t.alt);t.k=d[2];t.up=d[3];t.score=d[4];
      t.factor=d[5];t.w=d[6];t.urg=d[7];t.req=d[8];t.rr=d[9];t.rt=d[10];t.rd=d[11];t.ub=d[12];t.upper=d[13];
      t.tx=t.c*std::cos(t.az);t.ty=t.c*std::sin(t.az);
      for(int j=0;j<3;j++)t.mult[j]=d[14+j];t.focus=d[17]>0;e.targets.push_back(t);
    }
    return e;
}

extern "C" int global_field_search_v2(int n,const double*data,const double*cfg,double*out,double*stats) {
  try {
    Engine e=make_engine(n,data,cfg);
    if(e.nf>16||e.nf<1)return -2;
    e.search(cfg[16]*rad,cfg[17]*rad);
    auto const&r=e.best_action;
    out[0]=r.rate;out[1]=r.alt;out[2]=r.az;out[3]=r.duration;out[4]=r.program;out[5]=r.total;
    for(int f=0;f<e.nf;f++)out[6+f]=r.chosen[f];
    stats[0]=e.roots;stats[1]=e.visited;stats[2]=e.pruned;stats[3]=e.evaluations;stats[4]=e.matchings;
    stats[5]=e.improvements;stats[6]=e.root_pool_entries;stats[7]=e.root_full_entries;
    return r.duration>0?1:0;
  }catch(...){return -1;}
}

extern "C" double global_field_bound_v2(int n,const double*data,const double*cfg,const double*box) {
  Engine e=make_engine(n,data,cfg);e.incumbent=-inf;
  Node b{box[0]*rad,box[1]*rad,box[2]*rad,box[3]*rad,0};
  std::vector<int>pool;for(int i=0;i<n;i++)pool.push_back(i);
  if(!e.bound(b,pool))return 0;return b.bound;
}

extern "C" double global_field_point_action_v2(int n,const double*data,const double*cfg,double a,double z,double*out) {
  Engine e=make_engine(n,data,cfg);Node b;
  for(int i=0;i<n;i++)b.ids.push_back(i);
  Result r=e.evaluate(b,a*rad,z*rad);
  out[0]=r.rate;out[1]=r.alt;out[2]=r.az;out[3]=r.duration;out[4]=r.program;out[5]=r.total;
  for(int f=0;f<e.nf;f++)out[6+f]=r.chosen[f];
  return r.rate;
}

extern "C" unsigned global_field_mask_v2(double alt,double az,double al,double ah,double zl,double zh,int side,double pitch,double glass) {
  Engine e;e.side=side;e.pitch=pitch;e.glass=glass;
  Target t;t.alt=alt*rad;t.az=az*rad;t.s=std::sin(t.alt);t.c=std::cos(t.alt);
  Node b{al*rad,ah*rad,zl*rad,zh*rad,0};return e.mask(t,b);
}
