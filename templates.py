LOGIN_PAGE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>飞书知识库归档</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', sans-serif; background: #f5f6f8; display: flex; justify-content: center; align-items: center; min-height: 100vh; }
        .login-card { background: white; border-radius: 16px; padding: 48px 40px; text-align: center; box-shadow: 0 2px 12px rgba(0,0,0,0.08); max-width: 420px; width: 90%; }
        .login-card h1 { font-size: 24px; color: #1f2329; margin-bottom: 12px; }
        .login-card p { color: #646a73; font-size: 14px; margin-bottom: 32px; line-height: 1.6; }
        .login-btn { display: inline-block; background: #3370ff; color: white; text-decoration: none; padding: 12px 40px; border-radius: 8px; font-size: 15px; font-weight: 500; transition: background 0.2s; }
        .login-btn:hover { background: #2860e1; }
    </style>
</head>
<body>
    <div class="login-card">
        <h1>飞书知识库归档</h1>
        <p>以知识库为单位，把整个飞书知识库镜像为本地 Markdown（含图片与附件），支持手动增量同步与在线预览</p>
        <a href="{{ auth_url }}" class="login-btn">飞书登录</a>
    </div>
</body>
</html>
"""

INDEX_PAGE = r"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>飞书知识库归档</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', sans-serif; background: #f5f6f8; color: #1f2329; }
        .header { background: white; border-bottom: 1px solid #e5e6eb; padding: 14px 32px; display: flex; justify-content: space-between; align-items: center; position: sticky; top: 0; z-index: 10; }
        .header h1 { font-size: 17px; font-weight: 600; }
        .header .user { font-size: 14px; color: #646a73; display: flex; align-items: center; gap: 12px; }
        .header .avatar { width: 28px; height: 28px; border-radius: 50%; background: #3370ff; color: white; display: flex; align-items: center; justify-content: center; font-size: 13px; font-weight: 500; }
        .header .user a { color: #646a73; text-decoration: none; font-size: 13px; }
        .header .user a:hover { color: #f53f3f; }
        .container { max-width: 960px; margin: 28px auto; padding: 0 20px; }

        .add-card { background: white; border-radius: 12px; padding: 20px 24px; margin-bottom: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.04); }
        .add-card h2 { font-size: 15px; margin-bottom: 6px; font-weight: 600; }
        .add-card .sub { font-size: 12.5px; color: #86909c; margin-bottom: 14px; line-height: 1.6; }
        .input-row { display: flex; gap: 8px; position: relative; flex-wrap: wrap; }
        .input-wrap { flex: 1; min-width: 260px; position: relative; }
        .input-wrap input { width: 100%; padding: 10px 14px; border: 1px solid #dee0e3; border-radius: 8px; font-size: 14px; outline: none; transition: border-color 0.2s; }
        .input-wrap input:focus { border-color: #3370ff; box-shadow: 0 0 0 2px rgba(51,112,255,0.15); }
        .btn { padding: 10px 18px; border: none; border-radius: 8px; font-size: 14px; cursor: pointer; transition: background 0.2s; white-space: nowrap; font-family: inherit; }
        .btn-primary { background: #3370ff; color: white; }
        .btn-primary:hover { background: #2860e1; }
        .btn-light { background: #f2f3f5; color: #1f2329; }
        .btn-light:hover { background: #e5e6eb; }
        .btn:disabled { background: #c9cdd4; color: white; cursor: not-allowed; }

        .picker { position: absolute; top: calc(100% + 6px); left: 0; right: 0; background: white; border-radius: 10px; box-shadow: 0 8px 24px rgba(0,0,0,0.12); border: 1px solid #dee0e3; z-index: 100; display: none; flex-direction: column; max-height: 380px; }
        .picker.show { display: flex; }
        .picker-head { display: flex; gap: 8px; align-items: center; padding: 10px 12px; border-bottom: 1px solid #ebeef5; background: #f7f8fa; border-radius: 10px 10px 0 0; }
        .picker-head input { flex: 1; padding: 6px 10px; border: 1px solid #dee0e3; border-radius: 6px; font-size: 13px; outline: none; }
        .picker-head .close { cursor: pointer; color: #8f959e; font-size: 13px; padding: 4px 8px; border-radius: 6px; }
        .picker-head .close:hover { background: #e5e6eb; }
        .picker-list { overflow-y: auto; padding: 4px 0; }
        .picker-item { display: flex; align-items: center; gap: 10px; padding: 9px 14px; cursor: pointer; border-bottom: 1px solid #f7f8fa; }
        .picker-item:hover { background: #f2f6ff; }
        .picker-item.added { cursor: default; opacity: 0.55; }
        .picker-item.added:hover { background: transparent; }
        .picker-icon { width: 32px; height: 32px; border-radius: 8px; background: #e8f3ff; color: #3370ff; display: flex; align-items: center; justify-content: center; font-size: 15px; flex-shrink: 0; }
        .picker-main { flex: 1; min-width: 0; }
        .picker-name { font-size: 13.5px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .picker-desc { font-size: 11.5px; color: #8f959e; margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .tag { font-size: 11px; padding: 1px 6px; border-radius: 4px; background: #f2f3f5; color: #646a73; flex-shrink: 0; }
        .tag.blue { background: #e8f3ff; color: #3370ff; }
        .picker-empty { padding: 28px 16px; text-align: center; color: #8f959e; font-size: 13px; }

        .section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; gap: 12px; flex-wrap: wrap; }
        .section-title { font-size: 16px; font-weight: 600; }
        .count { font-size: 13px; color: #8f959e; font-weight: normal; margin-left: 6px; }

        .space-list { display: flex; flex-direction: column; gap: 12px; }
        .space-card { background: white; border-radius: 12px; padding: 16px 20px; border: 1px solid #dee0e3; border-left: 4px solid #dee0e3; box-shadow: 0 1px 3px rgba(0,0,0,0.04); display: flex; flex-direction: column; gap: 10px; transition: border-color 0.2s, box-shadow 0.2s; }
        .space-card:hover { border-color: #b3ccff; box-shadow: 0 4px 16px rgba(51,112,255,0.1); }
        .space-card.st-pending { border-left-color: #ff7d00; }
        .space-card.st-ok { border-left-color: #00b42a; }
        .space-card.st-partial { border-left-color: #ff7d00; }
        .space-card.st-syncing { border-left-color: #3370ff; }
        .space-card.st-error { border-left-color: #f53f3f; }
        .card-header { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
        .title-group { display: flex; align-items: center; gap: 8px; min-width: 0; flex: 1; overflow: hidden; }
        .title-group .name { font-size: 15px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 360px; }
        .icon-btn { cursor: pointer; font-size: 13px; opacity: 0.6; padding: 2px 4px; border-radius: 4px; user-select: none; flex-shrink: 0; }
        .icon-btn:hover { opacity: 1; background: #e5e6eb; }
        .origin-tag { background: #f2f3f5; color: #646a73; padding: 2px 8px; border-radius: 4px; font-size: 11px; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex-shrink: 0; }
        .actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
        .btn-preview { display: inline-flex; align-items: center; gap: 4px; padding: 6px 14px; border-radius: 8px; font-size: 12px; background: #e8f3ff; color: #3370ff; font-weight: 500; text-decoration: none; border: 1px solid rgba(51,112,255,0.2); white-space: nowrap; }
        .btn-preview:hover { background: #3370ff; color: white; }
        .btn-preview.disabled { opacity: 0.45; pointer-events: none; }
        .btn-sync { padding: 6px 16px; background: #00b42a; color: white; border: none; border-radius: 8px; font-size: 13px; cursor: pointer; font-weight: 500; white-space: nowrap; font-family: inherit; }
        .btn-sync:hover { background: #009a25; }
        .btn-sync.first { background: #ff7d00; }
        .btn-sync.first:hover { background: #e66e00; }
        .btn-stop { padding: 6px 14px; background: white; color: #f53f3f; border: 1px solid #ffd6d0; border-radius: 8px; font-size: 13px; cursor: pointer; font-family: inherit; }
        .btn-stop:hover { background: #ffece8; }

        .metrics { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 12px; color: #646a73; background: #f8f9fa; padding: 6px 12px; border-radius: 6px; }
        .m-label { color: #8f959e; }
        .m-val { color: #1f2329; font-weight: 500; }
        .m-sep { color: #c9cdd4; }
        .delta { font-family: 'SF Mono', Consolas, monospace; font-size: 11.5px; }
        .delta .add { color: #00b42a; } .delta .upd { color: #3370ff; } .delta .mv { color: #722ed1; } .delta .del { color: #f53f3f; }
        .mono { font-family: 'SF Mono', Consolas, monospace; font-size: 11px; color: #4e5969; cursor: pointer; border-radius: 4px; padding: 1px 4px; }
        .mono:hover { background: #e5e6eb; color: #3370ff; }

        .card-footer { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
        .footer-left { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 12px; }
        .footer-link { color: #3370ff; text-decoration: none; font-size: 12px; font-weight: 500; cursor: pointer; background: none; border: none; font-family: inherit; padding: 0; }
        .footer-link:hover { text-decoration: underline; }
        .footer-link.muted { color: #646a73; }
        .footer-link:disabled { color: #c9cdd4; cursor: not-allowed; text-decoration: none; }
        .dot { color: #d8dde3; }
        .btn-delete { padding: 4px 10px; background: transparent; color: #8f959e; border: 1px solid transparent; border-radius: 6px; font-size: 12px; cursor: pointer; font-family: inherit; }
        .btn-delete:hover { background: #ffece8; color: #f53f3f; border-color: #ffd6d0; }

        .badge { display: inline-flex; align-items: center; gap: 5px; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 500; flex-shrink: 0; }
        .badge .d { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
        .b-pending { background: #fff7e8; color: #ff7d00; }
        .b-ok { background: #e8ffea; color: #00b42a; }
        .b-partial { background: #fff7e8; color: #d46b08; }
        .b-syncing { background: #e8f3ff; color: #3370ff; }
        .b-syncing .d { animation: pulse 1.2s infinite; }
        .b-error { background: #ffece8; color: #f53f3f; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }

        .progress { display: none; }
        .progress.show { display: block; }
        .progress .stage { font-size: 12px; color: #4e5969; margin-bottom: 6px; line-height: 1.5; word-break: break-all; }
        .bar-wrap { width: 100%; height: 6px; background: #f2f3f5; border-radius: 3px; overflow: hidden; }
        .bar { height: 100%; background: linear-gradient(90deg, #3370ff, #00b42a); border-radius: 3px; width: 0%; transition: width 0.3s; }
        .bar.indeterminate { width: 30%; animation: slide 1.4s ease-in-out infinite; }
        @keyframes slide { 0% { margin-left: -30%; } 100% { margin-left: 100%; } }
        .progress.error .bar { background: #f53f3f; }
        .progress.error .stage { color: #f53f3f; }

        .issues { display: none; background: #fffaf2; border: 1px solid #ffe4ba; border-radius: 8px; padding: 10px 14px; font-size: 12px; color: #4e5969; max-height: 220px; overflow-y: auto; }
        .issues.show { display: block; }
        .issues li { margin: 3px 0 3px 16px; line-height: 1.5; word-break: break-all; }
        .issues b { color: #1f2329; font-weight: 500; }

        .empty { text-align: center; padding: 56px 24px; color: #86909c; background: white; border-radius: 12px; font-size: 14px; line-height: 1.8; }
        .toast { position: fixed; top: 20px; right: 20px; padding: 12px 22px; border-radius: 8px; color: white; font-size: 14px; z-index: 999; opacity: 0; transition: opacity 0.3s; pointer-events: none; max-width: 420px; line-height: 1.5; }
        .toast.show { opacity: 1; }
        .toast.success { background: #00b42a; } .toast.error { background: #f53f3f; } .toast.info { background: #3370ff; } .toast.warn { background: #ff7d00; }

        .modal-mask { position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: none; justify-content: center; align-items: center; z-index: 1000; }
        .modal-mask.show { display: flex; }
        .modal { background: white; border-radius: 12px; padding: 26px 30px; max-width: 460px; width: 90%; box-shadow: 0 4px 20px rgba(0,0,0,0.12); }
        .modal h3 { font-size: 17px; margin-bottom: 10px; }
        .modal p { font-size: 13px; color: #646a73; margin-bottom: 16px; line-height: 1.7; }
        .modal input[type=text] { width: 100%; padding: 8px 12px; border: 1px solid #dee0e3; border-radius: 6px; font-size: 13px; outline: none; margin-bottom: 16px; }
        .modal input[type=text]:focus { border-color: #3370ff; }
        .modal label { display: flex; align-items: center; gap: 8px; font-size: 13px; cursor: pointer; margin-bottom: 18px; background: #f7f8fa; border: 1px solid #dee0e3; border-radius: 8px; padding: 10px 12px; }
        .modal label input { width: 16px; height: 16px; accent-color: #f53f3f; }
        .modal-btns { display: flex; gap: 8px; justify-content: flex-end; }
        .modal-btns .btn { padding: 8px 18px; font-size: 13px; }
        .btn-danger { background: #f53f3f; color: white; }
        .btn-danger:hover { background: #d93636; }
        .btn-warn { background: #ff7d00; color: white; }
        .btn-warn:hover { background: #e66e00; }
        @media (max-width: 640px) {
            .header { padding: 12px 16px; }
            .container { padding: 0 16px; margin-top: 18px; }
            .card-header { flex-wrap: wrap; }
            .title-group .name { max-width: 200px; }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>📚 飞书知识库归档</h1>
        <div class="user">
            <div class="avatar">{{ (user.name or '?')[:1] }}</div>
            <span>{{ user.name }}</span>
            <a href="/auth/logout">退出</a>
        </div>
    </div>

    <div class="container">
        <div class="add-card">
            <h2>添加知识库</h2>
            <div class="sub">粘贴知识库内任一页面链接、知识库设置页链接或 space_id；也可以从你有权限的知识库中选择。添加后点击「同步」把整库拉到本地，之后每次同步只拉取有变化的文档。</div>
            <div class="input-row">
                <div class="input-wrap">
                    <input type="text" id="addInput" placeholder="https://xxx.feishu.cn/wiki/... 或 space_id" autocomplete="off">
                    <div class="picker" id="picker">
                        <div class="picker-head">
                            <input type="text" id="pickerSearch" placeholder="搜索知识库名称..." autocomplete="off">
                            <span class="close" onclick="closePicker()">关闭</span>
                        </div>
                        <div class="picker-list" id="pickerList"><div class="picker-empty">加载中...</div></div>
                    </div>
                </div>
                <button class="btn btn-light" id="pickBtn" onclick="openPicker()">从我的知识库选择 ▾</button>
                <button class="btn btn-primary" id="addBtn" onclick="addSpace()">添加</button>
            </div>
        </div>

        <div class="section-header">
            <div class="section-title">我的知识库<span class="count" id="spaceCount"></span></div>
        </div>
        <div class="space-list" id="spaceList"></div>
    </div>

    <div class="modal-mask" id="modalMask" onclick="if(event.target===this)closeModal()">
        <div class="modal" id="modalBox"></div>
    </div>
    <div class="toast" id="toast"></div>

    <script>
    var spaces = {{ spaces | tojson }};
    var pollers = {};
    var userSpaces = null;

    function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function(c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
    function toast(msg, type) {
        var t = document.getElementById('toast');
        t.textContent = msg; t.className = 'toast show ' + (type || 'info');
        clearTimeout(t._h); t._h = setTimeout(function() { t.className = 'toast'; }, type === 'error' ? 5000 : 3000);
    }
    function api(method, url, body) {
        return fetch(url, { method: method, headers: {'Content-Type': 'application/json'}, body: body ? JSON.stringify(body) : undefined })
            .then(function(r) { return r.json().catch(function() { return {}; }).then(function(d) { d._status = r.status; return d; }); });
    }
    function findSpace(id) { for (var i = 0; i < spaces.length; i++) if (spaces[i].id === id) return spaces[i]; return null; }

    function statusOf(s) {
        var p = s.progress;
        if (p && p.running) return ['syncing', '同步中'];
        if (p && p.stage === 'error') return ['error', '同步失败'];
        if (s.last_sync_status === 'ok') return ['ok', '已同步'];
        if (s.last_sync_status === 'partial') return ['partial', '部分失败'];
        if (s.last_sync_status === 'error') return ['error', '同步失败'];
        if (s.last_sync_status === 'cancelled') return ['partial', '已停止'];
        return ['pending', '未同步'];
    }

    function deltaHtml(sm) {
        if (!sm || sm.nodes === undefined) return '';
        var parts = [];
        if (sm.added) parts.push('<span class="add">+' + sm.added + '</span>');
        if (sm.updated) parts.push('<span class="upd">~' + sm.updated + '</span>');
        if (sm.moved) parts.push('<span class="mv">↷' + sm.moved + '</span>');
        if (sm.deleted) parts.push('<span class="del">−' + sm.deleted + '</span>');
        return '<span class="m-sep">|</span><span class="m-label">上次变更</span><span class="delta">' + (parts.length ? parts.join(' ') : '无变化') + '</span>';
    }

    function cardHtml(s) {
        var st = statusOf(s), p = s.progress || {}, sm = s.summary || {};
        var running = !!p.running;
        var showName = s.feishu_name && s.feishu_name !== s.name;
        var issues = (sm.errors || []);
        var issueCount = (sm.failed || 0) + (sm.warned || 0) + (sm.traverse_errors || 0);
        var h = '';
        h += '<div class="card-header"><div class="title-group">';
        h += '<span class="name" title="' + esc(s.name) + '">' + (s.space_type === 'my_library' ? '🗂️ ' : '📚 ') + esc(s.name) + '</span>';
        h += '<span class="icon-btn" title="重命名" onclick="renameModal(' + s.id + ')">✏️</span>';
        if (showName) h += '<span class="origin-tag" title="飞书知识库名称">' + esc(s.feishu_name) + '</span>';
        h += '<span class="badge b-' + st[0] + '"><span class="d"></span>' + st[1] + '</span>';
        h += '</div><div class="actions">';
        h += '<a class="btn-preview' + (s.has_cache ? '' : ' disabled') + '" href="/space/' + s.id + '">👁 预览</a>';
        if (running) h += '<button class="btn-stop" onclick="cancelSync(' + s.id + ')">停止</button>';
        else h += '<button class="btn-sync' + (s.last_sync_at ? '' : ' first') + '" onclick="startSync(' + s.id + ', false)">' + (s.last_sync_at ? '同步' : '首次同步') + '</button>';
        h += '</div></div>';

        h += '<div class="metrics">';
        h += '<span class="m-label">节点</span><span class="m-val">' + (s.node_count || 0) + '</span>';
        h += '<span class="m-sep">|</span><span class="m-label">文档</span><span class="m-val">' + (s.doc_count || 0) + '</span>';
        h += '<span class="m-sep">|</span><span class="m-label">最近同步</span><span class="m-val">' + (s.last_sync_at || '—') + '</span>';
        if (sm.seconds !== undefined) h += '<span class="m-label">· 用时 ' + sm.seconds + 's</span>';
        h += deltaHtml(sm);
        h += '<span class="m-sep">|</span><span class="mono" title="点击复制 space_id" onclick="copyText(\'' + esc(s.space_id) + '\')">' + esc(s.space_id) + ' ⧉</span>';
        h += '</div>';

        var progCls = 'progress' + (running || p.stage === 'error' ? ' show' : '') + (p.stage === 'error' ? ' error' : '');
        var pct = p.total ? Math.min(100, Math.round(p.current * 100 / p.total)) : 0;
        var indeterminate = running && (p.stage === 'traverse' || p.stage === 'starting' || !p.total);
        h += '<div class="' + progCls + '"><div class="stage">' + esc(p.error || p.message || '') + '</div>';
        // 轮询会重绘卡片：用负的 animation-delay 让不定进度动画连续，不会每次从头开始
        var barStyle = indeterminate ? 'animation-delay:-' + (Date.now() % 1400) + 'ms' : 'width:' + pct + '%';
        h += '<div class="bar-wrap"><div class="bar' + (indeterminate ? ' indeterminate' : '') + '" style="' + barStyle + '"></div></div></div>';

        h += '<div class="card-footer"><div class="footer-left">';
        h += '<button class="footer-link" ' + (running ? 'disabled' : '') + ' onclick="forceModal(' + s.id + ')">全量重建</button><span class="dot">·</span>';
        h += '<a class="footer-link" href="/space/' + s.id + '/download"' + (s.has_cache ? '' : ' style="pointer-events:none;color:#c9cdd4"') + '>下载 ZIP</a><span class="dot">·</span>';
        h += '<a class="footer-link muted" href="' + esc(s.web_url) + '" target="_blank" rel="noopener">在飞书中打开 ↗</a>';
        if (issueCount) h += '<span class="dot">·</span><button class="footer-link" style="color:#d46b08" onclick="toggleIssues(' + s.id + ')">⚠️ ' + issueCount + ' 个问题</button>';
        if (sm.skipped_delete) h += '<span class="dot">·</span><span style="color:#d46b08">目录遍历不完整，本次未处理删除</span>';
        h += '</div><button class="btn-delete" onclick="deleteModal(' + s.id + ')">删除</button></div>';

        if (issues.length) {
            h += '<div class="issues" id="issues-' + s.id + '"><ul>';
            issues.forEach(function(e) { h += '<li><b>' + esc(e.title || '') + '</b>：' + esc(e.error || '') + '</li>'; });
            h += '</ul></div>';
        }
        return h;
    }

    function render() {
        var list = document.getElementById('spaceList');
        document.getElementById('spaceCount').textContent = spaces.length ? '(' + spaces.length + ')' : '';
        if (!spaces.length) {
            list.innerHTML = '<div class="empty">还没有添加知识库<br>在上方粘贴知识库链接，或点击「从我的知识库选择」</div>';
            return;
        }
        var html = '';
        spaces.forEach(function(s) {
            html += '<div class="space-card st-' + statusOf(s)[0] + '" id="card-' + s.id + '">' + cardHtml(s) + '</div>';
        });
        list.innerHTML = html;
        spaces.forEach(function(s) { if (s.progress && s.progress.running) poll(s.id); });
    }

    function updateCard(s) {
        for (var i = 0; i < spaces.length; i++) if (spaces[i].id === s.id) spaces[i] = s;
        var el = document.getElementById('card-' + s.id);
        if (!el) return render();
        var openIssues = document.getElementById('issues-' + s.id);
        var wasOpen = openIssues && openIssues.classList.contains('show');
        el.className = 'space-card st-' + statusOf(s)[0];
        el.innerHTML = cardHtml(s);
        if (wasOpen) toggleIssues(s.id);
    }

    function poll(id) {
        if (pollers[id]) return;
        pollers[id] = setInterval(function() {
            api('GET', '/api/spaces/' + id + '/status').then(function(s) {
                if (s._status !== 200) { clearInterval(pollers[id]); delete pollers[id]; return; }
                updateCard(s);
                var p = s.progress || {};
                if (!p.running) {
                    clearInterval(pollers[id]); delete pollers[id];
                    if (p.stage === 'done') toast(p.message, (s.summary && (s.summary.failed || s.summary.traverse_errors)) ? 'warn' : 'success');
                    else if (p.stage === 'error') toast(p.error || '同步失败', 'error');
                    else if (p.stage === 'cancelled') toast(p.message, 'warn');
                }
            });
        }, 1500);
    }

    function startSync(id, force) {
        closeModal();
        api('POST', '/api/spaces/' + id + '/sync', {force: force}).then(function(d) {
            if (d._status !== 200) { toast(d.error || '启动失败', 'error'); return; }
            var s = findSpace(id);
            s.progress = {running: true, stage: 'starting', message: force ? '准备全量重建...' : '准备开始同步...'};
            updateCard(s); poll(id);
        });
    }
    function cancelSync(id) {
        api('POST', '/api/spaces/' + id + '/cancel').then(function() { toast('正在停止，当前正在拉取的文档完成后结束', 'info'); });
    }
    function toggleIssues(id) { var el = document.getElementById('issues-' + id); if (el) el.classList.toggle('show'); }
    function copyText(t) {
        (navigator.clipboard ? navigator.clipboard.writeText(t) : Promise.reject()).then(function() { toast('已复制 ' + t, 'success'); }, function() { toast(t, 'info'); });
    }

    // ===== 添加 =====
    function addSpace(input) {
        var el = document.getElementById('addInput');
        var value = input || el.value.trim();
        if (!value) { toast('请输入知识库链接或 space_id', 'warn'); el.focus(); return; }
        var btn = document.getElementById('addBtn');
        btn.disabled = true; btn.textContent = '添加中...';
        api('POST', '/api/spaces', {input: value}).then(function(d) {
            btn.disabled = false; btn.textContent = '添加';
            if (d._status !== 200) { toast(d.error || '添加失败', 'error'); return; }
            el.value = '';
            spaces.unshift(d.space); render(); closePicker();
            if (userSpaces) userSpaces.forEach(function(u) { if (u.space_id === d.space.space_id) u.added = true; });
            toast('已添加「' + d.space.name + '」，点击「首次同步」拉取整库', 'success');
        });
    }
    document.getElementById('addInput').addEventListener('keydown', function(e) { if (e.key === 'Enter') addSpace(); });

    function openPicker() {
        var pk = document.getElementById('picker');
        pk.classList.add('show');
        document.getElementById('pickerSearch').focus();
        if (userSpaces) return renderPicker();
        api('GET', '/api/user_spaces').then(function(d) {
            if (d._status !== 200) { document.getElementById('pickerList').innerHTML = '<div class="picker-empty">' + esc(d.error || '加载失败') + '</div>'; return; }
            userSpaces = d.spaces || []; renderPicker();
        });
    }
    function closePicker() { document.getElementById('picker').classList.remove('show'); }
    function renderPicker() {
        var q = document.getElementById('pickerSearch').value.trim().toLowerCase();
        var items = userSpaces.filter(function(u) { return !q || (u.name + ' ' + u.description + ' ' + u.space_id).toLowerCase().indexOf(q) >= 0; });
        if (!items.length) { document.getElementById('pickerList').innerHTML = '<div class="picker-empty">' + (userSpaces.length ? '没有匹配的知识库' : '没有可访问的知识库') + '</div>'; return; }
        var h = '';
        items.forEach(function(u) {
            var lib = u.space_type === 'my_library';
            h += '<div class="picker-item' + (u.added ? ' added' : '') + '"' + (u.added ? '' : ' onclick="addSpace(\'' + esc(u.space_id) + '\')"') + '>';
            h += '<div class="picker-icon">' + (lib ? '🗂️' : '📚') + '</div><div class="picker-main"><div class="picker-name">' + esc(u.name) + '</div>';
            h += '<div class="picker-desc">' + esc(u.description || u.space_id) + '</div></div>';
            if (lib) h += '<span class="tag blue">我的文档库</span>';
            else if (u.visibility === 'public') h += '<span class="tag">公开</span>';
            if (u.added) h += '<span class="tag">已添加</span>';
            h += '</div>';
        });
        document.getElementById('pickerList').innerHTML = h;
    }
    document.getElementById('pickerSearch').addEventListener('input', function() { if (userSpaces) renderPicker(); });
    document.addEventListener('click', function(e) {
        var pk = document.getElementById('picker');
        if (!pk.contains(e.target) && e.target.id !== 'pickBtn') closePicker();
    });

    // ===== 弹窗 =====
    function openModal(html) { document.getElementById('modalBox').innerHTML = html; document.getElementById('modalMask').classList.add('show'); }
    function closeModal() { document.getElementById('modalMask').classList.remove('show'); }
    document.addEventListener('keydown', function(e) { if (e.key === 'Escape') { closeModal(); closePicker(); } });

    function forceModal(id) {
        var s = findSpace(id);
        openModal('<h3>全量重建「' + esc(s.name) + '」？</h3>' +
            '<p>忽略本地已有内容，重新拉取知识库内全部 ' + (s.node_count || '') + ' 个节点。普通「同步」只拉取有变化的文档；全量重建适用于本地文件被改动、或转换规则升级后刷新全部内容。<br>大型知识库会占用较多接口配额，耗时也更长。</p>' +
            '<div class="modal-btns"><button class="btn btn-light" onclick="closeModal()">取消</button><button class="btn btn-warn" onclick="startSync(' + id + ', true)">开始全量重建</button></div>');
    }
    function deleteModal(id) {
        var s = findSpace(id);
        openModal('<h3>删除知识库「' + esc(s.name) + '」？</h3><p>只会移除本服务中的配置，不会影响飞书上的知识库。</p>' +
            '<label><input type="checkbox" id="delCache"' + (s.has_cache ? ' checked' : ' disabled') + '> 同时删除本地镜像文件（Markdown 与附件）</label>' +
            '<div class="modal-btns"><button class="btn btn-light" onclick="closeModal()">取消</button><button class="btn btn-danger" onclick="doDelete(' + id + ')">删除</button></div>');
    }
    function doDelete(id) {
        var del = document.getElementById('delCache').checked ? '1' : '0';
        api('DELETE', '/api/spaces/' + id + '?delete_cache=' + del).then(function(d) {
            closeModal();
            if (d._status !== 200) { toast(d.error || '删除失败', 'error'); return; }
            spaces = spaces.filter(function(s) { return s.id !== id; }); render();
            if (userSpaces) userSpaces = null;
            toast('已删除' + (d.cache_removed ? '（含本地文件）' : ''), 'success');
        });
    }
    function renameModal(id) {
        var s = findSpace(id);
        openModal('<h3>重命名</h3><p>仅修改在本服务中显示的名称' + (s.feishu_name ? '（飞书名称：' + esc(s.feishu_name) + '）' : '') + '，留空则恢复为飞书名称。本地目录名不变。</p>' +
            '<input type="text" id="renameInput" value="' + esc(s.name) + '">' +
            '<div class="modal-btns"><button class="btn btn-light" onclick="closeModal()">取消</button><button class="btn btn-primary" onclick="doRename(' + id + ')">保存</button></div>');
        var inp = document.getElementById('renameInput'); inp.focus(); inp.select();
        inp.addEventListener('keydown', function(e) { if (e.key === 'Enter') doRename(id); });
    }
    function doRename(id) {
        api('POST', '/api/spaces/' + id + '/rename', {name: document.getElementById('renameInput').value}).then(function(d) {
            closeModal();
            if (d._status !== 200) { toast(d.error || '保存失败', 'error'); return; }
            updateCard(d.space); toast('已保存', 'success');
        });
    }

    render();
    </script>
</body>
</html>
"""

VIEW_PAGE = r"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ space.name }} - 知识库预览</title>
    <script src="/static/marked.min.js?v=15.0.12"></script>
    <script>
        if (typeof marked === 'undefined') {
            document.write('<scr' + 'ipt src="https://cdn.bootcdn.net/ajax/libs/marked/15.0.12/marked.min.js"></scr' + 'ipt>');
        }
    </script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        html, body { height: 100%; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', sans-serif; background: #f5f6f8; color: #1f2329; display: flex; flex-direction: column; }
        .top-nav { background: white; border-bottom: 1px solid #e5e6eb; padding: 10px 24px; display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-shrink: 0; }
        .nav-left { display: flex; align-items: center; gap: 14px; min-width: 0; }
        .btn-back { color: #4e5969; text-decoration: none; font-size: 13px; padding: 6px 12px; border-radius: 6px; background: #f2f3f5; font-weight: 500; white-space: nowrap; }
        .btn-back:hover { background: #e5e6eb; color: #1f2329; }
        .space-title { font-size: 16px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .meta { font-size: 12px; color: #86909c; white-space: nowrap; }
        .nav-right { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
        .nav-btn { display: inline-flex; align-items: center; gap: 6px; padding: 7px 14px; border-radius: 6px; font-size: 13px; font-weight: 500; text-decoration: none; cursor: pointer; border: none; white-space: nowrap; }
        .btn-gray { background: #f2f3f5; color: #1f2329; }
        .btn-gray:hover { background: #e5e6eb; }
        .btn-blue { background: #3370ff; color: white; }
        .btn-blue:hover { background: #2860e1; }
        .btn-toggle { display: none; }

        .layout { flex: 1; display: flex; min-height: 0; }
        .sidebar { width: 300px; background: white; border-right: 1px solid #e5e6eb; display: flex; flex-direction: column; flex-shrink: 0; }
        .side-search { padding: 12px; border-bottom: 1px solid #f2f3f5; }
        .side-search input { width: 100%; padding: 7px 10px; border: 1px solid #dee0e3; border-radius: 6px; font-size: 13px; outline: none; }
        .side-search input:focus { border-color: #3370ff; }
        .tree { flex: 1; overflow-y: auto; padding: 6px 0 20px; font-size: 13px; }
        .tree ul { list-style: none; }
        .tree li > .row { display: flex; align-items: center; gap: 4px; padding: 5px 10px 5px 0; cursor: pointer; border-radius: 6px; margin: 0 6px; color: #1f2329; }
        .tree li > .row:hover { background: #f2f3f5; }
        .tree li > .row.active { background: #e8f3ff; color: #3370ff; font-weight: 500; }
        .tree .caret { width: 18px; text-align: center; color: #8f959e; font-size: 10px; flex-shrink: 0; transition: transform 0.15s; user-select: none; }
        .tree .caret.open { transform: rotate(90deg); }
        .tree .caret.none { visibility: hidden; }
        .tree .label { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 1; }
        .tree .st { font-size: 11px; flex-shrink: 0; }
        .tree li.collapsed > ul { display: none; }
        .tree li.hidden { display: none; }
        .tree mark { background: #ffe066; color: inherit; border-radius: 2px; }
        .tree .home { font-weight: 600; }

        .main { flex: 1; overflow-y: auto; padding: 24px; }
        .md-card { background: white; border-radius: 12px; padding: 32px 40px; box-shadow: 0 1px 3px rgba(0,0,0,0.04); line-height: 1.75; font-size: 14.5px; max-width: 920px; margin: 0 auto; }
        .breadcrumb { max-width: 920px; margin: 0 auto 12px; font-size: 12.5px; color: #86909c; display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
        .breadcrumb a { color: #646a73; text-decoration: none; }
        .breadcrumb a:hover { color: #3370ff; }
        .md-card h1 { font-size: 24px; margin-bottom: 12px; color: #1f2329; }
        .md-card h2 { font-size: 19px; margin: 26px 0 12px; padding-bottom: 6px; border-bottom: 1px solid #f2f3f5; }
        .md-card h3 { font-size: 16px; margin: 20px 0 10px; }
        .md-card h4, .md-card h5, .md-card h6 { font-size: 14.5px; margin: 16px 0 8px; }
        .md-card p { margin-bottom: 12px; word-break: break-word; }
        .md-card ul, .md-card ol { margin: 0 0 12px 22px; }
        .md-card li { margin: 3px 0; }
        .md-card li > ul, .md-card li > ol { margin-bottom: 0; }
        .md-card hr { border: none; height: 1px; background: #e5e6eb; margin: 22px 0; }
        .md-card blockquote { border-left: 4px solid #3370ff; padding: 8px 16px; background: #f7f9fd; color: #4e5969; border-radius: 0 6px 6px 0; margin-bottom: 14px; }
        .md-card blockquote p { margin-bottom: 4px; }
        .md-card code { font-family: 'SF Mono', Consolas, Monaco, monospace; background: #f2f3f5; padding: 2px 6px; border-radius: 4px; font-size: 12.5px; }
        .md-card pre { background: #1e1e1e; color: #d4d4d4; padding: 14px 18px; border-radius: 8px; overflow-x: auto; margin: 14px 0; font-size: 13px; line-height: 1.5; }
        .md-card pre code { background: transparent; color: inherit; padding: 0; }
        .md-card table { border-collapse: collapse; margin: 12px 0 16px; font-size: 13.5px; display: block; overflow-x: auto; }
        .md-card th, .md-card td { border: 1px solid #dee0e3; padding: 7px 12px; text-align: left; vertical-align: top; }
        .md-card th { background: #f7f8fa; font-weight: 600; }
        .md-card img { max-width: 100%; border-radius: 6px; margin: 8px 0; cursor: zoom-in; }
        .md-card a { color: #3370ff; text-decoration: none; word-break: break-all; }
        .md-card a:hover { text-decoration: underline; }
        .md-card input[type=checkbox] { margin-right: 6px; }
        .attachment-card { display: inline-flex; align-items: center; gap: 10px; background: #f7f8fa; border: 1px solid #dee0e3; border-radius: 8px; padding: 9px 14px; text-decoration: none !important; color: #1f2329 !important; font-size: 13.5px; margin: 6px 0; font-weight: 500; }
        .attachment-card:hover { background: #e8f3ff; border-color: #3370ff; color: #3370ff !important; }
        .attachment-card .tagdl { font-size: 12px; color: #3370ff; background: #e8f3ff; padding: 2px 8px; border-radius: 4px; }
        .empty-tip { text-align: center; padding: 60px 20px; color: #86909c; }
        .lightbox { position: fixed; inset: 0; background: rgba(0,0,0,0.85); display: none; justify-content: center; align-items: center; z-index: 1000; }
        .lightbox.show { display: flex; }
        .lightbox img { max-width: 94vw; max-height: 92vh; border-radius: 6px; }
        @media (max-width: 800px) {
            .sidebar { position: fixed; top: 53px; bottom: 0; left: 0; z-index: 50; transform: translateX(-100%); transition: transform 0.2s; box-shadow: 4px 0 16px rgba(0,0,0,0.08); }
            .sidebar.open { transform: none; }
            .btn-toggle { display: inline-flex; }
            .meta, .nav-btn .txt { display: none; }
            .main { padding: 16px; }
            .md-card { padding: 22px 18px; }
            .top-nav { padding: 10px 16px; }
        }
    </style>
</head>
<body>
    <div class="top-nav">
        <div class="nav-left">
            <button class="nav-btn btn-gray btn-toggle" onclick="document.getElementById('sidebar').classList.toggle('open')">☰</button>
            <a href="/" class="btn-back">← 返回</a>
            <span class="space-title">{{ space.name }}</span>
            <span class="meta">{{ space.node_count }} 个节点 · {{ info.asset_count }} 个附件 · {{ (info.total_size / 1048576) | round(1) }} MB{% if space.last_sync_at %} · 同步于 {{ space.last_sync_at }}{% endif %}</span>
        </div>
        <div class="nav-right">
            <a class="nav-btn btn-gray" id="openFeishu" href="{{ space.web_url }}" target="_blank" rel="noopener">↗<span class="txt"> 飞书原文</span></a>
            <a class="nav-btn btn-gray" id="rawLink" href="#" target="_blank">📄<span class="txt"> Markdown</span></a>
            <a class="nav-btn btn-blue" href="/space/{{ space.id }}/download">📦<span class="txt"> 下载 ZIP</span></a>
        </div>
    </div>
    <div class="layout">
        <aside class="sidebar" id="sidebar">
            <div class="side-search"><input type="text" id="filter" placeholder="筛选文档标题..." autocomplete="off"></div>
            <div class="tree" id="tree"></div>
        </aside>
        <main class="main" id="main">
            <div class="breadcrumb" id="crumb"></div>
            <div class="md-card" id="doc"><div class="empty-tip">加载中...</div></div>
        </main>
    </div>
    <div class="lightbox" id="lightbox" onclick="this.classList.remove('show')"><img id="lightboxImg" alt=""></div>

    <script>
    var SPACE_ID = {{ space.id }};
    var HAS_CACHE = {{ 'true' if space.has_cache else 'false' }};
    var nodes = [], byPath = {}, byToken = {}, current = null;

    function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function(c) { return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
    function fileUrl(path) { return '/space/' + SPACE_ID + '/files/' + path.split('/').map(encodeURIComponent).join('/'); }
    function dirname(p) { var i = p.lastIndexOf('/'); return i < 0 ? '' : p.slice(0, i); }
    function resolvePath(base, rel) {
        try { rel = decodeURIComponent(rel); } catch (e) {}
        var parts = base ? base.split('/') : [];
        rel.split('/').forEach(function(seg) {
            if (seg === '' || seg === '.') return;
            if (seg === '..') parts.pop(); else parts.push(seg);
        });
        return parts.join('/');
    }
    var ICON = {docx: '📄', doc: '📃', sheet: '📊', bitable: '🗂️', mindnote: '🧠', file: '📎', slides: '🖼️'};

    // ===== 目录树 =====
    function buildTree() {
        var kids = {};
        nodes.forEach(function(n) { (kids[n.p] = kids[n.p] || []).push(n); byPath[n.path] = n; byToken[n.t] = n; });
        function ul(parent, depth) {
            var list = kids[parent] || [];
            if (!list.length) return '';
            var h = '<ul>';
            list.forEach(function(n) {
                var has = !!kids[n.t];
                var st = n.status === 'error' ? '<span class="st" title="' + esc(n.error) + '">❌</span>' : (n.status === 'warn' ? '<span class="st" title="' + esc(n.error) + '">⚠️</span>' : '');
                h += '<li class="' + (has && depth >= 1 ? 'collapsed' : '') + '" data-t="' + n.t + '">';
                h += '<div class="row" data-path="' + esc(n.path) + '" style="padding-left:' + (depth * 14 + 4) + 'px">';
                h += '<span class="caret' + (has ? (depth >= 1 ? '' : ' open') : ' none') + '">▶</span>';
                h += '<span class="label" title="' + esc(n.title) + '">' + (n.shortcut ? '🔗' : (ICON[n.type] || '📦')) + ' <span class="t">' + esc(n.title) + '</span></span>' + st + '</div>';
                h += ul(n.t, depth + 1) + '</li>';
            });
            return h + '</ul>';
        }
        var home = '<ul><li><div class="row home" data-path="README.md" style="padding-left:4px"><span class="caret none">▶</span><span class="label">🏠 目录索引</span></div></li></ul>';
        document.getElementById('tree').innerHTML = home + ul('', 0);
    }
    document.getElementById('tree').addEventListener('click', function(e) {
        var row = e.target.closest('.row');
        if (!row) return;
        var li = row.parentElement;
        if (e.target.classList.contains('caret')) {
            li.classList.toggle('collapsed');
            e.target.classList.toggle('open', !li.classList.contains('collapsed'));
            return;
        }
        go(row.getAttribute('data-path'));
        document.getElementById('sidebar').classList.remove('open');
    });
    function highlightTree(path) {
        document.querySelectorAll('.tree .row.active').forEach(function(r) { r.classList.remove('active'); });
        var row = document.querySelector('.tree .row[data-path="' + CSS.escape(path) + '"]');
        if (!row) return;
        row.classList.add('active');
        var li = row.parentElement.parentElement.closest('li');
        while (li) {
            li.classList.remove('collapsed');
            var c = li.querySelector(':scope > .row .caret'); if (c) c.classList.add('open');
            li = li.parentElement.closest('li');
        }
        row.scrollIntoView({block: 'nearest'});
    }
    document.getElementById('filter').addEventListener('input', function() {
        var q = this.value.trim().toLowerCase();
        var lis = document.querySelectorAll('.tree li[data-t]');
        lis.forEach(function(li) {
            var n = byToken[li.getAttribute('data-t')];
            var t = li.querySelector(':scope > .row .t');
            t.innerHTML = esc(n.title);
            li.classList.remove('hidden');
            if (q) {
                var i = n.title.toLowerCase().indexOf(q);
                li._match = i >= 0;
                if (i >= 0) t.innerHTML = esc(n.title.slice(0, i)) + '<mark>' + esc(n.title.slice(i, i + q.length)) + '</mark>' + esc(n.title.slice(i + q.length));
            }
        });
        if (!q) return;
        // 自底向上：命中节点及其祖先可见并展开
        Array.prototype.slice.call(lis).reverse().forEach(function(li) {
            var childVisible = li.querySelector(':scope > ul > li:not(.hidden)');
            if (li._match || childVisible) {
                if (childVisible) { li.classList.remove('collapsed'); var c = li.querySelector(':scope > .row .caret'); if (c) c.classList.add('open'); }
            }
            else li.classList.add('hidden');
        });
    });

    // ===== 文档渲染 =====
    var ALLOWED_HTML = /^<\/?(u|br)\s*\/?>$/i;
    function makeRenderer(docPath) {
        var r = new marked.Renderer();
        var base = dirname(docPath);
        r.html = function(token) {
            var raw = (typeof token === 'object' && token) ? (token.raw || token.text || '') : String(token || '');
            return ALLOWED_HTML.test(raw.trim()) ? raw : esc(raw);
        };
        r.image = function(token) {
            var href = token.href || '', alt = token.text || '图片';
            var src = /^(https?:)?\/\//.test(href) ? href : fileUrl(resolvePath(base, href));
            return '<img src="' + esc(src) + '" alt="' + esc(alt) + '" loading="lazy" onclick="openLightbox(this.src)">';
        };
        r.link = function(token) {
            var href = token.href || '';
            var text = (this.parser && token.tokens) ? this.parser.parseInline(token.tokens) : esc(token.text || href);
            if (/^\s*(javascript|vbscript|data):/i.test(href)) return text;
            if (/^(https?:|mailto:)/i.test(href)) return '<a href="' + esc(href) + '" target="_blank" rel="noopener noreferrer">' + text + '</a>';
            if (href.charAt(0) === '#') return '<a href="' + esc(href) + '">' + text + '</a>';
            var target = resolvePath(base, href.split('#')[0]);
            if (/\.md$/i.test(target)) return '<a class="internal" href="#' + esc(encodeURIComponent(target)) + '">' + text + '</a>';
            text = text.replace(/^\s*📎\s*/, '');
            return '<a class="attachment-card" href="' + esc(fileUrl(target)) + '?download=1" download><span>📎</span><span>' + text + '</span><span class="tagdl">下载</span></a>';
        };
        r.checkbox = function(token) { return '<input type="checkbox" disabled' + (token.checked ? ' checked' : '') + '>'; };
        return r;
    }
    function stripFrontMatter(md) {
        var meta = {};
        var m = md.match(/^---\n([\s\S]*?)\n---\n?/);
        if (!m) return [md, meta];
        m[1].split('\n').forEach(function(line) {
            var i = line.indexOf(':');
            if (i > 0) { try { meta[line.slice(0, i).trim()] = JSON.parse(line.slice(i + 1).trim()); } catch (e) {} }
        });
        return [md.slice(m[0].length), meta];
    }
    function crumbs(path) {
        var n = byPath[path], chain = [];
        while (n) { chain.unshift(n); n = byToken[n.p]; }
        var h = '<span><a href="#README.md">' + esc({{ space.name | tojson }}) + '</a>';
        chain.forEach(function(c) { h += ' / <a href="#' + esc(encodeURIComponent(c.path)) + '">' + esc(c.title) + '</a>'; });
        return h + '</span>';
    }
    function go(path) {
        var h = '#' + encodeURIComponent(path);
        if (location.hash !== h) location.hash = h; else load(path);
    }
    function load(path) {
        current = path;
        var doc = document.getElementById('doc');
        document.getElementById('rawLink').href = fileUrl(path) + '?download=1';
        highlightTree(path);
        fetch(fileUrl(path)).then(function(r) {
            if (!r.ok) throw new Error(r.status === 404 ? '本地尚无此文件（可能还未同步）' : 'HTTP ' + r.status);
            return r.text();
        }).then(function(md) {
            if (current !== path) return;
            var fm = stripFrontMatter(md), meta = fm[1];
            document.getElementById('openFeishu').href = meta.source || {{ space.web_url | tojson }};
            document.getElementById('crumb').innerHTML = crumbs(path);
            if (typeof marked === 'undefined') { doc.innerHTML = '<pre style="white-space:pre-wrap">' + esc(fm[0]) + '</pre>'; return; }
            doc.innerHTML = marked.parse(fm[0], {renderer: makeRenderer(path), gfm: true, breaks: true});
            document.getElementById('main').scrollTop = 0;
        }).catch(function(e) {
            doc.innerHTML = '<div class="empty-tip">' + esc(e.message) + '</div>';
        });
    }
    function route() {
        var p = location.hash ? decodeURIComponent(location.hash.slice(1)) : 'README.md';
        load(p || 'README.md');
    }
    window.addEventListener('hashchange', route);
    function openLightbox(src) { document.getElementById('lightboxImg').src = src; document.getElementById('lightbox').classList.add('show'); }
    document.addEventListener('keydown', function(e) { if (e.key === 'Escape') document.getElementById('lightbox').classList.remove('show'); });

    if (!HAS_CACHE) {
        document.getElementById('doc').innerHTML = '<div class="empty-tip"><h3>还没有本地镜像</h3><p style="margin-top:10px">回到控制台点击「同步」拉取知识库。</p></div>';
    } else {
        fetch('/api/spaces/' + SPACE_ID + '/tree').then(function(r) { return r.json(); }).then(function(d) {
            nodes = d.nodes || []; buildTree(); route();
        });
    }
    </script>
</body>
</html>
"""
