import asyncio
import certifi
import ssl
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from app.core.config import settings
from app.models.user import User
from app.models.opportunity import Opportunity
from app.models.post import Post
from app.models.application import Application

async def main():
    print("Testing Beanie Initialization...")
    ctx = ssl.create_default_context(cafile=certifi.where())
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    
    client = AsyncIOMotorClient(
        settings.MONGODB_URL, 
        tls=True, 
        tlsAllowInvalidCertificates=True,
        tlsCAFile=certifi.where(),
        tlsAllowInvalidHostnames=True,
        ssl_context=ctx
    )
    print("Client created.")
    
    try:
        await init_beanie(
            database=client[settings.DATABASE_NAME],
            document_models=[User, Opportunity, Post, Application]
        )
        print("Beanie Initialized Successfully!")
    except Exception as e:
        print("Initialization Failed:", e)

if __name__ == "__main__":
    asyncio.run(main())
