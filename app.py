import os
import requests
import json
import pandas as pd
import io
from flask import Flask, render_template, request, send_file, flash, redirect, url_for
from werkzeug.utils import secure_filename

# --- Flask 앱 생성 ---
app = Flask(__name__)
# flash 메시지를 사용하려면 secret_key가 반드시 필요합니다.
app.config['SECRET_KEY'] = os.urandom(24)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB 파일 업로드 제한

# --- 상태 코드별 안내 문구 (변경 없음) ---
STATUS_CODE_MESSAGES = {
    400: "잘못된 요청 형식입니다. (API 서버가 이해할 수 없는 요청)",
    404: "API 서비스를 찾을 수 없습니다. (경로 확인 필요)",
    411: "필수 요청 파라미터가 누락되었습니다.",
    413: "요청 가능한 사업자번호 개수(100개)를 초과했습니다.",
    500: "국세청 API 서버에 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
}


# --- API 호출 함수 (변경 없음) ---
def check_business_registration(business_numbers: list, service_key: str):
    # (이전과 동일한 내용)
    api_url = f"https://api.odcloud.kr/api/nts-businessman/v1/status?serviceKey={service_key}"
    payload = {"b_no": business_numbers}
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    try:
        response = requests.post(api_url, headers=headers, data=json.dumps(payload), timeout=30, verify=False)
        if response.status_code == 200:
            return response.json()
        else:
            error_message = STATUS_CODE_MESSAGES.get(response.status_code,
                                                     f"알 수 없는 오류가 발생했습니다. (상태 코드: {response.status_code})")
            return {"error": error_message}
    except requests.exceptions.RequestException as e:
        detailed_error = str(e)
        print(f"!!! Detailed Network Error: {detailed_error}")
        return {"error": f"네트워크 오류 발생 (상세 정보): {detailed_error}"}


# --- 공통 API 호출 로직 ---
def process_api_calls(business_numbers: list, service_key: str):
    b_number_chunks = [business_numbers[i:i + 100] for i in range(0, len(business_numbers), 100)]
    all_results = []
    for chunk in b_number_chunks:
        api_response = check_business_registration(chunk, service_key)
        if api_response.get("error"):
            return None, api_response["error"]  # 결과는 없고, 에러 메시지만 반환
        if api_response.get("data"):
            all_results.extend(api_response["data"])
    return all_results, None  # 결과 반환, 에러 없음


# # --- [신규 기능] 매체(방송/정기간행물) 다중 키워드 검색 로직 ---
# def search_media_apis(keyword_input, service_key):
#     results = []
#     headers = {"Accept": "application/json"}
#
#     # 쉼표나 공백으로 구분된 여러 키워드를 리스트로 쪼개기
#     keywords = [k.strip() for k in keyword_input.replace(',', ' ').split() if k.strip()]
#     if not keywords:
#         return results
#
#     # 1. 방송통신위원회_방송사업자 허가 현황 API
#     base_brd_url = "https://api.odcloud.kr/api/3068655/v1/uddi:32ac4a9c-9cdd-4bb9-b273-ce1d95de235a"
#     brd_page = 1
#     brd_per_page = 1000
#     seen_brd = set()
#
#     while True:
#         brd_url = f"{base_brd_url}?page={brd_page}&perPage={brd_per_page}&serviceKey={service_key}"
#         try:
#             brd_res = requests.get(brd_url, headers=headers, verify=False, timeout=15)
#             if brd_res.status_code == 200:
#                 res_json = brd_res.json()
#                 data = res_json.get("data", [])
#                 current_count = res_json.get("currentCount", 0)
#
#                 if not data or current_count == 0:
#                     break
#
#                 for item in data:
#                     brd_name = item.get('방송사명', '')
#                     station_name = item.get('방송국명', '')
#
#                     # 여러 키워드 중 하나라도 포함되어 있는지 확인 (OR 검색)
#                     if any(k in str(brd_name) or k in str(station_name) for k in keywords):
#                         unique_key = f"{brd_name}_{station_name}"
#                         if unique_key not in seen_brd:
#                             seen_brd.add(unique_key)
#
#                             display_name = f"{brd_name} ({station_name})" if station_name and station_name != brd_name else (
#                                         brd_name or station_name or '-')
#                             brd_type = item.get('유형', '')
#                             category_text = f"방송사업자({brd_type})" if brd_type else "방송사업자"
#
#                             results.append({
#                                 "category": category_text,
#                                 "name": display_name,
#                                 "owner": "-",
#                                 "status": "허가"
#                             })
#
#                 if current_count < brd_per_page:
#                     break
#
#                 brd_page += 1
#
#             else:
#                 print(f"방송 API 호출 실패: 상태코드 {brd_res.status_code}")
#                 break
#         except Exception as e:
#             print(f"방송사업자 API 에러 (page {brd_page}): {e}")
#             break
#
#     # 2. 문화체육관광부_정기간행물 등록 현황 API
#     base_pub_url = "https://api.odcloud.kr/api/15070478/v1/uddi:b355cbd7-1239-44cb-a439-86e080c043a8"
#     pub_page = 1
#     pub_per_page = 1000
#     seen_pub = set()
#
#     while pub_page <= 60:
#         pub_url = f"{base_pub_url}?page={pub_page}&perPage={pub_per_page}&serviceKey={service_key}"
#         try:
#             pub_res = requests.get(pub_url, headers=headers, verify=False, timeout=15)
#             if pub_res.status_code == 200:
#                 res_json = pub_res.json()
#                 data = res_json.get("data", [])
#                 current_count = res_json.get("currentCount", 0)
#
#                 if not data or current_count == 0:
#                     break
#
#                 for item in data:
#                     # 여러 키워드 중 하나라도 포함되어 있는지 확인 (OR 검색)
#                     if any(k in str(item.get('제호', '')) or k in str(item.get('발행소명', '')) for k in keywords):
#
#                         unique_key = str(item.get('등록번호', '')) + str(item.get('제호', ''))
#                         if unique_key not in seen_pub:
#                             seen_pub.add(unique_key)
#
#                             jong_byeol = item.get('종별', '')
#                             category_text = f"정기간행물({jong_byeol})" if jong_byeol else "정기간행물"
#
#                             results.append({
#                                 "category": category_text,
#                                 "name": item.get('제호', '-'),
#                                 "owner": item.get('발행소명', '-'),
#                                 "status": item.get('상태', '-')
#                             })
#
#                 if current_count < pub_per_page:
#                     break
#
#                 pub_page += 1
#             else:
#                 print(f"정기간행물 API 호출 실패: 상태코드 {pub_res.status_code}")
#                 break
#         except Exception as e:
#             print(f"정기간행물 API 에러 (page {pub_page}): {e}")
#             break
#
#     return results

