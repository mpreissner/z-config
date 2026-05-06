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
    zpa_tenant_cloud = Column(String(255), nullable=True)  # e.g. "ZPATWO_NET"; from orgInformation.zpaTenantCloud
    zia_tenant_id = Column(String(255), nullable=True)     # numeric tenant ID; from orgInformation.pdomain
    zia_cloud = Column(String(255), nullable=True)          # e.g. "zscalertwo.net"; from orgInformation.cloudName
    zia_subscriptions = Column(JSON, nullable=True)         # full response from GET /subscriptions
    notes = Column(Text, nullable=True)
    last_validation_error = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    govcloud = Column(Boolean, default=False, nullable=False)
    zpa_disabled_resources = Column(JSON, nullable=True)   # resource types auto-disabled after 401
    zia_disabled_resources = Column(JSON, nullable=True)   # resource types auto-disabled after 401
    zcc_disabled_resources = Column(JSON, nullable=True)   # resource types auto-disabled after 401
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    audit_logs = relationship("AuditLog", back_populates="tenant", lazy="select")
    certificates = relationship("Certificate", back_populates="tenant", lazy="select")
    zpa_resources = relationship("ZPAResource", back_populates="tenant", lazy="select")
    zia_resources = relationship("ZIAResource", back_populates="tenant", lazy="select")
    zcc_resources = relationship("ZCCResource", back_populates="tenant", lazy="select")
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

    Rows with source='palo' are migration candidates generated by palo-tools.
    Their zpa_id is a synthetic key (palo:<pan_name>) until pushed to the tenant,
    at which point it is replaced with the real ZPA-assigned ID and source
    reverts to 'tenant'.
    """

    __tablename__ = "zpa_resources"
    __table_args__ = (UniqueConstraint("tenant_id", "resource_type", "zpa_id", name="uq_zpa_resource"),)

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenant_configs.id"), nullable=False)
    resource_type = Column(String(64), nullable=False)   # application, segment_group, pra_portal, etc.
    zpa_id = Column(String(255), nullable=False)         # ID assigned by ZPA; synthetic 'palo:<name>' for candidates
    name = Column(String(512), nullable=True)
    raw_config = Column(JSON, nullable=False)
    config_hash = Column(String(64), nullable=True)      # SHA-256 hex of raw_config for change detection
    first_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    synced_at = Column(DateTime, nullable=True)
    is_deleted = Column(Boolean, default=False, nullable=False)
    source = Column(String(32), default="tenant", nullable=False)          # 'tenant' | 'palo'
    candidate_status = Column(String(32), nullable=True)                   # 'pending' | 'accepted' | 'rejected' | NULL for live rows

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


class ZIATemplate(Base):
    """A sanitised ZIA configuration snapshot suitable for application to any tenant.

    Created from a RestorePoint by stripping tenant-specific resource types
    (locations, VPN credentials, static IPs, GRE tunnels, PAC files, and all
    reference-only types).  Templates are global — not tied to a single tenant.

    source_tenant_id and source_snapshot_id are nullable provenance references:
    they survive intact even if the source tenant or snapshot is later deleted
    (at which point they become NULL via ON DELETE SET NULL).

    snapshot stores the stripped resource blob in the same shape as
    RestorePoint.snapshot["resources"]:
        {"resource_type": [{"id": ..., "name": ..., "raw_config": {...}}, ...]}

    stripped_types records which resource types were present in the source
    snapshot but removed during template creation.
    """

    __tablename__ = "zia_templates"

    id                 = Column(Integer, primary_key=True)
    name               = Column(String(255), unique=True, nullable=False)
    description        = Column(Text, nullable=True)
    source_tenant_id   = Column(Integer, ForeignKey("tenant_configs.id", ondelete="SET NULL"),
                                nullable=True)
    source_snapshot_id = Column(Integer, ForeignKey("restore_points.id", ondelete="SET NULL"),
                                nullable=True)
    created_at         = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at         = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow,
                                nullable=False)
    resource_count     = Column(Integer, default=0, nullable=False)
    stripped_types     = Column(JSON, nullable=False)   # list of resource_type strings
    snapshot           = Column(JSON, nullable=False)   # {"resource_type": [{...}, ...]}

    source_tenant   = relationship("TenantConfig", foreign_keys=[source_tenant_id])
    source_snapshot = relationship("RestorePoint",  foreign_keys=[source_snapshot_id])

    def __repr__(self) -> str:
        return f"<ZIATemplate name={self.name!r} resources={self.resource_count}>"


class ZIAResource(Base):
    """Snapshot of a ZIA resource fetched from the API.

    One row per (tenant, resource_type, zia_id).  raw_config holds the full
    JSON payload from the API; config_hash is a SHA-256 of that payload so
    subsequent syncs can skip unchanged records.

    Rows with source='palo' are migration candidates generated by palo-tools.
    Their zia_id is a synthetic key (palo:<pan_name>) until pushed to the tenant,
    at which point it is replaced with the real ZIA-assigned ID and source
    reverts to 'tenant'.
    """

    __tablename__ = "zia_resources"
    __table_args__ = (UniqueConstraint("tenant_id", "resource_type", "zia_id", name="uq_zia_resource"),)

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenant_configs.id"), nullable=False)
    resource_type = Column(String(64), nullable=False)
    zia_id = Column(String(255), nullable=False)         # ID assigned by ZIA; synthetic 'palo:<name>' for candidates
    name = Column(String(512), nullable=True)
    raw_config = Column(JSON, nullable=False)
    config_hash = Column(String(64), nullable=True)
    first_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    synced_at = Column(DateTime, nullable=True)
    is_deleted = Column(Boolean, default=False, nullable=False)
    source = Column(String(32), default="tenant", nullable=False)          # 'tenant' | 'palo'
    candidate_status = Column(String(32), nullable=True)                   # 'pending' | 'accepted' | 'rejected' | NULL for live rows

    tenant = relationship("TenantConfig", back_populates="zia_resources")

    def __repr__(self) -> str:
        return f"<ZIAResource type={self.resource_type!r} name={self.name!r} id={self.zia_id!r}>"


class ZCCResource(Base):
    """Snapshot of a ZCC resource fetched from the API.

    One row per (tenant, resource_type, zcc_id).  raw_config holds the full
    JSON payload from the API; config_hash is a SHA-256 of that payload so
    subsequent syncs can skip unchanged records.
    """

    __tablename__ = "zcc_resources"
    __table_args__ = (UniqueConstraint("tenant_id", "resource_type", "zcc_id", name="uq_zcc_resource"),)

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenant_configs.id"), nullable=False)
    resource_type = Column(String(64), nullable=False)
    zcc_id = Column(String(255), nullable=False)
    name = Column(String(512), nullable=True)
    raw_config = Column(JSON, nullable=False)
    config_hash = Column(String(64), nullable=True)
    first_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    synced_at = Column(DateTime, nullable=True)
    is_deleted = Column(Boolean, default=False, nullable=False)

    tenant = relationship("TenantConfig", back_populates="zcc_resources")

    def __repr__(self) -> str:
        return f"<ZCCResource type={self.resource_type!r} name={self.name!r} id={self.zcc_id!r}>"


class AppSettings(Base):
    """Key-value store for application-level preferences.

    Used for settings that apply globally (not per-tenant), such as the
    plugin channel selection (stable vs dev).
    """

    __tablename__ = "app_settings"

    key   = Column(String(255), primary_key=True)
    value = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<AppSettings key={self.key!r} value={self.value!r}>"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("sso_provider", "sso_subject", name="uq_user_sso"),
    )
    id                    = Column(Integer, primary_key=True)
    username              = Column(String(255), unique=True, nullable=False)
    email                 = Column(String(512), nullable=True)
    role                  = Column(String(32), nullable=False, default="user")
    password_hash         = Column(Text, nullable=True)
    force_password_change = Column(Boolean, nullable=False, default=False)
    sso_provider          = Column(String(64), nullable=True)
    sso_subject           = Column(String(512), nullable=True)
    is_active             = Column(Boolean, nullable=False, default=True)
    mfa_required          = Column(Boolean, nullable=False, default=False)
    created_at            = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at            = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    last_login_at         = Column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<User username={self.username!r} role={self.role!r}>"


class WebAuthnCredential(Base):
    """FIDO2 / WebAuthn credential registered by a local user.

    One user may have multiple credentials (multiple hardware keys).
    Federated (SSO) users do not register credentials here — they do MFA
    at the IdP.
    """

    __tablename__ = "webauthn_credentials"

    id             = Column(Integer, primary_key=True)
    user_id        = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    credential_id  = Column(Text, nullable=False, unique=True)  # base64url-encoded bytes
    public_key     = Column(Text, nullable=False)               # COSE key, base64url-encoded
    sign_count     = Column(Integer, nullable=False, default=0)
    aaguid         = Column(String(64), nullable=True)          # authenticator model GUID
    label          = Column(String(255), nullable=True)         # user-assigned name ("YubiKey 5")
    created_at     = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_used_at   = Column(DateTime, nullable=True)

    user = relationship("User", backref="webauthn_credentials")

    def __repr__(self) -> str:
        return f"<WebAuthnCredential user_id={self.user_id} label={self.label!r}>"


class UserTenantEntitlement(Base):
    """Maps zs-config users to the tenants they are permitted to access.

    Admin users bypass this table (they can access all tenants).
    For role="user" accounts, only tenants with an entitlement row are visible.
    """

    __tablename__ = "user_tenant_entitlements"
    __table_args__ = (
        UniqueConstraint("user_id", "tenant_id", name="uq_user_tenant"),
    )

    id         = Column(Integer, primary_key=True)
    user_id    = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    tenant_id  = Column(Integer, ForeignKey("tenant_configs.id", ondelete="CASCADE"), nullable=False)
    granted_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user   = relationship("User", backref="tenant_entitlements")
    tenant = relationship("TenantConfig", backref="user_entitlements")

    def __repr__(self) -> str:
        return f"<UserTenantEntitlement user_id={self.user_id} tenant_id={self.tenant_id}>"


class ScheduledTask(Base):
    """A recurring cross-tenant ZIA config sync job.

    resource_groups is a list of group key strings that expand to the
    constituent resource_type values synced by the engine.
    cron_expression is always stored as a 5-field cron string regardless of
    whether the user entered a preset interval or a custom expression.
    """

    __tablename__ = "scheduled_tasks"

    id               = Column(Integer, primary_key=True)
    name             = Column(String(255), nullable=False, unique=True)
    source_tenant_id = Column(Integer, ForeignKey("tenant_configs.id"), nullable=False)
    target_tenant_id = Column(Integer, ForeignKey("tenant_configs.id"), nullable=False)
    resource_groups      = Column(JSON, nullable=False)
    sync_mode            = Column(String(16),  nullable=False, default="resource_type")
    label_name           = Column(String(255), nullable=True)
    label_resource_types = Column(JSON,        nullable=True)
    cron_expression      = Column(String(128), nullable=False)
    sync_deletes     = Column(Boolean, default=False, nullable=False)
    enabled          = Column(Boolean, default=True, nullable=False)
    owner_email      = Column(String(512), nullable=True)
    created_at       = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at       = Column(DateTime, default=datetime.utcnow,
                             onupdate=datetime.utcnow, nullable=False)

    source_tenant = relationship("TenantConfig", foreign_keys=[source_tenant_id])
    target_tenant = relationship("TenantConfig", foreign_keys=[target_tenant_id])
    runs          = relationship("TaskRunHistory", back_populates="task",
                                 cascade="all, delete-orphan", lazy="select")

    def __repr__(self) -> str:
        return f"<ScheduledTask name={self.name!r} enabled={self.enabled}>"


class TaskRunHistory(Base):
    """Records the outcome of each scheduled (or manual) sync task execution."""

    __tablename__ = "task_run_history"

    id               = Column(Integer, primary_key=True)
    task_id          = Column(Integer, ForeignKey("scheduled_tasks.id",
                              ondelete="CASCADE"), nullable=False)
    started_at       = Column(DateTime, nullable=False)
    finished_at      = Column(DateTime, nullable=True)
    status           = Column(String(16), nullable=False)
    # status values: "running", "success", "partial", "failed"
    resources_synced = Column(Integer, default=0, nullable=False)
    errors_json      = Column(JSON, nullable=True)
    # errors_json: list of {"resource_type": str, "resource_name": str,
    #                        "operation": str, "error": str}

    task = relationship("ScheduledTask", back_populates="runs")

    def __repr__(self) -> str:
        return f"<TaskRunHistory task_id={self.task_id} status={self.status!r}>"
