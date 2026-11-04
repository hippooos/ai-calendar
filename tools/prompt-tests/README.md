# 模型评测与坏例回归

## 真实 Prompt 评测

`prompt_v3_test.py` 包含 27 个输入案例，直接导入 `backend/app/prompts/` 当前生产 Prompt。需要先安装后端依赖，并配置环境变量或 `backend/.env` 中的模型地址、名称、密钥。

在仓库根目录运行：

```powershell
.\backend\.venv\Scripts\python.exe tools/prompt-tests/prompt_v3_test.py --cases T01,T02
```

不带 `--cases` 会运行全部案例。评测调用配置的模型服务，消耗模型额度，并在 `results/` 生成输出记录。结果目录默认不提交，评测记录与所使用的模型、Prompt 版本关联。

该脚本检查模型原始输出的结构与语义。应用服务层的归一化、排程与交互流程由后端及前端自动化测试分别覆盖，两类测试用于评估不同层面的行为。

## 坏例固化

`capture_badcases.py` 从本地 SQLite 诊断记录提取模型失败输出，并写入后端的回归样本目录。已有样本和对应测试保留在仓库中。

在仓库根目录运行：

```powershell
.\backend\.venv\Scripts\python.exe tools/prompt-tests/capture_badcases.py
```

脚本内的替换规则只覆盖有限的已知词语，不是完整隐私检测器。提交新样本前应自行检查是否包含真实姓名、联系方式、私人日程或其他私密内容，再补充对应回归断言。日常启动应用不需要运行这个工具。
