# 拾知自动发布

`main` 推送后：Python 3.10 / 3.13 业务与部署测试、JavaScript 语法检查、Chrome 嵌入字体回归、Compose 校验、生产镜像的阅读与上传隔离检查，通过后发布 GHCR，再自动更新现有 `shizhi` 服务。PR 只检查；`v*` 标签仍可发布版本镜像，自动部署仅限 main。

线上地址为 https://shizhi.omnibbfb.top ，旧 `kb.omnibbfb.top` 跳转至此。公网验收直接检查新域名的 `ok` 响应与实际目录 JSON，避免把跳转页面当作健康结果。

## 权限与入口

- 镜像：`ghcr.io/omnibbfb/shizhi:sha-<commit>`；GHCR 摘要记录在发布回执中，服务器按同一镜像的不可变 `sha256:` image ID 运行，不使用可变 latest。
- 仓库变量：`SHIZHI_AUTO_DEPLOY=true`。设为 `false` 可暂停更新，不影响 CI 检查和镜像发布。
- `production` 环境：secrets 为 `SHIZHI_DEPLOY_SSH_KEY`、`SHIZHI_DEPLOY_KNOWN_HOSTS`，变量为 `SHIZHI_DEPLOY_HOST`。
- 独立 Ed25519 部署 key，仅允许服务器固定命令 `python3 /root/docker/main/shizhi/deploy/remote-release.py`，带 `restrict`，不允许 shell、PTY 或转发。入口只接受 `deploy` 和本仓库固定摘要镜像。
- GHCR 发布使用 CI job 的临时 `GITHUB_TOKEN`。已测试镜像同时以无标签 Docker archive 保存为当前运行的短期 artifact，经专用 SSH 通道传送；服务器不保存或接收注册表 token。下载 artifact 使用 [GitHub 官方 actions](https://github.com/actions/download-artifact)。
- 镜像传输先发送有长度上限的 JSON 头，再传 gzip archive；服务器核对大小（最多 512 MiB）、完整文件 SHA-256、唯一且无标签的镜像清单、配置摘要及 Shizhi 来源标签，再导入镜像。不会覆盖其他项目镜像标签。

管理员首次安装入口与专用公钥、配置上述环境后，日常只需提交代码并执行 `git push origin main`。[查看流水线](https://github.com/OmniBBFB/shizhi/actions/workflows/ci.yml)。部署私钥及本机验收记录位于被忽略的 `.local/`。

## 发布顺序

1. 获取项目发布锁及共享栈的发布锁，和游戏站、BBNS 串行发布；仅更新拾知。
2. 接收并验证 CI 中的同一镜像，再以不可变 image ID 导入。使用 SSH 保活，避免空闲连接中断；不依赖服务器的 GHCR 层下载路径。通过容器内 procfs 检测打开的 `.upload-` 临时文件，等待现有上传空闲，最长 10 分钟。超时保留原服务。
3. 停止拾知，保存主 `.env`、Compose、上传口令配置和完整材料目录，备份位于 `shizhi/backups/cicd-<timestamp>`。备份目录权限 700，保留材料所有者与权限。
4. 用新镜像在无网络、只读的材料快照上构建目录，验证实际资料可以读取；不执行生产上传。
5. 原子替换主 `.env` 的 **SHIZHI_IMAGE 一项**。核对其他服务配置完全相同，仅执行 `docker compose up -d --no-deps shizhi`，再检查容器和公开 HTTPS。Nginx、上传口令、材料挂载位置均沿用现有配置。
6. 失败时恢复原镜像并重启服务，保留现有材料；不会用旧备份覆盖新的上传。

部署入口本身或 Nginx 的修改需管理员维护通道重新安装；常规流水线只发布应用镜像。`deploy/deployment.json`、`deploy/pdf-fonts.json` 是此前人工上线的验收快照，当前发布以服务器 `shizhi/deploy/release.json` 和 Actions 为准。

## 保留的字体修复

此前已上线的 PDF.js 6.4.299 legacy 主模块与 worker 已纳入 Git，原材料和资源 URL 保持。`pdf-fonts` 为镜像构建的必需前置检查，使用仓库内的嵌入字体 PDF，主动移除 worker 的 `Math.sumPrecise`，确认字体仍成功加载，避免自动发布回退字体兼容性。

## 本地检查

```sh
python3 -m unittest discover -s web/tests -v
python3 -m unittest discover -s tests -v
python3 tools/check-compose.py
docker build -t shizhi:ci .
python3 tools/check-image.py shizhi:ci
```

容器检查使用 tmpfs 合成材料和临时测试口令，不接触真实材料。字体检查方法见 [web/README.md](../web/README.md)。
