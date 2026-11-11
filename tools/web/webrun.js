#!/usr/bin/env node
// ブラウザの実行役。ヘッドレスのChromiumでHTMLを開き、起きたことを集めて、結果をJSONに書く。
// 合否は決めない。決めるのは tools/web_smoke.py。元は spikes/web/tools/webrun.js。
//
//   node tools/web/webrun.js --html FILE --mirror DIR --json FILE
//                            [--init-script JS] [--until REGEX] [--watch-ms N] [--timeout-ms N] [--shot FILE]
//                            [--local-storage PREFIX]
//
//   --html FILE      開くHTML。書き換えずに、そのまま file:// で開く
//   --mirror DIR     ランタイムの写し（tools/web/fetch_runtime.py が組み立てた mirror/）
//   --json FILE      結果を書く先
//   --init-script JS ページのどのスクリプトよりも前に実行するJavaScript。値をHTMLの外から渡すのに使う
//                    （例：window.CP_PROBE = {"ticks": 660}; 名前と形は clipping_point/cp_app/web_bridge.py）
//   --until REGEX    この形のコンソールの行が出るまで待つ（完了の合図）
//   --watch-ms N     開始のクリックの後、少なくともこの間は見続ける（既定 0）
//   --timeout-ms N   全体の時間切れ（既定 90000）
//   --shot FILE      最後の画面（canvas）のPNGを保存する
//   --local-storage PREFIX  終わりに、ページの localStorage の、鍵が PREFIX で始まるものを全部読んで、結果に入れる
//                    （localStorage: {prefix, entries: {鍵: 値}, error}。読めなければ entries が null で、error に理由）
//
// ランタイムへの要求（https://kitao.dev/…）は、ランタイムの写し（--mirror）のファイルで応える。
// そこに無いファイルへの要求と、その外へ出る要求（ほかのホスト、ほかのファイル）は、通さずに失敗として記す。
// 集める失敗の種類（failures[].kind）：
//   no_start_prompt  開始の表示（img#pyxel-prompt）が出ない。ランタイムが読み込めていない
//   unresponsive     ページへの問い合わせが返らない（Pythonが主スレッドを握ったまま、など）
//   error_overlay    Pyxelのエラー表示（#pyxel-error-overlay）がある。Pythonの例外
//   fatal_error      window.pyxelContext.hasFatalError
//   console_error    種類が error のコンソールの行
//   page_error       ページの中の、捕まえられなかった例外
//   outside_mirror   ランタイムの写しの外への要求
//   not_in_mirror    ランタイムの写しに無いファイルへの要求
//   request_failed   読み込みの失敗
//   http_status      400以上の応答
// 完了の合図が出たか（untilAt）と、画面の画素（canvas）は、失敗に数えずに値だけ書く。
// ページが返らないときも、そこまでに集めた分のJSONを書いてから、ブラウザを閉じる（閉じられなければ、そのまま終わる）。
// 終了コード：0＝結果のJSONを書いた、2＝使い方の誤りか、途中で止まった（JSONは書いていない）。
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const { pathToFileURL } = require("url");
const { chromium } = require("playwright");

const MIRROR_HOST = "kitao.dev";
const VIEWPORT = { width: 960, height: 720 };
const POLL_MS = 50;
const GIVE_UP_AFTER_FAILURE_MS = 1500; // 開始の表示より前に失敗が出たら、これだけ待って切り上げる
const CHANGE_GAP_MS = 400; // 画面が動いているかを見る、2枚の間
const ASK_TIMEOUT_MS = 10000; // ページへの問い合わせが、これだけ返らなければ「返らない」とみなす。ふつうは数msで返る
const CLOSE_TIMEOUT_MS = 5000; // ブラウザを閉じるのを待つ上限
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

// ページへの問い合わせが、時間の内に返らなかった。
class Unresponsive extends Error {}

// promise が ms の内に終わらなければ、Unresponsive を投げる。
function within(promise, ms, what) {
  promise.catch(() => {}); // 時間切れの後で失敗しても、捕まえられない例外にしない
  let timer;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Unresponsive(`${what} did not return within ${ms} ms`)), ms);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

