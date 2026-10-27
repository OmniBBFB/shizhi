"""View: escaped server-rendered HTML, usable without JavaScript."""
import html
import json
import re
from urllib.parse import urlencode, unquote

e = lambda value: html.escape(str(value), quote=True)


def url(**params):
    return '/?' + urlencode({k: v for k, v in params.items() if v is not None})


def layout(title, body):
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="阅读本地视频讲义、总结与字幕">
<title>{e(title)} | 拾知</title><link rel="stylesheet" href="/static/style.css"><script src="/static/app.js" defer></script></head>
<body><a class="skip" href="#content">跳到正文</a><header class="mast container"><a class="brand" href="/">拾知<span>把学过的，留给未来的自己。</span></a><nav aria-label="主导航"><a href="/">全部视频</a></nav></header>
<main id="content" class="container">{body}</main><footer class="container"><span>拾知</span><p>回到讲义，接着思考。</p><a href="/">返回书架</a></footer></body></html>'''


def shelf(videos, query='', kind='all'):
    filtered = [v for v in videos if query.casefold() in (v['title']+' '+v['id']+' '+v['author']+' '+' '.join(u['title'] for u in v['units'])).casefold()
                and (kind != 'pdf' or v['pdf_count']) and (kind != 'course' or v['part_count'])]
    options = ''.join(f'<option value="{key}" {"selected" if key == kind else ""}>{label}</option>' for key, label in [('all','全部材料'),('pdf','有 PDF 讲义'),('course','多分 P 课程')])
    rows = ''
    for v in filtered:
        cover = f'<img src="{e(v["cover"])}" alt="" width="240" height="135" loading="lazy">' if v['cover'] else '<div class="cover-empty">暂无封面</div>'
        state = f'{v["pdf_count"]} 份 PDF' if v['pdf_count'] else '暂无 PDF'
        rows += f'''<li><a class="video-row" href="{e(url(video=v['id']))}">{cover}<div class="row-title"><h2>{e(v['title'])}</h2><p>{e(v['author'])}</p><small>{e(v['id'])}</small></div><div class="row-state"><span class="tag">{state}</span><p>{str(v['part_count'])+' 个分 P' if v['part_count'] else '单个视频'}</p><span class="read-label">阅读材料</span></div></a></li>'''
    empty = '<section class="empty"><h2>还没有匹配的视频</h2><p>试试视频标题、BV 号，或切换材料类型。</p><a class="button" href="/">查看全部视频</a></section>'
    return layout('全部视频', f'''<section class="intro"><h1>让看过的，成为你的。</h1><p>在讲义、总结和原始字幕之间，重新找到值得记住的内容。</p></section>
<form class="filters" method="get"><div class="search-field"><label for="q">搜索书架</label><input id="q" name="q" type="search" value="{e(query)}" placeholder="标题、BV 号或分 P 名称"></div><div><label for="kind">材料类型</label><select name="kind" id="kind">{options}</select></div><button class="primary" type="submit">查找视频</button><p class="loading" role="status" hidden>正在读取书架…</p></form>
<div class="list-heading"><h2>全部视频</h2><p role="status">找到 {len(filtered)} 个视频</p></div><ul class="shelf">{rows}</ul>{empty if not filtered else ''}''')


def plain_document(text):
    # Render structure without trusting HTML, embedded scripts or Markdown URLs.
    lines = []
    fence = False
    for line in text.splitlines():
        if line.startswith('```'):
            lines.append('</code></pre>' if fence else '<pre><code>')
            fence = not fence
        elif fence:
            lines.append(e(line)+'\n')
        elif re.match(r'^#{1,6} ', line):
            level = min(len(line)-len(line.lstrip('#'))+1, 6)
            lines.append(f'<h{level}>{e(line.lstrip("# "))}</h{level}>')
        elif line.strip():
            lines.append(f'<p>{e(line)}</p>')
    if fence:
        lines.append('</code></pre>')
    return '\n'.join(lines)


def reader(library, video, unit, tab, doc=None):
    vid, uid = video['id'], unit['id']
    base = dict(video=vid, part=uid)
    tabs = ''.join(f'<a {"aria-current=page" if key == tab else ""} href="{e(url(**base,tab=key))}">{label}</a>' for key,label in [('pdf','PDF 讲义'),('text','文本总结'),('transcript','原始字幕'),('files','全部材料')])
    options = ''.join(f'<option value="{e(u["id"])}" {"selected" if u["id"] == uid else ""}>{e(u["id"]+" / "+u["title"])}</option>' for u in video['units'])
    selector = f'<form method="get" class="part-picker"><input type="hidden" name="video" value="{e(vid)}"><input type="hidden" name="tab" value="{e(tab)}"><label for="part">选择讲次</label><select name="part" id="part">{options}</select><button type="submit">打开讲次</button></form>' if len(video['units']) > 1 else ''
    content = ''
    if tab in {'pdf','text'}:
        files = unit['pdfs'] if tab == 'pdf' else unit['documents']
        selected = next((f for f in files if f['name'] == doc), files[0] if files else None)
        if files:
            links = ''.join(f'<div class="document-option"><span>{e(f["name"])}</span><a {"aria-current=true" if f == selected else ""} aria-label="阅读 {e(f["name"])}" href="{e(url(**base, tab=tab, doc=f["name"]))}">阅读文件</a></div>' for f in files)
            content += f'<details class="document-picker" ><summary>选择文件（{len(files)}）</summary><nav aria-label="文件选择">{links}</nav></details>'
            if tab == 'pdf':
                content += f'''<div class="document-bar"><p>{e(selected["name"])}</p><a class="button primary" href="{e(selected["url"])}" download>下载 PDF</a></div><section class="pdf-reader" data-pdf-url="{e(selected["url"])}" aria-label="PDF.js 讲义阅读器">
