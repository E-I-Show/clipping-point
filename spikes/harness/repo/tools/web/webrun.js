#!/usr/bin/env node
// Open a Pyxel Web page in headless Chromium, capture console / errors / screenshots,
// and decide pass or fail.
//
//   node tools/webrun.js --url <file path | file:// | http://...> [options]
//
// Options
//   --mirror DIR      Fulfil https://kitao.dev/** from DIR/kitao.dev/** (unmodified app2html HTML).
//                     Without it the page must reach its runtime by itself (e.g. patched pyxel.js).
//   --until REGEX     Console line that marks success (default: ^SPIKE_DONE). Required to pass.
//   --timeout MS      Overall time limit after the page is opened (default 120000).
//   --shot FILE       Screenshot of the page after success/failure/timeout.
//   --json FILE       Write the full result (console lines, errors, timings) as JSON.
//   --no-click        Do not dismiss the "click to start" prompt.
//   --downloads DIR   Save browser downloads into DIR.
//   --upload FILE     File to hand to the next <input type=file> chooser.
//   --settle MS       Extra wait after --until matched before taking the screenshot (default 300).
//   --on "REGEX=>ACT" When a console line matches REGEX (first time only) run ACT:
//                       key:<Name>     press a key (Playwright key name, e.g. o, Enter, ArrowLeft)
//                       click          click the middle of the page
//                       drop:<file>    dispatch a real "drop" event with that file on div#pyxel-screen
//                       upload:<file>  answer the next file chooser with that file
//                       reload         reload the page and pass the start gate again
//   --allow REGEX     Do not count failure details matching REGEX (use sparingly, say why).
//   --quiet           Do not echo console lines.
//   --profile DIR     Use a persistent browser profile in DIR (storage survives between runs).
//   --init-script F   JavaScript file evaluated in the page before any page script (e.g. a fake gamepad).
//                     (--on also accepts  eval:<javascript>  to run code in the page.)
//
// Exit code: 0 = until-line seen and no failure signal. 1 = failure. 2 = usage.
//
// Failure signals (any one fails the run):
//   - a console message of type "error"
//   - an uncaught page error
//   - a failed request or an HTTP status >= 400
//   - the element #pyxel-error-overlay exists (Pyxel's Python traceback overlay)
//   - window.pyxelContext.hasFatalError
//   - the until-line never appeared (timeout)  <- a silent hang is a failure, not a pass
const fs = require("fs");
const path = require("path");
const { pathToFileURL } = require("url");
const { chromium } = require("playwright");

