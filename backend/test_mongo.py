import certifi
import ssl
from pymongo import MongoClient

from app.core.config import settings


def main() -> None:
    try:
        print("Testing manual SSLContext injection...")

        # Bypass OSX root certs entirely by defining a custom SSL Context
        ctx = ssl.create_default_context(cafile=certifi.where())
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        _ = ctx  # keep reference for debugging

        mongodb_url = (settings.MONGODB_URL or "").strip()
        if not mongodb_url:
            raise RuntimeError("MONGODB_URL is not configured. Set it in backend/.env.")

        client = MongoClient(mongodb_url, tls=True, tlsAllowInvalidCertificates=True, tlsCAFile=certifi.where())
        db = client.test
        print("Ping:", db.command("ping"))
        print("Success!")
    except Exception as e:
        print("Failed")
        print(e)


if __name__ == "__main__":
    main()
