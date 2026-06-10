# スキャンファイル 格納アプリ

スキャンした PDF・Excel ファイルを自動リネームして Google Drive の指定フォルダに保存する  
デスクトップアプリです。**macOS・Windows どちらでも動作します。**

---

## アプリの使い方（お客様向け）

起動すると以下の 3 ステップで操作できます。

```
① ファイルを選ぶ        → 「ファイルを選択する」ボタン
② お客様情報を確認する  → 自動入力された内容を確認・修正
③ 保存先フォルダを選ぶ  → ツリーからフォルダをクリック

→ 「このフォルダに保存する」ボタン
```

保存後は Google Drive for Desktop が自動的にクラウドへ同期します。

---

## 開発者向け: アプリのビルド手順

### 前提条件

- Python 3.10 以上がインストール済み
- Google Drive for Desktop がインストール済み（お客様 PC 側）

### 1. 依存パッケージをインストール

```bash
cd project
pip install -r requirements.txt
```

### 2. アプリをビルドする

#### macOS の場合

```bash
chmod +x build_macos.sh
./build_macos.sh
```

完成物: `dist/スキャン格納アプリ.app`

#### Windows の場合

```
build_windows.bat をダブルクリック
```

完成物: `dist\スキャン格納アプリ\スキャン格納アプリ.exe`

---

## 配布方法

### macOS

1. `dist/スキャン格納アプリ.app` をお客様の Mac へコピー
2. `/Applications` フォルダに入れるか、デスクトップに置く
3. ダブルクリックで起動

> **「開発元を確認できません」と表示された場合:**
> ターミナルで以下を実行してから再度起動してください。
> ```bash
> xattr -cr /Applications/スキャン格納アプリ.app
> ```
> または: 右クリック →「開く」→「開く」をクリック

### Windows

1. `dist\スキャン格納アプリ` フォルダごとお客様の PC へコピー
2. フォルダ内の `.exe` ファイルのショートカットをデスクトップに作成

> **「WindowsによってPCが保護されました」と表示された場合:**
> 「詳細情報」→「実行」をクリックしてください。

---

## 初回起動時の設定

アプリを初めて起動すると「Google Drive のフォルダが見つかりました」と  
ダイアログが表示されます。**「はい」をクリックするだけで設定完了です。**

見つからない場合は「設定」ボタン →「自動で検出する」を試してください。

---

## ファイル構成

```
project/
├── main.py              # メイン GUI
├── extractor.py         # PDF・Excel 情報抽出
├── config_manager.py    # 設定の保存
├── requirements.txt     # 依存パッケージ
├── build_macos.sh       # macOS ビルドスクリプト
├── build_windows.bat    # Windows ビルドスクリプト
└── README.md
```

設定ファイルの保存場所（自動生成）:
- macOS: `~/Library/Application Support/FileRenameApp/config.json`
- Windows: `%APPDATA%\FileRenameApp\config.json`
# scan-file-app