function usage(message) {
  console.error(`webrun: ${message}`);
  process.exit(2);
}

function parseArgs(argv) {
  const opt = { watchMs: 0, timeoutMs: 90000 };
  const names = {
    "--html": "html", "--mirror": "mirror", "--json": "json", "--init-script": "initScript",
    "--until": "until", "--watch-ms": "watchMs", "--timeout-ms": "timeoutMs", "--shot": "shot",
    "--local-storage": "localStorage",
  };
  for (let i = 0; i < argv.length; i += 2) {
    const name = names[argv[i]];
    if (!name || i + 1 >= argv.length) usage(`unknown or incomplete option ${argv[i]}`);
    opt[name] = name.endsWith("Ms") ? Number(argv[i + 1]) : argv[i + 1];
  }
  for (const must of ["html", "mirror", "json"]) if (!opt[must]) usage(`--${must} is required`);
  if (!Number.isFinite(opt.watchMs) || !Number.isFinite(opt.timeoutMs)) usage("--watch-ms and --timeout-ms take numbers");
  return opt;
}

// PNGを別のページで読み、色ごとの画素を数える。いちばん多い色を背景とみなす。
async function countPixels(browser, png) {
  const context = await browser.newContext();
  try {
    const page = await context.newPage();
    return await page.evaluate(async (b64) => {
      const img = new Image();
      img.src = "data:image/png;base64," + b64;
      await img.decode();
      const canvas = document.createElement("canvas");
      canvas.width = img.naturalWidth;
      canvas.height = img.naturalHeight;
      const g = canvas.getContext("2d");
      g.drawImage(img, 0, 0);
      const data = g.getImageData(0, 0, canvas.width, canvas.height).data;
      const counts = new Map();
      for (let i = 0; i < data.length; i += 4) {
        const key = (data[i] << 16) | (data[i + 1] << 8) | data[i + 2];
        counts.set(key, (counts.get(key) || 0) + 1);
      }
      let background = 0;
      let most = 0;
      for (const [key, n] of counts) {
        if (n > most) {
          most = n;
          background = key;
        }
      }
      const total = data.length / 4;
      return {
        shotWidth: canvas.width,
        shotHeight: canvas.height,
        pixels: total,
        colors: counts.size,
        background: "#" + background.toString(16).padStart(6, "0"),
        ink: total - most, // 背景と違う色の画素の数
      };
    }, png.toString("base64"));
  } finally {
    await context.close();
  }
}

