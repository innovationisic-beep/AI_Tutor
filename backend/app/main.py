from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    admin_catalog_classroom,
    admin_content,
    admin_org,
    auth,
    classroom,
    curriculum,
    curriculum_structure,
    event_routes,
    health,
    organization,
    sessions,
    student,
    student_classroom,
    teacher,
    teacher_topic,
    topic_curriculum,
    tts,
    users,
)
from app.core.config import Settings
from app.core.database import connect_to_mongo


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: connect to MongoDB and initialize Beanie. Shutdown: clean up if needed."""
    settings = Settings()
    await connect_to_mongo(mongodb_url=settings.MONGODB_URL)
    print("MongoDB connected successfully")
    yield
    # Shutdown: Motor client cleanup is optional; connection closes when process exits


app = FastAPI(
    title="AI Tutor",
    description="Backend API for the AI Tutor system",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "X-TTS-Text-Chars",
        "X-TTS-Mode",
    ],
)

app.include_router(health.router)
app.include_router(tts.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(student.router)
app.include_router(curriculum.router)
app.include_router(curriculum_structure.router)
app.include_router(topic_curriculum.router)
app.include_router(sessions.router)
app.include_router(event_routes.router)
app.include_router(teacher.router)
app.include_router(teacher_topic.router)
app.include_router(classroom.router)
app.include_router(student_classroom.router)
app.include_router(admin_catalog_classroom.router)
app.include_router(admin_content.router)
app.include_router(admin_org.router)
app.include_router(organization.router)
