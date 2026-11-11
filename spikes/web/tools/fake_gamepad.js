// Synthetic "standard mapping" gamepad for headless tests. Shape follows the W3C Gamepad API.
// window.__pad is the live object; tests mutate it and bump timestamp.
(() => {
  const pad = {
    id: "Fake Standard Gamepad (STANDARD GAMEPAD Vendor: 045e Product: 028e)",
    index: 0,
    connected: true,
    mapping: "standard",
    timestamp: performance.now(),
    axes: [0, 0, 0, 0],
    buttons: Array.from({ length: 17 }, () => ({ pressed: false, touched: false, value: 0 })),
    vibrationActuator: null,
  };
  window.__pad = pad;
  window.__padStep = 0;
  navigator.getGamepads = () => [pad, null, null, null];
  window.__padConnect = () => {
    const ev = new Event("gamepadconnected");
    ev.gamepad = pad;
    window.dispatchEvent(ev);
    window.__padStep = 1;
  };
  window.__padSet = (step, axes, buttons) => {
    pad.axes = axes;
    for (const [i, v] of Object.entries(buttons)) {
      pad.buttons[i] = { pressed: v > 0.1, touched: v > 0, value: v };
    }
    pad.timestamp = performance.now();
    window.__padStep = step;
  };
})();
