"""
approve_clob.py
---------------
One-time setup script to approve the Polymarket CLOB contract for live trading.

What it does:
  1. Derives fresh API credentials from your PRIVATE_KEY
  2. Approves the USDC balance allowance for the CLOB contract
  3. Prints the valid credentials so you can update your .env

Run this once before switching dry_run: false in config.yaml.
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv(override=True)

private_key = os.getenv("PRIVATE_KEY")
clob_host   = os.getenv("CLOB_HOST", "https://clob.polymarket.com")
chain_id    = int(os.getenv("CHAIN_ID", "137"))

if not private_key:
    print("[ERROR] PRIVATE_KEY not found in .env")
    sys.exit(1)

print("=" * 60)
print("Polymarket CLOB Contract Approval")
print("=" * 60)

try:
    from py_clob_client.client import ClobClient
except ImportError:
    print("[ERROR] py_clob_client is not installed. Run: pip install py-clob-client")
    sys.exit(1)

# Connect with just the private key (no API creds yet)
print("[1/3] Connecting to Polymarket CLOB with private key only...")
try:
    client = ClobClient(host=clob_host, chain_id=chain_id, key=private_key)
    print("      Connected OK")
except Exception as e:
    print(f"[ERROR] Failed to connect: {e}")
    sys.exit(1)

# Derive fresh API credentials from the private key
print("[2/3] Deriving API credentials from your private key...")
try:
    creds = client.derive_api_key()
    print("      Credentials derived successfully!")
    print()
    print("  >>> COPY THESE INTO YOUR .env FILE <<<")
    print(f"  API_KEY       = {creds.api_key}")
    print(f"  API_SECRET    = {creds.api_secret}")
    print(f"  API_PASSPHRASE= {creds.api_passphrase}")
    print()
except Exception as e:
    print(f"[WARNING] Could not derive API key: {e}")
    print("          You may need to create a new API key instead.")
    try:
        print("          Trying create_api_key...")
        nonce = 0
        creds = client.create_api_key(nonce)
        print(f"  API_KEY       = {creds.api_key}")
        print(f"  API_SECRET    = {creds.api_secret}")
        print(f"  API_PASSPHRASE= {creds.api_passphrase}")
    except Exception as e2:
        print(f"[ERROR] Could not create API key either: {e2}")
        creds = None

# Approve USDC allowance
print("[3/3] Approving USDC balance allowance for CLOB contract...")
try:
    result = client.update_balance_allowance()
    print(f"      Allowance result: {result}")
except Exception as e:
    print(f"[WARNING] update_balance_allowance: {e}")
    print("          If allowance was already approved previously, this is OK.")

print()
print("=" * 60)
if creds:
    print("[SUCCESS] CLOB approval complete!")
    print()
    print("Next steps:")
    print("  1. Update your .env with the API credentials printed above")
    print("  2. Set  dry_run: false  in config.yaml")
    print("  3. Restart:  py main.py")
else:
    print("[PARTIAL] Allowance step ran — but API credentials need manual setup.")
    print("See: https://docs.polymarket.com/#api-keys")
print("=" * 60)
