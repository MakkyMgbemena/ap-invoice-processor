import json, os

# Write GCP credentials
os.makedirs(os.path.expanduser('~/ap-invoice-processor/credentials'), exist_ok=True)
creds = {
  "type": "service_account",
  "project_id": "project-24b04b3d-fdd9-4b07-855",
  "private_key_id": "b0fc3fc8e9be5707a4edefb4c2de1db6366ac432",
  "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQCXMNS5gr7XpTCkd6M2vFB5JCS59SyR3r5Dcv0nXIaBXhOxyZz2wXGMYaA4+oS/irttftGZ0DVObKO8YXKYksSPOGj1LNxbN0znAxYTua5mT2hvRP0XCRiurSMumjptyfFy29I8aCCP2w0dbhFRqGXvFSQiCqDbK3WaJ1GSSnz9xyQw8BWnx4nBouDIc7fI3U/VeP5wLkJe14m+H1Cl3PrvVGFlBH1w0VhmyztCuRtYy3cf38rp+1yOiQdKh2DKXjdStT92SexOsJ3l/90djH1PyN1+u5PA5eT0ScsQkenQCCV6Rq1lpc2Ic7+BFHgs7wHtg4LLC0XVn1m0L6JPQOFLAgMBAAECggEACDYrP54lzmGW+D/VOgpVVpcLdZwm3Q9bhx9ON56TYaBh8nSQVWihSa4dvSqCHkMjNem+6ZtA4e8Nn5QtXLMQAPVf4f0bRMsGnr9wqgaaPc1PT0fQdTlVwVr+/695v+/J
