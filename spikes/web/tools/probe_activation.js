// Does headless Chromium under Playwright enforce "file chooser needs a user activation"?
// Plain page, no Pyxel. No input at all is sent before input.click().
const { chromium } = require("playwright");
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const logs = [];
  page.on("console", (m) => logs.push(`${m.type()}: ${m.text()}`));
  let chooser = 0;
  page.on("filechooser", () => chooser++);
  await page.setContent(`<input id=f type=file><script>
    setTimeout(() => { console.log('isActive=' + navigator.userActivation.isActive + ' hasBeenActive=' + navigator.userActivation.hasBeenActive); document.getElementById('f').click(); }, 500);
  </script>`);
  await page.waitForTimeout(1500);
  console.log(JSON.stringify({ case: "no input ever, with filechooser listener", chooserEvents: chooser, logs }));
  await browser.close();

  // Same without a filechooser listener (Playwright then does not intercept the dialog).
  const b2 = await chromium.launch();
  const p2 = await b2.newPage();
  const logs2 = [];
  p2.on("console", (m) => logs2.push(`${m.type()}: ${m.text()}`));
  await p2.setContent(`<input id=f type=file><script>
    setTimeout(() => { document.getElementById('f').click(); console.log('clicked without activation'); }, 500);
  </script>`);
  await p2.waitForTimeout(1500);
  console.log(JSON.stringify({ case: "no input ever, no listener", logs: logs2 }));
  // key press then check activation
  await p2.setContent(`<body tabindex=0><script>
    document.addEventListener('keydown', () => console.log('keydown isActive=' + navigator.userActivation.isActive));
    document.addEventListener('mousedown', () => console.log('mousedown isActive=' + navigator.userActivation.isActive));
  </script>`);
  await p2.keyboard.press("o");
  await p2.waitForTimeout(100);
  console.log(JSON.stringify({ afterKey: await p2.evaluate(() => navigator.userActivation.isActive) }));
  await p2.mouse.click(50, 50);
  await p2.waitForTimeout(100);
  console.log(JSON.stringify({ afterClick: await p2.evaluate(() => navigator.userActivation.isActive), logs: logs2 }));
  await b2.close();
})();
