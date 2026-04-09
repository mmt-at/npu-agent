# npu-agent

从 `cu2tri` 的 `dev-npu` 分支拆出的独立 NPU 调度服务，主代码位于 `server/npu`。

快速启动：

```bash
python -m server.npu.main --npu-config server/npu/configs/npu_resources/aicc-06_npu_config.yml
```

当前机器默认策略：

- 如果未显式设置 `ASCEND_RT_VISIBLE_DEVICES`
- 且未通过 `--npus` 指定卡
- 且没有更窄的自定义配置

则服务默认只注册当前环境最后 4 张 NPU。在 `aicc-06` 上即 `4,5,6,7`。
