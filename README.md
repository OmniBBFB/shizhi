# 拾知

个人知识库，把视频讲义、学习笔记和字幕放在一个地方阅读。保留原有搜索、分 P、PDF.js 中文阅读、文本总结和材料下载功能。

从原「片刻书架」的 `web/` 抽取，使用 Python 标准库 MVC。程序与材料分开：仓库和镜像只装应用，`BV…` 和 `kb-…` 资料集文件夹是唯一内容来源，通过独立读写目录挂载；不包含视频生成、下载或转写工具，也没有数据库。网页上传通过独立口令保护，阅读与下载无需登录。

## 本地运行

Python 3.10+，无需 pip/npm 安装：

```sh
python3 -m web.controller --root /path/to/video-repository
# 浏览 http://127.0.0.1:8765
```

省略 `--root` 时使用 `SHIZHI_DATA_DIR`，未设置则使用本仓库的 `data/`。目录必须存在，空目录显示空书架。`--host` 默认 `127.0.0.1`，`--port` 默认 `8765`。

```sh
cp .env.example .env
# 将 .env 中的 SHIZHI_UPLOAD_TOKEN 设置为足够长的随机口令；空值会禁用上传。
SHIZHI_DATA_DIR=/path/to/video-repository docker compose up -d --build
```

本地 Compose 仅绑定 `127.0.0.1:8765`。容器以 UID 10001 运行，挂载的材料需要该用户可读写，目录需要可遍历（Linux 可用 `sudo chown -R 10001:10001 /path/to/materials` 设置专用材料目录）；不要把材料打入镜像或提交到 Git。

## 导出阅读材料

```sh
python3 scripts/export_data.py \
  --source /path/to/video-repository \
  --output /tmp/shizhi-data.tar.gz
```

导出程序只读取每个 BV 或 `kb-…` 目录及其 `P数字` 直接子目录中的 `metadata.json` 和阅读器允许的材料类型（PDF、文本、字幕、图片、TeX、ZIP）；不递归复制帧目录、音视频、脚本、缓存或符号链接。解压到材料目录后刷新页面即可读取。ZIP 若为已有讲义材料包会原样保留，包内内容不由导出程序筛选。

## 服务器 Docker + Nginx

站点：**https://kb.omnibbfb.top**。服务器已将拾知并入 `~/docker/main/` 的现有服务栈，统一使用主 Compose 和 Nginx：

```text
~/docker/main/
├── docker-compose.yml                  # nginx、shizhi 及其他现有服务
├── .env                                # SHIZHI_IMAGE 等全局配置（权限 600）
├── shizhi/
│   ├── .env                            # 仅上传口令 SHIZHI_UPLOAD_TOKEN（权限 600）
│   └── data/BV…/ 或 kb-…/              # 独立持久化阅读材料
└── nginx/conf/omnibbfb.top.conf          # 已包含 kb.omnibbfb.top 的 HTTP/HTTPS server
```

`deploy/compose.server.yaml` 是供合并到主 `docker-compose.yml` 的服务片段；`deploy/kb.omnibbfb.top.conf` 是供合并到现有 `nginx/conf/omnibbfb.top.conf` 的站点片段。服务器已归档原 `compose.shizhi.yaml` 和独立站点文件，日常管理使用同一个入口：

```sh
cd ~/docker/main
docker compose config --services
docker compose ps
docker compose up -d --no-deps shizhi
docker compose logs --tail 100 shizhi
docker compose restart shizhi
```

根目录 `.env` 负责选择拾知镜像，`shizhi/.env` 通过服务的 `env_file` 提供上传口令。无需额外指定 `-f` 或 `--env-file`。容器以原有 `nginx_net` 网络连接共享 Nginx，材料挂载仍为 `./shizhi/data:/data`，容器仅向网络内暴露 8765。

服务器已有 `*.omnibbfb.top` 通配符证书，复用 `/etc/letsencrypt/live/omnibbfb.top-0002/`。DNS A 记录指向 **123.56.248.107**，证书续期沿用现有流程。

构建镜像并传到服务器（以下标签只是示例，升级时使用新的唯一标签）：

```sh
docker build -t shizhi:20261029-pdf-fonts .
docker save shizhi:20261029-pdf-fonts | gzip > /tmp/shizhi-image.tar.gz
scp -o IdentitiesOnly=yes -i ~/.ssh/ecs_123_56_248_107_ed25519 \
  /tmp/shizhi-image.tar.gz root@123.56.248.107:/tmp/
```

服务器加载新镜像后，修改 `~/docker/main/.env` 中的 `SHIZHI_IMAGE` 再更新服务：

```sh
cd ~/docker/main
docker load -i /tmp/shizhi-image.tar.gz
# 修改根目录 .env 中的 SHIZHI_IMAGE=新镜像标签。
docker compose config --quiet
docker compose up -d --no-deps shizhi
```

回滚时将根目录 `.env` 的镜像标签改回旧值，再执行同一条 `up` 命令。`/healthz` 提供轻量存活检查，`/api/videos` 可检查材料目录。调整主 Nginx 配置后执行：

```sh
docker compose exec nginx nginx -t
docker compose exec nginx nginx -s reload
```

