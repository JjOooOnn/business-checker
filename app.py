import os
import re
import logging
import json
import io

import requests
import urllib3
import pandas as pd
from flask import Flask, render_template, request, send_file, flash, redirect, url_for
from werkzeug.utils import secure_filename

# ── SSL 경고 억제 (내부 검증된 API 서버 전용) ──────────────────────────────
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── 로깅 설정 ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ── Flask 앱 생성 ──────────────────────────────────────────────────────────
app = Flask(__name__)
# [수정] os.urandom(24) 는 서버 재시작마다 바뀌어 flash 메시지가 사라지는 문제 발생.
#        환경변수에서 고정 키를 읽고, 없을 때만 임시 키 사용.
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-me-in-production')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB

# ── 상태 코드별 안내 문구 ──────────────────────────────────────────────────
STATUS_CODE_MESSAGES = {
    400: "잘못된 요청 형식입니다. (API 서버가 이해할 수 없는 요청)",
    404: "API 서비스를 찾을 수 없습니다. (경로 확인 필요)",
    411: "필수 요청 파라미터가 누락되었습니다.",
    413: "요청 가능한 사업자번호 개수(100개)를 초과했습니다.",
    500: "국세청 API 서버에 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
}


# ── [신규] 사업자번호 유효성 검사 ─────────────────────────────────────────
def validate_b_no(b_no: str) -> bool:
    """사업자등록번호는 숫자 10자리여야 합니다."""
    return b_no.isdigit() and len(b_no) == 10


# ── API 호출 함수 ──────────────────────────────────────────────────────────
def check_business_registration(business_numbers: list, service_key: str):
    api_url = (
        f"https://api.odcloud.kr/api/nts-businessman/v1/status"
        f"?serviceKey={service_key}"
    )
    payload = {"b_no": business_numbers}
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    try:
        response = requests.post(
            api_url, headers=headers,
            data=json.dumps(payload),
            timeout=30, verify=False
        )
        if response.status_code == 200:
            return response.json()
        error_message = STATUS_CODE_MESSAGES.get(
            response.status_code,
            f"알 수 없는 오류가 발생했습니다. (상태 코드: {response.status_code})"
        )
        return {"error": error_message}
    except requests.exceptions.RequestException as e:
        logger.error("API 네트워크 오류: %s", e)
        return {"error": f"네트워크 오류 발생: {e}"}


# ── 공통 API 호출 로직 (유효성 검사 포함) ────────────────────────────────
def process_api_calls(business_numbers: list, service_key: str):
    # [수정] 유효하지 않은 번호를 미리 분리하여 API 호출 비용 절감 + 사용자 피드백 제공
    valid   = [b for b in business_numbers if validate_b_no(b)]
    invalid = [b for b in business_numbers if not validate_b_no(b)]

    if invalid:
        logger.warning("유효하지 않은 사업자번호 %d건 제외: %s", len(invalid), invalid[:10])

    if not valid:
        return None, None, "유효한 사업자등록번호(숫자 10자리)가 없습니다."

    chunks = [valid[i:i + 100] for i in range(0, len(valid), 100)]
    all_results = []
    for chunk in chunks:
        api_response = check_business_registration(chunk, service_key)
        if api_response.get("error"):
            return None, invalid, api_response["error"]
        if api_response.get("data"):
            all_results.extend(api_response["data"])

    return all_results, invalid, None   # (결과, 잘못된번호목록, 에러)


# ── 서버 구동 시 CSV 데이터를 메모리에 미리 로드 ─────────────────────────
brd_file = 'broadcasting_20250811.csv'
pub_file = 'periodicals_20260403.csv'


