import os
import requests
import json
from flask import Flask, render_template, request

# --- Flask 앱 생성 ---
app = Flask(__name__)


# --- 기존 제공된 함수 (수정 없이 거의 그대로 사용) ---
def check_business_registration(business_numbers: list, service_key: str):
    """
    국세청 사업자등록정보 상태조회 API를 호출합니다.
    """
    api_url = f"https://api.odcloud.kr/api/nts-businessman/v1/status?serviceKey={service_key}"
    payload = {"b_no": business_numbers}
    headers = {"Content-Type": "application/json", "Accept": "application/json"}

    try:
        # PythonAnywhere는 외부 요청 시 verify=True가 기본이며 잘 동작합니다.
        # verify=False 옵션은 보안상 좋지 않으므로 제거합니다.
        response = requests.post(api_url, headers=headers, data=json.dumps(payload), timeout=10)

        if response.status_code == 200:
            return response.json()
        else:
            # 오류 발생 시 사용자에게 보여줄 정보를 포함하여 반환
            return {"error": f"API 호출 오류: {response.status_code}", "details": response.text}

    except requests.exceptions.RequestException as e:
        return {"error": "네트워크 오류 발생", "details": str(e)}


# --- 기존 함수를 웹에 맞게 살짝 수정한 함수 ---
def find_business_statuses(business_numbers: list, service_key: str) -> dict:
    """
    사업자 번호 리스트를 조회하여 '모든' 사업자의 상태 정보를 반환합니다.
    (웹에서는 휴/폐업뿐만 아니라 정상 사업자 정보도 보여주는 것이 더 유용합니다.)
    """
    api_response = check_business_registration(business_numbers, service_key)

    # 결과를 저장할 딕셔너리
    results = {
        "data": [],
        "error": None,
        "raw_response": api_response  # 디버깅을 위해 원본 응답 저장
    }

    if api_response and api_response.get("data"):
        results["data"] = api_response["data"]
    elif api_response and api_response.get("error"):
        results["error"] = f"{api_response['error']} - {api_response['details']}"
    else:
        results["error"] = "API로부터 유효한 데이터를 받지 못했습니다."

    return results


# --- Flask 라우트 (웹 페이지 로직) ---
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        # 웹 양식에서 사용자가 입력한 사업자 번호와 서비스 키를 가져옵니다.
        # strip()으로 앞뒤 공백을 제거하고, 빈 줄은 제외합니다.
        b_numbers_input = [line.strip() for line in request.form['business_numbers'].splitlines() if line.strip()]

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