"""
ensure_allowance.py
-------------------
Sets and verifies USDC.e allowance for the Polymarket CLOB.
"""
import os
import time
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, BalanceAllowanceParams, AssetType

load_dotenv(override=True)

def run():
    creds = ApiCreds(
        api_key=os.getenv('API_KEY'),
        api_secret=os.getenv('API_SECRET'),
        api_passphrase=os.getenv('API_PASSPHRASE')
    )
    client = ClobClient(
        host=os.getenv('CLOB_HOST'),
        chain_id=137,
        key=os.getenv('PRIVATE_KEY'),
        creds=creds
    )

    print("--- Polymarket Allowance Checker ---")
    
    # 1. Check current state
    try:
        res = client.get_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
        balance = int(res.get('balance', 0)) / 1e6
        allowances = res.get('allowances', {})
        print(f"Current Balance: ${balance:.2f} USDC.e")
        
        needs_approval = False
        for addr, val in allowances.items():
            if int(val) == 0:
                print(f"  [!] Missing allowance for contract: {addr}")
                needs_approval = True
            else:
                print(f"  [OK] Allowance set for: {addr}")

        if not needs_approval:
            print("\n✅ All allowances are already set correctly!")
            return

        # 2. Update allowance
        print("\nSending allowance update transaction to Polygon...")
        print("(This requires MATIC for gas and may take 30-60 seconds)")
        
        # update_balance_allowance without params updates everything required
        resp = client.update_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
        print(f"Update Result: {resp}")
        
        print("\nWaiting 30 seconds for transaction to be mined...")
        time.sleep(30)
        
        # 3. Final verification
        res = client.get_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
        allowances = res.get('allowances', {})
        all_ok = True
        for addr, val in allowances.items():
            if int(val) == 0:
                all_ok = False
                print(f"  [ERROR] Still missing allowance for: {addr}")
        
        if all_ok:
            print("\n✅ SUCCESS: All allowances are now active!")
        else:
            print("\n❌ FAILED: Allowance transaction might still be pending or failed.")
            
    except Exception as e:
        print(f"\n[CRITICAL ERROR] {e}")

if __name__ == "__main__":
    run()