材料需要初次导入时，将导出包解压到 `shizhi/data/`，执行 `chown -R 10001:10001 shizhi/data`；日常更新通过 SCP 或网页上传，无需重建镜像。解压会覆盖同名文件，不删除源端已删除的文件；先保留备份，避免用旧快照覆盖新的上传。

阅读和下载免登录；网页写入需要上传口令。口令不进入 URL、Git、镜像或浏览器持久存储。

## 网页上传与 SCP

上传页：**https://kb.omnibbfb.top/upload**。选择已有资料集，或填写新资料集名称；支持多文件和选填讲次（例如 `P01`）。填写上传口令后提交。单文件上限 **128 MB**，同名文件返回冲突并保留原文件；传输中断时清理临时文件，完整写入后才出现在目录中。ZIP 保留为下载材料，不自动解压。口令未配置时上传返回 503，阅读仍正常。

首次部署已生成随机口令，保存在本机 `~/app/shizhi/.env` 和服务器 `~/docker/main/shizhi/.env`，均为权限 600，且被 Git 忽略。轮换口令：修改服务器 `~/docker/main/shizhi/.env` 中的 `SHIZHI_UPLOAD_TOKEN`，再运行 `docker compose up -d --no-deps shizhi` 重新创建服务；同时更新本机口令备份。

网页新建的资料集使用 `kb-<随机标识>/metadata.json`，名称保存在该文件。现有 BV 目录继续支持原有元数据和分 P。SCP 可以直接放入现有资料集：

```sh
scp -o IdentitiesOnly=yes -i ~/.ssh/ecs_123_56_248_107_ed25519 \
  ./新笔记.pdf root@123.56.248.107:/root/docker/main/shizhi/data/BV144nc6KEA4/
```

也可以新建通用资料集 `kb-my-notes/`（以 `kb-` 开头，后接字母、数字、下划线或短横线），直接上传 PDF/Markdown；无元数据时使用目录名展示。若通过 root/SCP 新建目录，完成后执行 `chown -R 10001:10001 ~/docker/main/shizhi/data/kb-my-notes`，使网页端可以继续向其中上传。刷新网页即可看到新文件。

这两种方式写入同一宿主机目录；更新程序、重建镜像或重建容器不会删除材料。不要在有新上传后用旧快照覆盖整个目录；备份请同时保存材料目录和口令配置。

## 页面与 PDF 加载性能

目录列表每次请求仍实时扫描文件；体积较大的 `metadata.json` 只在文件标识、大小或纳秒修改时间发生变化时重新解析，并且仅在进程内保留标题、作者和分 P 名称。服务启动时预热这些显示字段，没有持久索引，SCP 或网页上传的新材料仍立即可见。

静态资源和阅读材料提供 ETag、Last-Modified 与重新验证缓存，未变更时返回 304，无需重传文件；变更后会获取新内容。HTML/API 不缓存。服务器 Nginx 对 JavaScript、CSS、JSON 等开启 gzip；PDF 保持原始字节和 Range 读取，避免影响分段加载。

## CI 与镜像发布

`.github/workflows/ci.yml` 在 push / PR 时执行 Python 3.10、3.13 测试、JavaScript 语法检查、Chrome 嵌入字体回归检查、镜像构建和容器 HTTP 冒烟测试。字体检查主动模拟浏览器缺少新 JavaScript API 的情况，避免 PDF.js 升级后出现字体替换。推送 `v*` 标签或手动运行 workflow 时，用 GitHub 内置的 `GITHUB_TOKEN` 发布到 `ghcr.io/<owner>/<repo>`，提供标签/提交哈希镜像，不需要服务器 SSH 密钥。

GitHub 远程由你自行管理。若尚未配置远程，可按下列方式建立；已有 `origin` 时直接推送即可：

```sh
git remote add origin git@github.com:<owner>/<repo>.git
git push -u origin main
git tag v0.1.0
git push origin v0.1.0
```

新 GHCR 包默认可见性由 GitHub 设置决定。服务器使用私有镜像时先 `docker login ghcr.io`，或使用上述离线传镜像方式。CI 不会自动部署服务器。

## 检查与结构

```sh
python3 -m unittest discover -s web/tests -v
python3 -m unittest discover -s tests -v
node --check web/static/pdf-reader.mjs
node --check web/static/upload.js
# 可选：用现有材料验证真实 PDF 阅读功能
CHROME_PATH=/path/to/chrome \
  PUPPETEER_MODULE=/path/to/puppeteer-core \
  TEST_BASE_URL=http://127.0.0.1:8765 node web/tests/pdf-reader.browser.mjs
```

- `web/model.py`：实时读取材料和校验文件路径。
- `web/controller.py`：阅读路由、上传鉴权、健康检查和 PDF Range 流。
- `web/uploads.py`：挂载目录中的受限上传、完整文件发布与同名保护。
- `web/view.py`、`web/static/`：页面和完整离线 PDF.js 资源。
- `scripts/export_data.py`：导出可部署材料。
- `deploy/`：供合并进服务器主配置的 Compose/Nginx 片段，以及当前部署与性能记录。

PDF.js 为第三方 Apache-2.0 资源，许可证及来源保留于 `web/static/vendor/pdfjs/`。阅读器实现细节见 [web/README.md](web/README.md)。抽取不修改原始 `wdkns/web/`，已有本地入口继续可用。
