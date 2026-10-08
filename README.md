# golli-note-automation

「ChatGPTにnote運営を任せたら月10万円に届くか」の公開実験を記録する半自動化システムです。公開・削除・既存記事編集を行う機能はありません。

## 構成

- `browser.py`: Playwrightで表示済みDOMから実績を取得、新規の空編集画面に下書きを保存。noteの非公式APIを直接呼び出しません。
- `core.py`: snapshot追記、日時重複検査、同一集計範囲の比較、記事生成、Markdownとサムネmetadata保存。
- `cli.py`: 手動ログイン、排他制御、処理の実行、summary、GitHub Actions Job Summary出力。
- `config/example.json`: 実画面で確認するDOM契約。未設定の必須selectorは停止します。
- `tests/`: データ処理と公開防止・既存記事保護のオフラインテスト。
- `.github/workflows/tests.yml`: 認証不要のテストのみ。note運営の定期実行は有効化していません。

## インストールと実行

Python 3.9以上を使用します。

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
export PLAYWRIGHT_BROWSERS_PATH="$PWD/.playwright-browsers"
playwright install chromium
cp config/example.json config/local.json
note-automation login
# 実画面確認後にconfig/local.jsonのselectorを設定
note-automation run --headed
# ローカル下書きを確認し、下書き保存のDOM契約も設定後に実行
note-automation run --headed --save-note
```

通常のrunも実績をライブ取得します。初期参考値で取得失敗を補完する機能はありません。ユーザー提供の2026-10-05参考値（impressions96、PV12、スキ0、コメント0、売上0円、記事1 80/11、記事2 16/1）はライブ履歴に登録しません。記事名と集計範囲が未確認のため、比較の基準にも使いません。

## 初回に人間が行うこと

1. `login`で開いたブラウザでnoteへログインし、必要な認証を完了する。
2. アクセス状況と空の新規記事画面を確認して、`config/local.json`のURLとselectorを設定する。必須項目には表示された一意の要素を指定する。値が表示されない任意項目はnull。空文字のままにしない。
3. `period`は実際の集計日付範囲、`period_key`は週/月/全期間などの集計方式を指す。同じ文字列でも対象日付が変わる設定は避ける。PV/impressionsなど異なる定義の数値を置き換えない。
4. `articles_container`/`article_rows`は対象の一覧全体を指す。ページ送りがある場合、本実装は表示行だけを取得するため、取得範囲を確認する。全記事と誤認しない。
5. `new_editor_marker`は新規画面を肯定的に識別する要素にする。保存ボタンは表示文言が完全一致で「下書き保存」のものだけ対応。`saved_marker`は保存前には存在せず、保存成功後に出現する一意の確認表示を指定する。自動保存のみのUIや公開設定内の操作には対応しない。
6. `tags_input`は下書き画面で直接入力できる欄だけ設定する。公開設定を開く必要がある場合nullとし、metadataを見て人間がタグを設定する。

実画面未検証のため、初回のselector調整とnote保存の確認は必須です。画面が変わった場合も同様です。

## 保存物と安全性

- `data/note_metrics.json`: 過去履歴を保持して追記。日時重複は追加しない。同じ日時で内容が異なる場合はエラー。
- `drafts/YYYY-MM-DD-<snapshot-id>.md`: title、created_at、source_metrics、tags、statusをfrontmatterに保存。
- 同名の`.metadata.json`: タイトル候補5個、見出し、テーマ、選択理由、仮説、次回KPI、thumbnail_text、thumbnail_prompt。
- `logs/summary.json` / `summary.md`: 実績、差分、分析、テーマ、タイトル、仮説、KPI、下書き保存結果、人間の確認項目。`GITHUB_STEP_SUMMARY`があれば同じ内容を追記。

欠損はnull、非数値や不明瞭な表示、要素の欠落・重複は停止します。正常取得後の後段失敗では既に取得したsnapshotとローカル下書きを保持します。集計期間が異なる差分と新規記事の増減はnull。PV / impressionsは厳密なCTRとは呼びません。

記事生成は外部LLM不要のルールベース方式です。実データに基づくA（結果）/B（試す施策）/C（計測実験）/D（記録ノウハウ）の選択を行いますが、実施済み施策を入力する仕組みはまだありません。したがってB/Cは次の試行案として記述し、実施結果や成功を作りません。外部LLMや画像生成は未接続で、生成関数とmetadataを接続点にできます。

保存試行前に`data/note-save-attempt.json`を残します。成功・失敗を問わず次の自動保存を止めます。人間がnoteの下書きを確認した後、次の新規下書きを作る場合だけこのファイルを削除してください。タイムアウト後も再試行による重複を避けます。プロセス異常終了で`data/run.lock`が残る場合も、実行中プロセスがないことを確認してから削除します。

`.auth/`、`.env*`、storageState、Cookie類、ローカル設定、実績、下書き、ログはignore対象です。セッションはローカルの`.auth/storage_state.json`に権限600で保存し、Actionsへアップロードしません。セッション期限切れ時は再ログインします。ignoreは既に追跡済みの秘密を除去しないため、commit対象を毎回確認してください。自動スクリーンショット・DOMダンプ・セッションログは保存しません。Job Summaryには運営実績と下書き情報が出るため、リポジトリの閲覧者に注意してください。

公開前には人間が事実、読みやすさ、タグ、サムネを確認し、note上で公開操作を行います。サムネ画像自体、売上専用画面、流入元の構造化、ページ送り、継続的な定期実行は未対応です。初期設定後の運用でもDOM変更時には停止し、人間による再確認が必要です。

## テスト

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

実noteへのアクセスと保存成功は、ログイン済み環境と実DOM契約が必要なため別途確認してください。
