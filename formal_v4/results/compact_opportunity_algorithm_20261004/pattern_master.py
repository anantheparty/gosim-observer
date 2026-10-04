"""Exact finite LP reformulation, restricted master and full pricing oracle.

Patterns are physical complete assignments: zero or one target per fiber.
No weather/scenario loader or official truth inputs.
"""
from __future__ import annotations
import time
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix

TOL=1e-7
MAX_ROUNDS=24
MAX_PATTERNS=8192
PER_START=2

class PatternGraph:
    def __init__(self,n,nfib,cols,patterns=None):
        self.n=n;self.nfib=nfib;self.cols=cols;self.na=len(cols)
        self.target=np.concatenate([x['target'] for x in cols]).astype(np.int32)
        self.score=np.concatenate([x['c'] for x in cols])
        self.fiber=np.concatenate([x['fiber'] for x in cols]).astype(np.int32)
        self.edge_action=np.repeat(np.arange(self.na,dtype=np.int32),[len(x['target']) for x in cols])
        self.ne=len(self.target)
        if any(len(set(zip(map(int,c['target']),map(int,c['fiber']))))!=len(c['target']) or len(set(map(int,c['target'])))!=len(c['target']) for c in cols):
            raise ValueError('Each target must belong to exactly one fiber in each exposure')
        keys=self.edge_action*nfib+self.fiber
        self.cell_keys,self.cell=np.unique(keys,return_inverse=True)
        self.cell_action=self.cell_keys//nfib;self.nc=len(self.cell_keys)
        self.starts=np.asarray([x['start'] for x in cols]);self.ends=np.asarray([x['end'] for x in cols])
        if np.any(self.ends<=self.starts):raise ValueError('Positive duration required')
        self.endpoints=np.unique(np.r_[self.starts,self.ends]);self.nt=len(self.endpoints)-1
        self.left=np.searchsorted(self.endpoints,self.starts);self.right=np.searchsorted(self.endpoints,self.ends)
        self.patterns=list(patterns or []);self.seen={(e,ids) for e,ids in self.patterns}
        self.seed()

    def gain(self,b):return np.maximum(0.,self.score-b[self.target])

    def oracle(self,gain,sigma,lam,allowed):
        adjusted=gain-sigma[self.target];cellmax=np.zeros(self.nc)
        np.maximum.at(cellmax,self.cell,adjusted)
        winner=np.full(self.nc,self.ne,dtype=np.int32)
        good=np.flatnonzero((adjusted==cellmax[self.cell]) & (adjusted>0))
        np.minimum.at(winner,self.cell[good],good)
        chosen=winner[winner<self.ne]
        sizes=np.bincount(self.edge_action[chosen],minlength=self.na)
        offsets=np.r_[0,np.cumsum(sizes)]
        prefix=np.r_[0.,np.cumsum(lam)]
        price=np.bincount(self.cell_action,weights=cellmax,minlength=self.na)-(prefix[self.right]-prefix[self.left])
        price=np.where(allowed,price,-np.inf)
        return price,chosen,offsets

    def add(self,e,ids):
        ids=tuple(map(int,ids));key=(int(e),ids)
        if not ids or key in self.seen:return False
        if len(self.patterns)>=MAX_PATTERNS:return False
        if len(set(map(int,self.fiber[list(ids)])))!=len(ids):raise ValueError('Pattern fiber collision')
        if np.any(self.edge_action[list(ids)]!=e):raise ValueError('Pattern spans exposures')
        self.seen.add(key);self.patterns.append(key);return True

    def seed(self):
        gain=self.score
        price,chosen,offsets=self.oracle(gain,np.zeros(self.n),np.zeros(self.nt),np.ones(self.na,dtype=bool))
        best=np.zeros(self.n);np.maximum.at(best,self.target,gain)
        witness=np.full(self.n,self.ne,dtype=np.int32)
        good=np.flatnonzero(gain==best[self.target]);np.minimum.at(witness,self.target[good],good)
        selected=set(map(int,self.edge_action[witness[witness<self.ne]]))
        pairs=np.stack([self.left,self.right],axis=1);unique,group=np.unique(pairs,axis=0,return_inverse=True)
        order=np.lexsort((np.arange(self.na),-price,group));_,first=np.unique(group[order],return_index=True)
        selected.update(map(int,order[first]))
        for e in sorted(selected):self.add(e,chosen[offsets[e]:offsets[e+1]])

    def matrix(self,allowed,gain):
        active=[k for k,(e,ids) in enumerate(self.patterns) if allowed[e]]
        rows=[];columns=[];value=[]
        for col,k in enumerate(active):
            e,ids=self.patterns[k];ids=list(ids)
            targets=self.target[ids].tolist();atoms=list(range(self.left[e],self.right[e]))
            rows.extend(targets);rows.extend(self.n+j for j in atoms)
            columns.extend([col]*(len(targets)+len(atoms)));value.append(float(gain[ids].sum()))
        matrix=coo_matrix((np.ones(len(rows)),(rows,columns)),shape=(self.n+self.nt,len(active))).tocsr()
        return matrix,np.asarray(value),active

    def solve(self,b,blocked_until,now,cost,name,trace):
        start=time.perf_counter();cpu=time.process_time();gain=self.gain(b)
        allowed=~((self.starts<blocked_until)&(self.ends>now))
        if not np.any(allowed):
            row=dict(value=0.,full_feasible_dual_upper=0.,certified_gap=0.,pricing_residual=0.,converged=True,
                rounds=0,master_variables=0,master_rows=self.n+self.nt,master_nonzeros=0,restricted_dual_value=0.,
                positive_target_prices=0,positive_time_prices=0,empty_future_domain=True)
            trace.append(dict(branch=name,**row));return row,np.zeros(self.n),np.zeros(self.nt),[]
        output=None
        for iteration in range(MAX_ROUNDS):
            cost.check();t=time.perf_counter();A,values,active=self.matrix(allowed,gain)
            lp=linprog(-values,A_ub=A,b_ub=np.ones(self.n+self.nt),bounds=(0,None),method='highs',
                options=dict(time_limit=max(.001,10.-(time.perf_counter()-cost.start)),threads=1))
            if not lp.success:raise cost.stop_type('Restricted LP incomplete: '+lp.message)
            sigma=np.maximum(0.,-lp.ineqlin.marginals[:self.n]);lam=np.maximum(0.,-lp.ineqlin.marginals[self.n:])
            price,chosen,offsets=self.oracle(gain,sigma,lam,allowed)
            residual=max(0.,float(np.max(price)))
            repair=np.zeros(self.nt);np.maximum.at(repair,self.left[allowed],np.maximum(0.,price[allowed]))
            feasible_lambda=lam+repair
            # Re-run oracle rather than relying only on the repair argument.
            after,_,_=self.oracle(gain,sigma,feasible_lambda,allowed)
            if max(0.,float(np.max(after)))>1e-7:raise RuntimeError('Feasible dual repair failed')
            primal=float(-lp.fun);dual=float(sigma.sum()+feasible_lambda.sum())
            if dual+1e-7<primal:raise RuntimeError('Full feasible dual below restricted primal')
            row=dict(branch=name,iteration=iteration+1,patterns_total=len(self.patterns),patterns_active=len(active),
                master_rows=A.shape[0],master_nonzeros=A.nnz,
                matrix_bytes=A.data.nbytes+A.indices.nbytes+A.indptr.nbytes,
                restricted_primal=primal,pricing_residual=residual,dual_repair_sum=float(repair.sum()),
                full_feasible_dual_upper=dual,certified_gap=dual-primal,
                solve_and_pricing_wall_seconds=time.perf_counter()-t,solver_iterations=int(lp.nit),
                max_rss_bytes=cost.rss(),converged=residual<=TOL,
                target_prices=sigma.tolist(),time_prices=lam.tolist(),start_atom_dual_repair=repair.tolist())
            trace.append(row)
            cost.check()
            output=dict(value=primal,full_feasible_dual_upper=dual,certified_gap=dual-primal,
                pricing_residual=residual,converged=residual<=TOL,rounds=iteration+1,
                master_variables=len(active),master_rows=A.shape[0],master_nonzeros=A.nnz,
                restricted_dual_value=float(sigma.sum()+lam.sum()),
                positive_target_prices=int(np.count_nonzero(sigma>1e-9)),positive_time_prices=int(np.count_nonzero(lam>1e-9)))
            if residual<=TOL:break
            eligible=np.flatnonzero(price>TOL)
            order=eligible[np.lexsort((eligible,-price[eligible],self.left[eligible]))]
            groups={};added=0
            for e in order:
                group=int(self.left[e])
                if groups.get(group,0)>=PER_START:continue
                if self.add(int(e),chosen[offsets[e]:offsets[e+1]]):groups[group]=groups.get(group,0)+1;added+=1
            row['patterns_added']=added
            if not added:break
        cost.stages.append(dict(stage=name,wall_seconds=time.perf_counter()-start,cpu_seconds=time.process_time()-cpu,
            rounds=output['rounds'],converged=output['converged']))
        cost.check()
        # Restricted master pattern solution is also saved for mechanical feasibility audits.
        support=[]
        for q in np.flatnonzero(lp.x>1e-10):
            e,ids=self.patterns[active[int(q)]]
            support.append(dict(action=int(e),edges=list(ids),fraction=float(lp.x[q])))
        return output,sigma,lam,support

    def greedy(self,b,blocked_until,now,support):
        """Complete feasible integer schedule; no stochastic/weather claim."""
        ledger=np.asarray(b).copy();allowed=~((self.starts<blocked_until)&(self.ends>now))
        candidates=[(row['action'],row['edges']) for row in support if allowed[row['action']]];schedule=[];occupied=[]
        while candidates:
            best=None
            for e,edges in candidates:
                c=self.cols[e];ids=self.target[edges];scores=np.maximum(0.,self.score[edges]-ledger[ids])
                chosen=[edges[k] for k in np.flatnonzero(scores>0)];value=float(scores.sum())
                # Gain per occupied second is deterministic, not a true expected reward.
                key=(value/max(1.,c['end']-c['start']),value,-int(e))
                if value>0 and (best is None or key>best[0]):best=(key,int(e),chosen)
            if best is None:break
            _,e,chosen=best;c=self.cols[e]
            targets=self.target[chosen];scores=self.score[chosen]
            if any(c['start']<end and start<c['end'] for start,end in occupied):raise RuntimeError('Greedy interval collision')
            if len(set(map(int,self.fiber[chosen])))!=len(chosen):raise RuntimeError('Greedy fiber collision')
            ledger[targets]=np.maximum(ledger[targets],scores)
            schedule.append(dict(action=e,targets=targets.tolist(),fiber=self.fiber[chosen].tolist(),score=scores.tolist()))
            occupied.append((c['start'],c['end']))
            candidates=[(x,ids) for x,ids in candidates if not(self.starts[x]<c['end'] and c['start']<self.ends[x])]
        return dict(increment=float((ledger-b).sum()),final_ledger=ledger.tolist(),schedule=schedule,
            feasible_integer=True,control='greedy rounding of restricted master support',model_scope='fixed nominal science only')

    def metadata(self):return dict(actions=self.na,target_edges=self.ne,nonempty_action_fibers=self.nc,
        time_atoms=self.nt,master_rows=self.n+self.nt,patterns=len(self.patterns),
        solver_full_edge_variables_constructed=False,solver_full_fiber_rows_constructed=False)
