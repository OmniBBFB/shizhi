# 拾知

个人知识库，把视频讲义、学习笔记和字幕放在一个地方阅读。保留原有搜索、分 P、PDF.js 中文阅读、文本总结和材料下载功能。

从原「片刻书架」的 `web/` 抽取，使用 Python 标准库 MVC。程序与材料分开：仓库和镜像只装应用，`BV…` 文件夹是唯一内容来源，通过只读目录挂载；不包含视频生成、下载或转写工具，也没有数据库。

## 本地运行

Python 3.10+，无需 pip/npm 安装：

```sh
python3 -m web.controller --root /path/to/video-repository
# 浏览 http://127.0.0.1:8765
```

省略 `--root` 时使用 `SHIZHI_DATA_DIR`，未设置则使用本仓库的 `data/`。目录必须存在，空目录显示空书架。`--host` 默认 `127.0.0.1`，`--port` 默认 `8765`。

```sh
SHIZHI_DATA_DIR=/path/to/video-repository docker compose up -d --build
```

本地 Compose 仅绑定 `127.0.0.1:8765`。容器以 UID 10001 运行，挂载的材料需要该用户可读，目录需要可遍历；不要把材料打入镜像或提交到 Git。

## 导出阅读材料

```sh
python3 scripts/export_data.py \
  --source /path/to/video-repository \
  --output /tmp/shizhi-data.tar.gz
```

导出程序只读取每个 BV 目录及其 `P数字` 直接子目录中的 `metadata.json` 和阅读器允许的材料类型（PDF、文本、字幕、图片、TeX、ZIP）；不递归复制帧目录、音视频、脚本、缓存或符号链接。解压到材料目录后刷新页面即可读取。ZIP 若为已有讲义材料包会原样保留，包内内容不由导出程序筛选。

## 服务器 Docker + Nginx

目标站点：**https://kb.omnibbfb.top**。部署文件匹配服务器现有 `~/docker/main/` 布局和 `nginx_net` 网络：

```text
~/docker/main/
├── docker-compose.yml                 # 原有服务配置
├── compose.shizhi.yaml                # 来自 deploy/compose.server.yaml
├── shizhi/
│   ├── .env                          # SHIZHI_IMAGE=shizhi:20261027
│   └── data/BV…/                     # 独立持久化阅读材料
└── nginx/conf/kb.omnibbfb.top.conf     # 来自 deploy/ 同名文件
```

容器不发布宿主机端口，由现有 Nginx 通过 Docker 网络代理。服务器已有 `omnibbfb.top` 通配符证书，配置复用它。`kb.omnibbfb.top` 的 DNS A 记录指向 **123.56.248.107**；目前服务器没有 IPv6 入口，不添加 AAAA 记录。证书续期沿用现有服务器流程。

首次在本机构建镜像并传到服务器（`sss` 是 shell alias，下面写明等价 SSH 参数；`scp` 用大写 `-P` 设置非默认端口）：

```sh
docker build -t shizhi:20261027 .
docker save shizhi:20261027 | gzip > /tmp/shizhi-image.tar.gz
scp -o IdentitiesOnly=yes -i ~/.ssh/ecs_123_56_248_107_ed25519 \
  /tmp/shizhi-image.tar.gz /tmp/shizhi-data.tar.gz root@123.56.248.107:/tmp/
```

将 `deploy/compose.server.yaml` 和 Nginx 配置分别安装到上面目录，然后在服务器执行：

```sh
docker load -i /tmp/shizhi-image.tar.gz
cd ~/docker/main
mkdir -p shizhi/data
tar -xzf /tmp/shizhi-data.tar.gz -C shizhi/data
printf 'SHIZHI_IMAGE=shizhi:20261027\n' > shizhi/.env
docker compose --env-file shizhi/.env -f docker-compose.yml -f compose.shizhi.yaml up -d --no-deps shizhi
docker exec nginx nginx -t
docker exec nginx nginx -s reload
```

应用通过 `/healthz` 提供轻量存活检查，Docker 定期检查；它不代表材料内容完整性。`/api/videos` 用于验证目录发现结果。查看状态、日志和升级：

```sh
cd ~/docker/main
docker compose --env-file shizhi/.env -f docker-compose.yml -f compose.shizhi.yaml ps shizhi
docker logs --tail 100 shizhi
# 修改 shizhi/.env 的镜像标签，先 load/pull 对应镜像，再运行同一条 up 命令。
# 回滚：改回旧镜像标签并运行 up；材料目录独立保留。
```

更新材料时，将新导出包解压到 `shizhi/data/`，无需重建镜像。解压会覆盖同名文件，不删除源端已删除的文件；需要完全替换时先备份旧材料，再切换目录并重建容器挂载。

此版本没有用户账户和写入接口。按你的选择，当前站点免登录，知道地址的人可以阅读和下载。

## CI 与镜像发布

`.github/workflows/ci.yml` 在 push / PR 时执行 Python 3.10、3.13 测试、JavaScript 语法检查、镜像构建和容器 HTTP 冒烟测试。推送 `v*` 标签或手动运行 workflow 时，用 GitHub 内置的 `GITHUB_TOKEN` 发布到 `ghcr.io/<owner>/<repo>`，提供标签/提交哈希镜像，不需要服务器 SSH 密钥。

GitHub 仓库由你稍后创建。此处已初始化本地 Git，未配置远程或推送。建立远程后：

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
# 可选：用现有材料验证真实 PDF 阅读功能
CHROME_PATH=/path/to/chrome \
  PUPPETEER_MODULE=/path/to/puppeteer-core \
  TEST_BASE_URL=http://127.0.0.1:8765 node web/tests/pdf-reader.browser.mjs
```

- `web/model.py`：实时读取材料和校验文件路径。
- `web/controller.py`：只读 HTTP 路由、健康检查和 PDF Range 流。
- `web/view.py`、`web/static/`：页面和完整离线 PDF.js 资源。
- `scripts/export_data.py`：导出可部署材料。
- `deploy/`：现有服务器栈的 Compose 补充文件与 Nginx 站点。

PDF.js 为第三方 Apache-2.0 资源，许可证及来源保留于 `web/static/vendor/pdfjs/`。阅读器实现细节见 [web/README.md](web/README.md)。抽取不修改原始 `wdkns/web/`，已有本地入口继续可用。
