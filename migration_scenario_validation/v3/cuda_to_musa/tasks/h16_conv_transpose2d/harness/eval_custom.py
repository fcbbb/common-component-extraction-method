
#!/usr/bin/env python3
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

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--input',required=True); ap.add_argument('--result',required=True); a=ap.parse_args()
    r={'compiled':False,'correctness':False,'performance':None,'hardware':'musa:0','cheating':False}
    try:
        ref=_load(Path.cwd()/'reference/model.py','ref_model')
        sub=_load(Path(a.input),'sub_model')
        torch.manual_seed(4242)
        rm=ref.Model().to('musa'); torch.manual_seed(4242); nm=sub.ModelNew().to('musa')
        inputs=[x.to('musa') for x in ref.get_inputs()]
        r['compiled']=True
        expected=rm(*inputs); actual=nm(*[x.clone() for x in inputs]); torch.musa.synchronize()
        if expected.shape!=actual.shape or not torch.allclose(expected,actual,atol=1e-4,rtol=1e-4):
            d=(expected-actual).abs().max().item() if expected.shape==actual.shape else 'shape'
            raise RuntimeError(f'output mismatch max_abs={d}')
        r['correctness']=True
    except Exception as exc:
        r['correctness_info']=f'{type(exc).__name__}: {exc}'; print(r['correctness_info'],file=sys.stderr)
    _write(Path(a.result),r); return 0

if __name__=='__main__': raise SystemExit(main())
