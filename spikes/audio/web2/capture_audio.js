// Init script: record what SDL2's ScriptProcessorNode hands to the browser (the real Pyxel Web mixer output).
// window.__capSave(name) downloads it as raw s16le mono at the AudioContext sample rate.
(() => {
  const cap = { chunks: [], info: [], frames: 0 };
  window.__cap = cap;
  const hook = (Ctor) => {
    if (!Ctor) return;
    const orig = Ctor.prototype.createScriptProcessor;
    Ctor.prototype.createScriptProcessor = function (...args) {
      const node = orig.apply(this, args);
      const ctx = this;
      const desc = Object.getOwnPropertyDescriptor(ScriptProcessorNode.prototype, "onaudioprocess");
      cap.createArgs = args;
      cap.sampleRate = ctx.sampleRate;
      Object.defineProperty(node, "onaudioprocess", {
        configurable: true,
        get() { return desc.get.call(node); },
        set(fn) {
          desc.set.call(node, function (e) {
            fn.call(this, e);
            const d = e.outputBuffer.getChannelData(0);
            cap.chunks.push(new Float32Array(d));
            if (cap.info.length < 400) cap.info.push([cap.frames, Math.round(performance.now() * 10) / 10, e.playbackTime]);
            cap.frames += d.length;
          });
        },
      });
      return node;
    };
  };
  hook(window.AudioContext);
  hook(window.webkitAudioContext);
  window.__capInfo = () => JSON.stringify({ sampleRate: cap.sampleRate, createArgs: cap.createArgs, frames: cap.frames,
    chunks: cap.chunks.length, chunkLen: cap.chunks.length ? cap.chunks[0].length : 0, info: cap.info.slice(0, 60),
    perfNow: performance.now() });
  window.__capSave = (name) => {
    const out = new Int16Array(cap.frames);
    let o = 0;
    for (const c of cap.chunks) for (let i = 0; i < c.length; i++) out[o++] = Math.max(-32768, Math.min(32767, Math.round(c[i] * 32767)));
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([out.buffer], { type: "application/octet-stream" }));
    a.download = name;
    document.body.appendChild(a);
    a.click();
    return out.length;
  };
})();