<div class="pdf-toolbar" hidden>
<button type="button" data-pdf-prev disabled>上一页</button>
<form class="pdf-page-form" data-pdf-page-form><label for="pdf-page">页码</label><input id="pdf-page" name="pdfPage" type="number" min="1" value="1" step="1" required disabled><span data-pdf-total>共 — 页</span><button type="submit" disabled>跳转</button></form>
<button type="button" data-pdf-next disabled>下一页</button>
<div class="pdf-zoom"><label for="pdf-zoom">缩放</label><select id="pdf-zoom" disabled><option value="fit">适合宽度</option><option value="0.75">75%</option><option value="1">100%</option><option value="1.25">125%</option><option value="1.5">150%</option><option value="2">200%</option><option value="3">300%</option></select></div>
</div><p class="pdf-status" role="status" aria-live="polite">正在加载阅读器。若未显示，请使用下方的打开或下载链接。</p>
<button type="button" data-pdf-retry hidden>重新加载</button>
<div class="pdf-viewport" tabindex="0" role="region" aria-label="讲义页面，可用左右方向键翻页" hidden><div class="pdf-page"><canvas aria-hidden="true"></canvas><div class="textLayer" role="document" aria-label="当前页文字"></div></div></div>
<noscript><p>PDF.js 需要 JavaScript。请使用下方链接打开或下载 PDF。</p></noscript>
</section><script type="module" src="/static/pdf-reader.mjs"></script><p class="mobile-pdf">也可<a href="{e(selected["url"])}">在浏览器中打开 PDF</a>。</p>'''
            else:
                content += '<p class="notice">'+e(selected['name'])+'</p><article class="prose">'+plain_document(library.document(unquote(selected['url'][7:])))+'</article>'
    elif tab == 'transcript' and unit['transcript']:
        lines = []
        for line in library.document(unquote(unit['transcript'][7:])).splitlines():
            try:
                row = json.loads(line)
                start = max(0, int(float(row.get('start', 0))))
                stamp = f'{start//3600:02d}:{start//60%60:02d}:{start%60:02d}'
                lines.append(f'<p><a href="https://www.bilibili.com/video/{e(vid)}/?{e(urlencode({"p": int(uid[1:]) if uid.startswith("P") else 1,"t":start}))}">{stamp}</a><span>{e(row.get("text", ""))}</span></p>')
            except (ValueError, TypeError, AttributeError, OverflowError):
                lines.append(f'<p>{e(line)}</p>')
        content = '<p class="notice">原始转写可能包含识别错误。点击时间可回到视频核对。</p><article class="transcript">'+''.join(lines)+'</article>'
    elif tab == 'files':
        content = '<ul class="file-list">'+''.join(f'<li><span>{e(f["name"])}</span><a href="{e(f["url"])}" download>下载文件</a></li>' for f in unit['downloads'])+'</ul>' if unit['downloads'] else ''
    if not content:
        content = '<section class="empty"><h2>这个讲次暂无此类材料</h2><p>可以切换阅读标签，查看已经生成的内容。</p><a class="button" href="'+e(url(**base,tab='files'))+'">查看全部材料</a></section>'
    image = f'<img class="reader-cover" src="{e(video["cover"])}" alt="视频原始封面" width="240" height="135">' if video['cover'] else ''
    warning = f'<p class="notice">{e(video["warning"])}</p>' if video['warning'] else ''
    return layout(video['title'], f'''<a class="back" href="/">返回全部视频</a><section class="reader-head">{image}<div><h1>{e(video['title'])}</h1><p>{e(video['author'])}</p><a href="https://www.bilibili.com/video/{e(vid)}/">观看原视频</a></div></section>{warning}{selector}<div class="reading-title"><h2>{e(unit['title'])}</h2></div><nav class="tabs" aria-label="阅读方式">{tabs}</nav><section class="reading">{content}</section>''')


def error(message, status):
    return layout(str(status), f'<section class="empty"><h1>{e(message)}</h1><p>请返回书架重新选择，或刷新后再试。</p><a class="button" href="/">返回书架</a></section>')
