# Import all models here so Alembic can discover them
from app.db.base_class import Base
from app.models.user import User
from app.models.profile import Profile
from app.models.opportunity import Opportunity
from app.models.post import Post, Comment
from app.models.application import Application
# We will import other models as we create them
