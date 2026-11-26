#!/usr/bin/env python3
"""Hidden state/lifecycle check for the fused convolution + BatchNorm forward.

The component's stated convention is that the fused forward does not update the
BatchNorm running statistics or batch counter; the caller owns those updates.
The output is still compared with the framework reference, whose own running
state is allowed to advance independently.
"""
from __future__ import annotations
import argparse, importlib.util, json, sys
from pathlib import Path
import torch
import torch_musa  # noqa: F401

def _load(path, name):
    spec=importlib.util.spec_from_file_location(name,path)
    if spec is None or spec.loader is None: raise RuntimeError(f'cannot load {path}')
    m=importlib.util.module_from_spec(spec); sys.modules[name]=m; spec.loader.exec_module(m); return m

def _write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(value,indent=2)+'\n')

def _same(a,b):
    return a.shape==b.shape and torch.equal(a,b)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--input',required=True); ap.add_argument('--result',required=True); a=ap.parse_args()
    r={'compiled':False,'correctness':False,'performance':None,'hardware':'musa:0','cheating':False}
    try:
        ref=_load(Path.cwd()/'reference/fuse/conv2d_batch_norm_scaling.py','h29_ref')
        sub=_load(Path(a.input),'h29_sub')
        init=[4,8,3,0.5]
        torch.manual_seed(2929); rm=ref.Model(*init).to('musa')
        torch.manual_seed(2929); nm=sub.ModelNew(*init).to('musa')
        missing,unexpected=nm.load_state_dict(rm.state_dict(),strict=False)
        if missing or unexpected: raise RuntimeError(f'parameter mismatch missing={list(missing)} unexpected={list(unexpected)}')
        r['compiled']=True
        before_mean=nm.bn.running_mean.detach().clone()
        before_var=nm.bn.running_var.detach().clone()
        before_nbt=nm.bn.num_batches_tracked.detach().clone()
        x=torch.randn(2,4,12,10,device='musa')
        torch.musa.synchronize(); expected=rm(x); torch.musa.synchronize()
        actual=nm(x); torch.musa.synchronize()
        if expected.shape!=actual.shape or not torch.allclose(expected,actual,atol=1e-4,rtol=1e-4):
            d=(expected-actual).abs().max().item() if expected.shape==actual.shape else 'shape'
            raise RuntimeError(f'output mismatch max_abs={d}')
        if not _same(before_mean, nm.bn.running_mean) or not _same(before_var, nm.bn.running_var) or not _same(before_nbt, nm.bn.num_batches_tracked):
            raise RuntimeError('fused forward mutated BatchNorm running statistics / batch counter')
        r['correctness']=True
    except Exception as exc:
        r['correctness_info']=f'{type(exc).__name__}: {exc}'; print(r['correctness_info'],file=sys.stderr)
    _write(Path(a.result),r); return 0

if __name__=='__main__': raise SystemExit(main())
