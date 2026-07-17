# EvalClaw 远程 VM Provider 协议

本文描述 EvalClaw 如何在非本机环境创建一次性 VM、注入任务状态并连接桌面控制 bridge。

## 组件边界

EvalClaw 负责：

- 生成任务、baseline checks 和 evaluation checks。
- 把任务文件与 provisioning 构造成 NoCloud config-drive ISO。
- 根据任务要求解析 Provider 镜像。
- 驱动 target agent，并保存执行轨迹和评分结果。

VM Provider 负责：

- 管理镜像清单和虚拟化平台凭证。
- 接收并保存 config-drive。
- 创建、启动、隔离和销毁 VM。
- 把 config-drive 挂载到 VM 后再启动。
- 等待 guest desktop bridge 就绪，并返回受保护的 bridge 地址。

任务 JSON 不得包含 Provider 密钥、云账号凭证或 bridge 管理凭证。

## Provider v2 能力发现

### `GET /health`

返回 Provider 基本健康状态。旧 Provider 只实现该端点也可以继续使用同步 v1 协议。

### `GET /capabilities`

推荐响应：

```json
{
  "protocol_version": "evalclaw.vm_provider.v2",
  "features": [
    "image_inventory",
    "config_drive_upload",
    "async_create"
  ],
  "images": [
    {
      "id": "windows-11-evalclaw-v2",
      "digest": "sha256:...",
      "guest_os": "windows",
      "architecture": "x86_64",
      "capabilities": [
        "desktop_bridge",
        "cloudbase_init_nocloud",
        "powershell"
      ],
      "default": true,
      "priority": 100,
      "enabled": true
    }
  ]
}
```

只有明确返回 `protocol_version: "evalclaw.vm_provider.v2"`（也接受 `2` 或 `v2`）时，
EvalClaw 才启用 v2 的上传、镜像解析和异步创建行为。仅仅存在该端点但没有协议版本，
不会改变旧 Provider 的请求格式。

EvalClaw 会按以下条件筛选镜像：

1. 镜像处于 enabled 状态。
2. guest OS 和 architecture 匹配。
3. 镜像 capabilities 覆盖任务的全部 required_capabilities。
4. 如果用户固定了 image/template，则候选镜像还必须匹配该标识或 alias。
5. 多个候选按 default、priority、id 的稳定顺序选择。

如果 Provider 不公开镜像清单，但能自行解析要求，可以声明 `server_side_image_resolution`。

## Config-drive 上传

Provider v2 需要声明 `config_drive_upload`，然后实现：

### `POST /artifacts/config-drives`

请求为 multipart：

- `file`: ISO 文件。
- `sha256`: EvalClaw 计算的 SHA-256。
- `size`: 文件字节数。
- `lifecycle`: 当前固定为 `vm_scoped`。
- `Idempotency-Key`: `config-drive-{sha256}`。

响应：

```json
{
  "artifact_id": "artifact-123",
  "url": "https://provider.example/artifacts/artifact-123",
  "sha256": "..."
}
```

Provider 返回的 SHA-256 如果与本地不一致，EvalClaw 会在创建 VM 前 fail-closed。
本地 config-drive 路径不存在或不可读时同样 fail-closed，不会把无效的本机路径发送给远程 Provider。

Provider 可以把上传内容保存在本地、S3、MinIO、Azure Blob 或其它对象存储中，但返回给 EvalClaw 的 artifact_id/URL 必须能被后续 VM 创建流程解析。`vm_scoped` artifact 应在 VM 删除或 TTL 到期时清理。

## 创建 VM

### `POST /vms`

v2 请求：

```json
{
  "protocol_version": "evalclaw.vm_provider.v2",
  "request_id": "vm-...",
  "vm": {
    "guest_os": "windows",
    "image": "windows-11-evalclaw-v2",
    "resolved_image": {
      "id": "windows-11-evalclaw-v2",
      "digest": "sha256:..."
    },
    "config_drive": {
      "artifact_id": "artifact-123",
      "url": "https://provider.example/artifacts/artifact-123",
      "sha256": "...",
      "size": 419840,
      "media_type": "application/x-iso9660-image",
      "lifecycle": "vm_scoped"
    }
  },
  "session": {
    "application": "Windows Desktop",
    "baseline_checks": []
  }
}
```

请求带有 `Idempotency-Key: {request_id}`。Provider 应把同一个 key 的重试映射到同一个创建操作。

同步 Provider 可以直接返回：

```json
{
  "vm_id": "vm-123",
  "bridge_url": "https://provider.example/vms/vm-123/bridge",
  "bridge_api_key": "short-lived-token",
  "resolved_image": {
    "id": "windows-11-evalclaw-v2",
    "digest": "sha256:..."
  }
}
```

长时间创建应返回 HTTP 202：

```json
{
  "operation_id": "operation-123",
  "status": "creating",
  "status_url": "/operations/operation-123"
}
```

## 异步状态

### `GET /operations/{operation_id}`

进行中状态包括 `pending`、`queued`、`creating`、`starting` 和 `provisioning`。

成功响应：

```json
{
  "status": "ready",
  "vm_id": "vm-123",
  "bridge_url": "https://provider.example/vms/vm-123/bridge",
  "bridge_api_key": "short-lived-token"
}
```

失败状态包括 `failed`、`error`、`cancelled`。EvalClaw 只允许轮询同一 Provider origin 的 URL，防止 bearer token 被发送到其它主机。

## 删除 VM

### `DELETE /vms/{vm_id}`

删除操作应同时清理：

- VM 或写时复制磁盘。
- NAT、代理路由和临时防火墙规则。
- vm_scoped config-drive artifact。
- bridge 短期凭证。
- 与该 VM 绑定的临时密钥和会话。

## Guest Golden Image

Windows 基础镜像至少需要：

- Cloudbase-Init，并启用 NoCloud service。
- PowerShell。
- EvalClaw desktop bridge，默认 guest 端口 7766。
- 自动启动的 bridge 健康服务。
- 能读取挂载 config-drive 并在 bridge 暴露 session 前完成 provisioning。

Linux 基础镜像至少需要：

- cloud-init NoCloud。
- EvalClaw desktop bridge。
- 与任务声明一致的桌面和 shell 能力。

镜像构建版本和 digest 应进入 Provider inventory。任务特定故障不得固化进通用 Golden Image，应由每次运行的 config-drive 构造。

## Desktop Bridge

Provider 返回的 bridge 必须实现：

- `GET /health`
- `POST /sessions`
- `POST /sessions/{session_id}/actions`
- `POST /sessions/{session_id}/evaluate`
- `DELETE /sessions/{session_id}`

当 session 包含 baseline checks 时，bridge 必须在 target 获得控制权之前执行它们，并且只有全部成功时才返回 `baseline_verified=true`。

建议由 Provider 提供反向代理 URL，而不是直接暴露 guest 端口。bridge token 应短期有效、只绑定单个 VM，并且不得写入 benchmark task metadata。EvalClaw 的运行记录会保留脱敏后的 Provider、resolved image 和 config-drive provenance，不保存 bridge token。

## 兼容性

没有 `/capabilities` 的 Provider 按旧同步协议运行，`POST /vms` 仍接收 `{vm, session}`。该模式只能在 Provider 与 EvalClaw 共享 config-drive 文件系统，或 Provider 不需要本地 config-drive 时安全使用。

新建远程 Provider 应实现 v2。只要 Provider 声明 v2 能力，任务包含本地 config-drive 而 Provider未声明 `config_drive_upload`，EvalClaw 就会 fail-closed。
