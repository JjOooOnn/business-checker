import os
import requests
import json
from flask import Flask, render_template, request

# --- Flask 앱 생성 ---
app = Flask(__name__)

# --- 상태 코드별 안내 문구 (새로 추가) ---
STATUS_CODE_MESSAGES = {
    400: "잘못된 요청 형식입니다. (API 서버가 이해할 수 없는 요청)",
    404: "API 서비스를 찾을 수 없습니다. (경로 확인 필요)",
    411: "필수 요청 파라미터가 누락되었습니다.",
    413: "요청 가능한 사업자번호 개수(100개)를 초과했습니다.",
    500: "국세청 API 서버에 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
}


# --- check_business_registration 함수 (수정) ---
def check_business_registration(business_numbers: list, service_key: str):
    """
    국세청 사업자등록정보 상태조회 API를 호출하고, 상태 코드에 따라 적절한 오류 메시지를 반환합니다.
    """
    api_url = f"https://api.odcloud.kr/api/nts-businessman/v1/status?serviceKey={service_key}"
    payload = {"b_no": business_numbers}
    headers = {"Content-Type": "application/json", "Accept": "application/json"}

    try:
        response = requests.post(api_url, headers=headers, data=json.dumps(payload), timeout=10)

        if response.status_code == 200:
            return response.json()
        else:
            # 딕셔너리에서 상태 코드에 맞는 안내 문구를 찾고, 없으면 기본 메시지를 사용합니다.
            error_message = STATUS_CODE_MESSAGES.get(
                response.status_code,
                f"알 수 없는 오류가 발생했습니다. (상태 코드: {response.status_code})"
            )
            return {"error": error_message}

except requests.exceptions.RequestException as e:
# 더 자세한 오류 확인을 위해 실제 오류 내용을 포함시킵니다.
    detailed_error = str(e)
    print(f"!!! Detailed Network Error: {detailed_error}")  # Render 로그에 상세 오류 출력
    return {"error": f"네트워크 오류 발생 (상세 정보): {detailed_error}"}


# --- find_business_statuses 함수 (수정) ---
def find_business_statuses(business_numbers: list, service_key: str) -> dict:
    """
    사업자 번호 리스트를 조회하여 '모든' 사업자의 상태 정보를 반환합니다.
    """
    api_response = check_business_registration(business_numbers, service_key)

    results = {
        "data": [],
        "error": None,
    }

    if api_response and api_response.get("data"):
        results["data"] = api_response["data"]
    elif api_response and api_response.get("error"):
        # check_business_registration에서 반환된 친절한 오류 메시지를 그대로 사용합니다.
        results["error"] = api_response["error"]
    else:
        results["error"] = "API로부터 유효한 데이터를 받지 못했습니다."

    return results


# --- Flask 라우트 (웹 페이지 로직) ---
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        # 웹 양식에서 사용자가 입력한 사업자 번호와 서비스 키를 가져옵니다.
        # strip()으로 앞뒤 공백을 제거하고, 빈 줄은 제외합니다.
        b_numbers_input = [line.strip().replace('-', '') for line in request.form['business_numbers'].splitlines() if line.strip()]

        # 🚨 보안을 위해 서비스 키는 환경 변수에서 가져오는 것이 가장 좋습니다.
        # PythonAnywhere 설정에서 이 변수를 추가할 것입니다.
        my_service_key = os.environ.get("NTS_SERVICE_KEY")

        if not my_service_key:
            # 환경 변수가 설정되지 않은 경우를 대비한 오류 처리
            error_message = "서버에 서비스 키가 설정되지 않았습니다. 관리자에게 문의하세요."
            return render_template('index.html', error=error_message)

        if not b_numbers_input:
            # 입력된 사업자 번호가 없는 경우
            error_message = "조회할 사업자 번호를 입력해주세요."
            return render_template('index.html', error=error_message)

        # 함수를 호출하여 결과를 받습니다.
        results_data = find_business_statuses(b_numbers_input, my_service_key)

        # results.html 템플릿에 결과를 담아 사용자에게 보여줍니다.
        return render_template('results.html', results=results_data['data'], error=results_data['error'],
                               original_input=request.form['business_numbers'])

    # GET 요청(첫 페이지 접속) 시에는 입력 폼을 보여줍니다.
    return render_template('index.html')


# --- 로컬 테스트용 실행 코드 ---
# (PythonAnywhere에서는 이 부분이 사용되지 않습니다.)
if __name__ == '__main__':
    app.run(debug=True)