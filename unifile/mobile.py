"""Read-only LAN companion for the UniFile tag library."""

from __future__ import annotations

import html
import secrets
import socket
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

_MOBILE_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#0ea5e9">
  <meta name="description" content="Read-only UniFile tag library browser">
  <link rel="manifest" href="/mobile/manifest.json?token={{TOKEN}}">
  <title>UniFile Mobile Companion</title>
  <style>
    :root { color-scheme: dark; font-family: system-ui, -apple-system, sans-serif; }
    body { margin: 0; background: #0b1020; color: #e5eefb; }
    header { position: sticky; top: 0; z-index: 2; padding: 18px 16px 14px;
      background: linear-gradient(135deg, #111b38, #102b48); border-bottom: 1px solid #29415c; }
    h1 { font-size: 1.2rem; margin: 0 0 12px; }
    .search { display: flex; gap: 8px; }
    input { flex: 1; min-width: 0; border: 1px solid #47627f; border-radius: 10px;
      padding: 12px; background: #101a2c; color: #fff; font-size: 1rem; }
    button { border: 0; border-radius: 10px; padding: 10px 14px; background: #0ea5e9;
      color: #04111f; font-weight: 700; font-size: .95rem; }
    button.secondary { background: #20364f; color: #d9edff; }
    main { max-width: 980px; margin: 0 auto; padding: 14px 16px 40px; }
    #summary { color: #a9bfd6; font-size: .9rem; margin: 6px 0 12px; }
    #tags { display: flex; gap: 6px; overflow-x: auto; padding: 4px 0 12px; }
    .chip { white-space: nowrap; border-radius: 999px; padding: 6px 10px; background: #182b43;
      color: #b8dcf7; border: 1px solid #2a4b69; cursor: pointer; }
    .chip.active { background: #0ea5e9; color: #04111f; }
    #entries { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
    .card { display: grid; grid-template-columns: 72px 1fr; gap: 12px; min-height: 88px;
      padding: 12px; border: 1px solid #273e59; border-radius: 14px; background: #111a2a; }
    .thumb { width: 72px; height: 72px; object-fit: cover; border-radius: 9px; background: #1b2b40;
      display: grid; place-items: center; color: #86a6c4; font-size: .75rem; }
    .name { font-weight: 700; overflow-wrap: anywhere; }
    .path, .meta { color: #9fb5cb; font-size: .78rem; overflow-wrap: anywhere; margin-top: 4px; }
    .tags { color: #83d4ff; font-size: .78rem; margin-top: 7px; overflow-wrap: anywhere; }
    .empty { color: #9fb5cb; text-align: center; padding: 36px 12px; }
    @media (min-width: 700px) { header { padding-left: max(16px, calc((100% - 948px) / 2));
      padding-right: max(16px, calc((100% - 948px) / 2)); } }
  </style>
</head>
<body>
  <header>
    <h1>UniFile Mobile Companion <small>(read-only)</small></h1>
    <div class="search">
      <input id="query" type="search" placeholder="Search files, tags, or fields…" autocomplete="off">
      <button id="refresh" class="secondary" type="button">Refresh</button>
    </div>
  </header>
  <main>
    <div id="summary">Loading library…</div>
    <div id="tags" aria-label="Popular tags"></div>
    <section id="entries" aria-live="polite"></section>
  </main>
  <script>
    const token = new URL(location.href).searchParams.get('token') || '';
    const queryInput = document.getElementById('query');
    const summary = document.getElementById('summary');
    const tags = document.getElementById('tags');
    const entries = document.getElementById('entries');
    let activeTag = '';
    let timer;
    function apiUrl(path) {
      const url = new URL('/mobile/api' + path, location.origin);
      if (token) url.searchParams.set('token', token);
      return url;
    }
    async function api(path) {
      const response = await fetch(apiUrl(path), { headers: token ? {'X-API-Key': token} : {} });
      if (!response.ok) throw new Error('Request failed (' + response.status + ')');
      return response.json();
    }
    function esc(value) {
      return String(value ?? '').replace(/[&<>\"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',\"'\":'&#39;',\"\\\"\":'&quot;'}[c]));
    }
    function renderTags(items) {
      tags.innerHTML = '';
      const all = document.createElement('button');
      all.className = 'chip' + (activeTag ? '' : ' active');
      all.textContent = 'All files';
      all.onclick = () => { activeTag = ''; load(); };
      tags.appendChild(all);
      (items || []).slice(0, 24).forEach(item => {
        const button = document.createElement('button');
        button.className = 'chip' + (activeTag === item.name ? ' active' : '');
        button.textContent = item.name + ' (' + item.entry_count + ')';
        button.onclick = () => { activeTag = item.name; load(); };
        tags.appendChild(button);
      });
    }
    function renderEntries(items) {
      entries.innerHTML = '';
      if (!items || !items.length) { entries.innerHTML = '<div class="empty">No matching library entries.</div>'; return; }
      items.forEach(item => {
        const card = document.createElement('article'); card.className = 'card';
        const thumb = item.preview_url ? document.createElement('img') : document.createElement('div');
        thumb.className = 'thumb';
        if (item.preview_url) { thumb.loading = 'lazy'; thumb.alt = ''; thumb.src = apiUrl(item.preview_url.replace('/mobile/api', '')).toString(); }
        else thumb.textContent = (item.extension || 'file').toUpperCase();
        const body = document.createElement('div');
        body.innerHTML = '<div class="name">' + esc(item.name) + '</div>'
          + '<div class="path">' + esc(item.path) + '</div>'
          + '<div class="meta">' + esc(item.modified || '') + (item.size == null ? '' : ' · ' + Number(item.size).toLocaleString() + ' bytes') + '</div>'
          + '<div class="tags">' + esc((item.tags || []).join(' · ')) + '</div>';
        card.append(thumb, body); entries.appendChild(card);
      });
    }
    async function load() {
      summary.textContent = 'Loading…';
      try {
        const params = new URLSearchParams({limit: '80'});
        if (activeTag) params.set('tag', activeTag);
        else if (queryInput.value.trim()) params.set('query', queryInput.value.trim());
        const [catalog, report] = await Promise.all([api('/entries?' + params), api('/library')]);
        renderTags(report.tags); renderEntries(catalog.entries);
        summary.textContent = report.entry_count + ' files · ' + report.tag_count + ' tags' + (catalog.query ? ' · filtered' : '');
      } catch (error) { summary.textContent = error.message; entries.innerHTML = ''; }
    }
    queryInput.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(load, 250); });
    document.getElementById('refresh').onclick = load;
    if ('serviceWorker' in navigator) navigator.serviceWorker.register('/mobile/sw.js?token=' + encodeURIComponent(token));
    load();
  </script>
</body>
</html>"""

_SERVICE_WORKER = """const CACHE = 'unifile-mobile-shell-v1';
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.add('/mobile')));
  self.skipWaiting();
});
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET' || new URL(event.request.url).pathname.includes('/mobile/api/')) return;
  event.respondWith(fetch(event.request).then(response => {
    const copy = response.clone(); caches.open(CACHE).then(cache => cache.put(event.request, copy)); return response;
  }).catch(() => caches.match(event.request)));
});"""


def render_mobile_page(token: str) -> str:
    """Render the shell with the per-server token carried into PWA requests."""
    return _MOBILE_PAGE.replace("{{TOKEN}}", html.escape(token, quote=True))


def mobile_manifest(token: str) -> dict:
    """Return an installable manifest whose start URL preserves authentication."""
    encoded = quote(token, safe="")
    return {
        "name": "UniFile Mobile Companion",
        "short_name": "UniFile",
        "description": "Read-only UniFile tag library browser",
        "start_url": f"/mobile?token={encoded}",
        "scope": "/mobile/",
        "display": "standalone",
        "background_color": "#0b1020",
        "theme_color": "#0ea5e9",
        "icons": [{
            "src": f"/mobile/icon.svg?token={encoded}",
            "type": "image/svg+xml",
            "sizes": "any",
            "purpose": "any maskable",
        }],
    }


def register_mobile_routes(app, service) -> None:
    """Register mobile HTML, PWA, catalog, and thumbnail routes on a Flask app."""
    from flask import Response, abort, jsonify, request, send_file

    token = str(app.config.get("MOBILE_TOKEN", ""))

    @app.get("/mobile")
    def mobile_page():
        return Response(render_mobile_page(token), mimetype="text/html")

    @app.get("/mobile/manifest.json")
    def mobile_manifest_route():
        return jsonify(mobile_manifest(token))

    @app.get("/mobile/sw.js")
    def mobile_service_worker():
        return Response(_SERVICE_WORKER, mimetype="application/javascript")

    @app.get("/mobile/icon.svg")
    def mobile_icon():
        return Response(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192">'
            '<rect width="192" height="192" rx="42" fill="#0ea5e9"/>'
            '<path d="M45 54h102v24H45zm0 36h72v24H45zm0 36h102v24H45z" fill="#04111f"/>'
            '</svg>',
            mimetype="image/svg+xml",
        )

    @app.get("/mobile/api/library")
    def mobile_library():
        try:
            return jsonify(service.mobile_library())
        except (OSError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 500

    @app.get("/mobile/api/entries")
    def mobile_entries():
        try:
            return jsonify({
                "query": request.args.get("query", ""),
                "tag": request.args.get("tag", ""),
                "entries": service.mobile_entries(
                    query=request.args.get("query", ""),
                    tag=request.args.get("tag", ""),
                    limit=request.args.get("limit", 80),
                    offset=request.args.get("offset", 0),
                ),
            })
        except (OSError, TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.get("/mobile/api/entries/<int:entry_id>")
    def mobile_entry(entry_id: int):
        try:
            payload = service.mobile_entry(entry_id)
        except (OSError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 500
        if payload is None:
            abort(404)
        return jsonify(payload)

    @app.get("/mobile/api/entries/<int:entry_id>/preview")
    def mobile_preview(entry_id: int):
        payload = service.mobile_entry(entry_id, include_private=True)
        if payload is None or not payload.get("preview_url"):
            abort(404)
        try:
            path = service._allowed_file(payload["absolute_path"])
        except (OSError, PermissionError, ValueError):
            abort(404)
        if path.stat().st_size > 12 * 1024 * 1024:
            abort(413)
        try:
            from PIL import Image

            image = Image.open(path)
            image.thumbnail((480, 480))
            if image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
            output = BytesIO()
            image.save(output, format="JPEG", quality=78, optimize=True)
            output.seek(0)
            return send_file(output, mimetype="image/jpeg", max_age=300)
        except ImportError:
            return send_file(path, mimetype=payload.get("mime_type"), max_age=300)
        except (OSError, ValueError):
            abort(404)


def run_mobile_server(library_root: str | Path, *, host: str = "0.0.0.0", port: int = 8788,
                      token: str | None = None) -> int:
    """Start a read-only companion server and print its authenticated URL."""
    from unifile.headless import create_app

    mobile_token = token or secrets.token_urlsafe(18)
    app = create_app({
        "LIBRARY_ROOT": str(Path(library_root).expanduser()),
        "MOBILE_ONLY": True,
        "MOBILE_TOKEN": mobile_token,
        "ALLOW_UNAUTHENTICATED": False,
        "START_SCHEDULER": False,
    })
    display_host = host
    if host in {"0.0.0.0", "::"}:
        try:
            addresses = socket.gethostbyname_ex(socket.gethostname())[2]
            display_host = next((address for address in addresses if not address.startswith("127.")), "127.0.0.1")
        except OSError:
            display_host = "127.0.0.1"
    print(f"UniFile Mobile Companion: http://{display_host}:{port}/mobile?token={quote(mobile_token, safe='')}", flush=True)
    print("The server is read-only; stop it with Ctrl+C.", flush=True)
    app.run(host=host, port=port, debug=False, use_reloader=False)
    return 0


__all__ = ["mobile_manifest", "register_mobile_routes", "render_mobile_page", "run_mobile_server"]
