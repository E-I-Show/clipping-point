// 偽のコントローラー。ブラウザ版の煙テスト（tools/web_smoke.py の筋書き gamepad）が、ページを開く前に差し込む。
// navigator.getGamepads を差し替えて、予定のとおりに、未接続、接続、値の変化、切断、標準でない並びを順に見せる。
// 元は spikes/web/tools/fake_gamepad.js。
//
// 予定は、このスクリプトの前につなぐ1行で置く。予定と、判定に使う値は tools/web_smoke.py の1か所（PAD_STAGES）に持つ。
//   window.CP_FAKE_PAD_PLAN = [{until: 30, pad: null}, {until: 60, pad: {mapping: "standard", axes: [0, 0, 0, 0], buttons: {"7": 0.3}}}, …]
//     until  この段が終わるtick（この値は、段に入らない）。最後の段は、その後も続く
//     pad    null なら未接続（コントローラーの枠が全部空）。そうでなければ、接続中のコントローラー。
//            mapping は Gamepad API の mapping。axes は4個の軸の値。buttons は、0でないボタンの「番号: 値」
// 予定は、実時間では進めない。getGamepads が呼ばれるたびに、アプリが置く tick の印（window.CP_PROBE_TICK。無ければ0）を見て、
// 段を選ぶ。開始のクリックからアプリが動き始めるまでの時間が、決まらないため。
// 段へ入るたびに、コンソールへ「CP_FAKE_PAD stage=<段の番号。1始まり> tick=<そのときの tick の印>」を出す。
// 段が替わったら、timestamp を進める（ランタイムは、timestamp が変わったときだけ、値を読み直す）。
// 空から接続へ変わったら gamepadconnected、接続から空へ変わったら gamepaddisconnected を、window へ送る。合図には gamepad を付ける。
// 合図は、getGamepads の中から直に送らず、後回しにして送る（呼んでいるのが、アプリの更新の途中のことがあるため）。
// コントローラーには、Gamepad API の形を全部持たせる（ボタン17個、軸4個）。欠けていると、ランタイムが全部の枠を読む所で落ちる（実測）。
(() => {
  const BUTTONS = 17;
  const AXES = 4;
  const SLOTS = 4; // コントローラーの枠の数。Chromiumと同じ
  const PRESSED_OVER = 0.1; // 値がこれを超えたら、押している（試作と同じ）
  const LOG_MARK = "CP_FAKE_PAD";
  const plan = window.CP_FAKE_PAD_PLAN;
  if (!Array.isArray(plan) || plan.length === 0) throw new Error("fake_gamepad: window.CP_FAKE_PAD_PLAN is missing or empty");

  let stage = -1; // いまの段の番号（0始まり）。まだどの段にも入っていなければ −1
  let pad = null; // いま見せているコントローラー。未接続なら null
  let stamp = 0;

  const makeButtons = (values) =>
    Array.from({ length: BUTTONS }, (_, i) => {
      const value = Number(values[i] || 0);
      return { pressed: value > PRESSED_OVER, touched: value > 0, value };
    });
  const makeAxes = (values) => Array.from({ length: AXES }, (_, i) => Number(values[i] || 0));
  const send = (type, gamepad) =>
    setTimeout(() => {
      const event = new Event(type);
      event.gamepad = gamepad;
      window.dispatchEvent(event);
    }, 0);

  const enter = (index, tick) => {
    stage = index;
    console.log(`${LOG_MARK} stage=${index + 1} tick=${tick}`);
    const want = plan[index].pad;
    if (want === null) {
      if (pad !== null) {
        const gone = pad;
        pad = null;
        gone.connected = false;
        send("gamepaddisconnected", gone);
      }
      return;
    }
    const fresh = pad === null;
    if (fresh) {
      pad = { id: "Fake Gamepad (Vendor: 045e Product: 028e)", index: 0, connected: true, vibrationActuator: null, hapticActuators: [] };
    }
    pad.mapping = want.mapping;
    pad.axes = makeAxes(want.axes || []);
    pad.buttons = makeButtons(want.buttons || {});
    stamp = Math.max(stamp + 1, performance.now());
    pad.timestamp = stamp;
    if (fresh) send("gamepadconnected", pad);
  };

  navigator.getGamepads = () => {
    const tick = window.CP_PROBE_TICK || 0;
    let index = plan.findIndex((entry) => tick < entry.until);
    if (index < 0) index = plan.length - 1;
    while (stage < index) enter(stage + 1, tick); // 段を飛ばさずに、順に入る
    const slots = Array.from({ length: SLOTS }, () => null);
    if (pad !== null) slots[0] = pad;
    return slots;
  };
})();
