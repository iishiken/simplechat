# lambda/index.py
import json
import os
import urllib.request  # urllib.request をインポート
import urllib.error    # urllib.error をインポート
import time

# requests のインポートを削除

# boto3 と ClientError のインポートを削除
# 正規表現モジュールのインポートを削除 (リージョン抽出が不要なため)

# ==================================================
# グローバル変数
# ==================================================
# APIエンドポイントURL
API_URL = "https://0098-34-82-105-21.ngrok-free.app/generate"

# リージョン抽出関数と Bedrock クライアント初期化を削除

# MODEL_ID を削除

# ==================================================
# Lambda ハンドラー
# ==================================================
def lambda_handler(event, context):
    try:
        # Bedrock クライアント初期化ロジックを削除
        print(f"Using API endpoint: {API_URL}")

        print("Received event:", json.dumps(event))

        # Cognito 認証ユーザー情報の取得ロジックはそのまま維持
        user_info = None
        if 'requestContext' in event and 'authorizer' in event['requestContext']:
            user_info = event['requestContext']['authorizer']['claims']
            print(f"Authenticated user: {user_info.get('email') or user_info.get('cognito:username')}")

        # リクエストボディの解析
        body = json.loads(event['body'])
        message = body['message']
        conversation_history = body.get('conversationHistory', [])

        print("Processing message:", message)

        # ---- 会話履歴からプロンプトを作成 ----
        # 会話履歴を結合してプロンプト文字列を作成
        # 形式: "User: ...\nAssistant: ...\nUser: ..."
        prompt_parts = []
        for msg in conversation_history:
            role = "User" if msg["role"] == "user" else "Assistant"
            prompt_parts.append(f"{role}: {msg['content']}")
        # 現在のユーザーメッセージを追加
        prompt_parts.append(f"User: {message}")
        prompt = "\n".join(prompt_parts)

        # デバッグ用にプロンプトを表示 (本番では削除またはレベル調整を検討)
        print("Generated prompt:", prompt)

        # ---- ローカルLLM API 呼び出し (urllib.request) ----
        # リクエストペイロードを作成
        payload = {
            "prompt": prompt,
            "max_new_tokens": 512,
            "temperature": 0.7,
            "top_p": 0.9,
            "do_sample": True
        }

        print("Calling local LLM API with payload:", json.dumps(payload))

        # リクエストデータをJSONに変換し、バイト列にエンコード
        req_data = json.dumps(payload).encode('utf-8')

        # リクエストオブジェクトを作成
        req = urllib.request.Request(
            API_URL,
            data=req_data,
            method='POST',
            headers={'Content-Type': 'application/json'}
        )

        start_time = time.time()
        try:
            # API呼び出し実行
            with urllib.request.urlopen(req, timeout=60) as response:
                total_time = time.time() - start_time
                status_code = response.status
                print(f"API response status code: {status_code}")
                print(f"API request time: {total_time:.2f}s")

                # レスポンスボディを読み取り、デコード
                response_body = response.read().decode('utf-8')
                # レスポンスをJSONとして解析
                response_data = json.loads(response_body)

        except urllib.error.HTTPError as e:
            # HTTPエラー (4xx, 5xx)
            total_time = time.time() - start_time
            print(f"HTTP Error: {e.code} {e.reason}")
            print(f"Request attempt time: {total_time:.2f}s")
            error_body = "(Could not read error body)"
            if e.readable(): # エラーレスポンスボディが読めるか確認
                try:
                    error_body = e.read().decode('utf-8')
                except Exception as read_err:
                    error_body = f"(Failed to read error body: {read_err})"
            print(f"Error body: {error_body}")
            # 例外を再発生させて後続の except ブロックで処理
            raise Exception(f"API request failed with status {e.code}. Body: {error_body}") from e

        except urllib.error.URLError as e:
            # 接続エラー、タイムアウトなど
            total_time = time.time() - start_time
            print(f"URL Error: {e.reason}")
            print(f"Request attempt time: {total_time:.2f}s")
            # タイムアウトかどうかを判定 (reasonがsocket.timeoutの場合など)
            if isinstance(e.reason, TimeoutError) or (hasattr(e.reason, 'errno') and e.reason.errno == 60): # errno 60 は macOS のタイムアウト
                 raise TimeoutError("LLM API request timed out.") from e
            else:
                 raise ConnectionError(f"Could not connect to the LLM API: {e.reason}") from e

        # --- レスポンス処理 --- (urlopenが成功した場合)
        print("API response data:", json.dumps(response_data, default=str))

        # 応答の検証と取得
        if "generated_text" not in response_data:
            raise Exception("No 'generated_text' in the response from the local API")

        assistant_response = response_data["generated_text"]

        # ---- 会話履歴の更新 ----
        # 更新された会話履歴を作成 (元の messages 変数と同様の処理)
        updated_history = conversation_history.copy()
        updated_history.append({"role": "user", "content": message})
        updated_history.append({"role": "assistant", "content": assistant_response})

        # 成功レスポンスの返却
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token",
                "Access-Control-Allow-Methods": "OPTIONS,POST"
            },
            "body": json.dumps({
                "success": True,
                "response": assistant_response,
                "conversationHistory": updated_history # 更新された会話履歴を返す
            })
        }

    # ---- エラーハンドリング ----
    except TimeoutError as timeout_error:
        print(f"Timeout Error: {str(timeout_error)}")
        return {
            "statusCode": 504, # Gateway Timeout
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token",
                "Access-Control-Allow-Methods": "OPTIONS,POST"
            },
            "body": json.dumps({
                "success": False,
                "error": str(timeout_error)
            })
        }

    except ConnectionError as conn_error:
        print(f"Connection Error: {str(conn_error)}")
        return {
            "statusCode": 503, # Service Unavailable
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token",
                "Access-Control-Allow-Methods": "OPTIONS,POST"
            },
            "body": json.dumps({
                "success": False,
                "error": str(conn_error)
            })
        }

    except Exception as error:
        # HTTPErrorやその他の予期せぬエラー
        print(f"General Error: {str(error)}")
        status_code = 500 # デフォルトは Internal Server Error
        # HTTPErrorの場合、可能であれば元のステータスコードを使用
        if isinstance(error.__cause__, urllib.error.HTTPError):
            status_code = error.__cause__.code
            # 4xxエラーはクライアントエラーとして扱う場合もある
            if 400 <= status_code < 500:
                 status_code = 400 # 例: Bad Request として返す

        return {
            "statusCode": status_code,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token",
                "Access-Control-Allow-Methods": "OPTIONS,POST"
            },
            "body": json.dumps({
                "success": False,
                "error": f"An error occurred: {str(error)}"
            })
        }
