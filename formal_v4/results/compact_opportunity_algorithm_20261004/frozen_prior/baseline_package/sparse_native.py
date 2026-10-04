"""Exact compiled arithmetic/maxima; Python retains all search decisions."""
import ctypes, platform
from pathlib import Path
import numpy as np
LIBNAME = 'sparse_kernel_darwin_arm64.dylib' if platform.system()=='Darwin' and platform.machine()=='arm64' else 'sparse_kernel_linux_x86_64.so'
lib=ctypes.CDLL(str(Path(__file__).with_name(LIBNAME)))
P=ctypes.c_void_p;I=ctypes.c_int;Q=ctypes.c_double
lib.fine_values.argtypes=[P,I,P,I,P,I,I]+[P]*13+[Q]*4+[Q,I,Q,Q]+[P]*7
lib.fine_values.restype=None
lib.coarse_cells.argtypes=[I,I,I]+[P]*7
lib.coarse_cells.restype=None

def ptr(a):return None if a is None else a.ctypes.data

def fine_tables(planner,idx,fiber,durations,frame):
 up,k,scores,factors,multiplier,missing,rr,rt,rd,ub,urgency,safety,focus=frame
 D,N=len(durations),len(idx);shape=(D,3,planner.nfib)
 value=np.empty((D,3,N));cells=np.empty(shape);ecells=np.empty(shape)
 allowed=np.empty((D,N),dtype=bool);eligible=np.empty((D,N),dtype=bool)
 membership=None;reward=0.;left=1;threshold=0.;deadline=0.
 if focus is not None:membership,reward,left,threshold,deadline=focus
 args=[durations,idx,fiber,up,k,scores,factors,planner.weight,multiplier,missing,rr,rt,rd,ub,urgency,membership]
 assert all(a is None or a.flags.c_contiguous for a in args)
 lib.fine_values(ptr(durations),D,ptr(idx),N,ptr(fiber),planner.nfib,planner.n,
  ptr(up),ptr(k),ptr(scores),ptr(factors),ptr(planner.weight),ptr(multiplier),ptr(missing),ptr(rr),ptr(rt),ptr(rd),ptr(ub),ptr(urgency),ptr(membership),
  planner.req_threshold,planner.uniform_threshold,planner.req_penalty,safety,reward,left,threshold,deadline,
  ptr(value),ptr(cells),ptr(ecells),ptr(allowed),ptr(eligible),None,None)
 return value,cells,ecells,allowed,eligible if focus is not None else None

def max_cells(fibers,valid,value,allowed,eligible,nfib):
 C,N=fibers.shape
 fibers=np.ascontiguousarray(fibers,dtype=np.int32);valid=np.ascontiguousarray(valid,dtype=bool)
 value=np.ascontiguousarray(value);allowed=np.ascontiguousarray(allowed)
 eligible=None if eligible is None else np.ascontiguousarray(eligible)
 cells=np.empty((C,3,nfib));ecells=np.empty_like(cells)
 lib.coarse_cells(C,N,nfib,ptr(fibers),ptr(valid),ptr(value),ptr(allowed),ptr(eligible),ptr(cells),ptr(ecells))
 return cells,ecells


def fine_cells(planner,idx,fiber,durations,frame):
 up,k,scores,factors,multiplier,missing,rr,rt,rd,ub,urgency,safety,focus=frame
 D,N=len(durations),len(idx);shape=(D,3,planner.nfib)
 cells=np.empty(shape);ecells=np.empty(shape)
 winner=np.empty(shape,dtype=np.int64);ewinner=np.empty(shape,dtype=np.int64)
 membership=None;reward=0.;left=1;threshold=0.;deadline=0.
 if focus is not None:membership,reward,left,threshold,deadline=focus
 args=[durations,idx,fiber,up,k,scores,factors,planner.weight,multiplier,missing,rr,rt,rd,ub,urgency,membership]
 assert all(a is None or a.flags.c_contiguous for a in args)
 lib.fine_values(ptr(durations),D,ptr(idx),N,ptr(fiber),planner.nfib,planner.n,
  ptr(up),ptr(k),ptr(scores),ptr(factors),ptr(planner.weight),ptr(multiplier),ptr(missing),ptr(rr),ptr(rt),ptr(rd),ptr(ub),ptr(urgency),ptr(membership),
  planner.req_threshold,planner.uniform_threshold,planner.req_penalty,safety,reward,left,threshold,deadline,
  None,ptr(cells),ptr(ecells),None,None,ptr(winner),ptr(ewinner))
 return cells,ecells,winner,ewinner
