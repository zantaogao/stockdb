
try:
    import pytdx
    print("Importing pytdx... SUCCESS")
    api = pytdx.DataApi()
    if api.connect():
        print("Connecting to TDX server... SUCCESS")
        # 尝试获取 600000 的实时行情
        # 参数: 市场(1:沪深), 代码('600000')
        res = api.get_security_quotes(1, '600000')
        if res:
            print(f"Fetch quote for 600000... SUCCESS: {res}")
        else:
            print("Fetch quote failed: No data returned")
    else:
        print("Connecting to TDX server... FAILED")
except Exception as e:
    print(f"Error occurred: {e}")