def _load_csv(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        logger.warning("파일 없음: %s", path)
        return pd.DataFrame()
    for enc in ('utf-8', 'cp949'):
        try:
            df = pd.read_csv(path, encoding=enc).fillna('')
            logger.info("로드 완료 (%s): %d건", path, len(df))
            return df
        except UnicodeDecodeError:
            continue
    logger.error("인코딩 감지 실패: %s", path)
    return pd.DataFrame()


global_df_brd = _load_csv(brd_file)
global_df_pub  = _load_csv(pub_file)


# ── 매체 다중 키워드 검색 (판다스 벡터화 + 정규식 안전 처리) ───────────
def search_media_csv(keyword_input: str) -> list:
    results = []
    keywords = [k.strip() for k in keyword_input.replace(',', ' ').split() if k.strip()]
    if not keywords:
        return results

    # [수정] re.escape() 적용 → 검색어에 '(' ')' '.' 등 특수문자가 포함돼도 서버 에러 없음
    pattern = '|'.join(re.escape(k) for k in keywords)

    # 1. 방송사업자 검색
    if not global_df_brd.empty:
        mask = (
            global_df_brd['방송사명'].astype(str).str.contains(pattern, na=False)
            | global_df_brd['방송국명'].astype(str).str.contains(pattern, na=False)
        )
        for _, row in global_df_brd[mask].iterrows():
            brd_name     = str(row.get('방송사명', ''))
            station_name = str(row.get('방송국명', ''))
            display_name = (
                f"{brd_name} ({station_name})"
                if station_name and station_name != brd_name
                else (brd_name or station_name or '-')
            )
            brd_type = str(row.get('유형', ''))
            results.append({
                "category": f"방송사업자({brd_type})" if brd_type else "방송사업자",
                "name":     display_name,
                "owner":    "-",
                "status":   "허가",
            })

    # 2. 정기간행물 검색
    if not global_df_pub.empty:
        mask = (
            global_df_pub['제호'].astype(str).str.contains(pattern, na=False)
            | global_df_pub['발행소명'].astype(str).str.contains(pattern, na=False)
        )
        for _, row in global_df_pub[mask].iterrows():
            jong_byeol = str(row.get('종별', ''))
            results.append({
                "category": f"정기간행물({jong_byeol})" if jong_byeol else "정기간행물",
                "name":     str(row.get('제호',    '-')) or '-',
                "owner":    str(row.get('발행소명', '-')) or '-',
                "status":   str(row.get('상태',    '-')),
            })

    return results


# ── 결과 → 엑셀 변환 헬퍼 ─────────────────────────────────────────────────
def _results_to_excel(results: list, sheet_name: str = 'Result') -> io.BytesIO:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        pd.DataFrame(results).to_excel(writer, index=False, sheet_name=sheet_name)
    output.seek(0)
    return output


# ════════════════════════════════════════════════════════════════════════════
#  라우팅
# ════════════════════════════════════════════════════════════════════════════

@app.route('/')
def index():
    return render_template('index.html')


# ── 직접 입력 조회 ────────────────────────────────────────────────────────
@app.route('/lookup-direct', methods=['POST'])
def lookup_direct():
    my_service_key = os.environ.get("NTS_SERVICE_KEY")
    if not my_service_key:
        return render_template('results.html', error="서버에 서비스 키가 설정되지 않았습니다.")

    b_numbers_raw_text = request.form.get('business_numbers', '')
    b_numbers = [
        num.strip().replace('-', '').replace(' ', '')
        for num in b_numbers_raw_text.splitlines()
        if num.strip()
    ]

    if not b_numbers:
        return render_template('results.html', error="조회할 사업자 번호를 입력해주세요.")

    results, invalid_numbers, error = process_api_calls(b_numbers, my_service_key)
    if error:
        return render_template('results.html', error=f"API 호출 중 오류 발생: {error}")

    # [신규] 통계 계산
    stats = _calc_stats(results or [])

    return render_template(
        'results.html',
        results=results,
        invalid_numbers=invalid_numbers,
        stats=stats,
        b_numbers_raw=b_numbers_raw_text,   # 엑셀 다운로드 재사용
    )


# ── [신규] 직접 입력 결과 엑셀 다운로드 ──────────────────────────────────
@app.route('/download-direct-excel', methods=['POST'])
def download_direct_excel():
    my_service_key = os.environ.get("NTS_SERVICE_KEY")
    if not my_service_key:
        flash("서버에 서비스 키가 설정되지 않았습니다.")
        return redirect(url_for('index'))

    b_numbers_raw_text = request.form.get('business_numbers', '')
    b_numbers = [
        num.strip().replace('-', '').replace(' ', '')
        for num in b_numbers_raw_text.splitlines()
        if num.strip()
    ]

    results, _, error = process_api_calls(b_numbers, my_service_key)
    if error:
        flash(f"API 호출 중 오류: {error}")
        return redirect(url_for('index'))
    if not results:
        flash("다운로드할 데이터가 없습니다.")
        return redirect(url_for('index'))

    return send_file(
        _results_to_excel(results, sheet_name='사업자조회결과'),
        download_name='사업자조회결과.xlsx',
        as_attachment=True,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )


# ── 엑셀 업로드 처리 ──────────────────────────────────────────────────────
@app.route('/upload-excel', methods=['POST'])
def upload_excel():
    my_service_key = os.environ.get("NTS_SERVICE_KEY")
    if not my_service_key:
        flash("서버에 서비스 키가 설정되지 않았습니다.")
        return redirect(url_for('index'))

    if 'excel_file' not in request.files or request.files['excel_file'].filename == '':
        flash("엑셀 파일을 선택해주세요.")
        return redirect(url_for('index'))

    file = request.files['excel_file']
    filename = secure_filename(file.filename)
    if not filename.lower().endswith('.xlsx'):
        flash("엑셀 파일(.xlsx)만 업로드할 수 있습니다.")
        return redirect(url_for('index'))

    try:
        df = pd.read_excel(file, engine='openpyxl')
        if df.empty:
            flash("엑셀 파일이 비어있습니다.")
            return redirect(url_for('index'))

        b_numbers = [
            str(num).strip().replace('-', '').replace(' ', '')
            for num in df.iloc[:, 0].dropna()
            if str(num).strip()
        ]

        if not b_numbers:
            flash("엑셀 파일의 첫 번째 열에서 유효한 사업자등록번호를 찾을 수 없습니다.")
            return redirect(url_for('index'))

        results, _, error = process_api_calls(b_numbers, my_service_key)
        if error:
            flash(f"API 호출 중 오류 발생: {error}")
            return redirect(url_for('index'))
        if not results:
            flash("조회된 결과가 없습니다.")
            return redirect(url_for('index'))

        return send_file(
            _results_to_excel(results),
            download_name='business_status_results.xlsx',
            as_attachment=True,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )

    except Exception as e:
        logger.error("엑셀 업로드 오류: %s", e)
        flash(f"파일 처리 중 오류 발생: {e}")
        return redirect(url_for('index'))


# ── 매체 검색 ─────────────────────────────────────────────────────────────
@app.route('/search-media', methods=['POST'])
def search_media():
    keyword = request.form.get('keyword', '').strip()
    if not keyword:
        return render_template('media_results.html', error="검색어를 입력해주세요.")
    results = search_media_csv(keyword)
    return render_template('media_results.html', keyword=keyword, results=results)


# ── 매체 검색 결과 엑셀 다운로드 ─────────────────────────────────────────
@app.route('/download-media-excel', methods=['POST'])
def download_media_excel():
    keyword = request.form.get('keyword', '').strip()
    if not keyword:
        flash("검색어가 없습니다.")
        return redirect(url_for('index'))

    results = search_media_csv(keyword)
    if not results:
        flash("다운로드할 데이터가 없습니다.")
        return redirect(url_for('index'))

    df = pd.DataFrame(results).rename(columns={
        'category': '구분',
        'name':     '매체명(제호/방송사명)',
        'owner':    '발행소명',
        'status':   '상태',
    })
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='매체검색결과')
    output.seek(0)

    return send_file(
        output,
        download_name=f'매체검색결과_{keyword}.xlsx',
        as_attachment=True,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )


# ── 헬퍼: 결과 통계 ──────────────────────────────────────────────────────
def _calc_stats(results: list) -> dict:
    return {
        'active':    sum(1 for r in results if r.get('b_stt_cd') == '01'),
        'suspended': sum(1 for r in results if r.get('b_stt_cd') == '02'),
        'closed':    sum(1 for r in results if r.get('b_stt_cd') == '03'),
    }


if __name__ == '__main__':
    app.run(debug=True)