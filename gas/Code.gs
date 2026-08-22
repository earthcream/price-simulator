// 価格波及シミュレーターのメール登録を受け取り、スプレッドシートに1行追記する
// デプロイ手順は docs/メール登録の設定手順.md を参照

const SPREADSHEET_ID = "1wxOAYMw8zZfLwHx1T_lXk1rNeeOd0p-_xqP-Ea9c-xA";
const SHEET_NAME = "まとめてやるぜ";   // 見つからない場合は下の SHEET_GID で探す
const SHEET_GID = 1915479797;

function getSheet_() {
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  let sh = ss.getSheetByName(SHEET_NAME);
  if (!sh) sh = ss.getSheets().find(s => s.getSheetId() === SHEET_GID);
  if (!sh) throw new Error("シートが見つかりません: " + SHEET_NAME);
  return sh;
}

// サイトからのPOSTを受ける
function doPost(e) {
  const p = (e && e.parameter) || {};
  const email = String(p.email || "").trim();
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email)) {
    return ContentService.createTextOutput("invalid");
  }
  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    const sh = getSheet_();
    // 列: 取得元 / 日時 / メールアドレス（既存シートの並びに合わせる）
    sh.appendRow(["価格シミュレーション", new Date(), email]);
  } finally {
    lock.releaseLock();
  }
  return ContentService.createTextOutput("ok");
}

// 動作確認用（ブラウザでウェブアプリURLを開くと表示される）
function doGet() {
  return ContentService.createTextOutput("price-simulator mail endpoint: alive");
}

// エディタから実行してシートへの書き込み権限を承認するためのテスト関数
function testAppend() {
  getSheet_().appendRow(["価格シミュレーション", new Date(), "test@example.com"]);
}
