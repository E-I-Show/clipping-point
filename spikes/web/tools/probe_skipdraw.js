// When draw() returns without drawing (every 2nd call), does the canvas keep the previous image?
// Take 12 screenshots ~35 ms apart; a blank frame would be a much smaller PNG.
const { chromium } = require("playwright");
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 640, height: 480 } });
  await page.goto("http://127.0.0.1:8765/apps/ticks.html#fps=60&skip=1&n=100000");
  await page.waitForSelector("img#pyxel-prompt", { state: "attached" });
  await page.mouse.click(320, 240);
  await page.waitForTimeout(2500);
  const sizes = [];
  for (let i = 0; i < 12; i++) {
    const buf = await page.screenshot();
    sizes.push(buf.length);
    await page.waitForTimeout(35);
  }
  // reference: what a blank canvas looks like
  const blank = await page.evaluate(() => {
    const c = document.querySelector("canvas#canvas");
    return { w: c.width, h: c.height };
  });
  console.log(JSON.stringify({ pngSizes: sizes, min: Math.min(...sizes), max: Math.max(...sizes), canvas: blank }));
  await browser.close();
})();
