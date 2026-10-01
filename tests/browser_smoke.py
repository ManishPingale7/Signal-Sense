import json, time, urllib.request, argparse
parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=8890)
parser.add_argument("--chrome-port", type=int, default=9224)
args = parser.parse_args()
base_url = f"http://127.0.0.1:{args.port}"
from pathlib import Path
from websockets.sync.client import connect
pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{args.chrome_port}/json"))
page = next(p for p in pages if p['type'] == 'page')
ws = connect(page['webSocketDebuggerUrl'], open_timeout=10, max_size=20000000)
counter = 0
errors = []
def cdp(method, params=None):
    global counter
    counter += 1
    ws.send(json.dumps({'id':counter, 'method':method, 'params':params or {}}))
    while True:
        event = json.loads(ws.recv(timeout=20))
        if event.get('method') == 'Runtime.exceptionThrown':
            errors.append(event['params']['exceptionDetails'].get('text'))
        if event.get('id') == counter:
            if 'error' in event:
                raise RuntimeError(event['error'])
            return event.get('result', {})
def js(expression):
    result = cdp('Runtime.evaluate', {'expression':expression,'returnByValue':True,'awaitPromise':True})
    if 'exceptionDetails' in result:
        raise RuntimeError(result['exceptionDetails'])
    return result.get('result',{}).get('value')
cdp('Runtime.enable'); cdp('Page.enable')
cdp('Page.navigate', {'url':base_url + "/?demo=1"})
time.sleep(2)
assert js('currentBrief.stories.length') == 9
assert js('document.getElementById("status-label").textContent') == 'SAVED RUN'
assert js('document.getElementById("run-button").disabled')
print('PASS: saved demo renders 9 cards with date label and no live generation')
assert js('document.getElementById("demo-note").textContent.includes("27")')
js('searchStories.value = "NO_MATCH_FOR_TEST"; searchStories.dispatchEvent(new Event("input"));')
assert js('document.getElementById("brief-content").textContent.includes("No matching updates")')
js('searchStories.value = ""; searchStories.dispatchEvent(new Event("input"));')
print('PASS: story search and reset')
js('categoryFilter.value = "model"; categoryFilter.dispatchEvent(new Event("input"));')
assert js('document.getElementById("filter-count").textContent')
js('categoryFilter.value = ""; categoryFilter.dispatchEvent(new Event("input"));')
assert js('Array.from(document.querySelectorAll(".story-card a")).every(a => a.href.startsWith("https://"))')
print('PASS: category filtering and HTTPS source links')
js('document.querySelector(".story-card details summary").click()')
assert js('document.querySelector(".story-card details").open')
print('PASS: story explanation expands')
# Keep downloaded page usable while the network is completely disabled.
cdp('Network.enable')
cdp('Network.emulateNetworkConditions', {'offline':True,'latency':0,'downloadThroughput':0,'uploadThroughput':0})
js('searchStories.value = "Claude"; searchStories.dispatchEvent(new Event("input"));')
assert js('document.getElementById("brief-content").textContent.includes("Claude")')
print('PASS: saved story interaction without network')
cdp('Network.emulateNetworkConditions', {'offline':False,'latency':0,'downloadThroughput':-1,'uploadThroughput':-1})
js('searchStories.value = ""; searchStories.dispatchEvent(new Event("input"));')
cdp('Emulation.setDeviceMetricsOverride', {'width':390,'height':844,'deviceScaleFactor':1,'mobile':True})
time.sleep(.5)
assert js('document.documentElement.scrollWidth <= window.innerWidth + 1')
print('PASS: mobile view without horizontal overflow')
cdp('Emulation.setDeviceMetricsOverride', {'width':1440,'height':1000,'deviceScaleFactor':1,'mobile':False})
# Simulate API states at the fetch boundary. Never invoke /api/run or Teams.
js('''window.originalFetch = window.fetch;
window.fixtureBrief = currentBrief;
window.fetch = async (url, opts) => {
 if (String(url).startsWith('/api/state')) return new Response(JSON.stringify({status:'running',activity:[],briefing:window.fixtureBrief,configured:true,teams_configured:false,started_at:new Date().toISOString()}), {status:200,headers:{'Content-Type':'application/json'}});
 return window.originalFetch(url,opts);
}; demoMode = false; applyDemoMode();''')
js('refresh()')
assert js('runButton.disabled')
assert not js('demoButton.disabled')
js('enterDemo()')
assert js('demoMode && currentBrief.stories.length === 9')
print('PASS: saved demo remains accessible during live generation')
js('''window.fetch = async (url, opts) => {
 if (String(url).startsWith('/api/state')) return new Response(JSON.stringify({status:'fallback',saved_demo:true,error:'Rate limited',activity:[],briefing:window.fixtureBrief,configured:true,teams_configured:false}), {status:200,headers:{'Content-Type':'application/json'}});
 return window.originalFetch(url,opts);
}; demoMode=false; applyDemoMode();''')
js('refresh()')
assert js('demoMode && document.getElementById("status-label").textContent === "SAVED RUN"')
assert js('document.getElementById("toast").textContent.includes("dated saved briefing")')
print('PASS: live failure automatically shows explicitly labelled saved briefing')
js('''window.fetch = async () => {throw new TypeError('Network unavailable')}; demoMode=false; applyDemoMode();''')
js('refresh()')
assert not js('document.getElementById("connection-banner").hidden')
assert js('currentBrief.stories.length') == 9
print('PASS: connection failure preserves rendered cards')
js('window.fetch=window.originalFetch; demoMode=true; applyDemoMode();')
js('enterDemo()')
assert not errors, errors
print('PASS: no JavaScript runtime exceptions')
import base64
export_dir = Path(__file__).resolve().parents[1] / "data" / "demo-export-checks"
export_dir.mkdir(exist_ok=True)
cdp('Browser.setDownloadBehavior', {'behavior':'allow','downloadPath':str(export_dir.resolve())})
js('document.getElementById("export-button").click()')
time.sleep(1)
exports = list(export_dir.glob('*.md'))
assert exports and "# Signal & Sense" in exports[-1].read_text(encoding='utf-8')
print('PASS: Markdown export')
pdf = cdp('Page.printToPDF', {'printBackground':True,'preferCSSPageSize':True})
content = base64.b64decode(pdf['data'])
assert content.startswith(b'%PDF')
(export_dir / 'presentation.pdf').write_bytes(content)
print('PASS: PDF presentation export')
ws.close()