// ページを開いて、開始のクリックから最後の画面までを進める。ページが返らなければ Unresponsive を投げる。
async function drive(browser, page, opt, result, env) {
  const { now, deadline, untilRe, fail, pageUrl } = env;
  // ページの中で fn を実行する（arg は、fn へ渡す値）。返らなければ Unresponsive。ほかの失敗（ページの切り替わりなど）は fallback を返す。
  const ask = (fn, fallback, arg) =>
    within(page.evaluate(fn, arg), ASK_TIMEOUT_MS, "page.evaluate").catch((e) => {
      if (e instanceof Unresponsive) throw e;
      return fallback;
    });

  await page.goto(pageUrl, { waitUntil: "load", timeout: opt.timeoutMs });
  // 開始の表示を待って、クリックする。音のために、クリックの前はアプリが動かない。
  let firstFailureAt = null;
  while (Date.now() < deadline) {
    if (await ask(() => !!document.querySelector("img#pyxel-prompt"), false)) {
      result.promptAt = now();
      break;
    }
    if (result.failures.length && firstFailureAt === null) firstFailureAt = Date.now();
    if (firstFailureAt !== null && Date.now() - firstFailureAt >= GIVE_UP_AFTER_FAILURE_MS) break;
    await page.waitForTimeout(POLL_MS);
  }
  if (result.promptAt === null) {
    fail("no_start_prompt", "img#pyxel-prompt did not appear");
  } else {
    await within(page.mouse.click(VIEWPORT.width / 2, VIEWPORT.height / 2), ASK_TIMEOUT_MS, "page.mouse.click");
    result.clickedAt = now();
    while (Date.now() < deadline) {
      const watched = now() - result.clickedAt >= opt.watchMs;
      if (watched && (untilRe === null || result.untilAt !== null)) break;
      // Pythonの例外が出たら、この先は何も起きない。
      if (await ask(() => !!document.getElementById("pyxel-error-overlay"), false)) break;
      await page.waitForTimeout(POLL_MS);
    }
    await page.waitForTimeout(300); // エラー表示は、標準エラーの行を100 msまとめてから出る
  }

  result.state = await ask(
    () => {
      const overlay = document.getElementById("pyxel-error-overlay");
      const context = window.pyxelContext;
      return {
        overlayText: overlay ? overlay.textContent : null,
        hasFatalError: !!(context && context.hasFatalError),
        initialized: !!(context && context.initialized),
      };
    },
    { evalError: true },
  );
  if (result.state.overlayText) fail("error_overlay", result.state.overlayText);
  if (result.state.hasFatalError) fail("fatal_error", "window.pyxelContext.hasFatalError is true");

  // 画面（canvas）の画素。ページの中からは読めない（WebGLの絵は残らない）ので、スクリーンショットを数える。
  const box = await ask(() => {
    const canvas = document.querySelector("canvas#canvas");
    if (!canvas) return null;
    const r = canvas.getBoundingClientRect();
    return { x: r.x, y: r.y, width: r.width, height: r.height, pixelWidth: canvas.width, pixelHeight: canvas.height };
  }, null);
  if (box && box.width >= 1 && box.height >= 1) {
    const clip = { x: box.x, y: box.y, width: box.width, height: box.height };
    const first = await within(page.screenshot({ clip }), ASK_TIMEOUT_MS, "page.screenshot");
    await page.waitForTimeout(CHANGE_GAP_MS);
    const png = await within(page.screenshot({ clip }), ASK_TIMEOUT_MS, "page.screenshot");
    if (opt.shot) {
      fs.mkdirSync(path.dirname(path.resolve(opt.shot)), { recursive: true });
      fs.writeFileSync(opt.shot, png);
    }
    result.canvas = { ...box, ...(await countPixels(browser, png)), changed: !first.equals(png), changeGapMs: CHANGE_GAP_MS };
  }

  // localStorage の中身。頼まれたときだけ読む。合否は決めない（筋書き probe で保存の往復の値を照らすのも、
  // 筋書き shipped で鍵が1つも無いことを見るのも tools/web_smoke.py）。
  if (opt.localStorage) {
    result.localStorage = await ask(
      (prefix) => {
        try {
          const entries = {};
          for (let i = 0; i < window.localStorage.length; i += 1) {
            const key = window.localStorage.key(i);
            if (key !== null && key.startsWith(prefix)) entries[key] = window.localStorage.getItem(key);
          }
          return { prefix, entries, error: null };
        } catch (e) {
          return { prefix, entries: null, error: String(e) }; // localStorage に触れると例外になる文書
        }
      },
      { prefix: opt.localStorage, entries: null, error: "page.evaluate failed" },
      opt.localStorage,
    );
  }
}

