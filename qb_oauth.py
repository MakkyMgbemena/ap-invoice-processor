"""
One-time QuickBooks OAuth2 helper.
Run this, visit the printed URL, authenticate, and it captures
your access_token, refresh_token, and realm_id automatically.
"""
import os, json, base64, urllib.parse, http.server, threading, webbrowser
import urllib.request

CLIENT_ID     = "ABHtBBKmYkudGrxPmg6tzanr5rR47dQYl54A9oeWiporpQrteG"
CLIENT_SECRET = "Ja7g6tQZ62cMREg4yHHVLVR1uE3yzyuVC6mYQ4Et"
REDIRECT_URI  = "http://localhost:8085/callback"
SCOPE         = "com.intuit.quickbooks.accounting"
AUTH_URL      = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_URL     = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"

result = {}

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        code      = params.get("code", [None])[0]
        realm_id  = params.get("realmId", [None])[0]

        if not code:
            self.send_response(400); self.end_headers()
            self.wfile.write(b"Missing code"); return

        # Exchange code for tokens
        creds = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
        data  = urllib.parse.urlencode({
            "grant_type":   "authorization_code",
            "code":         code,
            "redirect_uri": REDIRECT_URI,
        }).encode()
        req = urllib.request.Request(TOKEN_URL, data=data, headers={
            "Authorization": f"Basic {creds}",
            "Content-Type":  "application/x-www-form-urlencoded",
            "Accept":        "application/json",
        })
        with urllib.request.urlopen(req) as resp:
            tokens = json.loads(resp.read())

        result["access_token"]   = tokens.get("access_token")
        result["refresh_token"]  = tokens.get("refresh_token")
        result["realm_id"]       = realm_id

        self.send_response(200); self.end_headers()
        self.wfile.write(b"<h2>Auth complete! Return to your terminal.</h2>")
        threading.Thread(target=self.server.shutdown).start()

    def log_message(self, *args): pass

# Build auth URL
params = urllib.parse.urlencode({
    "client_id":     CLIENT_ID,
    "response_type": "code",
    "scope":         SCOPE,
    "redirect_uri":  REDIRECT_URI,
    "state":         "ap_pipeline",
})
full_url = f"{AUTH_URL}?{params}"
print("\n🔐 Visit this URL in your browser:\n")
print(full_url)
print("\nWaiting for QB callback on port 8085...\n")

server = http.server.HTTPServer(("localhost", 8085), Handler)
server.serve_forever()

print("✅ Tokens captured!")
print(f"   QB_REALM_ID={result['realm_id']}")
print(f"   QB_ACCESS_TOKEN={result['access_token']}")
print(f"   QB_REFRESH_TOKEN={result['refresh_token']}")
print("\nCopy these into your .env file and we're live.")
