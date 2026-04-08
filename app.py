import streamlit as st
import os
from dotenv import load_dotenv
import anthropic
import requests
from docx import Document
import io

load_dotenv()

BOX_CLIENT_ID = os.getenv("BOX_CLIENT_ID")
BOX_CLIENT_SECRET = os.getenv("BOX_CLIENT_SECRET")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

st.title("法律事務所 書類アレンジシステム")

def get_box_auth_url():
    auth_url = (
        "https://account.box.com/api/oauth2/authorize"
        "?client_id=" + BOX_CLIENT_ID +
        "&response_type=code"
        "&redirect_uri=http://localhost:8501"
    )
    return auth_url

def get_access_token(auth_code):
    response = requests.post(
        "https://api.box.com/oauth2/token",
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "client_id": BOX_CLIENT_ID,
            "client_secret": BOX_CLIENT_SECRET,
        }
    )
    tokens = response.json()
    return tokens.get("access_token")

def get_folder_items(access_token, folder_id):
    headers = {"Authorization": "Bearer " + access_token}
    all_entries = []
    offset = 0
    while True:
        response = requests.get(
            "https://api.box.com/2.0/folders/" + folder_id + "/items?limit=1000&offset=" + str(offset),
            headers=headers
        )
        data = response.json()
        entries = data.get("entries", [])
        all_entries += entries
        total = data.get("total_count", 0)
        offset += len(entries)
        if offset >= total or not entries:
            break
    return all_entries

def download_file(access_token, file_id):
    headers = {"Authorization": "Bearer " + access_token}
    response = requests.get(
        "https://api.box.com/2.0/files/" + file_id + "/content",
        headers=headers
    )
    return response.content

def extract_text_from_docx(file_content):
    try:
        doc = Document(io.BytesIO(file_content))
        text = ""
        for para in doc.paragraphs:
            text += para.text + "\n"
        return text
    except:
        return ""

def search_similar_folders(access_token, case_type, limit=20):
    all_items = get_folder_items(access_token, "278953491818")
    matched = [i for i in all_items if i["type"] == "folder" and case_type in i["name"]]
    matched_with_time = []
    for folder in matched:
        headers = {"Authorization": "Bearer " + access_token}
        r = requests.get("https://api.box.com/2.0/folders/" + folder["id"], headers=headers)
        info = r.json()
        modified_at = info.get("modified_at", "")
        matched_with_time.append({
            "id": folder["id"],
            "name": folder["name"],
            "modified_at": modified_at
        })
    matched_with_time.sort(key=lambda x: x["modified_at"], reverse=True)
    return matched_with_time[:limit]

def find_best_document(access_token, folders, case_summary, doc_type, ai_client):
    candidates = []
    for folder in folders:
        items = get_folder_items(access_token, folder["id"])
        all_files = [i for i in items if i["name"].endswith(".docx") or i["name"].endswith(".doc")]
        subfolders = [i for i in items if i["type"] == "folder"]
        for subfolder in subfolders:
            subitems = get_folder_items(access_token, subfolder["id"])
            all_files += [i for i in subitems if i["name"].endswith(".docx") or i["name"].endswith(".doc")]
        matched_files = [f for f in all_files if doc_type in f["name"]]
        if not matched_files:
            matched_files = all_files
        if matched_files:
            file_content = download_file(access_token, matched_files[0]["id"])
            text = extract_text_from_docx(file_content)
            if text:
                candidates.append({
                    "folder_name": folder["name"],
                    "file_id": matched_files[0]["id"],
                    "file_name": matched_files[0]["name"],
                    "text": text[:500]
                })
    if not candidates:
        return None
    lines = []
    for i, c in enumerate(candidates):
        line = str(i+1) + " フォルダ:" + c["folder_name"] + " ファイル:" + c["file_name"] + " 内容:" + c["text"]
        lines.append(line)
    candidate_list = "\n\n".join(lines)
    message = ai_client.messages.create(
        model="claude-opus-4-5",
        max_tokens=100,
        messages=[{
            "role": "user",
            "content": "新事件の概要: " + case_summary + "\n書類の種類: " + doc_type + "\n\n候補書類:\n" + candidate_list + "\n\n最も類似している書類の番号を数字だけで答えてください。"
        }]
    )
    try:
        best_index = int(message.content[0].text.strip()) - 1
        return candidates[best_index]
    except:
        return candidates[0]

query_params = st.query_params
auth_code = query_params.get("code")

if auth_code and "access_token" not in st.session_state:
    try:
        access_token = get_access_token(auth_code)
        st.session_state["access_token"] = access_token
        st.rerun()
    except Exception as e:
        st.error("BOX認証エラー: " + str(e))

if "access_token" not in st.session_state:
    st.write("まずBOXにログインしてください。")
    if st.button("BOXにログイン"):
        auth_url = get_box_auth_url()
        st.markdown("[こちらをクリックしてBOXにログイン](" + auth_url + ")")
else:
    access_token = st.session_state["access_token"]
    st.success("BOXに接続済みです")
    st.header("新事件の情報を入力")
    case_type = st.selectbox("事件の種類", ["労働", "離婚", "交通事故", "債務", "不動産", "その他"])
    doc_type = st.selectbox("書類の種類", ["訴状", "準備書面", "答弁書", "照会申出書", "証拠申出書", "鑑定申出書", "上申書", "調査嘱託申出書", "送付嘱託申出書", "その他"])
    case_summary = st.text_area("事件の概要を入力してください", height=150)
    new_client_name = st.text_input("依頼者名")
    opponent_name = st.text_input("相手方名")

    if st.button("最適な書類を探して生成する"):
        if not case_summary:
            st.warning("事件の概要を入力してください。")
        else:
            ai_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            with st.spinner("類似案件を検索中..."):
                folders = search_similar_folders(access_token, case_type)
            if not folders:
                st.error("該当するフォルダが見つかりませんでした。")
            else:
                st.info(str(len(folders)) + "件の類似案件が見つかりました。AIが最適な書類を選択中...")
                with st.spinner("AIが最適な書類を選択中..."):
                    best = find_best_document(access_token, folders, case_summary, doc_type, ai_client)
                if not best:
                    st.error("Wordファイルが見つかりませんでした。")
                else:
                    st.success("選択された書類: " + best["folder_name"] + " / " + best["file_name"])
                    with st.spinner("新しい書類を生成中..."):
                        file_content = download_file(access_token, best["file_id"])
                        original_text = extract_text_from_docx(file_content)
                        message = ai_client.messages.create(
                            model="claude-opus-4-5",
                            max_tokens=4096,
                            messages=[{
                                "role": "user",
                                "content": "以下の過去の書類をベースに、新しい事件用にアレンジしてください。\n\n【過去の書類】\n" + original_text + "\n\n【新しい事件の情報】\n事件の種類: " + case_type + "\n書類の種類: " + doc_type + "\n依頼者名: " + new_client_name + "\n相手方名: " + opponent_name + "\n事件の概要: " + case_summary + "\n\n" + doc_type + "として新しい事件に合わせて書類を日本語で書き直してください。"
                            }]
                        )
                        result = message.content[0].text
                        st.header("生成された書類")
                        st.text_area("内容", result, height=500)
                        st.download_button(
                            label="テキストとしてダウンロード",
                            data=result,
                            file_name="新規書類.txt",
                            mime="text/plain"
                        )