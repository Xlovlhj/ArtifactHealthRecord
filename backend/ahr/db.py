from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import create_engine, event, Column, String, Integer, Float, Boolean, JSON, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import declarative_base, sessionmaker
from .config import settings

Base = declarative_base()


def now():
    return datetime.now(timezone.utc).isoformat()


def uid(prefix=""):
    return prefix + uuid4().hex[:16]


engine = create_engine(settings().db_url, connect_args={"check_same_thread": False} if settings().db_url.startswith("sqlite") else {}, pool_pre_ping=True)
if settings().db_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def sqlite_options(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=lambda: uid("U-"))
    username = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    role = Column(String, nullable=False)
    org = Column(String, default="甘肃壁画保护演示组")
    password_hash = Column(String, nullable=False)
    active = Column(Boolean, default=True)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    expires_at = Column(Float, nullable=False)


class Artifact(Base):
    __tablename__ = "artifacts"
    id = Column(String, primary_key=True, default=lambda: uid("ART-"))
    org = Column(String, nullable=False)
    data = Column(JSON, default=dict)
    is_demo = Column(Boolean, default=False)
    created_at = Column(String, default=now)


class Survey(Base):
    __tablename__ = "surveys"
    id = Column(String, primary_key=True, default=lambda: uid("SUR-"))
    artifact_id = Column(String, ForeignKey("artifacts.id"), nullable=False)
    data = Column(JSON, default=dict)


class Record(Base):
    __tablename__ = "records"
    id = Column(String, primary_key=True, default=lambda: uid("AHR-"))
    artifact_id = Column(String, ForeignKey("artifacts.id"), nullable=False)
    survey_id = Column(String, ForeignKey("surveys.id"), nullable=False)
    chief_complaint = Column(Text, default="")
    history = Column(Text, default="")
    diagnosis = Column(JSON, default=dict)
    clinical_data = Column(JSON, default=dict)
    evidence_ids = Column(JSON, default=list)
    status = Column(String, default="draft")
    version = Column(Integer, default=1, nullable=False)
    created_at = Column(String, default=now)
    updated_at = Column(String, default=now)
    __mapper_args__ = {"version_id_col": version, "version_id_generator": False}


class ImageAsset(Base):
    __tablename__ = "images"
    id = Column(String, primary_key=True, default=lambda: uid("IMG-"))
    artifact_id = Column(String, ForeignKey("artifacts.id"), nullable=False)
    record_id = Column(String, ForeignKey("records.id"), nullable=False)
    filename = Column(String, nullable=False)
    storage_key = Column(String, nullable=False)
    sha256 = Column(String, nullable=False)
    image_type = Column(String, default="original")
    width = Column(Integer, nullable=False)
    height = Column(Integer, nullable=False)
    quality = Column(JSON, default=dict)
    calibration = Column(JSON, nullable=True)
    provenance = Column(JSON, default=dict)
    created_at = Column(String, default=now)


class Disease(Base):
    __tablename__ = "diseases"
    id = Column(String, primary_key=True, default=lambda: uid("D-"))
    record_id = Column(String, ForeignKey("records.id"), nullable=False)
    image_id = Column(String, ForeignKey("images.id"), nullable=False)
    type = Column(String, nullable=False)
    polygon = Column(JSON, nullable=False)
    centerline = Column(JSON, nullable=True)
    area_px = Column(Float, nullable=False)
    area_cm2 = Column(Float, nullable=True)
    area_ratio = Column(Float, nullable=False)
    severity = Column(String, default="待确认")
    confidence = Column(Float, nullable=True)
    evidence = Column(Text, default="")
    field_evidence = Column(Text, default="")
    confirmed = Column(Boolean, default=False)
    source = Column(String, default="manual")
    model_job_id = Column(String, nullable=True)
    model_version = Column(String, nullable=True)
    proposal_index = Column(Integer, nullable=True)
    standard_code = Column(String, default="GB/T 30237-2025（条号待核）")


class CaseReference(Base):
    __tablename__ = "cases"
    id = Column(String, primary_key=True)
    source = Column(String, nullable=False)
    data = Column(JSON, default=dict)
    org = Column(String, nullable=True)
    record_id = Column(String, ForeignKey("records.id"), nullable=True)
    version = Column(Integer, default=1, nullable=False)
    created_at = Column(String, default=now)
    updated_at = Column(String, default=now)


