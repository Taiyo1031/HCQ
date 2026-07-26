# HCQ Fix Backlog

このファイルは、HCQ の修正依頼を集約して整理するための正本です。
このチャット内外を問わず、修正を実行するときはこのバックログを基準にします。

## 運用ルール

- 新しい修正依頼は、まずこのファイルへ整理して追加します。
- ユーザーが明示的に「まとめて修正して」「このToDoを見て修正して」と指示するまでは、実装しません。
- 追加時はカテゴリ、優先度、状態を必ず付けます。
- 重複しそうな依頼は新規乱立させず、既存項目へ統合するか、関連項目として追記します。
- 画像つき指摘は「画像あり」だけで済ませず、後から画像を見なくても修正意図が分かるように詳細を文章化します。必要なら画像を `docs/fix_backlog_assets/` に保存し、該当項目へ保存先を記録します。
- 実装開始前に `Open` を `Ready` へ見直し、実装中は `In Progress`、完了後はいったん `Done` にしたうえでアーカイブへ移し、保留は `Blocked` に更新します。

## 優先度の定義

| Priority | Meaning |
| --- | --- |
| `P0` | 進行不能、重大破損、データ損失リスク、主要フローの停止 |
| `P1` | 主要機能の不具合、優先して直したい体験劣化 |
| `P2` | 通常の改善、使い勝手向上、仕様の詰め |
| `P3` | 軽微な文言、見た目、将来候補、低頻度の小修正 |

## 状態の定義

| Status | Meaning |
| --- | --- |
| `Open` | 受付済み。未整理または実装待ち |
| `Ready` | 実装前提の情報が揃っている |
| `In Progress` | 実装中 |
| `Done` | 実装済み |
| `Blocked` | 追加情報待ち、依存待ち、判断待ち |

## カテゴリ一覧

- `UI/UX`
- `機能不具合`
- `文言`
- `挙動改善`
- `ドキュメント`
- `要調査`
- `配布/インストール`

必要になったらカテゴリは追加して構いません。

## 優先対応

現時点では未登録です。

## 実装待ち一覧

現時点では未登録です。

## カテゴリ別一覧

### UI/UX

現時点では未登録です。

### 機能不具合

現時点では未登録です。

### 文言

現時点では未登録です。

### 挙動改善

現時点では未登録です。

### ドキュメント

現時点では未登録です。

### 要調査

現時点では未登録です。

### 配布/インストール

現時点では未登録です。

## 追加テンプレート

以下のテンプレートをコピーして使います。

```md
## FIX-0001: 短いタイトル

- Status: `Open`
- Priority: `P2`
- Category: `UI/UX`
- Summary: 何が起きていて、何を直したいかを1-2文で書く。
- Repro / Expected:
  - 現状:
  - 期待:
  - 再現手順:
- Impact: どの画面、機能、ユーザー操作に影響するかを書く。
- Notes:
  - 画像がある場合は、画面のどの位置の何がどう見えるかを文章で残す。
  - 重複項目がある場合は統合先IDを書く。
```

## 更新メモ

- 新しい依頼を受けたら、まず既存の `FIX-` ID を検索して類似項目がないか確認します。
- 別チャットから実装に入る場合も、このファイルを最新のソースオブトゥルースとして扱います。
- 添付画像を残す必要がある場合は `docs/fix_backlog_assets/` に `fix-xxxx-<short-name>` 形式で保存します。
- 完了した項目は `Done` に更新したあと、一覧に残し続けず `## Archived` セクションへ移動します。

## Archived

## FIX-0001: README から Houdini 公式ダウンロードボタンを削除する

- Status: `Done`
- Priority: `P3`
- Category: `ドキュメント`
- Summary: README の Download セクションから Houdini 公式ダウンロードボタンを削除した。
- Resolution:
  - HCQ 本体とReleaseのダウンロード導線は維持した。
  - Houdini 21.0以降が必要というRequirementsは維持した。
- Validation: README差分とリンク構成を確認した。

## FIX-0002: Python Panel ヘッダー右側のボタン表示崩れを修正する

- Status: `Done`
- Priority: `P2`
- Category: `UI/UX`
- Summary: `Usage`と`Update`を右寄せし、Houdiniテーマでも全文表示できる自然幅を確保した。
- Resolution:
  - Text-only `QToolButton`を明示し、通常表示と`Checking…`表示の双方を含む最小幅を設定した。
  - タイトルとの間へstretchと余白を追加し、520px幅でも重ならない構成にした。
- Validation: Houdini/PySide6 UI smokeで文字幅、右寄せ、非重複を確認した。
- Evidence: `docs/fix_backlog_assets/fix-0002-python-panel-header-buttons.png`

## FIX-0003: Run タブ下部の実行系ボタンを整理して分かりやすくする

