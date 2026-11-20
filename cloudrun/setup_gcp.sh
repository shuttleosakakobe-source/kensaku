#!/usr/bin/env bash
# =====================================================================
# メンテナンスアプリ Cloud Run 初期設定スクリプト（Cloud Shell で1回だけ実行）
#
# 使い方（Google Cloud の画面右上「Cloud Shell をアクティブにする」で開いた黒い画面に貼り付け）:
#   curl -fsSL https://raw.githubusercontent.com/shuttleosakakobe-source/kensaku/claude/cloud-run-deploy/cloudrun/setup_gcp.sh -o setup_gcp.sh
#   bash setup_gcp.sh あなたのプロジェクトID
#
# 神戸版（kensaku）と京都版（kyoto-chuo-mente）の両方の設定をまとめて行います。
# 何度実行しても大丈夫です（作成済みのものはそのまま使います）。
# =====================================================================
set -euo pipefail

PROJECT_ID="${1:-}"
if [ -z "$PROJECT_ID" ]; then
  echo "使い方: bash setup_gcp.sh <プロジェクトID>" >&2
  exit 1
fi

REGION="asia-northeast1"           # 東京
GITHUB_OWNER="shuttleosakakobe-source"
REPOS=("kensaku" "kyoto-chuo-mente")
AR_REPO="mente-apps"
DEPLOYER_SA_NAME="github-deployer"
RUNTIME_SA_NAME="mente-app-runner"
POOL="github-pool"
PROVIDER="github-provider"
SECRET_NAME="anthropic-api-key"

DEPLOYER_SA="${DEPLOYER_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
RUNTIME_SA="${RUNTIME_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "▶ プロジェクト ${PROJECT_ID} を設定します"
gcloud config set project "$PROJECT_ID" >/dev/null
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')

echo "▶ [1/6] 必要な機能のスイッチを入れています（1〜2分かかります）"
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  cloudresourcemanager.googleapis.com

echo "▶ [2/6] アプリの保管庫（Artifact Registry）を作成"
gcloud artifacts repositories describe "$AR_REPO" --location "$REGION" >/dev/null 2>&1 || \
  gcloud artifacts repositories create "$AR_REPO" --repository-format=docker --location "$REGION" \
    --description="メンテナンスアプリ"

echo "▶ [3/6] ロボット用アカウント（サービスアカウント）を作成"
gcloud iam service-accounts describe "$DEPLOYER_SA" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "$DEPLOYER_SA_NAME" --display-name="GitHub から Cloud Run へ載せる係"
gcloud iam service-accounts describe "$RUNTIME_SA" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "$RUNTIME_SA_NAME" --display-name="メンテナンスアプリ実行用"

for ROLE in roles/run.admin roles/artifactregistry.writer; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${DEPLOYER_SA}" --role="$ROLE" --condition=None >/dev/null
done
# 載せる係が「実行用アカウント」でアプリを動かせるようにする
gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_SA" \
  --member="serviceAccount:${DEPLOYER_SA}" --role="roles/iam.serviceAccountUser" >/dev/null
# 載せる係が AI 用の鍵の有無を確認できるようにする（中身は読めない）
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${DEPLOYER_SA}" --role="roles/secretmanager.viewer" --condition=None >/dev/null

echo "▶ [4/6] GitHub と Google Cloud を鍵ファイルなしでつなぐ（Workload Identity 連携）"
gcloud iam workload-identity-pools describe "$POOL" --location=global >/dev/null 2>&1 || \
  gcloud iam workload-identity-pools create "$POOL" --location=global --display-name="GitHub Actions"
gcloud iam workload-identity-pools providers describe "$PROVIDER" --location=global \
  --workload-identity-pool="$POOL" >/dev/null 2>&1 || \
  gcloud iam workload-identity-pools providers create-oidc "$PROVIDER" \
    --location=global --workload-identity-pool="$POOL" \
    --display-name="GitHub" \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner" \
    --attribute-condition="assertion.repository_owner=='${GITHUB_OWNER}'"

for REPO in "${REPOS[@]}"; do
  gcloud iam service-accounts add-iam-policy-binding "$DEPLOYER_SA" \
    --role="roles/iam.workloadIdentityUser" \
    --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}/attribute.repository/${GITHUB_OWNER}/${REPO}" >/dev/null
done

echo "▶ [5/6] AI チェック用の鍵（ANTHROPIC_API_KEY）を金庫（Secret Manager）に保管"
if gcloud secrets describe "$SECRET_NAME" >/dev/null 2>&1; then
  echo "  すでに保管済みです（変更する場合は Secret Manager の画面から新しいバージョンを追加してください）"
else
  echo "  Streamlit の Secrets に入っている ANTHROPIC_API_KEY の値を貼り付けて Enter を押してください。"
  echo "  （入力した文字は画面に表示されません。AI チェックを使わない場合は何も入れずに Enter）"
  read -r -s API_KEY
  echo
  if [ -n "$API_KEY" ]; then
    printf '%s' "$API_KEY" | gcloud secrets create "$SECRET_NAME" --replication-policy=automatic --data-file=-
    unset API_KEY
  else
    echo "  スキップしました（AI チェック機能だけ無効の状態で動きます）"
  fi
fi
if gcloud secrets describe "$SECRET_NAME" >/dev/null 2>&1; then
  gcloud secrets add-iam-policy-binding "$SECRET_NAME" \
    --member="serviceAccount:${RUNTIME_SA}" --role="roles/secretmanager.secretAccessor" >/dev/null
fi

echo "▶ [6/6] 完了しました"
echo
echo "======================================================================"
echo " GitHub の両リポジトリ（kensaku と kyoto-chuo-mente）それぞれで"
echo " Settings → Secrets and variables → Actions → New repository secret から"
echo " 次の3つを登録してください（名前と値をそのままコピー）"
echo "======================================================================"
echo
echo "GCP_PROJECT_ID"
echo "  ${PROJECT_ID}"
echo
echo "GCP_WORKLOAD_IDENTITY_PROVIDER"
echo "  projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}/providers/${PROVIDER}"
echo
echo "GCP_SERVICE_ACCOUNT"
echo "  ${DEPLOYER_SA}"
echo