class Plan(Base):
    __tablename__ = "plans"
    __table_args__ = (UniqueConstraint("record_id", "version", name="uq_plan_version"),)
    id = Column(String, primary_key=True, default=lambda: uid("PLAN-"))
    record_id = Column(String, ForeignKey("records.id"), nullable=False)
    version = Column(Integer, nullable=False)
    record_version = Column(Integer, nullable=False)
    record_snapshot = Column(JSON, default=dict)
    evidence_snapshot = Column(JSON, default=list)
    sections = Column(JSON, default=dict)
    citations = Column(JSON, default=list)
    checks = Column(JSON, default=list)
    status = Column(String, default="draft")
    author = Column(String, ForeignKey("users.id"), nullable=False)
    reviewer = Column(String, nullable=True)
    signed_at = Column(String, nullable=True)
    content_hash = Column(String, nullable=True)
    provider = Column(String, default="template_fallback")
    model_version = Column(String, default="template-v1")
    generation_note = Column(Text, default="")
    created_at = Column(String, default=now)
    revision = Column(Integer, default=1, nullable=False)
    __mapper_args__ = {"version_id_col": revision}


class PlanCheck(Base):
    __tablename__ = "plan_checks"
    id = Column(String, primary_key=True, default=lambda: uid("CHECK-"))
    plan_id = Column(String, ForeignKey("plans.id"), nullable=False)
    data = Column(JSON, default=dict)
    created_at = Column(String, default=now)


class Consultation(Base):
    __tablename__ = "consultations"
    id = Column(String, primary_key=True, default=lambda: uid("CON-"))
    record_id = Column(String, ForeignKey("records.id"), nullable=False)
    plan_id = Column(String, ForeignKey("plans.id"), nullable=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    comment = Column(Text, nullable=False)
    decision = Column(String, default="comment")
    signature = Column(String, default="")
    content_hash = Column(String, nullable=True)
    created_at = Column(String, default=now)


class Simulation(Base):
    __tablename__ = "simulations"
    id = Column(String, primary_key=True, default=lambda: uid("SIM-"))
    record_id = Column(String, ForeignKey("records.id"), nullable=False)
    image_id = Column(String, ForeignKey("images.id"), nullable=False)
    storage_key = Column(String, nullable=False)
    data = Column(JSON, default=dict)
    created_at = Column(String, default=now)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(String, primary_key=True, default=lambda: uid("LOG-"))
    user_id = Column(String, nullable=False)
    action = Column(String, nullable=False)
    object_type = Column(String, nullable=False)
    object_id = Column(String, nullable=False)
    record_id = Column(String, nullable=True, index=True)
    before = Column(JSON, nullable=True)
    after = Column(JSON, nullable=True)
    metadata_versions = Column(JSON, default=dict)
    previous_hash = Column(String, default="")
    entry_hash = Column(String, default="")
    created_at = Column(String, default=now)


class Job(Base):
    __tablename__ = "jobs"
    id = Column(String, primary_key=True, default=lambda: uid("JOB-"))
    user_id = Column(String, nullable=False)
    record_id = Column(String, ForeignKey("records.id"), nullable=False)
    kind = Column(String, nullable=False)
    status = Column(String, default="pending")
    result = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(String, default=now)
    updated_at = Column(String, default=now)


class ArchiveEntry(Base):
    __tablename__ = "archive_entries"
    id = Column(String, primary_key=True, default=lambda: uid("ARC-"))
    record_id = Column(String, ForeignKey("records.id"), nullable=False)
    section = Column(String, nullable=False)
    title = Column(String, nullable=False)
    text = Column(Text, default="")
    date = Column(String, default="")
    author = Column(String, nullable=False)
    storage_key = Column(String, nullable=True)
    filename = Column(String, nullable=True)
    sha256 = Column(String, nullable=True)
    created_at = Column(String, default=now)


class ExportRequest(Base):
    __tablename__ = "export_requests"
    id = Column(String, primary_key=True, default=lambda: uid("EXP-"))
    record_id = Column(String, ForeignKey("records.id"), nullable=False)
    record_version = Column(Integer, nullable=False)
    requester = Column(String, ForeignKey("users.id"), nullable=False)
    purpose = Column(Text, nullable=False)
    status = Column(String, default="pending")
    reviewer = Column(String, nullable=True)
    comment = Column(Text, default="")
    created_at = Column(String, default=now)


class SchemaMigration(Base):
    __tablename__ = "schema_migrations"
    version = Column(String, primary_key=True)
    applied_at = Column(String, default=now)


def get_db():
    with SessionLocal() as db:
        yield db


def asdict(row):
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}
