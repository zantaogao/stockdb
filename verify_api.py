
import requests
try:
    resp = requests.get('http://127.0.0.1:5000/api/data', timeout=2)
    data = resp.json()
    if 'watchlist' in data and len(data['watchlist']) > 0:
        first_item = data['watchlist'][0]
        print(f"API Version Check: {'NEW' if 'model' in first_item else 'OLD'}")
        print(f"Sample Data: {first_item}")
    else:
        print("API Response: No watchlist data or empty.")
except Exception as e:
    print(f"API Connection Error: {e}")
