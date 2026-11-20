# Cloud Run への移行メモ

このフォルダと `Dockerfile`・`.github/workflows/deploy-cloudrun.yml` は、
アプリを Google Cloud Run で動かすための設定です。
今の Streamlit Community Cloud 版はそのまま動き続けます（並行運用できます）。

## しくみ

- `Dockerfile` … アプリを「箱詰め」する設計図
- `.github/workflows/deploy-cloudrun.yml` … main に変更が入ると、自動で箱詰めして Cloud Run に載せる
- `cloudrun/setup_gcp.sh` … Google Cloud 側の初期設定（Cloud Shell で1回だけ実行）

GitHub の Secrets が未登録のあいだは、自動デプロイは何もせずにスキップします。

## 初回の手順

1. Google Cloud でプロジェクトを作り、課金（お支払い）を有効にする
2. Google Cloud の画面右上「Cloud Shell」を開き、次を貼り付けて実行する

   ```
   curl -fsSL https://raw.githubusercontent.com/shuttleosakakobe-source/kensaku/claude/cloud-run-deploy/cloudrun/setup_gcp.sh -o setup_gcp.sh
   bash setup_gcp.sh <プロジェクトID>
   ```

   途中で ANTHROPIC_API_KEY の入力を求められます（Streamlit の Secrets に入っている値）。
3. 最後に表示される3つの値を、kensaku と kyoto-chuo-mente の両方の
   Settings → Secrets and variables → Actions に登録する
4. PR をマージする（またはActions タブの「Deploy to Cloud Run」→「Run workflow」）
5. Actions の実行結果の「公開URL」を開いて動作確認する

## 設定値

| 項目 | 値 |
|---|---|
| リージョン | asia-northeast1（東京） |
| 待機台数 | 0台（使うときだけ起動）。待ち時間が気になれば `--min-instances 1` に変更 |
| 最大台数 | 3台 |
| 公開範囲 | URL を知っていれば誰でも開ける（ログイン画面で認証） |

会社の Google Workspace の設定で「外部への公開」が禁止されている場合、
デプロイ時に `--allow-unauthenticated` の部分でエラーになります。そのときは管理者に相談してください。