async function main() {
  const opt = parseArgs(process.argv.slice(2));
  const t0 = Date.now();
  const now = () => Date.now() - t0;
  const htmlPath = path.resolve(opt.html);
  const mirrorRoot = path.resolve(opt.mirror);
  const hostRoot = path.join(mirrorRoot, MIRROR_HOST);
  const pageUrl = pathToFileURL(htmlPath).href;
  const result = {
    html: htmlPath,
    htmlSha256: crypto.createHash("sha256").update(fs.readFileSync(htmlPath)).digest("hex"),
    url: pageUrl,
    mirror: mirrorRoot,
    initScript: opt.initScript || null,
    until: opt.until || null,
    watchMs: opt.watchMs,
    timeoutMs: opt.timeoutMs,
    console: [],
    failures: [],
    requests: [],
    promptAt: null,
    clickedAt: null,
    untilAt: null,
    state: null,
    canvas: null,
    localStorage: null,
    elapsedMs: null,
  };
  const fail = (kind, detail) => result.failures.push({ t: now(), kind, detail: String(detail).slice(0, 4000) });
  const deadline = t0 + opt.timeoutMs;
  const untilRe = opt.until ? new RegExp(opt.until) : null;

  const browser = await chromium.launch();
  const closeBrowser = () => within(browser.close(), CLOSE_TIMEOUT_MS, "browser.close").catch(() => {});
  try {
    const context = await browser.newContext({ viewport: VIEWPORT });
    if (opt.initScript) await context.addInitScript(opt.initScript);
    const refused = new Set(); // ここで通さなかった要求。読み込みの失敗として二重に数えない
    await context.route("**/*", async (route) => {
      const url = route.request().url();
      if (url === pageUrl || url.startsWith("data:") || url.startsWith("blob:")) return route.continue();
      let target = null;
      try {
        const u = new URL(url);
        if (u.protocol === "https:" && u.hostname === MIRROR_HOST) target = path.join(hostRoot, decodeURIComponent(u.pathname));
      } catch (e) {
        target = null;
      }
      if (target === null) {
        refused.add(url);
        fail("outside_mirror", url);
        return route.abort();
      }
      const inside = path.resolve(target).startsWith(hostRoot + path.sep);
      if (!inside || !fs.existsSync(target) || !fs.statSync(target).isFile()) {
        refused.add(url);
        fail("not_in_mirror", url);
        return route.abort();
      }
      result.requests.push({ t: now(), url: url.slice(0, 300), served: path.relative(mirrorRoot, target) });
      // 開くページは file://（origin が null）なので、どこからでも読めるように応える。
      return route.fulfill({
        status: 200,
        body: fs.readFileSync(target),
        headers: { "content-type": MIME[path.extname(target)] || "application/octet-stream", "access-control-allow-origin": "*" },
      });
    });

    const page = await context.newPage();
    page.on("console", (msg) => {
      const entry = { t: now(), type: msg.type(), text: msg.text() };
      result.console.push(entry);
      if (entry.type === "error") fail("console_error", entry.text);
      if (untilRe && result.untilAt === null && untilRe.test(entry.text)) result.untilAt = entry.t;
    });
    page.on("pageerror", (err) => fail("page_error", err && err.stack ? err.stack : err));
    page.on("requestfailed", (req) => {
      if (!refused.has(req.url())) fail("request_failed", `${req.url().slice(0, 300)} ${req.failure() ? req.failure().errorText : ""}`);
    });
    page.on("response", (res) => {
      if (res.status() >= 400) fail("http_status", `${res.status()} ${res.url().slice(0, 300)}`);
    });

    try {
      await drive(browser, page, opt, result, { now, deadline, untilRe, fail, pageUrl });
    } catch (e) {
      if (!(e instanceof Unresponsive)) throw e;
      fail("unresponsive", e.message); // 集めた分は、下でJSONに書く
    }
  } catch (e) {
    await closeBrowser();
    throw e;
  }
  // 先にJSONを書く。ページが返らないときは、ブラウザを閉じるのも返らないことがある。
  result.elapsedMs = now();
  fs.mkdirSync(path.dirname(path.resolve(opt.json)), { recursive: true });
  fs.writeFileSync(opt.json, JSON.stringify(result, null, 1));
  console.log(
    `webrun: wrote ${opt.json} elapsed_ms=${result.elapsedMs} failures=${result.failures.length} ` +
      `until_at=${result.untilAt} canvas_ink=${result.canvas ? result.canvas.ink : null}`,
  );
  await closeBrowser();
  process.exit(0); // 閉じられなかったブラウザを待たない
}

main().catch((e) => {
  console.error("webrun: stopped:", e);
  process.exit(2);
});