# --- [신규 기능] 서버 구동 시 CSV 데이터를 메모리에 미리 로드 (속도 100배 향상) ---
brd_file = 'broadcasting_20250811.csv'
pub_file = 'periodicals_20251104.csv'

# 1. 방송사업자 데이터 전역 변수로 로드
if os.path.exists(brd_file):
    try:
        global_df_brd = pd.read_csv(brd_file, encoding='utf-8').fillna('')
    except UnicodeDecodeError:
        global_df_brd = pd.read_csv(brd_file, encoding='cp949').fillna('')
else:
    print(f"🚨 서버 경고: 파일이 없습니다 -> {brd_file}")
    global_df_brd = pd.DataFrame()

# 2. 정기간행물 데이터 전역 변수로 로드
if os.path.exists(pub_file):
    try:
        global_df_pub = pd.read_csv(pub_file, encoding='utf-8').fillna('')
    except UnicodeDecodeError:
        global_df_pub = pd.read_csv(pub_file, encoding='cp949').fillna('')
else:
    print(f"🚨 서버 경고: 파일이 없습니다 -> {pub_file}")
    global_df_pub = pd.DataFrame()


# --- [완벽 최적화] 매체 다중 키워드 검색 로직 (판다스 벡터화 검색 적용) ---
def search_media_csv(keyword_input):
    results = []
    keywords = [k.strip() for k in keyword_input.replace(',', ' ').split() if k.strip()]
    if not keywords:
        return results

    # 다중 키워드를 판다스 검색용 패턴(예: "미디어|뉴스|라디오")으로 변환
    pattern = '|'.join(keywords)

    # 1. 방송사업자 초고속 검색
    if not global_df_brd.empty:
        # 한 줄씩 읽지 않고, 데이터 전체에서 키워드가 포함된 행(row)을 한 번에 필터링
        mask = (global_df_brd['방송사명'].astype(str).str.contains(pattern, na=False)) | \
               (global_df_brd['방송국명'].astype(str).str.contains(pattern, na=False))

        # 검색에 적중한 소수의 결과만 반복문 돌리기 (0.001초 소요)
        filtered_brd = global_df_brd[mask]
        for _, row in filtered_brd.iterrows():
            brd_name = str(row.get('방송사명', ''))
            station_name = str(row.get('방송국명', ''))
            display_name = f"{brd_name} ({station_name})" if station_name and station_name != brd_name else (
                        brd_name or station_name or '-')
            brd_type = str(row.get('유형', ''))
            category_text = f"방송사업자({brd_type})" if brd_type else "방송사업자"

            results.append({
                "category": category_text,
                "name": display_name,
                "owner": "-",
                "status": "허가"
            })

    # 2. 정기간행물 초고속 검색
    if not global_df_pub.empty:
        # 제호 또는 발행소명에 키워드가 있는 데이터 전체를 단숨에 필터링
        mask = (global_df_pub['제호'].astype(str).str.contains(pattern, na=False)) | \
               (global_df_pub['발행소명'].astype(str).str.contains(pattern, na=False))

        filtered_pub = global_df_pub[mask]
        for _, row in filtered_pub.iterrows():
            title = str(row.get('제호', ''))
            publisher = str(row.get('발행소명', ''))
            jong_byeol = str(row.get('종별', ''))
            category_text = f"정기간행물({jong_byeol})" if jong_byeol else "정기간행물"

            results.append({
                "category": category_text,
                "name": title or '-',
                "owner": publisher or '-',
                "status": str(row.get('상태', '-'))
            })

    return results

