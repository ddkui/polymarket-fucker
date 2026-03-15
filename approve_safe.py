"""
approve_safe.py
---------------
Sets USDC.e allowance for the Polymarket CTF contracts on behalf
of the Gnosis Safe proxy wallet, so it can trade on Polymarket.
"""
import os, time
from dotenv import load_dotenv
from web3 import Web3
from eth_account import Account
from eth_account.messages import encode_defunct

load_dotenv(override=True)

PRIVATE_KEY = os.getenv("PRIVATE_KEY")
PROXY_WALLET = os.getenv("PROXY_WALLET", "0x03d8D90B5cF01171345539e8fC08c79210B877aB")
RPC = "https://polygon-bor-rpc.publicnode.com"
USDC_E = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
# Polymarket exchange contracts to approve
SPENDERS = [
    "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E",
    "0xC5d563A36AE78145C45a50134d48A1215220f80a",
    "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296",
]

w3 = Web3(Web3.HTTPProvider(RPC))
acct = Account.from_key(PRIVATE_KEY)
safe_addr = w3.to_checksum_address(PROXY_WALLET)
usdc = w3.to_checksum_address(USDC_E)

# Gnosis Safe ABI (minimal)
SAFE_ABI = [
    {"name": "nonce", "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function", "inputs": []},
    {"name": "execTransaction", "type": "function", "stateMutability": "payable", "inputs": [
        {"name": "to", "type": "address"},
        {"name": "value", "type": "uint256"},
        {"name": "data", "type": "bytes"},
        {"name": "operation", "type": "uint8"},
        {"name": "safeTxGas", "type": "uint256"},
        {"name": "baseGas", "type": "uint256"},
        {"name": "gasPrice", "type": "uint256"},
        {"name": "gasToken", "type": "address"},
        {"name": "refundReceiver", "type": "address"},
        {"name": "signatures", "type": "bytes"},
    ], "outputs": [{"type": "bool"}]},
    {"name": "getTransactionHash", "type": "function", "stateMutability": "view", "inputs": [
        {"name": "to", "type": "address"},
        {"name": "value", "type": "uint256"},
        {"name": "data", "type": "bytes"},
        {"name": "operation", "type": "uint8"},
        {"name": "safeTxGas", "type": "uint256"},
        {"name": "baseGas", "type": "uint256"},
        {"name": "gasPrice", "type": "uint256"},
        {"name": "gasToken", "type": "address"},
        {"name": "refundReceiver", "type": "address"},
        {"name": "nonce", "type": "uint256"},
    ], "outputs": [{"type": "bytes32"}]},
]

USDC_ABI = [
    {"name": "approve", "type": "function", "inputs": [
        {"name": "_spender", "type": "address"},
        {"name": "_value", "type": "uint256"},
    ], "outputs": [{"type": "bool"}]}
]

safe_contract = w3.eth.contract(address=safe_addr, abi=SAFE_ABI)
usdc_contract = w3.eth.contract(address=usdc, abi=USDC_ABI)
MAX_UINT = 2**256 - 1

print("=== Gnosis Safe USDC Approvals ===")
print(f"Safe: {safe_addr}")
print(f"Signer: {acct.address}")

for spender_raw in SPENDERS:
    spender = w3.to_checksum_address(spender_raw)
    try:
        approve_data = usdc_contract.encode_abi("approve", args=[spender, MAX_UINT])
        nonce = safe_contract.functions.nonce().call()

        tx_hash = safe_contract.functions.getTransactionHash(
            usdc, 0, approve_data, 0, 0, 0, 0,
            "0x0000000000000000000000000000000000000000",
            "0x0000000000000000000000000000000000000000",
            nonce
        ).call()

        # Sign the Safe transaction hash
        signed = acct.unsafe_sign_hash(tx_hash)
        r = signed.r.to_bytes(32, "big")
        s = signed.s.to_bytes(32, "big")
        v = (signed.v).to_bytes(1, "big")
        signature = r + s + v

        # Execute via Safe
        eoa_nonce = w3.eth.get_transaction_count(acct.address)
        tx = safe_contract.functions.execTransaction(
            usdc, 0, approve_data, 0, 0, 0, 0,
            "0x0000000000000000000000000000000000000000",
            "0x0000000000000000000000000000000000000000",
            signature
        ).build_transaction({
            "from": acct.address,
            "nonce": eoa_nonce,
            "gas": 200000,
            "gasPrice": int(w3.eth.gas_price * 1.5),
        })
        signed_tx = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
        tx_hash_sent = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
        print(f"Approving {spender[:10]}... TX: {tx_hash_sent.hex()[:16]}...")

        time.sleep(3)

    except Exception as e:
        print(f"  Error for {spender[:10]}: {e}")

print("\nWaiting 20s for confirmations...")
time.sleep(20)
print("Done! Try placing a trade now.")
