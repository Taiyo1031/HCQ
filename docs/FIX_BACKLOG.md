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

必要になったらカテゴリは追加して構いません。

## 優先対応

- `FIX-0004` CPU を使い切らない設定を分かりやすくする

## 実装待ち一覧

## FIX-0004: CPU を使い切らない設定を分かりやすくする

- Status: `Open`
- Priority: `P2`
- Category: `要調査`
- Summary: CPU を 100% 使い切らないようにしたい意図はあるが、現状 UI 上で「1コア残す」「少し余力を残す」といった設定が分かりにくい可能性がある。
- Repro / Expected:
  - 現状: 重い処理中に Windows のタスクマネージャー上で CPU 使用率が高く張り付きやすく、ユーザー視点では「CPU を使いすぎない設定」が見つけにくい。たとえば「1コア残す」「100%使用しないようにする」といった考え方で設定したい。
  - 期待: CPU 使用量を抑える考え方が UI 上で理解しやすく、必要なら「1コア残す」「複数コアを予約する」などの表現で直感的に選べる。
  - 再現手順: HCQ で重いジョブを実行し、Windows タスクマネージャーの CPU グラフを確認しながら、HCQ 側の CPU 設定導線とラベルを見比べる。
- Impact: マシン全体の操作快適性、他アプリ併用時の負荷感、CPU 制限機能の理解しやすさに影響する。
- Notes:
  - 現状コードと README には CPU 制限機能があり、`Fixed Thread Count`、`Reserve Threads`、`single-thread` 相当の選択肢が存在する。
  - そのため本件は「機能不足」の可能性もあるが、まずは既存機能の見つけやすさ、名称、説明不足、デフォルト値、プリセット不足のどこが問題か切り分けたい。
  - 画像ベースの観察内容: Windows タスクマネージャーで CPU 使用率が 93% 前後まで上がっており、ユーザーは HCQ 実行中に CPU を使い切らない制御を求めている。
  - 実装検討時は `README.md` の CPU 説明、`hcq/ui/editors.py` の CPU 項目、`hcq/ui/tabs.py` の Settings 側デフォルト CPU 設定を確認する。
  - 保存画像: `docs/fix_backlog_assets/fix-0004-cpu-usage-limit-request.png`

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

## FIX-0004: CPU を使い切らない設定を分かりやすくする

- Status: `Open`
- Priority: `P2`
- Category: `要調査`
- Summary: CPU を 100% 使い切らないようにしたい意図はあるが、現状 UI 上で「1コア残す」「少し余力を残す」といった設定が分かりにくい可能性がある。

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
