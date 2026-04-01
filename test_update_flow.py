"""
Basic E2E smoke test for auto-update endpoints.

Checks:
1) Agent can call /latest
2) If update available, package can be downloaded
3) Agent can call /health
"""

import os
import zipfile
import requests

SERVER_URL = "http://localhost:5050"
AGENT_ID = "f2f4857c-2f1f-4343-9571-dfa32d2129fc"
CURRENT_VERSION = "2.4.0"
API_TOKEN = (
    os.environ.get("UPDATE_TEST_TOKEN")
    or os.environ.get("SENTINELEDGE_API_TOKEN")
    or ""
)
API_KEY = os.environ.get("UPDATE_TEST_API_KEY", "")


def _auth_headers() -> dict:
    headers = {}
    if API_TOKEN:
        headers["Authorization"] = f"Bearer {API_TOKEN}"
    elif API_KEY:
        headers["X-API-Key"] = API_KEY
    return headers


def test_check_for_update():
    print("\n" + "=" * 60)
    print("TEST 1: Agent checks for update")
    print("=" * 60)

    url = f"{SERVER_URL}/api/v1/updates/latest"
    headers = {"X-Agent-ID": AGENT_ID, "X-Agent-Version": CURRENT_VERSION}
    headers.update(_auth_headers())
    print(f"GET {url}")
    print(f"Headers: {headers}")

    try:
        response = requests.get(url, headers=headers, timeout=10)
        print(f"Status: {response.status_code}")
        data = response.json()
        print(f"Body: {data}")

        if response.status_code != 200:
            print("[ERROR] /latest returned non-200")
            return None

        if data.get("update_available"):
            print(f"[OK] Update available: {data.get('version')}")
            return data

        print(f"[INFO] No update available: {data.get('message', 'N/A')}")
        return None
    except requests.exceptions.ConnectionError:
        print(f"[ERROR] Cannot connect to {SERVER_URL}")
        return None
    except Exception as exc:
        print(f"[ERROR] /latest check failed: {exc}")
        return None


def test_download_package(version: str):
    print("\n" + "=" * 60)
    print(f"TEST 2: Download update package v{version}")
    print("=" * 60)

    url = f"{SERVER_URL}/api/v1/updates/download/{version}"
    print(f"GET {url}")

    try:
        response = requests.get(url, headers=_auth_headers(), timeout=60, stream=True)
        print(f"Status: {response.status_code}")
        if response.status_code != 200:
            print(f"[ERROR] Download failed: {response.text}")
            return None

        temp_path = f"test_download_{version}.zip"
        with open(temp_path, "wb") as handle:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    handle.write(chunk)

        file_size = os.path.getsize(temp_path)
        print(f"[OK] Downloaded {temp_path} ({file_size:,} bytes)")

        with zipfile.ZipFile(temp_path, "r") as zf:
            print(f"[OK] ZIP entries: {len(zf.namelist())}")
        return temp_path
    except Exception as exc:
        print(f"[ERROR] Download test failed: {exc}")
        return None


def test_report_health():
    print("\n" + "=" * 60)
    print("TEST 3: Report health status")
    print("=" * 60)

    url = f"{SERVER_URL}/api/v1/updates/health"
    payload = {
        "agent_id": AGENT_ID,
        "version": "2.5.0",
        "previous_version": "2.4.0",
        "status": "healthy",
    }

    print(f"POST {url}")
    print(f"Payload: {payload}")

    try:
        response = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json", **_auth_headers()},
            timeout=10,
        )
        print(f"Status: {response.status_code}")
        try:
            body = response.json()
        except Exception:
            body = response.text
        print(f"Body: {body}")
        return response.status_code == 200
    except Exception as exc:
        print(f"[ERROR] /health failed: {exc}")
        return False


def main():
    print("=" * 60)
    print("SentinelEdge Auto-Update Test")
    print("=" * 60)
    print(f"Server: {SERVER_URL}")
    print(f"Agent ID: {AGENT_ID}")
    print(f"Current Version: {CURRENT_VERSION}")
    if not API_TOKEN and not API_KEY:
        print("[WARN] No auth token/key in env. Protected endpoints may return 401.")

    update_info = test_check_for_update()
    if update_info and update_info.get("update_available"):
        version = update_info.get("version")
        downloaded = test_download_package(version)
        if downloaded and os.path.exists(downloaded):
            os.remove(downloaded)
            print("[OK] Test ZIP removed")

    test_report_health()
    print("\n" + "=" * 60)
    print("Test complete")
    print("=" * 60)


if __name__ == "__main__":
    main()