# --- 라우팅 로직 (대규모 수정) ---

# 1. 메인 페이지 (GET 요청만 처리)
@app.route('/')
def index():
    return render_template('index.html')


# 2. 직접 입력 처리
@app.route('/lookup-direct', methods=['POST'])
def lookup_direct():
    my_service_key = os.environ.get("NTS_SERVICE_KEY")
    if not my_service_key:
        return render_template('results.html', error="서버에 서비스 키가 설정되지 않았습니다.")

    b_numbers_raw = request.form.get('business_numbers', '').splitlines()
    b_numbers = [num.strip().replace('-', '').replace(' ', '') for num in b_numbers_raw if num.strip()]

    if not b_numbers:
        return render_template('results.html', error="조회할 사업자 번호를 입력해주세요.")

    results, error = process_api_calls(b_numbers, my_service_key)
    if error:
        return render_template('results.html', error=f"API 호출 중 오류 발생: {error}")

    return render_template('results.html', results=results)


# 3. 엑셀 업로드 처리
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
    filename = secure_filename(file.filename)  # 파일명에서 해킹용 특수문자 자동 제거
    # 소문자로 변환하여 .XLSX 등 대문자 우회 방어
    if not filename.lower().endswith('.xlsx'):
        flash("엑셀 파일(.xlsx)만 업로드할 수 있습니다.")
        return redirect(url_for('index'))

    try:
        df = pd.read_excel(file, engine='openpyxl')
        if df.empty:
            flash("엑셀 파일이 비어있습니다.")
            return redirect(url_for('index'))

        b_numbers_raw = df.iloc[:, 0].dropna().astype(str)
        b_numbers = [num.strip().replace('-', '').replace(' ', '') for num in b_numbers_raw if num.strip()]

        if not b_numbers:
            flash("엑셀 파일의 첫 번째 열에서 유효한 사업자등록번호를 찾을 수 없습니다.")
            return redirect(url_for('index'))

        results, error = process_api_calls(b_numbers, my_service_key)
        if error:
            flash(f"API 호출 중 오류 발생: {error}")
            return redirect(url_for('index'))

        if not results:
            flash("조회된 결과가 없습니다.")
            return redirect(url_for('index'))

        result_df = pd.DataFrame(results)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            result_df.to_excel(writer, index=False, sheet_name='Result')
        output.seek(0)

        return send_file(
            output,
            download_name='business_status_results.xlsx',
            as_attachment=True,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )

    except Exception as e:
        flash(f"파일 처리 중 오류 발생: {e}")
        return redirect(url_for('index'))


# # --- [신규 기능] 라우팅 ---
# @app.route('/search-media', methods=['POST'])
# def search_media():
#     my_service_key = os.environ.get("NTS_SERVICE_KEY")
#     if not my_service_key:
#         return render_template('media_results.html', error="서버에 서비스 키가 설정되지 않았습니다.")
#
#     keyword = request.form.get('keyword', '').strip()
#     if not keyword:
#         return render_template('media_results.html', error="검색어를 입력해주세요.")
#
#     results = search_media_apis(keyword, my_service_key)
#
#     return render_template('media_results.html', keyword=keyword, results=results)

# --- 라우팅 ---
@app.route('/search-media', methods=['POST'])
def search_media():
    # CSV 버전을 사용하므로 이제 국세청 API 키(service_key)가 없어도 이 기능은 작동합니다.
    keyword = request.form.get('keyword', '').strip()
    if not keyword:
        return render_template('media_results.html', error="검색어를 입력해주세요.")

    # API 대신 판다스로 CSV 검색 함수 실행
    results = search_media_csv(keyword)

    return render_template('media_results.html', keyword=keyword, results=results)

# --- [신규 기능] 매체 검색 결과 엑셀 다운로드 라우팅 ---
@app.route('/download-media-excel', methods=['POST'])
def download_media_excel():
    keyword = request.form.get('keyword', '').strip()
    if not keyword:
        flash("검색어가 없습니다.")
        return redirect(url_for('index'))

    # 기존에 만들어둔 초고속 메모리 검색 함수 재사용
    results = search_media_csv(keyword)

    if not results:
        flash("다운로드할 데이터가 없습니다.")
        return redirect(url_for('index'))

    # 결과를 데이터프레임으로 변환하고 엑셀용으로 컬럼명 예쁘게 변경
    df = pd.DataFrame(results)
    df.rename(columns={
        'category': '구분',
        'name': '매체명(제호/방송사명)',
        'owner': '발행소명',
        'status': '상태'
    }, inplace=True)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='매체검색결과')
    output.seek(0)

    # 파일명에 검색어를 포함시켜서 다운로드
    return send_file(
        output,
        download_name=f'매체검색결과_{keyword}.xlsx',
        as_attachment=True,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


if __name__ == '__main__':
    app.run(debug=True)