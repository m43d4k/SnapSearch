import os
import platform
import time
import subprocess
import requests
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import threading
import sys
import yaml

# 動的インポートの設定
UPLOAD_SERVICE = None
try:
    config = yaml.safe_load(open("config.yaml", "r", encoding="utf-8"))
    UPLOAD_SERVICE = config["upload_service"]
except Exception as e:
    print(f"Error loading config.yaml: {e}")
    sys.exit(1)

if UPLOAD_SERVICE == "google_drive":
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        print("Missing Google Drive dependencies. Install with `pip install -e .[google_drive]`")
        sys.exit(1)
elif UPLOAD_SERVICE == "imgur":
    try:
        from PIL import Image
    except ImportError:
        print("Missing Imgur dependencies. Install with `pip install -e .[imgur]`")
        sys.exit(1)
else:
    print(f"Invalid upload_service in config.yaml: {UPLOAD_SERVICE}")
    sys.exit(1)

# 設定値の展開
MONITOR_DIR = os.path.expanduser(config["monitor"]["directory"])
LOG_FILE_PATH = os.path.join(MONITOR_DIR, config["monitor"]["log_file"])
SUPPORTED_FORMATS = tuple(config["supported_formats"])
SCOPES = config["google_drive"]["scopes"]
FOLDER_NAME = config["google_drive"]["folder_name"]
IMGUR_API_URL = config["imgur"]["api_url"]
IMGUR_CLIENT_ID = config["imgur"]["client_id"]
TIMEOUT_FILE_READY = config["timeouts"]["file_ready_wait"]
TIMEOUT_SCRIPT_TERMINATION = config["timeouts"]["script_termination"]
TIMEOUT_DELETE_WAIT = config["timeouts"]["delete_wait"]
DEBUG_MODE = config["debug"]["enabled"]
TEMPORARY_PREFIXES = config["temporary_files"]["prefixes"]
TEMPORARY_SUFFIXES = config["temporary_files"]["suffixes"]

# プラットフォームの判別
CURRENT_PLATFORM = platform.system()

# Google Drive 認証情報の取得
def get_credentials():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
            with open("token.json", "w") as token:
                token.write(creds.to_json())
    return creds

# img_search フォルダのIDを取得（存在しない場合は作成）
def get_or_create_folder(service, folder_name):
    results = service.files().list(
        q=f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
        fields="files(id, name)"
    ).execute()
    items = results.get("files", [])
    if items:
        return items[0]["id"]
    else:
        file_metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder"
        }
        folder = service.files().create(body=file_metadata, fields="id").execute()
        return folder.get("id")

# Google Drive に画像をアップロードし、公開 URL を取得
def upload_to_google_drive(image_path, service, folder_id):
    file_name = os.path.basename(image_path)
    file_metadata = {
        "name": file_name,
        "parents": [folder_id]
    }
    media = MediaFileUpload(image_path, mimetype="image/jpeg")
    file = service.files().create(body=file_metadata, media_body=media, fields="id").execute()
    file_id = file.get("id")
    # 公開リンクを有効にする
    permission = {
        "role": "reader",
        "type": "anyone"
    }
    service.permissions().create(fileId=file_id, body=permission).execute()
    # 公開 URL を生成
    file_url = f"https://drive.google.com/uc?id={file_id}"
    return file_id, file_url

# Imgur に画像をアップロード
def upload_to_imgur(image_path):
    _, ext = os.path.splitext(image_path)
    if ext.lower() not in SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported file format: {ext}. Supported formats are {SUPPORTED_FORMATS}")
    MAX_FILE_SIZE_MB = 10
    file_size_mb = os.path.getsize(image_path) / (1024 * 1024)
    if file_size_mb > MAX_FILE_SIZE_MB:
        raise ValueError(f"File size exceeds the limit of {MAX_FILE_SIZE_MB}MB: {file_size_mb:.2f}MB")
    headers = {"Authorization": f"Client-ID {IMGUR_CLIENT_ID}"}
    with open(image_path, "rb") as image_file:
        files = {"image": image_file}
        response = requests.post(IMGUR_API_URL, headers=headers, files=files)
        if response.status_code == 200:
            imgur_url = response.json()["data"]["link"]
            log_message(f"Imgur URL 取得成功: {imgur_url}")
            return imgur_url
        else:
            raise Exception(f"Imgur upload failed: {response.text}")

# デフォルトブラウザで指定された URL を開く
def open_in_default_browser(url):
    try:
        log_message(f"Opening in default browser: {url}")
        if CURRENT_PLATFORM == "Darwin":  # macOS
            subprocess.run(["open", url])
        elif CURRENT_PLATFORM == "Windows":  # Windows
            subprocess.run(["start", url], shell=True)
        else:  # Linux
            subprocess.run(["xdg-open", url])
    except Exception as e:
        log_message(f"Error opening URL in browser: {str(e)}")
        raise

# ログをファイルに保存する関数
def log_message(message):
    with open(LOG_FILE_PATH, "a", encoding="utf-8") as log_file:
        log_file.write(f"[LOG] {message}\n")
    print(f"[LOG] {message}")  # コンソールにも出力

# スクリプト開始時にログファイルをクリア
def clear_log_file():
    if not os.path.exists(MONITOR_DIR):
        os.makedirs(MONITOR_DIR)  # ディレクトリが存在しない場合は作成
    if os.path.exists(LOG_FILE_PATH):
        with open(LOG_FILE_PATH, "w", encoding="utf-8"):
            pass
    log_message("Log file cleared.")

