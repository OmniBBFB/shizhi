# 拾知

此目录为从片刻书架抽取的 MVC 阅读应用。完整运行与部署说明见 [根目录 README](../README.md)。

从仓库根目录启动，无需安装依赖（Python 3.10+）：

```sh
python3 -m web.controller --root /path/to/video-repository
```

浏览器访问 http://127.0.0.1:8765 。停止服务按 Ctrl+C。

```sh
python3 -m web.controller --port 9000 --root /path/to/video-repository
python3 -m unittest discover -s web/tests -v
```

## MVC 与唯一事实来源

- `model.py`：每次请求读取根目录下 `BV` 加 10 位字母数字的目录及 `kb-…` 通用资料集，读取 `metadata.json`、封面和本层材料，并发现 `P数字` 子目录。没有数据库、静态内容副本或持久索引。
- `controller.py`：处理书架查询、分 P、阅读标签、JSON 目录接口和文件流。默认仅监听本机；提供受口令保护的材料上传，不提供删除或执行脚本的功能。
- `view.py`：服务端 HTML 视图，文本转义后展示；CSS 和少量渐进增强脚本位于 `static/`。关闭 JavaScript 仍可搜索和阅读文本，并直接打开或下载 PDF。

`GET /` 是书架；`?q=关键词&kind=pdf` 筛选材料；`?video=BV…&part=P01&tab=pdf|text|transcript|files` 打开讲次。`doc=文件名` 选择 PDF 或文本，所有选择保存在 URL。`GET /api/videos` 返回实时目录。`GET /upload` 是网页上传页；`POST /api/collections` 和 `POST /api/uploads` 需要 Bearer 上传口令，详见根目录 README。

目录中的 PDF 通过本地部署的 PDF.js 6.4.299 渲染，沿用现有 Range 文件接口。阅读器提供上一页、下一页、页码跳转、适合宽度、固定比例缩放，以及文字选择复制。聚焦页面区域后可用左右方向键、PageUp/PageDown 翻页，Home/End 跳至首尾页；`pdfPage`、`pdfZoom` URL 参数保存当前页和缩放。无 JavaScript 或加载失败时可直接打开或下载 PDF。文本标签显示本层 Markdown 及已有 PDF 文本提取结果，不运行 LaTeX，也不调用模型重新生成总结。Markdown 仅渲染标题、段落、代码围栏，其他标记以原文展示；数学公式和排版以 PDF 为准。原始字幕读取 `transcript.jsonl`，时间链接打开对应分 P 的 Bilibili 视频。

新增或修改 BV 文件后刷新页面即可看到变化。分 P 标题优先采用根元数据的 `pages[].part`，缺失时使用分 P 自身元数据或目录名。PDF 数量只统计实际文件，不代表内容审核或课程完成状态。缺失材料、搜索无结果和读取错误都有独立提示。

文件接口只允许资料集目录内的阅读材料扩展名，拒绝路径越界和符号链接，不暴露脚本、环境文件或仓库其他目录。材料通过独立目录挂载；阅读接口只读，上传接口需要管理口令。材料目录应来自可信来源；服务器通过 Nginx 提供 HTTPS 访问，不提供多用户账户。

## PDF.js 资源与验证

`static/pdf-reader.mjs` 负责阅读器交互和单页渲染队列，页面重绘完成后才允许下一次操作，按设备像素比绘制并限制 canvas 像素总量。翻页与缩放时保留当前可见画面，在未挂载的替换节点中完成 canvas 与文字层渲染后一次性替换，避免清空画面闪烁；同页缩放尽量保留阅读位置，滚动条预留固定空间。文字层使用 PDF.js TextLayer，支持选中复制；当前为基础阅读器，未实现全文搜索、批注编辑、书签面板及 PDF 内部链接交互。

PDF.js display、worker、中文 CMap、标准字体和 WASM 资源固定在 `static/vendor/pdfjs/`，无需 npm 安装或 CDN。版本、来源和压缩包 SHA-256 见该目录的 `PROVENANCE.json`；保留上游 Apache-2.0 LICENSE 及各资源目录中的许可文件。更新时须同时替换同一版本的主模块、worker 和辅助资源。

页面 CSP 允许同源 worker、WASM、动态字体和 PDF.js 生成的内联样式，不允许内联脚本；第三方运行时资源通过专用白名单提供。所有材料来自独立挂载的资料集目录。

可选浏览器验证需要自行安装 `puppeteer-core` 并提供 Chromium 路径，在服务运行时执行：

```sh
CHROME_PATH=/path/to/chrome node web/tests/pdf-reader.browser.mjs
```

该检查使用仓库现有中文 PDF 验证实际渲染、翻页、跳页、缩放、URL 恢复、手机布局和失败回退；`TEST_BASE_URL` 可指定服务地址，`PUPPETEER_MODULE` 可指定现有 Puppeteer 模块路径。

闪烁回归检查：在同样的 Puppeteer 与 Chromium 环境中运行 `node web/tests/pdf-reader-stability.browser.mjs`。它在真实 PDF 翻页、缩放和窗口尺寸变化期间逐帧检查页面可见性及 canvas 像素，并检查无操作时是否出现重复重绘。

换页时，临时锁定的控件保持原来的颜色与不透明度，完成后直接更新页码；首尾页的实际禁用状态仍然正常显示。状态栏在已有页面重绘期间保留已完成的信息，避免文字与高度跳变。`node web/tests/pdf-reader-chrome.browser.mjs` 在桌面和手机宽度下逐帧检查控件变灰、临时消息闪现和阅读区跳动。
