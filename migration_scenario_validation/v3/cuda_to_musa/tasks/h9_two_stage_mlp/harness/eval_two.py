#!/usr/bin/env python3
from __future__ import annotations
import argparse, importlib.util, json, sys
from pathlib import Path
import torch
import torch_musa  # noqa: F401

def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None: raise RuntimeError(f"cannot load {path}")
    m = importlib.util.module_from_spec(spec); sys.modules[name] = m; spec.loader.exec_module(m); return m

def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value, indent=2)+"\n")

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--input',required=True); ap.add_argument('--result',required=True); a=ap.parse_args()
    r={'compiled':False,'correctness':False,'performance':None,'hardware':'musa:0','cheating':False}
    try:
        ref=_load(Path.cwd()/'reference/fuse/two_stage_mlp.py','h9_ref'); sub=_load(Path(a.input),'h9_sub')
        torch.manual_seed(7101); rm=ref.Model(*ref.get_init_inputs()).to('musa')
        torch.manual_seed(7101); nm=sub.ModelNew(*ref.get_init_inputs()).to('musa')
        missing, unexpected = nm.load_state_dict(rm.state_dict(), strict=False)
        if missing or unexpected: raise RuntimeError(f'parameter container mismatch: missing={list(missing)} unexpected={list(unexpected)}')
        r['compiled']=True
        for i,scale in enumerate((0.2,0.5,1.0)):
            x=torch.randn(37,64,device='musa')*scale
            torch.musa.synchronize(); e=rm(x); torch.musa.synchronize(); y=nm(x); torch.musa.synchronize()
            if e.shape != y.shape or not torch.allclose(e,y,atol=1e-4,rtol=1e-4):
                d=(e-y).abs().max().item() if e.shape==y.shape else 'shape'
                raise RuntimeError(f'trial {i} mismatch: max_abs={d}')
        r['correctness']=True
    except Exception as exc:
        r['correctness_info']=f'{type(exc).__name__}: {exc}'; print(r['correctness_info'], file=sys.stderr)
    _write(Path(a.result), r); return 0

if __name__=='__main__': raise SystemExit(main())
