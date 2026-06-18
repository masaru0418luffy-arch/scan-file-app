from __future__ import annotations

import io
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

import requests as req
import streamlit as st
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

from extractor import extract_from_pdf, extract_from_excel

# ─────────────────────────────────────────────────────────────────────────────
# 定数
# ─────────────────────────────────────────────────────────────────────────────

SCOPES        = ['https://www.googleapis.com/auth/drive']
INVALID_CHARS = re.compile(r'[/\\:*?"<>|]')
MIME = {
    '.pdf':  'application/pdf',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
}

# ─────────────────────────────────────────────────────────────────────────────
# ページ設定
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="スキャンファイル 格納アプリ",
    page_icon="📁",
    layout="centered",
)

st.markdown("""
<style>
.preview-box {
    background: #e8f2ff;
    border-left: 5px solid #0066cc;
    border-radius: 6px;
    padding: 10px 16px;
    font-family: monospace;
    font-size: 1.05em;
    color: #003d99;
    margin: 8px 0 16px 0;
}
</style>
""", unsafe_allow_html=True)


def sanitize(text: str) -> str:
    return INVALID_CHARS.sub('_', text)


# ─────────────────────────────────────────────────────────────────────────────
# Google Drive ヘルパー関数
# ─────────────────────────────────────────────────────────────────────────────

def _client_config() -> dict:
    g = st.secrets['google']
    return {
        'web': {
            'client_id':     g['client_id'],
            'client_secret': g['client_secret'],
            'auth_uri':  'https://accounts.google.com/o/oauth2/auth',
            'token_uri': 'https://oauth2.googleapis.com/token',
        }
    }


def get_auth_url() -> str:
    g = st.secrets['google']
    params = {
        'client_id':     g['client_id'],
        'redirect_uri':  g['redirect_uri'],
        'response_type': 'code',
        'scope':         ' '.join(SCOPES),
        'access_type':   'offline',
        'prompt':        'consent',
    }
    query = '&'.join(f"{k}={v}" for k, v in params.items())
    return f"https://accounts.google.com/o/oauth2/auth?{query}"


