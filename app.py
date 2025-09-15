import os
import requests
import json
import pandas as pd
import io
from flask import Flask, render_template, request, send_file, flash, redirect, url_for

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
        response = requests.post(api_url, headers=headers, data=json.dumps(payload), timeout=30)
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
    if not file.filename.endswith('.xlsx'):
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


if __name__ == '__main__':
    app.run(debug=True)