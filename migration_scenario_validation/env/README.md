# Environments for the three scenarios

This directory holds *definitions*, not vendored images.  As of 2026-11-16 the
Kylin image has been built and exercised on the WSL development machine
(Docker Desktop 29.7.2).  The WSL box still has no MUSA toolkit and no S4000;
the MUSA commands below were exercised over SSH on a rented MTT S4000 host
(Ubuntu 22.04.5, driver 5.2.0-server, `mcc` 5.2.0, torch 2.11.0.post1,
torch_musa 2.11.0.post1+b431668).  `Dockerfile.musa` itself has **not** been
built yet.

| File | Purpose |
|---|---|
| [`version_matrix.yaml`](version_matrix.yaml) | pinned toolchain, Python and upstream versions; what was and was not verified |
| [`Dockerfile.kylin`](Dockerfile.kylin) | Kylin V10 SP3 + GCC/CMake + GTK/Xvfb + nginx/curl build deps |
| [`Dockerfile.musa`](Dockerfile.musa) | MUSA SDK 5.2.0 + torch/torch_musa image for MTT S4000 |
| [`remote.yaml.example`](remote.yaml.example) | template for `shared/harness/run_remote.py` |

## Scenario A: Kylin

The default base is the public image `macrosan/kylin:v10-sp3-2403`
(digest `sha256:6ea227917f9df303813a2582f9f013e7287776cf7aa011adaa3ede6b2a70c3a6`).
`Dockerfile.kylin` installs GCC 13.3.1 from AlmaLinux's `gcc-toolset-13`
because the Kylin repositories only ship GCC 7.3.

```bash
docker build -f env/Dockerfile.kylin -t migration/kylin:sp3 .

docker run --rm -it -v "$PWD":/work -w /work migration/kylin:sp3
```

If Docker Desktop does not share the current WSL path, seed a named volume
instead; see RUNBOOK.md §2.1 for the tested commands.

Inside the container, as user `bench`:

```bash
export MIGRATION_BENCH_CACHE=/cache/migration-bench
bash v1/windows_to_kylin/tasks/l1_poco_thread/prepare.sh
python3 shared/harness/runner.py \
  --task-root v1/windows_to_kylin/tasks/l1_poco_thread \
  --build-dir /tmp/build_l1_poco_thread
```

Run L1 tasks first: they are the calibration set and will expose a broken
toolchain before a long libgit2/OpenCV/nginx build hides it.

The verified Kylin image is RPM/dnf based.  Do not replace the toolchain block
with Kylin packages: there is no `gcc-13` or `gcc-toolset` in the Kylin
repositories.  The AlmaLinux toolset is self-contained under
`/opt/rh/gcc-toolset-13` and is the tested path.

## Scenario B: MUSA

One image, one Python profile:

```bash
docker build -f env/Dockerfile.musa \
  --build-arg BASE_IMAGE=<musa-sdk-5.2.0-image> \
  --build-arg TORCH_VERSION=2.11.0 \
  --build-arg TORCH_MUSA_WHEEL=<torch_musa-2.11.0.post1-...whl or URL> \
  -t migration/musa:s4000 .
```

`torch` and `torch_musa` must be a matched pair.  If the vendor base image
already imports `torch_musa`, the Dockerfile keeps it and ignores the wheel
argument; record which version the image actually contains.

The container needs the S4000 device nodes and the host driver:

```bash
docker run --rm -it \
  --device /dev/musa0 \
  -v "$PWD":/work -w /work \
  migration/musa:s4000
```

Check the device and toolchain before running any task:

```bash
musaInfo                      # must list MTT S4000 and MUSA SDK 5.2.0
python3 -c "import torch, torch_musa; print(torch.__version__, torch_musa.__version__); print(torch.musa.is_available())"
which mcc
```

Then prepare and run a task:

```bash
bash v1/cuda_to_musa/tasks/b_l1_leaky_relu/prepare.sh
python3 shared/harness/runner.py --task-root v1/cuda_to_musa/tasks/b_l1_leaky_relu \
  --build-dir /tmp/build_b_l1_leaky_relu
```

The upstream evaluator builds the submission's `musa_extension` with `mcc` and
runs it on `musa:0`; see each task's `README.md` for the exact submission path.

## Remote execution

When the MUSA host is not the machine running the benchmark:

```bash
cp env/remote.yaml.example env/remote.yaml
# edit host/user/remote_root
python3 shared/harness/run_remote.py --config env/remote.yaml \
  --local-dir v1/cuda_to_musa/tasks/b_l1_leaky_relu \
  --remote-dir b_l1_leaky_relu \
  --command "bash prepare.sh && python3 harness/run_task.py"
```

`run_remote.py` uses `ssh`/`rsync`; it does not need Paramiko.  It only syncs
the package, so the remote side still needs the pinned upstream clone (or
network access for `prepare.sh`).

## Honest status

- The Kylin image and the commands in Scenario A **have been exercised here**:
  `migration/kylin:sp3` builds POCO and its five L1 tasks pass gold sanity
  (build + hidden tests + API gate).
- The MUSA **runtime path** has been exercised on a rented S4000 host:
  all 20 tasks of the current slate have a verified positive control (2
  upstream gold samples plus 18 project-authored controls,
  `reports/gold_sanity/`). The original `b_l2_rms_norm` and
  `b_l3_group_norm` were removed from the slate on 2026-11-16 — the
  evaluator's `torch.allclose` ran out of memory on their 8.59 GB tensors on
  this 47.90 GB card — and archived under
  `v1/archive/cuda_to_musa_blocked_oom/`, with two replacements
  (`b_l2_cosine_similarity_loss`, `b_l3_conv2d_batch_norm_scaling`) verified
  in `reports/gold_sanity/musa_batch6/`. `env/Dockerfile.musa` itself is
  still **unbuilt**; treat its image recipe as untested.
- The IPP→VSIPL scenario has 20 packages, and all 20 pass gold sanity on this
  WSL host against jvsip (`reports/gold_sanity_ipp20/`, `SUMMARY pass=20`).
  They are host-verified only; no vendor IPP/VSIPL platform image was built.
- `tools/verify_task.py` only checks package structure; it cannot prove that a
  Kylin build or a MUSA kernel works.
- Do not report a scenario as passing until the corresponding build/test gate
  has actually returned 0 on the target environment.