
import pytdx
from pytdx.constant import Stock_Type_1

def test_tdx():
    data = pytdx.DataApi()
    # 尝试连接通达信服务器（默认服务器）
    if data.connect():
        print("TDX Connection: SUCCESS")
        # 测试获取一只股票的实时行情 (例如 600000 浦发银行)
        res = data.get_security_quotes(Stock_Type_1, '600000')
        if res:
            print(f"Real-time check: 600000 price is {res[0]['price']}")
            return True
        else:
            print("TDX Connection SUCCESS, but failed to fetch quotes.")
            return False
    else:
        print("TDX Connection: FAILED")
        return False

if __name__ == '__main__':
    test_tdx()