def exchange_code(code: str) -> dict:
    """認証コードをアクセストークンに交換する（requests で直接リクエスト）。"""
    g = st.secrets['google']
    resp = req.post(
        'https://oauth2.googleapis.com/token',
        data={
            'code':          code,
            'client_id':     g['client_id'],
            'client_secret': g['client_secret'],
            'redirect_uri':  g['redirect_uri'],
            'grant_type':    'authorization_code',
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if 'error' in data:
        raise ValueError(data.get('error_description', data['error']))
    return {
        'token':         data['access_token'],
        'refresh_token': data.get('refresh_token'),
        'token_uri':     'https://oauth2.googleapis.com/token',
        'scopes':        data.get('scope', ' '.join(SCOPES)).split(),
    }


def build_service():
    d = st.session_state['credentials']
    g = st.secrets['google']
    creds = Credentials(
        token=d['token'],
        refresh_token=d.get('refresh_token'),
        token_uri=d.get('token_uri', 'https://oauth2.googleapis.com/token'),
        client_id=g['client_id'],
        client_secret=g['client_secret'],
        scopes=d.get('scopes', SCOPES),
    )
    return build('drive', 'v3', credentials=creds)


def search_folders(service, name: str) -> list:
    """キーワードを含むフォルダを Drive 全体（共有ドライブ含む）から検索する。"""
    safe = name.replace("'", "\\'")
    q = (
        f"name contains '{safe}' "
        "and mimeType = 'application/vnd.google-apps.folder' "
        "and trashed = false"
    )
    res = service.files().list(
        q=q,
        fields='files(id, name, parents)',
        orderBy='name',
        pageSize=50,
        includeItemsFromAllDrives=True,   # 共有ドライブを含める
        supportsAllDrives=True,
        corpora='allDrives',              # マイドライブ＋共有ドライブ全体を対象
    ).execute()
    return res.get('files', [])


def get_folder_path(service, folder_id: str) -> str:
    """フォルダの表示パスを返す（最大4階層まで）。"""
    parts: list[str] = []
    fid = folder_id
    seen: set[str] = set()

    for _ in range(6):
        if fid in seen:
            break
        seen.add(fid)
        try:
            meta = service.files().get(
                fileId=fid, fields='name,parents',
                supportsAllDrives=True,
            ).execute()
            parts.insert(0, meta['name'])
            parents = meta.get('parents', [])
            if not parents:
                break
            fid = parents[0]
        except Exception:
            break

    if len(parts) > 4:
        parts = ['…'] + parts[-4:]
    return ' › '.join(parts) if parts else folder_id


# ─────────────────────────────────────────────────────────────────────────────
# OAuth コールバック処理（Google から戻ってきたとき）
# ─────────────────────────────────────────────────────────────────────────────

params = st.query_params.to_dict()

if 'error' in params:
    err_msg = f"{params.get('error')}: {params.get('error_description', '')}"
    st.session_state['auth_error'] = err_msg
    st.query_params.clear()
    st.rerun()

elif 'code' in params:
    code = params['code']
    # 同じコードを二度処理しない
    if st.session_state.get('_last_code') != code:
        st.session_state['_last_code'] = code
        st.session_state.pop('auth_error', None)
        try:
            st.session_state['credentials'] = exchange_code(code)
        except Exception as e:
            st.session_state['auth_error'] = (
                f"{type(e).__name__}: {e}\n\n"
                f"redirect_uri = {st.secrets['google'].get('redirect_uri', '未設定')}"
            )
    st.query_params.clear()
    st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# ヘッダー
# ─────────────────────────────────────────────────────────────────────────────

st.title("📁 スキャンファイル 格納アプリ")

# ─────────────────────────────────────────────────────────────────────────────
# デスクトップアプリのダウンロード（サインイン不要で表示）
# ─────────────────────────────────────────────────────────────────────────────

with st.expander("💻 デスクトップアプリをダウンロードする（毎回URLを開かずに使えます）"):
    st.markdown(
        "ダウンロードしてデスクトップに置くと、**ダブルクリックだけでアプリが開きます。**"
    )
    st.markdown("---")
    col_mac, col_win = st.columns(2)

    with col_mac:
        st.markdown("#### 🍎 Mac をお使いの方")
        mac_path = os.path.join(os.path.dirname(__file__), "downloads", "スキャンファイル格納-mac.zip")
        if os.path.exists(mac_path):
            with open(mac_path, "rb") as f:
                st.download_button(
                    label="Mac版をダウンロード (.zip)",
                    data=f.read(),
                    file_name="スキャンファイル格納-mac.zip",
                    mime="application/zip",
                    use_container_width=True,
                )
            st.caption("① zipを解凍 → ② .appをデスクトップへ → ③ ダブルクリック")
        else:
            st.info("準備中です。")

    with col_win:
        st.markdown("#### 🪟 Windows をお使いの方")
        win_path = os.path.join(os.path.dirname(__file__), "downloads", "スキャンファイル格納.url")
        if os.path.exists(win_path):
            with open(win_path, "rb") as f:
                st.download_button(
                    label="Windows版をダウンロード (.url)",
                    data=f.read(),
                    file_name="スキャンファイル格納.url",
                    mime="application/internet-shortcut",
                    use_container_width=True,
                )
            st.caption("① ダウンロード → ② デスクトップへ移動 → ③ ダブルクリック")
        else:
            st.info("準備中です。")

st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# 認証ゲート
# ─────────────────────────────────────────────────────────────────────────────

if 'credentials' not in st.session_state:
    st.markdown("---")
    st.markdown("### はじめに Google アカウントでサインインしてください")
    st.markdown(
        "ファイルを Google Drive に保存するため、"
        "Googleアカウントへのサインインが必要です。"
    )

    # 認証エラーがあれば表示（pop しない → 消えない）
    if 'auth_error' in st.session_state:
        st.error(f"⚠️ サインインエラー:\n\n{st.session_state['auth_error']}")

    try:
        st.link_button(
            "🔑  Google アカウントでサインインする",
            get_auth_url(),
            type='primary',
            use_container_width=True,
        )
    except Exception:
        st.error("アプリの設定が完了していません。管理者にお問い合わせください。")
    st.stop()

try:
    service = build_service()
except Exception:
    st.warning("サインイン情報が古くなりました。再度サインインしてください。")
    del st.session_state['credentials']
    st.rerun()

col_msg, col_out = st.columns([5, 1])
with col_msg:
    st.success("✅ Google アカウントでサインイン済み")
with col_out:
    if st.button("ログアウト"):
        for k in ['credentials', 'selected_folder', 'search_results', 'search_no_result']:
            st.session_state.pop(k, None)
        st.rerun()

st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# ① ファイルを選ぶ
# ─────────────────────────────────────────────────────────────────────────────

st.subheader("① ファイルを選ぶ")

uploaded = st.file_uploader(
    "PDF または Excel ファイルをドラッグ＆ドロップ、またはクリックして選択",
    type=['pdf', 'xlsx'],
)

if not uploaded:
    st.info("↑ まずファイルを選んでください。")
    st.stop()


@st.cache_data(show_spinner="ファイルを読み込んでいます…")
def _extract(name: str, data: bytes) -> tuple:
    suffix = Path(name).suffix.lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
        f.write(data)
        path = f.name
    try:
        return extract_from_pdf(path) if suffix == '.pdf' else extract_from_excel(path)
    except Exception:
        return None, None
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


customer, title = _extract(uploaded.name, uploaded.getvalue())
st.success(f"📄 **{uploaded.name}** を選択しました")
st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# ② お客様情報を確認する
# ─────────────────────────────────────────────────────────────────────────────

st.subheader("② お客様情報を確認する")

if not customer and not title:
    st.warning("自動で読み取れませんでした。下の欄に入力してください。")

col1, col2 = st.columns(2)
with col1:
    cust_val = st.text_input("お客様名", value=customer or '', placeholder="例: 山崎")
with col2:
    ttl_val = st.text_input("題名", value=title or '', placeholder="例: 請負契約書")

if not cust_val or not ttl_val:
    st.warning("お客様名と題名を入力してください。")
    st.stop()

date_str = datetime.now().strftime('%Y%m%d')
file_ext = Path(uploaded.name).suffix
new_name = f"{date_str}_{sanitize(cust_val)}_{sanitize(ttl_val)}{file_ext}"

st.markdown(
    f'<div class="preview-box">💾 保存ファイル名：<strong>{new_name}</strong></div>',
    unsafe_allow_html=True,
)
st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# ③ 保存先フォルダを指定する（名前入力 → 自動検索）
# ─────────────────────────────────────────────────────────────────────────────

st.subheader("③ 保存先フォルダを指定する")
st.caption("フォルダ名の一部を入力してください。キーワードを含むフォルダを自動で探します。")

# フォルダ検索フォーム（Enter キーでも送信できる）
with st.form("folder_search_form", clear_on_submit=False):
    folder_query = st.text_input(
        "フォルダ名（一部でもOK）",
        placeholder="例: 請負　/ 契約　/ 山崎",
        help="フォルダ名の一部を入力するだけで候補が表示されます。",
    )
    search_submitted = st.form_submit_button("🔍 このフォルダを探す", use_container_width=True)

# 検索実行
if search_submitted and folder_query.strip():
    # 前回の結果をリセット
    for k in ['selected_folder', 'search_results', 'search_no_result']:
        st.session_state.pop(k, None)

    with st.spinner(f"「{folder_query.strip()}」を Google Drive で検索中…"):
        found = search_folders(service, folder_query.strip())

    if not found:
        st.session_state['search_no_result'] = folder_query.strip()
    elif len(found) == 1:
        path = get_folder_path(service, found[0]['id'])
        st.session_state['selected_folder'] = {'id': found[0]['id'], 'path': path}
    else:
        # 複数ヒット → パスを取得してリストに保存
        st.session_state['search_results'] = [
            {'id': f['id'], 'path': get_folder_path(service, f['id'])}
            for f in found
        ]
    st.rerun()

# ── 見つからなかった場合 ──────────────────────────────────────────────────────
if 'search_no_result' in st.session_state:
    q = st.session_state['search_no_result']
    st.error(
        f"「{q}」を含むフォルダが見つかりませんでした。\n\n"
        "別のキーワードで試してください。"
    )
    st.stop()

# ── 複数ヒットした場合 → どれか選ばせる ─────────────────────────────────────
if 'search_results' in st.session_state and 'selected_folder' not in st.session_state:
    results = st.session_state['search_results']
    st.info(
        f"同じ名前のフォルダが **{len(results)}件** 見つかりました。\n"
        "保存先をクリックして選んでください："
    )
    for r in results:
        if st.button(f"📁  {r['path']}", key=f"pick_{r['id']}", use_container_width=True):
            st.session_state['selected_folder'] = r
            del st.session_state['search_results']
            st.rerun()
    st.stop()

# ── 保存先が未選択の場合はここで停止 ─────────────────────────────────────────
selected = st.session_state.get('selected_folder')
if not selected:
    st.info("フォルダ名を入力して「探す」をクリックしてください。")
    st.stop()

# ── 保存先が確定した場合 ──────────────────────────────────────────────────────
st.success(f"✅ 保存先：**{selected['path']}**")

if st.button("🔄 フォルダを変更する"):
    for k in ['selected_folder', 'search_results', 'search_no_result']:
        st.session_state.pop(k, None)
    st.rerun()

st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# 保存ボタン
# ─────────────────────────────────────────────────────────────────────────────

if st.button("💾  このフォルダに保存する", type='primary', use_container_width=True):
    folder_id = selected['id']
    mime      = MIME.get(file_ext, 'application/octet-stream')

    with st.spinner("Google Drive にアップロードしています…"):
        try:
            media  = MediaIoBaseUpload(io.BytesIO(uploaded.getvalue()), mimetype=mime)
            result = service.files().create(
                body={'name': new_name, 'parents': [folder_id]},
                media_body=media,
                fields='id,webViewLink',
                supportsAllDrives=True,   # 共有ドライブへのアップロード対応
            ).execute()

            st.balloons()
            st.success(f"✅ 保存しました！　**{new_name}**")
            if result.get('webViewLink'):
                st.link_button("Google Drive で確認する 🔗", result['webViewLink'])

        except Exception as e:
            st.error(f"保存に失敗しました。もう一度お試しください。\n（{e}）")
