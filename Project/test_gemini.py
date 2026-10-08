
import os
import sys
from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

# Load the API key from .env
load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    raise ValueError(
        "API key not found. Check your .env file."
    )

try:
    with genai.Client(api_key=api_key) as client:
        response = client.models.generate_content(
            model=os.getenv("GEMINI_MODEL", "models/gemini-3.1-flash-lite"),
            contents="Reply with: Gemini API is working!",
            config=types.GenerateContentConfig(
                http_options=types.HttpOptions(
                    retry_options=types.HttpRetryOptions(attempts=1)
                ),
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=True
                )
            ),
        )
    print(response.text)
except errors.APIError as error:
    print(f"Gemini API request failed: HTTP {error.code} ({error.status})")
    if error.message:
        print(f"Message: {error.message}")
    error_details = error.details if isinstance(error.details, dict) else {}
    error_body = error_details.get("error", error_details)
    details = error_body.get("details", []) if isinstance(error_body, dict) else []
    for detail in details:
        if not isinstance(detail, dict):
            continue
        if str(detail.get("@type", "")).endswith("QuotaFailure"):
            for violation in detail.get("violations", []):
                if isinstance(violation, dict):
                    print(
                        "Quota:",
                        violation.get("quotaId") or violation.get("quotaMetric"),
                        "value:",
                        violation.get("quotaValue"),
                    )
        elif str(detail.get("@type", "")).endswith("RetryInfo"):
            print("Retry delay:", detail.get("retryDelay"))
    sys.exit(1)
