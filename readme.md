# SnapSearch

## 概要
ローカルの画像を Google Lens で検索するための Python スクリプトです。  
スクリーンショットツールと組み合せ、Android のようにシステムワイドで Lens を利用しようと作成しました。  
Web ブラウザで検索結果を開きます。

## 動作フロー
- 指定されたディレクトリを監視
- 新しい画像が追加されると Google Drive または Imgur にアップロード
- 公開URLをGoogle Lens （画像検索）に連携し Web ブラウザで表示
- Google Drive 使用時は、画像を自動削除
- スクリプトを終了（常駐はしません。）

## 要求環境

### プラットフォーム
Mac, Windows, Linux に対応

### Python バージョン
Python 3.8 以上

### 必要なライブラリ
- **google-auth, google-auth-oauthlib, google-auth-httplib2, google-api-python-client**: Google Drive API と連携。
- **Pillow**: 画像処理ライブラリ。
- **PyYYAML**: YAML 形式のファイルを読み込み。
- **requests**: HTTP リクエストを処理。
- **watchdog**: ファイルシステムの変更を監視。

## 設定方法

### 設定ファイル
スクリプトと同じディレクトリに config.yaml を作成し、以下の内容を記述してください。

``` yaml:config.yaml
monitor:
  directory: "~/Pictures/up_Screenshots"    # 監視するディレクトリ
  log_file: "log.txt"    # ログファイル名
supported_formats:
  - ".png"
  - ".jpg"
  - ".jpeg"
  - ".gif"
google_drive:
  scopes:
    - "https://www.googleapis.com/auth/drive"
  folder_name: "img_search"    # アップロード先のフォルダ名
imgur:
  api_url: "https://api.imgur.com/3/image"
  client_id: "<IMGUR_CLIENT_ID>"    # Imgur API のクライアント ID
timeouts:
  file_ready_wait: 5    # ファイル準備完了の待機時間 (秒)
  script_termination: 20    # スクリプト終了までの時間 (秒)
  delete_wait: 1    # Google Drive 削除前の待機時間 (秒)
debug:
  enabled: false    # デバッグモードを有効にするかどうか
temporary_files:
  prefixes:
    - "."
    - ".."
  suffixes:
    - "-Epcu"
    - ".tmp"
upload_service: "google_drive"    # 使用するアップロードサービス ("google_drive" または "imgur")
```

### ライブラリをインストール

```sh
pip install -r requirements.txt
```

### Google Drive の認証設定（Google Drive を利用する場合）
- [Google Cloud Console](https://console.cloud.google.com/) から OAuth 2.0 クライアント ID を取得  
- 認証情報を credentials.json として、スクリプトと同じディレクトリに保存
- 初回実行時に Google アカウントで認証すると自動的に token.json が保存される

### Imgur の API 設定（Imgur を利用する場合）
- [Imgur API](https://api.imgur.com/oauth2/addclient) でクライアント ID を取得し、config.yaml の imgur.client_id に設定

## 実行方法
main.py を実行するだけです。

``` sh
python main.py
```

## 使い方の例
1. スクリプトを実行
2. 同時にスクリーンショット取得ツールを起動

```sh
# Macの例）保存ディレクトリとファイル名を指定し、領域選択モードでスクリーンショットツールを起動。
screencapture -i ~/Pictures/up_Screenshots/search.png
```

3. 監視フォルダにスクリーンショットを保存
4.  Web ブラウザに画像検索の結果が表示

## 備考
- ., .., -Epcu, .tmp などのプレフィックスまたはサフィックスを持つファイルは一時ファイルとみなされ、処理されません。
- Imgur では、10MB までのファイルしかアップロードできません。
- config.yaml の debug.enabled を true に設定すると、デバッグログを出力できます。
