from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class TenantConfig(Base):
    """Stores connection details for a Zscaler tenant.

    client_secret is stored encrypted (Fernet). The encryption key is held
    in the ZSCALER_SECRET_KEY environment variable and never written to disk.
    """

    __tablename__ = "tenant_configs"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    zidentity_base_url = Column(String(512), nullable=False)
    oneapi_base_url = Column(String(512), default="https://api.zsapi.net", nullable=False)
    client_id = Column(String(512), nullable=False)
    client_secret_enc = Column(Text, nullable=False)       # Fernet-encrypted
    zpa_customer_id = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    zpa_disabled_resources = Column(JSON, nullable=True)   # resource types auto-disabled after 401
    zia_disabled_resources = Column(JSON, nullable=True)   # resource types auto-disabled after 401
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    audit_logs = relationship("AuditLog", back_populates="tenant", lazy="select")
    certificates = relationship("Certificate", back_populates="tenant", lazy="select")
    zpa_resources = relationship("ZPAResource", back_populates="tenant", lazy="select")
    zia_resources = relationship("ZIAResource", back_populates="tenant", lazy="select")
    sync_logs = relationship("SyncLog", back_populates="tenant", lazy="select")
    restore_points = relationship("RestorePoint", back_populates="tenant",
                                  cascade="all, delete-orphan", lazy="select")

    def __repr__(self) -> str:
        return f"<TenantConfig name={self.name!r} active={self.is_active}>"


class AuditLog(Base):
    """Immutable record of every operation performed through this toolset.

    Provides an audit trail for compliance, troubleshooting, and redeployment
    — you can replay operations by querying the log.
    """

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenant_configs.id"), nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    product = Column(String(32), nullable=True)        # ZPA, ZIA, ZCC, ZDX, etc.
    operation = Column(String(128), nullable=True)     # rotate_certificate, update_url_category, etc.
    action = Column(String(32), nullable=True)         # CREATE, UPDATE, DELETE, READ
    status = Column(String(16), nullable=True)         # SUCCESS, FAILURE
    resource_type = Column(String(128), nullable=True) # certificate, application, url_category, etc.
    resource_id = Column(String(255), nullable=True)
    resource_name = Column(String(512), nullable=True)
    details = Column(JSON, nullable=True)              # arbitrary context (domain, old cert ID, etc.)
    error_message = Column(Text, nullable=True)

    tenant = relationship("TenantConfig", back_populates="audit_logs")

    def __repr__(self) -> str:
        return f"<AuditLog [{self.timestamp}] {self.product} {self.operation} {self.status}>"


