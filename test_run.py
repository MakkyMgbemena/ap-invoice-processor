import os
import asyncio
import traceback
import httpx

from app.services.quickbooks import (
    _refresh_access_token,
    BASE_URL,
    QB_REALM_ID,
)


async def main():
    async with httpx.AsyncClient(timeout=15) as client:
        token = await _refresh_access_token(client) or os.getenv("QB_ACCESS_TOKEN")
        print("token_present:", bool(token))
        print("realm:", QB_REALM_ID)
        print("base_url:", BASE_URL)

        if not token:
            print("STOP: no QuickBooks access token available")
            return

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        queries = {
            "vendors": "select Id, DisplayName, Active from Vendor maxresults 20",
            "accounts": "select Id, Name, AccountType, AccountSubType, Active from Account maxresults 100",
        }

        for label, query in queries.items():
            print(f"\n--- {label.upper()} ---")
            try:
                r = await client.get(
                    f"{BASE_URL}/v3/company/{QB_REALM_ID}/query",
                    params={"query": query, "minorversion": "65"},
                    headers=headers,
                )
                print("status:", r.status_code)
                print(r.text[:8000])
            except Exception:
                traceback.print_exc()


asyncio.run(main())