import sys
import certifi
import ssl
from pymongo import MongoClient

try:
    print("Testing manual SSLContext injection...")
    
    # Bypass OSX root certs entirely by defining a custom SSL Context
    ctx = ssl.create_default_context(cafile=certifi.where())
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    
    client = MongoClient(
        "mongodb+srv://bobthebuilder144411_db_user:nn9lUoDQuy7wrtrf@vidyaverse.okbocmk.mongodb.net/?appName=vidyaverse",
        tls=True,
        tlsAllowInvalidCertificates=True,
        tlsCAFile=certifi.where()
    )
    db = client.test
    print("Ping:", db.command("ping"))
    print("Success!")
except Exception as e:
    print("Failed")
    print(e)
