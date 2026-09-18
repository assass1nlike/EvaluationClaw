`native-scoring.tar.gz` 保存评分适配前的 `run.py`、`README.md` 和 `upstream/src/petri/` 下全部 Python 源码，包括 23 维定义、裁判提示词、评分解析及对话导出。对应 Petri `v0.1.0`，commit `4ba39bbcd494e7ef8ea949f2853fa00305e083e3`；不包含密钥或运行产物。

日常切换只需在运行命令中加入 `--scoring native`，直接使用保留的原生实现。

如需恢复适配前的文件，在 `baselines/` 下执行以下命令；解压会覆盖备份中同名文件：

```bash
(cd petri/backups && sha256sum -c native-scoring.sha256)
tar -xzf petri/backups/native-scoring.tar.gz -C petri
```
