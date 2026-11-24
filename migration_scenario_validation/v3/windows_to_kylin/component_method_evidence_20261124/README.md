# 组件方法证据目录（2026-11-24）

本目录是 `windows_to_kylin_v3` 上“组件检索（method）”与“直接迁移（default）”的 20 题配对分析，包含数据、案例摘录和报告。

## 先看

- **[REPORT.md](REPORT.md)** — 结果报告：20 题分类、总体统计、典型案例、威胁与限制。

## 一句话结论

三个合成题（fs / spawn / thread）是干净证据：method PASS、default 在组件 README 派生的深层检查上 FAIL。20 题子集上 method 11 PASS vs default 8 PASS，严格 method-win 4 个；计入全部 23 对后为 11:10、区分题 4:3，因此不能表述为“20 个 method-win”。

## 目录

```
.
├── REPORT.md                 # 主报告
├── build_dataset.py          # 数据生成脚本（只读 reports/bench）
├── data/
│   ├── results_long.csv      # 40 行：20 题 × 2 臂
│   ├── results_wide.csv      # 20 行：每题一行
│   ├── results.json          # 汇总 + 宽表 + 长表
│   ├── summary.json          # 计数与实验配置
│   └── sources/              # 原始 summary / attempt / selection 副本
└── cases/                    # 8 个典型案例的判分日志尾部
```

## 口径提醒

1. 20 题是筛选子集：排除了 3 个 method 明显错误的 ERROR（`v2_path`、`v2_shared_library`、`v2_curl_build`）。
2. 第 20 个 `negative_win32_eventlog` 是负向对照：method 检索判断正确，但流程按 ERROR 中止，不计 PASS。
3. `l2_opencv_highgui` 的 default 失败含环境因素（网络下载、numpy、超时），是弱证据。
4. `v2_nginx_full` 的 method 只有 batch rc=1，没有 attempt.json。

## 重新生成

```bash
cd /home/fcbbbb/projects/demo_common_exreaction/common-component-extraction-method/repository/migration_scenario_validation
python3 -I v3/windows_to_kylin/component_method_evidence_20261124/build_dataset.py
```

脚本只读 `reports/bench/`，不会修改既有结果。