# 一時ファイルかどうかを判定する関数
def is_temporary_file(file_path):
    file_name = os.path.basename(file_path)
    if any(file_name.startswith(prefix) for prefix in TEMPORARY_PREFIXES):
        return True
    if any(file_name.endswith(suffix) for suffix in TEMPORARY_SUFFIXES):
        return True
    return False

# ファイルが準備完了になるまで待機
def wait_for_file_ready(file_path, timeout=TIMEOUT_FILE_READY):
    log_message(f"Waiting for the file to be ready: {file_path}")
    start_time = time.time()
    previous_size = -1
    while time.time() - start_time < timeout:
        try:
            current_size = os.path.getsize(file_path)
            if current_size == previous_size and current_size > 0:
                log_message(f"File is ready: {file_path}")
                return
            previous_size = current_size
        except FileNotFoundError:
            log_message(f"File not found during size check: {file_path}")
        time.sleep(0.5)
    raise TimeoutError(f"File did not stabilize within {timeout} seconds: {file_path}")

# 画像処理関数
def process_image(image_path, stop_event):
    try:
        if is_temporary_file(image_path):
            log_message(f"Ignoring temporary file: {image_path}")
            return
        if not os.path.exists(image_path):
            log_message(f"File does not exist: {image_path}")
            return
        # ファイルが準備完了になるまで待機
        wait_for_file_ready(image_path)
        # アップロードサービスに基づいて処理を分岐
        if UPLOAD_SERVICE == "google_drive":
            creds = get_credentials()
            service = build("drive", "v3", credentials=creds)
            folder_id = get_or_create_folder(service, FOLDER_NAME)
            log_message(f"Uploading image to Google Drive folder: {FOLDER_NAME}...")
            file_id, drive_url = upload_to_google_drive(image_path, service, folder_id)
            log_message(f"Google Drive Public URL: {drive_url}")
            public_url = drive_url
        elif UPLOAD_SERVICE == "imgur":
            log_message("Uploading to Imgur...")
            public_url = upload_to_imgur(image_path)
        else:
            raise ValueError(f"Invalid upload service specified in config.yaml: {UPLOAD_SERVICE}")
        # Google Lens の「Upload by URL」に公開 URL を渡す
        lens_url = f"https://lens.google.com/uploadbyurl?url={public_url}"
        log_message(f"Opening Google Lens with URL: {lens_url}")
        open_in_default_browser(lens_url)
        # 指定時間待機してから Google Drive からファイルを削除
        if UPLOAD_SERVICE == "google_drive":
            log_message(f"Waiting for {TIMEOUT_DELETE_WAIT} seconds before deleting the file from Google Drive...")
            time.sleep(TIMEOUT_DELETE_WAIT)  # 待機時間を設定値から取得
            delete_from_google_drive(service, file_id)
        # 処理が完了した画像をローカルから削除
        os.remove(image_path)
        log_message(f"Deleted processed image locally: {image_path}")
    except TimeoutError as e:
        log_message(f"Timeout occurred: {e}")
    except Exception as e:
        log_message(f"Unexpected error during process: {str(e)}")
        import traceback
        log_message(traceback.format_exc())  # スタックトレースをログに記録
    finally:
        stop_event.set()

# Google Drive からファイルを削除
def delete_from_google_drive(service, file_id):
    try:
        log_message(f"Deleting file from Google Drive: {file_id}")
        service.files().delete(fileId=file_id).execute()
        log_message(f"Deleted file from Google Drive: {file_id}")
    except Exception as e:
        log_message(f"Error deleting file from Google Drive: {str(e)}")
        raise

# フォルダ監視ハンドラ
class ScreenshotHandler(FileSystemEventHandler):
    def __init__(self, stop_event):
        self.stop_event = stop_event

    def on_created(self, event):
        if not event.is_directory and event.src_path.lower().endswith(SUPPORTED_FORMATS):
            if is_temporary_file(event.src_path):
                log_message(f"Ignoring temporary file (on_created): {event.src_path}")
                return
            log_message(f"New screenshot detected (on_created): {event.src_path}")
            process_image(event.src_path, self.stop_event)

    def on_moved(self, event):
        if not event.is_directory and event.dest_path.lower().endswith(SUPPORTED_FORMATS):
            if is_temporary_file(event.dest_path):
                log_message(f"Ignoring temporary file (on_moved): {event.dest_path}")
                return
            log_message(f"File moved detected (on_moved): {event.dest_path}")
            process_image(event.dest_path, self.stop_event)

# メイン処理
def main():
    clear_log_file()
    observer = Observer()
    stop_event = threading.Event()
    event_handler = ScreenshotHandler(stop_event)
    observer.schedule(event_handler, MONITOR_DIR, recursive=False)
    observer.start()
    log_message("Monitoring folder for new screenshots...")
    # 指定時間後にスクリプトを終了させるタイマーを設定
    def terminate_script():
        log_message(f"{TIMEOUT_SCRIPT_TERMINATION} seconds elapsed. Stopping the script...")
        stop_event.set()
        observer.stop()
        observer.join()
        log_message("Script has been terminated.")
        sys.exit(0)
    timer_thread = threading.Timer(TIMEOUT_SCRIPT_TERMINATION, terminate_script)
    timer_thread.start()
    try:
        while not stop_event.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        log_message("Stopping the script...")
        stop_event.set()
        observer.stop()
        observer.join()
    finally:
        timer_thread.cancel()  # タイマーをキャンセル
        log_message("Script has been terminated.")
        sys.exit(0)

if __name__ == "__main__":
    main()