"""Local network speed test: a tiny web server a phone or another PC opens in its browser.

The page measures ping, download and upload between that device and this PC, then reports the result back.
Requests need the random token in the link and must come from a private (LAN) address."""
import ipaddress
import json
import os
import re
import secrets
import socket
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CHUNK = os.urandom(1 << 20)
MAX_DOWN = 200 * 1024 * 1024
PORTS = range(8765, 8785)

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Local speed test</title>
<style>
:root{--bg:#14151a;--panel:#1c1e25;--line:#2a2c35;--text:#e8e9ee;--dim:#8b8fa0;--blue:#7f9cff;--purple:#b58cff}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;background:var(--bg);color:var(--text);font-family:system-ui,"Segoe UI",sans-serif;
display:flex;flex-direction:column;align-items:center;padding:28px 16px;gap:18px}
h1{font-size:16px;font-weight:500;margin:0;color:var(--dim)}
.gauge{position:relative;width:min(300px,80vw);aspect-ratio:1}
.gauge svg{width:100%;height:100%}
.center{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;padding-top:34%}
#num{font-size:44px;font-weight:500}
#phase{font-size:13px;color:var(--dim)}
.tiles{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;width:min(360px,92vw)}
.tile{background:var(--panel);border-radius:12px;padding:12px;text-align:center}
.tile span{display:block;font-size:12px;color:var(--dim)}
.tile b{font-size:20px;font-weight:500}
.results{display:none;width:min(360px,92vw);flex-direction:column;gap:12px}
body.done .gauge,body.done .tiles{display:none}
body.done .results{display:flex}
#ok{text-align:center;font-size:18px;color:#5fd8a6;font-weight:500}
.big{background:var(--panel);border-radius:16px;padding:18px;text-align:center}
.big span{display:block;font-size:14px;color:var(--dim)}
.big b{font-size:44px;font-weight:500}
button{background:var(--blue);color:#14151a;border:0;border-radius:10px;padding:12px 28px;font-size:15px;font-weight:500}
button:disabled{opacity:.5}
#msg{font-size:13px;color:var(--dim);text-align:center;max-width:340px}
</style></head><body>
<h1>Speed between this device and the PC</h1>
<div class="gauge">
<svg viewBox="0 0 200 200"><g transform="rotate(135 100 100)" fill="none" stroke-linecap="round" stroke-width="12">
<circle cx="100" cy="100" r="80" stroke="#2a2c35" stroke-dasharray="376.99 502.65"/>
<circle id="arc" cx="100" cy="100" r="80" stroke="#7f9cff" stroke-dasharray="0 502.65"/></g></svg>
<div class="center"><div id="num">0</div><div id="phase">Mb/s</div></div></div>
<div class="tiles"><div class="tile"><span>Ping</span><b id="tp">–</b></div>
<div class="tile"><span>Download</span><b id="td">–</b></div>
<div class="tile"><span>Upload</span><b id="tu">–</b></div></div>
<div class="results"><div id="ok">&#10003; Test complete</div>
<div class="big"><span>Download</span><b id="rd" style="color:#7f9cff">–</b></div>
<div class="big"><span>Upload</span><b id="ru" style="color:#b58cff">–</b></div>
<div class="tile"><span>Ping</span><b id="rp">–</b></div></div>
<button id="go">Start test</button>
<div id="msg">Keep this page open while the test runs.</div>
<script>
const T=new URLSearchParams(location.search).get('t');
const q=p=>p+(p.includes('?')?'&':'?')+'t='+T+'&r='+Math.random();
const MARKS=[0,5,10,50,100,250,500,750,1000];
const frac=v=>{v=Math.max(0,Math.min(1000,v));for(let i=0;i<8;i++){if(v<=MARKS[i+1])return(i+(v-MARKS[i])/(MARKS[i+1]-MARKS[i]))/8}return 1};
const $=id=>document.getElementById(id);
const fmt=v=>v>=1000?(v/1000).toFixed(2)+' Gb/s':v.toFixed(0)+' Mb/s';
function show(v,phase,color){$('num').textContent=v<100?v.toFixed(1):Math.round(v);$('phase').textContent=phase+' · Mb/s';
$('arc').setAttribute('stroke',color);$('arc').setAttribute('stroke-dasharray',(376.99*frac(v))+' 502.65')}
async function ping(){const s=[];for(let i=0;i<12;i++){const t=performance.now();await fetch(q('/ping'),{cache:'no-store'});s.push(performance.now()-t)}
s.shift();s.sort((a,b)=>a-b);return s[s.length>>1]}
async function down(){const dur=7000,t0=performance.now();let bytes=0;const ctl=new AbortController();
const worker=async()=>{try{while(performance.now()-t0<dur){const r=await fetch(q('/down?size=50000000'),{cache:'no-store',signal:ctl.signal});
const rd=r.body.getReader();for(;;){const{done,value}=await rd.read();if(done)break;bytes+=value.length;const el=performance.now()-t0;
if(el>=dur){ctl.abort();return}if(el>300)show(bytes*8/el/1e3,'Download','#7f9cff')}}}catch(e){}};
await Promise.all([worker(),worker(),worker(),worker()]);return bytes*8/(performance.now()-t0)/1e3}
function up(){return new Promise(res=>{const dur=7000,n=3,t0=performance.now(),sent=[0,0,0],blob=new Blob([new Uint8Array(4e6)]);let fin=0;
const total=()=>sent[0]+sent[1]+sent[2];
const run=i=>{if(performance.now()-t0>=dur){if(++fin===n)res(total()*8/(performance.now()-t0)/1e3);return}
const x=new XMLHttpRequest();x.open('POST',q('/up'));let last=0;
x.upload.onprogress=e=>{sent[i]+=e.loaded-last;last=e.loaded;const el=performance.now()-t0;if(el>300)show(total()*8/el/1e3,'Upload','#b58cff');if(el>=dur+400)x.abort()};
x.onload=x.onerror=x.onabort=()=>run(i);x.send(blob)};for(let i=0;i<n;i++)run(i)})}
async function main(){document.body.classList.remove('done');fetch(q('/begin')).catch(()=>{});$('go').disabled=true;['tp','td','tu'].forEach(i=>$(i).textContent='–');$('msg').textContent='Testing…';
try{show(0,'Ping','#7f9cff');const p=await ping();$('tp').textContent=p.toFixed(0)+' ms';
const d=await down();show(d,'Download','#7f9cff');$('td').textContent=fmt(d);await new Promise(r=>setTimeout(r,1200));
show(0,'Upload','#b58cff');await new Promise(r=>setTimeout(r,800));const u=await up();show(u,'Upload','#b58cff');$('tu').textContent=fmt(u);
await fetch(q('/result'),{method:'POST',body:JSON.stringify({ping:p,down:d,up:u})});
$('rd').textContent=fmt(d);$('ru').textContent=fmt(u);$('rp').textContent=p.toFixed(0)+' ms';document.body.classList.add('done');
$('msg').textContent='The result was also sent to the PC.'}catch(e){$('msg').textContent='The test failed. Check that you are on the same network.'}
$('go').disabled=false;$('go').textContent='Run again'}
$('go').onclick=main;setTimeout(main,400);
</script></body></html>
"""


def device_name(ua):
    if "Android" in ua:
        m = re.search(r"Android [\d.]+; ([^;)]+)", ua)
        model = m.group(1).strip() if m else ""
        if len(model) > 1:  # Chrome hides the real model behind a placeholder such as "K"
            return model
        return "Android phone" if "Mobile" in ua else "Android tablet"
    for key, name in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Windows", "Windows PC"), ("Macintosh", "Mac"),
                      ("CrOS", "Chromebook"), ("Linux", "Linux device")):
        if key in ua:
            return name
    return "Device"


def lan_ip():
    """This PC's LAN address, found without sending any traffic."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class _Meter:
    """Counts the bytes the server really moves, so the PC can show the test live."""

    def __init__(self):
        self.lock = threading.Lock()
        self.total = {"down": 0, "up": 0}
        self.ip = {"down": "", "up": ""}

    def add(self, kind, n, ip):
        with self.lock:
            self.total[kind] += n
            self.ip[kind] = ip

    def snapshot(self):
        with self.lock:
            return dict(self.total), dict(self.ip)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False  # on Windows this would let two servers share one port

    def __init__(self, addr, token, on_result):
        super().__init__(addr, _Handler)
        self.token, self.on_result, self.meter = token, on_result, _Meter()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        pass

    def _reply(self, code, body=b"", ctype="text/plain"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _authorized(self, query):
        try:
            private = ipaddress.ip_address(self.client_address[0]).is_private
        except ValueError:
            private = False
        ok = private and secrets.compare_digest(query.get("t", [""])[0], self.server.token)
        if not ok:
            self._reply(403, b"Forbidden")
        return ok

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(url.query)
        if not self._authorized(query):
            return
        if url.path == "/":
            self._reply(200, PAGE.encode(), "text/html; charset=utf-8")
        elif url.path == "/ping":
            self._reply(200, b"ok")
        elif url.path == "/begin":
            self._reply(200, b"ok")
            self.server.on_result({"event": "start", "ip": self.client_address[0],
                                   "device": device_name(self.headers.get("User-Agent", ""))})
        elif url.path == "/down":
            try:
                size = max(0, min(int(query.get("size", ["10000000"])[0]), MAX_DOWN))
            except ValueError:
                size = 10_000_000
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                while size > 0:
                    piece = CHUNK[:min(len(CHUNK), size)]
                    self.wfile.write(piece)
                    size -= len(piece)
                    self.server.meter.add("down", len(piece), self.client_address[0])
            except OSError:  # the page stops the stream when its time is up
                self.close_connection = True
        else:
            self._reply(404, b"Not found")

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(url.query)
        length = int(self.headers.get("Content-Length") or 0)
        if not self._authorized(query):
            self.close_connection = True
            return
        if url.path == "/up":
            left = length
            while left > 0:
                data = self.rfile.read(min(left, 1 << 20))
                if not data:
                    break
                left -= len(data)
                self.server.meter.add("up", len(data), self.client_address[0])
            self._reply(200, b"ok")
        elif url.path == "/result" and length < 4096:
            try:
                data = json.loads(self.rfile.read(length))
                result = {"event": "result", "ping": float(data["ping"]), "down": float(data["down"]), "up": float(data["up"]),
                          "ip": self.client_address[0], "device": device_name(self.headers.get("User-Agent", "")),
                          "time": time.strftime("%d %b %H:%M")}
            except (ValueError, KeyError, TypeError):
                self._reply(400, b"Bad result")
                return
            self._reply(200, b"ok")
            self.server.on_result(result)
        else:
            self._reply(404, b"Not found")


class LocalServer:
    def __init__(self, on_result):
        self.on_result, self.server, self.token, self.port = on_result, None, secrets.token_urlsafe(6), 0

    def start(self):
        for port in PORTS:
            try:
                self.server = _Server(("0.0.0.0", port), self.token, self.on_result)
                break
            except OSError:
                continue
        else:
            raise OSError("No free port between 8765 and 8784.")
        self.port = port
        self._halt = threading.Event()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        threading.Thread(target=self._sample, args=(self.server,), daemon=True).start()

    def _sample(self, server):
        """Five times a second, turns the byte counters into a smoothed live speed for the PC to show."""
        prev, smooth = {"down": 0, "up": 0}, {"down": 0.0, "up": 0.0}
        active, last_move = {"down": False, "up": False}, {"down": 0.0, "up": 0.0}
        t_prev = time.time()
        while not self._halt.wait(0.2):
            total, ip = server.meter.snapshot()
            now = time.time()
            dt, t_prev = max(now - t_prev, 0.001), now
            for kind in ("down", "up"):
                delta, prev[kind] = total[kind] - prev[kind], total[kind]
                if delta > 0:
                    inst = delta * 8 / dt / 1e6
                    smooth[kind] = 0.5 * smooth[kind] + 0.5 * inst if active[kind] else inst
                    active[kind], last_move[kind] = True, now
                    self.on_result({"event": "live", "phase": kind, "mbps": smooth[kind], "ip": ip[kind]})
                elif active[kind] and now - last_move[kind] > 0.6:
                    active[kind], smooth[kind] = False, 0.0
                    self.on_result({"event": "live", "phase": kind, "mbps": 0.0, "ip": ip[kind]})

    def refresh(self):
        """Issues a new token. The old link and QR code stop working immediately."""
        self.token = secrets.token_urlsafe(6)
        if self.server:
            self.server.token = self.token

    def url(self, ip):
        return f"http://{ip}:{self.port}/?t={self.token}"

    def stop(self):
        if self.server:
            self._halt.set()
            self.server.shutdown()
            self.server.server_close()
            self.server = None
