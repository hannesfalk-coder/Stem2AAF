"""
help_panel.py

Native macOS "How to use Stem2AAF" help panel — a floating NSPanel
containing a WKWebView with scrollable step-by-step instructions.
Mirrors the visual style of CategoryOrderPanel (same font, orange accent,
dark/light-mode aware) but is read-only: no message handler needed beyond
a simple Close button.
"""

import objc
from AppKit import (
    NSApp,
    NSBackingStoreBuffered,
    NSMakeRect,
    NSPanel,
)
from Foundation import NSObject
from WebKit import WKUserContentController, WKWebView, WKWebViewConfiguration

_TITLED   = 1
_CLOSABLE = 2

_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --text:#1d1d1f;
  --text2:#6e6e73;
  --sep:rgba(0,0,0,.10);
  --num-bg:#e07b2c;
  --btn:#e07b2c;
  --btn-h:#c96b1e;
}
@media(prefers-color-scheme:dark){
  :root{
    --text:#f5f5f5;
    --text2:#8e8e93;
    --sep:rgba(255,255,255,.10);
    --btn-h:#f08c3d;
  }
}
html,body{
  width:320px;height:100%;
  font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text",sans-serif;
  background:Canvas;color:var(--text);
  -webkit-font-smoothing:antialiased;
  -webkit-user-select:none;user-select:none;
}
.scroll{
  overflow-y:auto;
  padding:14px 14px 0;
  /* height is set by JS to fill the panel minus the footer */
}
.scroll::-webkit-scrollbar{width:4px}
.scroll::-webkit-scrollbar-track{background:transparent}
.scroll::-webkit-scrollbar-thumb{background:rgba(128,128,128,.35);border-radius:2px}
.item{
  display:flex;align-items:flex-start;
  gap:10px;padding:10px 0;
  border-bottom:1px solid var(--sep);
}
.item:last-child{border-bottom:none}
.num{
  flex-shrink:0;width:20px;height:20px;
  background:var(--num-bg);border-radius:5px;
  display:flex;align-items:center;justify-content:center;
  font-size:11px;font-weight:700;color:#fff;
  margin-top:1px;
}
.body{flex:1}
.label{
  font-size:13px;font-weight:600;
  color:var(--text);line-height:1.3;margin-bottom:3px;
}
.desc{
  font-size:12px;color:var(--text2);line-height:1.55;
}
.footer{
  padding:10px 14px 14px;
  display:flex;justify-content:flex-end;
  border-top:1px solid var(--sep);
}
.btn-close{
  font-family:inherit;font-size:13px;font-weight:600;
  color:#fff;background:var(--btn);
  border:none;border-radius:6px;
  padding:6px 18px;cursor:pointer;
}
.btn-close:hover{background:var(--btn-h)}
.btn-close:active{transform:scale(.97)}
</style>
</head>
<body>
<div class="scroll" id="scroll">

  <div class="item">
    <div class="num">1</div>
    <div class="body">
      <div class="label">Choose folder</div>
      <div class="desc">Select the folder where your DAW exports stem files. The AAF is saved inside that folder and named after it — so a folder called “My Song” produces “My Song_v1.aaf”.</div>
    </div>
  </div>

  <div class="item">
    <div class="num">2</div>
    <div class="body">
      <div class="label">Launch at login</div>
      <div class="desc">Turn on to have Stem2AAF start automatically every time you log in to your Mac.</div>
    </div>
  </div>

  <div class="item">
    <div class="num">3</div>
    <div class="body">
      <div class="label">Group stems by category</div>
      <div class="desc">When on, stems are sorted into groups in the AAF — Drums, Bass, Guitar, Keys, and so on — and renamed to match their category. The order they were exported is replaced by the category order.</div>
    </div>
  </div>

  <div class="item">
    <div class="num">4</div>
    <div class="body">
      <div class="label">Category Order</div>
      <div class="desc">Opens a window where you can change the order of categories and turn individual ones on or off. Only available when Group stems by category is on.</div>
    </div>
  </div>

  <div class="item">
    <div class="num">5</div>
    <div class="body">
      <div class="label">Delete stems after conversion</div>
      <div class="desc">When on, the original stem files are deleted after a successful conversion. When off, they are moved into the same folder as the AAF file and kept as a backup.</div>
    </div>
  </div>

  <div class="item">
    <div class="num">6</div>
    <div class="body">
      <div class="label">Automatic conversion</div>
      <div class="desc">When on, the app converts automatically as soon as it detects that your DAW has finished exporting — no need to click Convert to AAF manually.</div>
    </div>
  </div>

  <div class="item">
    <div class="num">7</div>
    <div class="body">
      <div class="label">Convert to AAF</div>
      <div class="desc">Converts all stems currently waiting in the folder into one AAF file. The number in brackets shows how many stems are ready.</div>
    </div>
  </div>

</div>
<div class="footer">
  <button class="btn-close" onclick="closePanel()">Close</button>
</div>
<script>
function closePanel() {
  window.webkit.messageHandlers.helpPanel.postMessage({action: 'close'});
}
// Fill available height: window height minus footer
window.addEventListener('load', function() {
  var footer = document.querySelector('.footer');
  var scroll = document.getElementById('scroll');
  scroll.style.height = (window.innerHeight - footer.offsetHeight) + 'px';
});
</script>
</body>
</html>
"""


class _CloseHandler(NSObject):
    def init(self):
        self = objc.super(_CloseHandler, self).init()
        self._panel = None
        return self

    def userContentController_didReceiveScriptMessage_(self, controller, message):
        try:
            body = message.body()
            if body.get("action") == "close" and self._panel is not None:
                self._panel.orderOut_(None)
        except Exception:
            pass


class HelpPanel:
    """
    Floating read-only NSPanel showing step-by-step usage instructions.

    Usage:
        panel = HelpPanel()
        panel.show()
    """

    def __init__(self):
        self._handler = None
        self._webview = None
        self._panel = None
        self._build()

    def _build(self):
        handler = _CloseHandler.alloc().init()
        self._handler = handler

        controller = WKUserContentController.alloc().init()
        controller.addScriptMessageHandler_name_(handler, "helpPanel")
        cfg = WKWebViewConfiguration.alloc().init()
        cfg.setUserContentController_(controller)

        frame = NSMakeRect(0, 0, 320, 540)
        webview = WKWebView.alloc().initWithFrame_configuration_(frame, cfg)
        webview.setValue_forKey_(False, "drawsBackground")
        self._webview = webview

        webview.loadHTMLString_baseURL_(_HTML, None)

        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            frame, _TITLED | _CLOSABLE, NSBackingStoreBuffered, False
        )
        panel.setTitle_("How to use Stem2AAF")
        panel.setContentView_(webview)
        panel.setReleasedWhenClosed_(False)
        panel.center()
        self._panel = panel

        # Give the handler a reference to the panel so Close works
        handler._panel = panel

    def show(self):
        NSApp.activateIgnoringOtherApps_(True)
        self._panel.makeKeyAndOrderFront_(None)