- Status: `Done`
- Priority: `P2`
- Category: `UI/UX`
- Summary: 実行前操作と実行中操作を2段に分け、`Run Queue`を主操作として強調した。
- Resolution:
  - 上段をPreflight、Export、Run Queue、下段を`During Run:`付きのPause、Resume、Cancelに分けた。
  - idle、running、pause requested、paused、cancel requested、terminalに応じて操作可否を更新する。
- Validation: Houdini/PySide6 UI smokeで2段配置、520px幅、全状態のenable/disableを確認した。
- Evidence:
  - `docs/fix_backlog_assets/fix-0003-run-tab-button-layout-full.png`
  - `docs/fix_backlog_assets/fix-0003-run-tab-button-layout-closeup.png`

## FIX-0004: CPU を使い切らない設定を分かりやすくする

- Status: `Done`
- Priority: `P2`
- Category: `UI/UX`
- Summary: CPU制限機能を、物理コアや固定CPU使用率と誤解せず、空ける論理スレッド数として直感的に設定できるようにした。
- Resolution:
  - Settings、Queue Editor、Job Settingsの選択肢を`Leave Logical Threads Free`などの明確な英語表記へ統一した。
  - 使用可能な論理スレッド数から計算したHoudiniの実効上限をCPU設定の直下へ表示した。16論理スレッドで1を空ける場合は、15スレッド上限になることを表示する。
  - Queue/Run一覧では`reserve`などの内部値を表示せず、`Leave 1 Thread Free`のような表示にした。
  - 使用可能数以上を空ける指定にはPreflight warningを追加し、Houdini用に最低1論理スレッドを維持することを示した。
  - 既定値は`Use Current Houdini Setting`のまま維持し、既存の`reserve` JSON形式とスキーマを変更しなかった。
- Validation:
  - 59 unit testsでCPU計算、上限超過warning、保存互換性、例外時のCPU復元を確認した。
  - Houdini 21.0.729 integrationで`Leave 1 Thread Free`の適用と元設定への復元を確認した。
  - PySide6 UI smokeで3か所のCPU選択肢、動的な実効値説明、既定値維持を確認した。
- Evidence: `docs/fix_backlog_assets/fix-0004-cpu-usage-limit-request.png`

## FIX-0005: アップデート後に再起動確認ボタンを出す

- Status: `Done`
- Priority: `P2`
- Category: `挙動改善`
- Summary: 更新準備完了時に、今すぐ安全に再起動するか後で再起動するかを選択できるようにした。
- Resolution:
  - `Restart Now`と`Later`をmodalダイアログで提示する。
  - Queue実行中または別Houdiniセッションが同じHCQを使用中の場合は再起動を拒否する。
  - Houdini標準の未保存HIP確認後、同梱Python helperが現在プロセスの終了を待ち、同じHoudiniと保存済みHIPを再度開く。
  - 旧配置から標準インストーラーへ移行する場合は`Install and Restart`を表示する。
- Validation:
  - unit testでQueue/別プロセス抑止、保存確認Cancel、helper起動、インストーラー先行実行、HIP引数を確認した。
  - PySide6 smokeでUpdaterのready結果が再起動フローへ渡ることを確認した。

## FIX-0006: 配布・インストール・更新方式を標準化する

- Status: `Done`
- Priority: `P2`
- Category: `配布/インストール`
- Summary: 管理者権限不要のWindows Setupを主配布、Houdini Package Archiveを代替配布とし、本体・Package登録・ユーザーデータを分離した。
- Resolution:
  - `%LOCALAPPDATA%\Programs\HCQ`へ導入するInno Setup定義を追加した。
  - Documents/OneDrive側とuser-profile側の検出済みHoudini 21.xへ同じPackage JSONを登録する。
  - 旧1.1.x用互換ZIP、Package Archive、Setup EXEと各SHA-256を同じビルドから生成する。
  - 旧manifestに含まれる未変更プラグインファイルだけをバックアップして除去し、設定、Queues、履歴、ログ、Recoveryを保持する。
  - 更新用stage、lock、backupをインストール先ID単位で`%LOCALAPPDATA%\HCQ\updates`へ分離した。
  - GitHub Actionsでunit test、Inno build、asset検証、タグRelease公開、任意Authenticode署名を自動化した。
  - README、INSTALL、Distribution Guideへ導入、移行、更新、アンインストール手順を記載した。
- Validation:
  - 71 unit testsで移行、path safety、共有ロック、transaction rollback、Updater、再起動を確認した。
  - Legacy ZIPとPackage ArchiveをHoudini 21.0.729のclean preferenceから読み込み、HCQ 1.2.0を確認した。
  - Inno Setup 6.7.3で`HCQ-Setup-1.2.0.exe`を生成し、PEヘッダー、manifest、SHA-256を検証した。
  - このPCではApplication Controlが未署名ローカルEXEの起動を拒否したため、実インストール/アンインストール操作はAcceptance Checklistへ手動確認項目として残した。
