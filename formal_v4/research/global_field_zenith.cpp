// Independent endpoint proposal. The running global-field L1 source is unchanged.
// Fixed actual altitude; analytic spherical glass-boundary events in azimuth.
#include "global_field_search.cpp"

extern "C" int global_field_zenith_search(int n,const double*data,const double*cfg,double*out,double*stats) {
  try {
    Engine e=make_engine(n,data,cfg);e.keep=(int)cfg[11];
    double a=cfg[17]*rad;
    if(a<0||a>pi/2)return -2;
    bool pole=std::abs(a-pi/2)<1e-14;
    double period=pole?pi/2:2*pi;
    double fieldradius=std::atan(e.side*e.pitch/std::sqrt(2.)*rad);
    Node b;std::vector<double>angles{0.,period};
    auto event=[&](double z) {
      z=std::fmod(z,period);if(z<0)z+=period;
      if(z>1e-14&&z<period-1e-14)angles.push_back(z);
    };
    double sa=std::sin(a),ca=std::cos(a),half=e.glass/2-.008;
    for(int i=0;i<n;i++) {
      auto const&t=e.targets[i];
      if(std::abs(t.alt-a)>fieldradius+1e-12||t.upper<=0)continue;
      b.ids.push_back(i);
      if(t.c<1e-15)continue;
      for(int cell=0;cell<e.side;cell++)for(int sign:{-1,1}) {
        double edge=((cell-(e.side-1)/2.)*e.pitch+sign*half)*rad;
        // n/q = edge.
        double denominator=t.c*(sa+edge*ca);
        if(std::abs(denominator)>1e-16) {
          double rhs=t.s*(ca-edge*sa)/denominator;
          if(std::abs(rhs)<=1+1e-13) {
            double d=std::acos(std::clamp(rhs,-1.,1.));
            event(t.az-d);event(t.az+d);
          }
        }
        // e/q = edge: sin(delta)-edge*cos(a)*cos(delta)
        //            = edge*tan(h)*sin(a).
        double R=std::sqrt(1+edge*edge*ca*ca),phi=std::atan(edge*ca);
        double rhs=edge*(t.s/t.c)*sa/R;
        if(std::abs(rhs)<=1+1e-13) {
          double d=std::asin(std::clamp(rhs,-1.,1.));
          event(t.az-phi-d);event(t.az-phi-pi+d);
        }
      }
    }
    std::sort(angles.begin(),angles.end());
    angles.erase(std::unique(angles.begin(),angles.end(),[](double x,double y){return std::abs(x-y)<1e-13;}),angles.end());
    int evaluated=0;
    for(int j=0;j<(int)angles.size();j++) {
      if(j+1<(int)angles.size()) {
        double z=(angles[j]+angles[j+1])/2;
        e.propose(e.evaluate(b,a,z),a,z);evaluated++;
      }
      // Include exact event points: equality is accepted by the inherited
      // margin contract, so a zero-width feasible assignment may exist.
      if(angles[j]<period) {e.propose(e.evaluate(b,a,angles[j]),a,angles[j]);evaluated++;}
    }
    for(int j=0;j<(int)e.proposals.size();j++){out[3*j]=e.proposals[j].rate;out[3*j+1]=e.proposals[j].alt;out[3*j+2]=e.proposals[j].az;}
    stats[0]=b.ids.size();stats[1]=angles.size();stats[2]=evaluated;stats[3]=pole;stats[4]=period/rad;
    return e.proposals.size();
  }catch(...){return -1;}
}
