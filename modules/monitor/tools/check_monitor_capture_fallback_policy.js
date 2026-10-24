"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
require(path.join(__dirname, "..", "extension", "monitor-ui-layout.js"));
const layout = globalThis.MonitorUiLayout;
assert.match(layout.ENDPOINT, /capture_fallback=1/, "new Monitor must request extended schema");
const source = fs.readFileSync(path.join(__dirname, "..", "extension", "monitor.js"), "utf8");
const css = fs.readFileSync(path.join(__dirname, "..", "extension", "monitor-ui-layout.css"), "utf8");
const start = source.indexOf("function monitorWindowFallbackDataUri(");
const end = source.indexOf("async function captureDesktopFrame(", start);
assert.ok(start > 0 && end > start, "fallback image is independently bounded");
const chooseStart = source.indexOf("function monitorChooseCaptureView(");
assert.ok(chooseStart > 0 && chooseStart < start, "renderer compatibility fallback is independently bounded");
const ctx = { encodeURIComponent, Date, Number, String, MonitorUiLayout: layout,
  bwmUiLayoutControl: { read: () => ({
  captureFallback: {mode:"last_good", staleAfterSeconds:20, maxAgeSeconds:180}
})}};
vm.createContext(ctx);
vm.runInContext(source.slice(chooseStart,end)+
  "; globalThis.draw = monitorWindowFallbackDataUri; globalThis.choose = monitorChooseCaptureView;",ctx);
const compatible = ctx.choose({nextState:"captured",nextSource:"blob:compatible",now:100});
assert.equal(compatible.state,"captured");
ctx.MonitorUiLayout = {};
const partialPayload = ctx.choose({nextState:"captured",nextSource:"blob:partial",now:200});
assert.equal(partialPayload.state,"captured", "partial layout payload must not abort thumbnail rendering");
assert.equal(ctx.choose({nextState:"placeholder",nextSource:"",now:200}).state,"placeholder");
ctx.MonitorUiLayout = layout;
const compact = decodeURIComponent(ctx.draw({title:"YouTube - Chrome"}).split(",",2)[1]);
assert.match(compact, /<svg.*width="480".*height="270"/);
assert.match(compact, /<rect x="8" y="8" width="214" height="52"/);
assert.doesNotMatch(compact, /<rect x="18" y="18" width="444"/, "large fallback must be hidden by default");
ctx.bwmUiLayoutControl.read = () => ({captureFallback:{mode:"legacy"}});
const legacy = decodeURIComponent(ctx.draw({title:"YouTube - Chrome"}).split(",",2)[1]);
assert.match(legacy, /<rect x="18" y="18" width="444"/, "explicit rollback mode preserves legacy");
assert.match(css, /\.monitor-window-capture-age-label[\s\S]*pointer-events:\s*none;/);
assert.match(source, /captureFailureReason = nextCaptureState === "captured"/);
assert.match(source, /Number\(entry\.item\?\.cloaked/);
assert.match(source, /monitorCapturedAt/);
assert.match(source, /captureView\.label/);
assert.match(source, /monitorChooseCaptureView/);
assert.match(source, /bwm-thumbnail-policy-changed/);
assert.match(source, /nextCapturedAt: nextCaptureState==="captured"\?Number\(entry\.capturedAt/);
assert.match(source, /refreshBackgroundThumbs\(/);

const now = 5_000_000;
const first = layout.chooseCaptureView({nextState:"captured",nextSource:"blob:real",now});
assert.equal(first.state,"captured");
const cached = layout.chooseCaptureView({nextState:"captured",
  nextSource:"blob:real",nextCapturedAt:now,now:now+40_000});
assert.equal(cached.capturedAt,now,"cached frame may not renew the capture timestamp");
assert.equal(cached.state,"stale", "a 40-second cached frame must be marked old");
const obsoleteCache = layout.chooseCaptureView({nextState:"captured",
  nextSource:"blob:real",nextCapturedAt:now,now:now+181_000});
assert.equal(obsoleteCache.state,"placeholder");
assert.equal(obsoleteCache.source,"");
const fallback = "data:image/svg+xml,SMALL";
const quick = layout.chooseCaptureView({previousState:first.state,previousSource:first.source,
  previousCapturedAt:now,nextState:"placeholder",nextSource:fallback,now:now+5_000});
assert.equal(quick.state,"held");
assert.equal(quick.label,"이전 화면");
const old = layout.chooseCaptureView({previousState:quick.state,previousSource:quick.source,
  previousCapturedAt:now,nextState:"placeholder",nextSource:fallback,now:now+25_000});
assert.equal(old.state,"stale");
assert.equal(old.label,"오래된 화면");
const expired = layout.chooseCaptureView({previousState:old.state,previousSource:old.source,
  previousCapturedAt:now,nextState:"placeholder",nextSource:fallback,now:now+181_000});
assert.equal(expired.state,"placeholder");
assert.equal(expired.source,fallback);
assert.equal(layout.chooseCaptureView({previousState:first.state,previousSource:first.source,
  previousCapturedAt:now,nextState:"placeholder",nextSource:fallback,now:now+1_000},{mode:"compact"}).state,"placeholder");
assert.equal(layout.chooseCaptureView({previousState:first.state,previousSource:first.source,
  previousCapturedAt:now,nextState:"placeholder",nextSource:fallback,now:now+1_000},{mode:"legacy"}).state,"placeholder");
console.log("PASS: compact SVG fallback, legacy mode, bounded last-good/stale retention, provenance, click-through label");