const args = process.argv.slice(2);
const opt = { until: "^SPIKE_DONE", timeout: 120000, settle: 300, click: true, quiet: false, on: [], allow: [] };
for (let i = 0; i < args.length; i++) {
  const a = args[i];
  const next = () => args[++i];
  if (a === "--url") opt.url = next();
  else if (a === "--mirror") opt.mirror = next();
  else if (a === "--until") opt.until = next();
  else if (a === "--timeout") opt.timeout = Number(next());
  else if (a === "--shot") opt.shot = next();
  else if (a === "--json") opt.json = next();
  else if (a === "--no-click") opt.click = false;
  else if (a === "--downloads") opt.downloads = next();
  else if (a === "--upload") opt.upload = next();

  else if (a === "--settle") opt.settle = Number(next());
  else if (a === "--on") {
    const spec = next();
    const i = spec.indexOf("=>");
    opt.on.push({ re: new RegExp(spec.slice(0, i)), action: spec.slice(i + 2), fired: false });
  } else if (a === "--allow") opt.allow.push(new RegExp(next()));
  else if (a === "--quiet") opt.quiet = true;
  else if (a === "--profile") opt.profile = next();
  else if (a === "--init-script") opt.initScript = next();
  else {
    console.error(`unknown option ${a}`);
    process.exit(2);
  }
}
if (!opt.url) {
  console.error("--url is required");
  process.exit(2);
}
let url = opt.url;
if (!/^[a-z]+:\/\//.test(url)) url = pathToFileURL(path.resolve(url)).href;

const MIME = {
  ".js": "text/javascript",
  ".mjs": "text/javascript",
  ".wasm": "application/wasm",
  ".json": "application/json",
  ".zip": "application/zip",
  ".whl": "application/octet-stream",
  ".py": "text/plain; charset=utf-8",
  ".css": "text/css",
  ".png": "image/png",
  ".ico": "image/x-icon",
};

(async () => {
  const t0 = Date.now();
  const result = {
    url,
    mirror: opt.mirror || null,
    console: [],
    failures: [],
    requests: [],
    downloads: [],
    allowed: [],
    actions: [],
    filechoosers: [],
    passed: false,
  };
  const fail = (kind, detail) => {
    const entry = { t: Date.now() - t0, kind, detail };
    if (opt.allow.some((re) => re.test(`${kind}: ${detail}`))) {
      result.allowed.push(entry);
    } else {
      result.failures.push(entry);
    }
  };
  const pending = [];

  let browser = null;
  let context;
  const ctxOptions = { acceptDownloads: true, viewport: { width: 960, height: 720 } };
  if (opt.profile) {
    context = await chromium.launchPersistentContext(opt.profile, ctxOptions);
  } else {
    browser = await chromium.launch();
    context = await browser.newContext(ctxOptions);
  }
  if (opt.initScript) await context.addInitScript({ path: opt.initScript });
  const page = await context.newPage();

  if (opt.mirror) {
    // Serve the CDN from disk. CORS header: the page may be file:// (origin "null").
    await context.route("https://kitao.dev/**", async (route) => {
      const u = new URL(route.request().url());
      const file = path.join(opt.mirror, "kitao.dev", decodeURIComponent(u.pathname));
      if (!file.startsWith(path.resolve(opt.mirror)) && !path.resolve(file).startsWith(path.resolve(opt.mirror))) {
        return route.abort();
      }
      if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) {
        return route.fulfill({ status: 404, body: "not in mirror" });
      }
      await route.fulfill({
        status: 200,
        body: fs.readFileSync(file),
        headers: {
          "content-type": MIME[path.extname(file)] || "application/octet-stream",
          "access-control-allow-origin": "*",
        },
      });
    });
    await context.route("https://cdn.jsdelivr.net/**", (route) => route.fulfill({ status: 404, body: "not in mirror" }));
  }

  let untilSeen = null;
  const untilRe = new RegExp(opt.until);
  page.on("console", (msg) => {
    const text = msg.text();
    const entry = { t: Date.now() - t0, type: msg.type(), text };
    result.console.push(entry);
    if (!opt.quiet) console.log(`[${String(entry.t).padStart(6)}ms ${entry.type}] ${text}`);
    if (msg.type() === "error") fail("console.error", text);
    if (untilSeen === null && untilRe.test(text)) untilSeen = entry.t;
    for (const rule of opt.on) {
      if (!rule.fired && rule.re.test(text)) {
        rule.fired = true;
        pending.push(rule.action);
      }
    }
  });
  page.on("pageerror", (err) => fail("pageerror", String(err && err.stack ? err.stack : err)));
  page.on("requestfailed", (req) => {
    fail("requestfailed", `${req.url().slice(0, 200)} ${req.failure() ? req.failure().errorText : ""}`);
  });
  page.on("response", (res) => {
    const u = res.url();
    if (!u.startsWith("data:") && !u.startsWith("blob:")) {
      result.requests.push({ t: Date.now() - t0, status: res.status(), url: u.slice(0, 200) });
    }
    if (res.status() >= 400) fail("http", `${res.status()} ${u.slice(0, 200)}`);
  });
  page.on("download", async (dl) => {
    const name = dl.suggestedFilename();
    const entry = { t: Date.now() - t0, name };
    if (opt.downloads) {
      fs.mkdirSync(opt.downloads, { recursive: true });
      const dst = path.join(opt.downloads, name);
      await dl.saveAs(dst);
      entry.path = dst;
      entry.size = fs.statSync(dst).size;
    }
    result.downloads.push(entry);
    if (!opt.quiet) console.log(`[download] ${JSON.stringify(entry)}`);
  });
  page.on("filechooser", async (chooser) => {
    const entry = { t: Date.now() - t0, answeredWith: opt.upload || null };
    result.filechoosers.push(entry);
    if (opt.upload) {
      await chooser.setFiles(opt.upload);
      if (!opt.quiet) console.log(`[filechooser] opened at ${entry.t}ms, set ${opt.upload}`);
    } else {
      if (!opt.quiet) console.log(`[filechooser] opened at ${entry.t}ms but no file to give`);
    }
  });

  const passStartGate = async () => {
    // Dismiss the "click to start" gate (needed for audio; the app does not run before it).
    if (!opt.click) return;
    try {
      await page.waitForSelector("img#pyxel-prompt", { timeout: opt.timeout, state: "attached" });
      result.promptAt = Date.now() - t0;
      await page.mouse.click(480, 360);
      result.clickedAt = Date.now() - t0;
    } catch (e) {
      fail("no-start-prompt", String(e).slice(0, 300));
    }
  };

  const runAction = async (action) => {
    result.actions.push({ t: Date.now() - t0, action });
    if (!opt.quiet) console.log(`[action] ${action}`);
    if (action.startsWith("key:")) {
      const k = action.slice(4);
      await page.keyboard.down(k);
      await page.waitForTimeout(120);
      await page.keyboard.up(k);
    } else if (action === "click") {
      await page.mouse.click(480, 360);
    } else if (action.startsWith("upload:")) {
      opt.upload = action.slice(7);
    } else if (action.startsWith("drop:")) {
      const file = action.slice(5);
      const data = [...fs.readFileSync(file)];
      const name = path.basename(file);
      // Same path a user's drag-and-drop takes: a real DragEvent carrying a File.
      await page.evaluate(
        ({ name, data }) => {
          const dt = new DataTransfer();
          dt.items.add(new File([new Uint8Array(data)], name, { type: "application/octet-stream" }));
          const target = document.querySelector("div#pyxel-screen");
          target.dispatchEvent(new DragEvent("dragover", { dataTransfer: dt, bubbles: true, cancelable: true }));
          target.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true }));
        },
        { name, data },
      );
    } else if (action.startsWith("eval:")) {
      await page.evaluate(action.slice(5));
    } else if (action === "reload") {
      await page.reload({ waitUntil: "load" });
      await passStartGate();
    } else {
      fail("driver", `unknown action ${action}`);
    }
  };

  await page.goto(url, { waitUntil: "load", timeout: opt.timeout });
  await passStartGate();

  const deadline = Date.now() + opt.timeout;
  while (Date.now() < deadline && untilSeen === null) {
    while (pending.length) {
      try {
        await runAction(pending.shift());
      } catch (e) {
        fail("driver", String(e).slice(0, 300));
      }
    }
    // Stop early when Pyxel reported a Python error: nothing more will happen.
    const overlay = await page.evaluate(() => !!document.getElementById("pyxel-error-overlay")).catch(() => false);
    if (overlay) {
      await page.waitForTimeout(300);
      break;
    }
    await page.waitForTimeout(50);
  }
  await page.waitForTimeout(opt.settle);

  const state = await page
    .evaluate(() => {
      const o = document.getElementById("pyxel-error-overlay");
      const c = document.querySelector("canvas#canvas");
      return {
        overlayText: o ? o.textContent : null,
        hasFatalError: !!(window.pyxelContext && window.pyxelContext.hasFatalError),
        initialized: !!(window.pyxelContext && window.pyxelContext.initialized),
        canvas: c ? { width: c.width, height: c.height, cssW: c.clientWidth, cssH: c.clientHeight } : null,
      };
    })
    .catch((e) => ({ evalError: String(e) }));
  result.state = state;
  if (state.overlayText !== null && state.overlayText !== undefined) fail("pyxel-error-overlay", state.overlayText);
  if (state.hasFatalError) fail("hasFatalError", "window.pyxelContext.hasFatalError is true");
  if (untilSeen === null) fail("until-not-seen", `no console line matched /${opt.until}/ within ${opt.timeout} ms`);
  result.untilAt = untilSeen;

  if (opt.shot) {
    fs.mkdirSync(path.dirname(path.resolve(opt.shot)), { recursive: true });
    await page.screenshot({ path: opt.shot });
  }
  await context.close();
  if (browser) await browser.close();

  result.elapsedMs = Date.now() - t0;
  result.passed = result.failures.length === 0;
  if (opt.json) {
    fs.mkdirSync(path.dirname(path.resolve(opt.json)), { recursive: true });
    fs.writeFileSync(opt.json, JSON.stringify(result, null, 1));
  }
  console.log(`RESULT ${result.passed ? "PASS" : "FAIL"} elapsed=${result.elapsedMs}ms failures=${result.failures.length}`);
  for (const f of result.failures) console.log(`  FAILURE ${f.kind}: ${String(f.detail).split("\n").slice(0, 12).join("\n    ")}`);
  process.exit(result.passed ? 0 : 1);
})().catch((e) => {
  console.error("runner crashed:", e);
  process.exit(1);
});
