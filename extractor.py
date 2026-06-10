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


def extract_from_pdf(filepath: str) -> Tuple[Optional[str], Optional[str]]:
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError(
            "pdfplumberがインストールされていません。\npip install pdfplumber を実行してください。"
        )

    try:
        with pdfplumber.open(filepath) as pdf:
            if not pdf.pages:
                return None, None
            text = pdf.pages[0].extract_text() or ''
    except Exception as e:
        raise RuntimeError(f"PDFの読み取りに失敗しました: {e}")

    lines = [ln.strip() for ln in text.split('\n') if ln.strip()]
    return _find_customer(lines), _find_title(lines)


def extract_from_excel(filepath: str) -> Tuple[Optional[str], Optional[str]]:
    try:
        import openpyxl
    except ImportError:
        raise RuntimeError(
            "openpyxlがインストールされていません。\npip install openpyxl を実行してください。"
        )

    try:
        wb = openpyxl.load_workbook(filepath, data_only=True)
        ws = wb.active
        cells: list[str] = []
        for row in ws.iter_rows(min_row=1, max_row=10, min_col=1, max_col=3, values_only=True):
            for val in row:
                if val is not None:
                    s = str(val).strip()
                    if s:
                        cells.append(s)
    except Exception as e:
        raise RuntimeError(f"Excelファイルの読み取りに失敗しました: {e}")

    return _find_customer(cells), _find_title(cells)


def _find_title(lines: list) -> Optional[str]:
    for line in lines[:15]:
        for kw in TITLE_KEYWORDS:
            if kw in line:
                # Return the full line if it's short enough, otherwise just the keyword
                return line if len(line) <= 30 else kw
    return None


def _find_customer(lines: list) -> Optional[str]:
    for line in lines[:20]:
        for pat in CUSTOMER_PATTERNS:
            m = pat.search(line)
            if m:
                name = m.group(1).strip()
                if name:
                    return name
    return None
