import os
from beem import Steem
from beem.account import Account

username = os.environ["STEEM_USERNAME"]
posting_key = os.environ["STEEM_POSTING_KEY"]

print("Connecting to Steemit...")

try:
    steem = Steem(
        keys=[posting_key],
        nodes=["https://api.steemit.com"]
    )

    account = Account(username, blockchain_instance=steem)

    print("✅ Steemit connection successful!")
    print("Username:", account["name"])

except Exception as e:
    print("❌ Connection failed!")
    print("Error:", e)
