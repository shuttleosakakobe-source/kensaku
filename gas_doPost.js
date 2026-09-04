/**
 * gidを正しく解決してシートを取得するヘルパー
 * ※ SpreadsheetApp.openByUrl() はURLの #gid=... / ?gid=... を無視するため、
 *    そのまま getSheets()[0] を使うと「一番左のシート」しか取れず、
 *    gid で別シートを指定したつもりでも別のシートを触ってしまう。
 *    （TAB4/TAB5でDEST_SHEET_URLのgidを混同していたのはこれが原因）
 */
function getSheetFromUrl(url) {
  var ss = SpreadsheetApp.openByUrl(url);
  var gidMatch = url.match(/[?&#]gid=(\d+)/);
  if (gidMatch) {
    var gid = Number(gidMatch[1]);
    var sheets = ss.getSheets();
    for (var i = 0; i < sheets.length; i++) {
      if (sheets[i].getSheetId() === gid) {
        return sheets[i];
      }
    }
  }
  // gid指定が無い、または一致するシートが見つからない場合は先頭シートにフォールバック
  return ss.getSheets()[0];
}

function doPost(e) {
  try {
    var data = JSON.parse(e.postData.contents);
    var action = data.action || data.status;

    // 💡 日本の現在時刻を確実に取得するコード
    var japanTime = Utilities.formatDate(new Date(), "JST", "yyyy/MM/dd HH:mm:ss");

    // ==========================================
    // 1. タブ1・2用（申請・承認・差戻しなど）
    // 対象: https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/edit?gid=0#gid=0
    // 「ルート変更」「契約内容変更」モードの SUBMIT_ROUTE_CHANGE / SUBMIT_CONTRACT_CHANGE 等も同じ分岐を共用する
    // （target_sheet_url で書き込み先シートを切り替える）
    // ==========================================
    if (action === "SUBMIT_MAINTENANCE" || action === "RESUBMIT_MAINTENANCE" || action === "APPROVE_MAINTENANCE" || action === "REJECT_MAINTENANCE" || action === "DELETE_MAINTENANCE" ||
        action === "SUBMIT_ROUTE_CHANGE" || action === "RESUBMIT_ROUTE_CHANGE" || action === "APPROVE_ROUTE_CHANGE" || action === "REJECT_ROUTE_CHANGE" || action === "DELETE_ROUTE_CHANGE" ||
        action === "SUBMIT_CONTRACT_CHANGE" || action === "RESUBMIT_CONTRACT_CHANGE" || action === "APPROVE_CONTRACT_CHANGE" || action === "REJECT_CONTRACT_CHANGE" || action === "DELETE_CONTRACT_CHANGE" ||
        action === "SUBMIT_SPOT_ROUTE_CHANGE" || action === "RESUBMIT_SPOT_ROUTE_CHANGE" || action === "APPROVE_SPOT_ROUTE_CHANGE" || action === "REJECT_SPOT_ROUTE_CHANGE" || action === "DELETE_SPOT_ROUTE_CHANGE" ||
        action === "SUBMIT_DELIVERY_QTY_CHANGE" || action === "RESUBMIT_DELIVERY_QTY_CHANGE" || action === "APPROVE_DELIVERY_QTY_CHANGE" || action === "REJECT_DELIVERY_QTY_CHANGE" || action === "DELETE_DELIVERY_QTY_CHANGE" ||
        action === "SUBMIT_CUSTOMER_BALANCE_CHANGE" || action === "RESUBMIT_CUSTOMER_BALANCE_CHANGE" || action === "APPROVE_CUSTOMER_BALANCE_CHANGE" || action === "REJECT_CUSTOMER_BALANCE_CHANGE" || action === "DELETE_CUSTOMER_BALANCE_CHANGE" ||
        action === "SUBMIT_PERIOD_STOP_CHANGE" || action === "RESUBMIT_PERIOD_STOP_CHANGE" || action === "APPROVE_PERIOD_STOP_CHANGE" || action === "REJECT_PERIOD_STOP_CHANGE" || action === "DELETE_PERIOD_STOP_CHANGE" ||
        action === "SUBMIT_OTHER_MAINTENANCE_CHANGE" || action === "RESUBMIT_OTHER_MAINTENANCE_CHANGE" || action === "APPROVE_OTHER_MAINTENANCE_CHANGE" || action === "REJECT_OTHER_MAINTENANCE_CHANGE" || action === "DELETE_OTHER_MAINTENANCE_CHANGE" ||
        action === "SUBMIT_CANCEL_CHANGE" || action === "RESUBMIT_CANCEL_CHANGE" || action === "APPROVE_CANCEL_CHANGE" || action === "REJECT_CANCEL_CHANGE" || action === "DELETE_CANCEL_CHANGE") {
      var targetUrl = data.target_sheet_url || "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/edit?gid=0#gid=0";
      var sheet = getSheetFromUrl(targetUrl);

      if (action === "SUBMIT_MAINTENANCE" || action === "SUBMIT_ROUTE_CHANGE" || action === "SUBMIT_CONTRACT_CHANGE" || action === "SUBMIT_SPOT_ROUTE_CHANGE" || action === "SUBMIT_DELIVERY_QTY_CHANGE" || action === "SUBMIT_CUSTOMER_BALANCE_CHANGE" || action === "SUBMIT_PERIOD_STOP_CHANGE" || action === "SUBMIT_OTHER_MAINTENANCE_CHANGE" || action === "SUBMIT_CANCEL_CHANGE") {
        sheet.appendRow(data.full_row);
      } else {
        var rowIndex = data.row_index;
        var range = sheet.getRange(rowIndex, 1, 1, data.updated_row.length);
        range.setValues([data.updated_row]);
      }
      return ContentService.createTextOutput(JSON.stringify({"status": "success"})).setMimeType(ContentService.MimeType.JSON);

    // ==========================================
    // 2. タブ3用（業務転記：タブ1・2用シートの行を「業務転記済」にし、タブ3・4用の実データシートへ追加）
    // 転記先: https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/edit?gid=0#gid=0
    // 「ルート変更」「契約内容変更」モードの TRANSFER_ROUTE_TO_OPERATOR / TRANSFER_CONTRACT_CHANGE_TO_OPERATOR も共用
    // （data.status_col で「業務転記済」を書く列を切り替え、未指定時は商品発注の31列目 = AE列がデフォルト）
    // ==========================================
    } else if (action === "TRANSFER_TO_OPERATOR" || action === "TRANSFER_ROUTE_TO_OPERATOR" || action === "TRANSFER_CONTRACT_CHANGE_TO_OPERATOR" || action === "TRANSFER_SPOT_ROUTE_TO_OPERATOR" || action === "TRANSFER_DELIVERY_QTY_TO_OPERATOR" || action === "TRANSFER_CUSTOMER_BALANCE_TO_OPERATOR" || action === "TRANSFER_PERIOD_STOP_TO_OPERATOR" || action === "TRANSFER_OTHER_MAINTENANCE_TO_OPERATOR" || action === "TRANSFER_CANCEL_TO_OPERATOR") {
      var targetUrl = data.target_sheet_url || "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/edit?gid=0#gid=0";
      var sheet = getSheetFromUrl(targetUrl);
      var rowIndex = data.row_index;
      var statusCol = data.status_col || 31;
      sheet.getRange(rowIndex, statusCol).setValue("業務転記済");

      var destUrl = data.dest_sheet_url || "https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/edit?gid=0#gid=0";
      var destSheet = getSheetFromUrl(destUrl);
      destSheet.appendRow(data.transfer_row);

      return ContentService.createTextOutput(JSON.stringify({"status": "success"})).setMimeType(ContentService.MimeType.JSON);

    // ==========================================
    // 3. タブ4用（メンテナンスチェックの更新）
    // 対象: https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/edit?gid=0#gid=0
    // 「ルート変更」「契約内容変更」モードの UPDATE_ROUTE_CHECK / UPDATE_CONTRACT_CHANGE_CHECK も同じ分岐を共用する
    // ==========================================
    } else if (action === "UPDATE_MAINTENANCE_CHECK" || action === "UPDATE_ROUTE_CHECK" || action === "UPDATE_CONTRACT_CHANGE_CHECK" || action === "UPDATE_SPOT_ROUTE_CHECK" || action === "UPDATE_DELIVERY_QTY_CHECK" || action === "UPDATE_CUSTOMER_BALANCE_CHECK" || action === "UPDATE_PERIOD_STOP_CHECK" || action === "UPDATE_OTHER_MAINTENANCE_CHECK" || action === "UPDATE_CANCEL_CHECK") {
      var destUrl = data.target_sheet_url || "https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/edit?gid=0#gid=0";
      var destSheet = getSheetFromUrl(destUrl);

      var rowIndex = data.row_index;
      var updatedRow = data.updated_row;

      var range = destSheet.getRange(rowIndex, 1, 1, updatedRow.length);
      range.setValues([updatedRow]);

      return ContentService.createTextOutput(JSON.stringify({"status": "success"})).setMimeType(ContentService.MimeType.JSON);

    // ==========================================
    // 4. タブ5用（印刷フォーマット用スプレッドシートへ、C1と数件分のブロックをまとめて反映する）
    // 対象: https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/edit?gid=457221393#gid=457221393（商品発注）
    //       https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/edit?gid=1261728197#gid=1261728197（ルート変更）
    // data.c1_value は文字列、data.blocks は2種類の形式に対応する（block単位でどちらか片方）：
    //   (a) 商品発注用: {start_row: 4, rows: [{offset: 0, values: [...5列...]}, {offset: 2, values: [...]}, ...]}
    //   (b) ルート変更用: {start_row: 4, cells: [{offset: 0, col: 1, value: "..."}, {offset: 2, col: 3, value: "..."}, ...]}
    // ※ どちらの形式でも、指定されていない行・セルはテンプレート側の固定見出し／レイアウトなので
    //   一切書き込まない（以前は行ごとまとめてsetValuesしていたため、間の固定見出し行まで
    //   空文字で上書きされ消えてしまっていた）。
    // ==========================================
    } else if (action === "SYNC_PRINT_STORE_DATA") {
      var printUrl = data.print_sheet_url || data.dest_sheet_url || "https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/edit?gid=457221393#gid=457221393";
      var printSheet = getSheetFromUrl(printUrl);

      if (data.c1_value !== undefined) {
        printSheet.getRange("C1").setValue(data.c1_value);
      }

      // data.header_cells: [{cell: "I1", value: "..."}, ...]
      // c1_value（C1固定）とは別に、任意のセル（ページ全体で1回だけ書く見出し等）に値を書きたい場合に使う
      // （契約内容変更のTAB5はI1に加盟店名を書くため追加）
      var headerCells = data.header_cells || [];
      for (var h = 0; h < headerCells.length; h++) {
        printSheet.getRange(headerCells[h].cell).setValue(headerCells[h].value);
      }

      var blocks = data.blocks || [];
      for (var b = 0; b < blocks.length; b++) {
        var block = blocks[b];

        var rowEntries = block.rows || [];
        for (var r2 = 0; r2 < rowEntries.length; r2++) {
          var entry = rowEntries[r2];
          var values = entry.values;
          if (values && values.length > 0) {
            var targetRow = block.start_row + entry.offset;
            printSheet.getRange(targetRow, 1, 1, values.length).setValues([values]);
          }
        }

        var cellEntries = block.cells || [];
        for (var c2 = 0; c2 < cellEntries.length; c2++) {
          var cellEntry = cellEntries[c2];
          var targetCellRow = block.start_row + cellEntry.offset;
          printSheet.getRange(targetCellRow, cellEntry.col).setValue(cellEntry.value);
        }
      }

      return ContentService.createTextOutput(JSON.stringify({"status": "success"})).setMimeType(ContentService.MimeType.JSON);

    // ==========================================
    // 5. タブ5用（印刷済みマーク：実データシートの指定列に印刷日時を入れる）
    // 対象: https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/edit?gid=0#gid=0
    // data.row_indices は実際のシート行番号（1始まり）の配列
    // data.print_col は書き込み先の列番号（1始まり）。未指定時は商品発注のAL列＝38列目がデフォルト
    // ==========================================
    } else if (action === "MARK_PRINTED") {
      var targetUrl = data.target_sheet_url || "https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/edit?gid=0#gid=0";
      var sheet = getSheetFromUrl(targetUrl);
      var printCol = data.print_col || 38;
      var printTime = data.print_time || Utilities.formatDate(new Date(), "JST", "yyyy/MM/dd HH:mm:ss");
      var rowIndices = data.row_indices || [];

      for (var r = 0; r < rowIndices.length; r++) {
        sheet.getRange(rowIndices[r], printCol).setValue(printTime);
      }

      return ContentService.createTextOutput(JSON.stringify({"status": "success"})).setMimeType(ContentService.MimeType.JSON);

    // ==========================================
    // 6. 顧客・契約データ管理画面用（権限3／権限0専用）
    // 対象: https://docs.google.com/spreadsheets/d/1AkMb1J2m3VZAIyMCKmr3T3E8-kJB0BDDdWQJuEn7YGc/edit?gid=127347205#gid=127347205（顧客マスター）
    //       https://docs.google.com/spreadsheets/d/1AkMb1J2m3VZAIyMCKmr3T3E8-kJB0BDDdWQJuEn7YGc/edit?gid=2011677989#gid=2011677989（ご契約データ）
    // Excelから貼り付けた表（data.rows：行×列の2次元配列）で、対象シートの中身をまるごと置き換える。
    // 既存データへの部分マージではなく、シート全体を一旦クリアしてから貼り付け内容を書き込む
    // （棚卸し・一括更新の仕様。誤操作防止はStreamlit側のチェックボックス確認で担保する）。
    // ==========================================
    } else if (action === "REPLACE_CUSTOMER_MASTER" || action === "REPLACE_CONTRACT_DATA") {
      var targetSheet = getSheetFromUrl(data.target_sheet_url);
      var newRows = data.rows || [];

      targetSheet.clearContents();

      if (newRows.length > 0) {
        var numCols = newRows[0].length;
        targetSheet.getRange(1, 1, newRows.length, numCols).setValues(newRows);
      }

      return ContentService.createTextOutput(JSON.stringify({"status": "success"})).setMimeType(ContentService.MimeType.JSON);
    }

    return ContentService.createTextOutput(JSON.stringify({"status": "error", "message": "未定義のアクション: " + action})).setMimeType(ContentService.MimeType.JSON);

  } catch (error) {
    return ContentService.createTextOutput(JSON.stringify({"status": "error", "message": error.toString()})).setMimeType(ContentService.MimeType.JSON);
  }
}
