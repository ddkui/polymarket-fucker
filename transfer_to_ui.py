import os
import time
from dotenv import load_dotenv
from web3 import Web3
from eth_account import Account

def run():
    print("--- TRANSFERRING FUNDS TO POLYMARKET UI WALLET ---")
    load_dotenv(override=True)
    pk = os.getenv('PRIVATE_KEY')
    if not pk:
        print("[ERROR] No PRIVATE_KEY in .env")
        return

    acct = Account.from_key(pk)
    w3 = Web3(Web3.HTTPProvider('https://polygon-bor-rpc.publicnode.com'))
    
    # User's Proxy Wallet on Polymarket UI
    ui_wallet = w3.to_checksum_address('0x03d8D90B5cF01171345539e8fC08c79210B877aB')
    usdc_e_addr = w3.to_checksum_address('0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174')
    
    # Standard ERC20 ABI
    abi = [
        {'constant': True, 'inputs': [{'name': '_owner', 'type': 'address'}], 'name': 'balanceOf', 'outputs': [{'name': 'balance', 'type': 'uint256'}], 'type': 'function'},
        {'constant': False, 'inputs': [{'name': '_to', 'type': 'address'}, {'name': '_value', 'type': 'uint256'}], 'name': 'transfer', 'outputs': [{'name': '', 'type': 'bool'}], 'type': 'function'}
    ]
    
    usdc_contract = w3.eth.contract(address=usdc_e_addr, abi=abi)
    
    # 1. Fetch current balance
    try:
        balance_wei = usdc_contract.functions.balanceOf(acct.address).call()
        balance_usd = balance_wei / 1e6
        print(f"[STATUS] Bot Wallet ({acct.address[:6]}...) has ${balance_usd:.4f} USDC.e")
        
        if balance_wei == 0:
            print("[INFO] No funds to transfer. Wait for winning tickets to redeem.")
            return
            
        print(f"[ACTION] Transferring to UI Wallet ({ui_wallet})...")
        
        nonce = w3.eth.get_transaction_count(acct.address)
        tx = usdc_contract.functions.transfer(ui_wallet, balance_wei).build_transaction({
            'from': acct.address,
            'nonce': nonce,
            'gas': 100000,
            'gasPrice': int(w3.eth.gas_price * 1.5)  # slightly higher gas to ensure it mines fast
        })
        
        # 2. Sign and Send
        signed_tx = w3.eth.account.sign_transaction(tx, private_key=pk)
        tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        hex_hash = tx_hash.hex()
        
        print(f"[SUCCESS] Transaction sent! Hash: {hex_hash}")
        print("Waiting 15 seconds to confirm...")
        time.sleep(15)
        
        receipt = w3.eth.get_transaction_receipt(hex_hash)
        if receipt and receipt.status == 1:
            print("[CONFIRMED] Transfer was successful!")
            print(f"You should now see roughly ${balance_usd:.2f} on the Polymarket website.")
        else:
            print("[WARNING] Transaction might still be pending or failed.")
            
    except Exception as e:
        print(f"[ERROR] {e}")

if __name__ == "__main__":
    run()
