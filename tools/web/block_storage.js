// 保存先に触れると例外になる文書の代わり。ブラウザ版の煙テスト（tools/web_smoke.py の筋書き storage_blocked）が、ページを開く前に差し込む。
// window.localStorage を読むと、SecurityError の DOMException を投げる（保存を止めたブラウザや、埋め込み先での見え方）。
// アプリは、起動時の試し書きで、これを捕まえて、メモリの保存先へ切り替える（clipping_point/cp_app/storage_select.py）。
//
// 投げる物には、stack（文字列）を付ける。ブラウザが自分で投げる例外は stack を持つ（実測）。スクリプトで作っただけの
// DOMException には無く、Pyodide が別の Error に包み直して、Pythonから見える例外の名が "Error" になる（実測）。
// stack を付けると、Pythonからは、名が "SecurityError" の JsException に見える。
// ランタイム（Pyxel と Pyodide）は、自分では localStorage に触れない（これを差し込んでも、ほかの理由では落ちない。実測）。
(() => {
  const MESSAGE = "Failed to read the 'localStorage' property from 'Window': Access is denied for this document.";
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    get() {
      const error = new DOMException(MESSAGE, "SecurityError");
      Object.defineProperty(error, "stack", { value: `SecurityError: ${MESSAGE}\n    at get localStorage (block_storage.js)` });
      throw error;
    },
  });
})();
