import re
from typing import Optional, Tuple

# Ordered by specificity (longer/more specific first to avoid partial matches)
TITLE_KEYWORDS = [
    '工事請負契約書', '請負契約書', '工事請書', '工事注文書',
    '御見積書', '見積書', '見積もり書',
    '御請求書', '請求書',
    '納品書', '受領書',
    '領収証', '領収書',
    '売買契約書', '業務委託契約書', '秘密保持契約書', '契約書',
    '提案書', '企画書', '仕様書',
    '報告書', '調査報告書',
    '議事録', '打合せ記録',
    '発注書', '注文書',
    '確認書', '同意書', '覚書', '誓約書', '委任状',
    '申請書', '依頼書',
]

CUSTOMER_PATTERNS = [
    re.compile(r'^(.+?)\s*様\s*$'),
    re.compile(r'^(.+?)\s*御中\s*$'),
    re.compile(r'^(.+?)\s*殿\s*$'),
    re.compile(r'(?:お客様名?|顧客名|取引先名?|宛先|宛名)[：:\s]+(.+)'),
    re.compile(r'^((?:株式会社|有限会社|合同会社|一般社団法人|公益社団法人|一般財団法人|公益財団法人|特定非営利活動法人|学校法人|医療法人).+)'),
    re.compile(r'^(.+(?:株式会社|有限会社|合同会社))\s*$'),
]


def extract_from_pdf(filepath: str) -> Tuple[Optional[str], Optional[str], list]:
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError(
            "pdfplumberがインストールされていません。\npip install pdfplumber を実行してください。"
        )

    try:
        with pdfplumber.open(filepath) as pdf:
            if not pdf.pages:
                return None, None, None
            text = pdf.pages[0].extract_text() or ''
    except Exception as e:
        raise RuntimeError(f"PDFの読み取りに失敗しました: {e}")

    lines = [ln.strip() for ln in text.split('\n') if ln.strip()]
    return _find_customer(lines), _find_title(lines), _find_heading_candidates(lines)


def extract_from_excel(filepath: str) -> Tuple[Optional[str], Optional[str], list]:
    try:
        import openpyxl
    except ImportError:
        raise RuntimeError(
            "openpyxlがインストールされていません。\npip install openpyxl を実行してください。"
        )

    try:
        wb = openpyxl.load_workbook(filepath, data_only=True)
        ws = wb.active
        # 見出し候補を十分に集めるため、先頭付近を広めに読む（A1〜H40）
        cells: list[str] = []
        for row in ws.iter_rows(min_row=1, max_row=40, min_col=1, max_col=8, values_only=True):
            for val in row:
                if val is not None:
                    s = str(val).strip()
                    if s and s not in cells:
                        cells.append(s)
    except Exception as e:
        raise RuntimeError(f"Excelファイルの読み取りに失敗しました: {e}")

    return _find_customer(cells), _find_title(cells), _find_heading_candidates(cells)


def _find_title(lines: list) -> Optional[str]:
    for line in lines[:15]:
        for kw in TITLE_KEYWORDS:
            if kw in line:
                # Return the full line if it's short enough, otherwise just the keyword
                return line if len(line) <= 30 else kw
    return None


# 見出しとして採用したくない行を弾くためのパターン
_DATE_RE = re.compile(r'^[\s　]*(?:令和|平成|西暦)?\s*\d{1,4}\s*[年./-]')
_NUM_ONLY_RE = re.compile(r'^[\s　0-9０-９.,，、\-－/／ｰ−–—]+$')
_PAGE_RE = re.compile(r'(?:ページ|頁|page|P\.|No\.?|№)', re.IGNORECASE)
_CUSTOMER_END_RE = re.compile(r'(?:様|御中|殿)\s*$')


def _looks_like_heading(line: str) -> bool:
    """その行が文書の見出し（題名）らしいかどうかを判定する。"""
    s = line.strip()
    if not (2 <= len(s) <= 40):
        return False
    if _CUSTOMER_END_RE.search(s):          # 「○○様」などの宛名行
        return False
    if _DATE_RE.match(s):                    # 日付行
        return False
    if _NUM_ONLY_RE.match(s):                # 数字・記号だけの行
        return False
    if _PAGE_RE.search(s):                   # ページ番号など
        return False
    # 住所・電話・メールらしき行
    if re.search(r'(?:〒|TEL|FAX|E-?mail|@|電話|住所)', s, re.IGNORECASE):
        return False
    # 会社名の宛先行（御中等が無い純粋な社名は見出しではないことが多い）
    if re.match(r'^(?:株式会社|有限会社|合同会社)', s) and len(s) <= 20:
        return False
    return True


def _find_heading_candidates(lines: list, limit: int = 12) -> list:
    """文書の上部から、題名候補となる文章を「上から順番に」収集して返す。

    リロード機能で順番に提案できるよう、文書の並び順のまま候補をリストで返す。
    日付・ページ番号・数字だけの行などの明らかなノイズのみ除外する。
    """
    keyworded: list = []  # 「報告書」「契約書」等の題名キーワードを含む行（最優先）
    others: list = []     # それ以外の見出し候補（文書の上から順）

    for line in lines[:30]:
        s = line.strip()
        if not (2 <= len(s) <= 50):
            continue
        if _NUM_ONLY_RE.match(s) or _DATE_RE.match(s) or _PAGE_RE.search(s):
            continue
        if re.search(r'(?:〒|TEL|FAX|E-?mail|@|電話)', s, re.IGNORECASE):
            continue

        if any(kw in s for kw in TITLE_KEYWORDS):
            if s not in keyworded:
                keyworded.append(s)
        else:
            if s not in others:
                others.append(s)

    # 題名キーワードを含む行を先頭に、その後に上から順の候補を並べる
    result: list = []
    for s in keyworded + others:
        if s not in result:
            result.append(s)
        if len(result) >= limit:
            break
    return result


def _find_customer(lines: list) -> Optional[str]:
    for line in lines[:20]:
        for pat in CUSTOMER_PATTERNS:
            m = pat.search(line)
            if m:
                name = m.group(1).strip()
                if name:
                    return name
    return None