class Certificate(Base):
    """Tracks certificates uploaded and managed by this toolset.

    Enables auditing of certificate lifecycle: when uploaded, what domain,
    when it expires, and whether it has been superseded by a newer cert.
    """

    __tablename__ = "certificates"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenant_configs.id"), nullable=False)
    zpa_cert_id = Column(String(255), nullable=True)   # ID assigned by ZPA
    name = Column(String(512), nullable=True)
    domain = Column(String(512), nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    replaced_by_id = Column(Integer, ForeignKey("certificates.id"), nullable=True)

    tenant = relationship("TenantConfig", back_populates="certificates")
    replaced_by = relationship("Certificate", remote_side=[id], foreign_keys=[replaced_by_id])

    def __repr__(self) -> str:
        return f"<Certificate name={self.name!r} domain={self.domain!r} active={self.is_active}>"


class ZPAResource(Base):
    """Snapshot of a ZPA resource fetched from the API.

    One row per (tenant, resource_type, zpa_id).  raw_config holds the full
    JSON payload from the API; config_hash is a SHA-256 of that payload so
    subsequent syncs can skip unchanged records.
    """

    __tablename__ = "zpa_resources"
    __table_args__ = (UniqueConstraint("tenant_id", "resource_type", "zpa_id", name="uq_zpa_resource"),)

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenant_configs.id"), nullable=False)
    resource_type = Column(String(64), nullable=False)   # application, segment_group, pra_portal, etc.
    zpa_id = Column(String(255), nullable=False)         # ID assigned by ZPA
    name = Column(String(512), nullable=True)
    raw_config = Column(JSON, nullable=False)
    config_hash = Column(String(64), nullable=True)      # SHA-256 hex of raw_config for change detection
    first_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    synced_at = Column(DateTime, nullable=True)
    is_deleted = Column(Boolean, default=False, nullable=False)

    tenant = relationship("TenantConfig", back_populates="zpa_resources")

    def __repr__(self) -> str:
        return f"<ZPAResource type={self.resource_type!r} name={self.name!r} id={self.zpa_id!r}>"


class SyncLog(Base):
    """Records the outcome of each config-import run.

    Tracks aggregate stats (resources synced/updated/deleted) and a final
    status so the user can see when the last successful sync happened.
    """

    __tablename__ = "sync_logs"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenant_configs.id"), nullable=False)
    product = Column(String(32), nullable=False)         # ZPA, ZIA, etc.
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    status = Column(String(16), nullable=True)           # RUNNING, SUCCESS, FAILED, PARTIAL
    resources_synced = Column(Integer, default=0, nullable=False)
    resources_updated = Column(Integer, default=0, nullable=False)
    resources_deleted = Column(Integer, default=0, nullable=False)
    error_message = Column(Text, nullable=True)
    details = Column(JSON, nullable=True)

    tenant = relationship("TenantConfig", back_populates="sync_logs")

    def __repr__(self) -> str:
        return f"<SyncLog [{self.started_at}] {self.product} {self.status}>"


class RestorePoint(Base):
    """Point-in-time snapshot of a tenant's full ZPA or ZIA configuration.

    Stores the complete resource inventory captured from the local DB at the
    time of the snapshot, enabling pre/post-change diffing and export.
    """

    __tablename__ = "restore_points"

    id             = Column(Integer, primary_key=True)
    tenant_id      = Column(Integer, ForeignKey("tenant_configs.id"), nullable=False)
    product        = Column(String(32),  nullable=False)   # "ZPA" or "ZIA"
    name           = Column(String(255), nullable=False)   # auto timestamp
    comment        = Column(Text,        nullable=True)
    created_at     = Column(DateTime,    default=datetime.utcnow)
    resource_count = Column(Integer,     default=0)
    snapshot       = Column(JSON,        nullable=False)
    # snapshot structure: {"resources": {"resource_type": [{"id","name","raw_config"}, ...]}}

    tenant = relationship("TenantConfig", back_populates="restore_points")

    def __repr__(self) -> str:
        return f"<RestorePoint product={self.product!r} name={self.name!r} resources={self.resource_count}>"


class ZIAResource(Base):
    """Snapshot of a ZIA resource fetched from the API.

    One row per (tenant, resource_type, zia_id).  raw_config holds the full
    JSON payload from the API; config_hash is a SHA-256 of that payload so
    subsequent syncs can skip unchanged records.
    """

    __tablename__ = "zia_resources"
    __table_args__ = (UniqueConstraint("tenant_id", "resource_type", "zia_id", name="uq_zia_resource"),)

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenant_configs.id"), nullable=False)
    resource_type = Column(String(64), nullable=False)
    zia_id = Column(String(255), nullable=False)
    name = Column(String(512), nullable=True)
    raw_config = Column(JSON, nullable=False)
    config_hash = Column(String(64), nullable=True)
    first_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    synced_at = Column(DateTime, nullable=True)
    is_deleted = Column(Boolean, default=False, nullable=False)

    tenant = relationship("TenantConfig", back_populates="zia_resources")

    def __repr__(self) -> str:
        return f"<ZIAResource type={self.resource_type!r} name={self.name!r} id={self.zia_id!r}>"
