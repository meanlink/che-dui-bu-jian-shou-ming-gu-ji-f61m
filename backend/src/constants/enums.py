from enum import Enum
class Role(str, Enum):
    admin = 'admin'
    analyst = 'analyst'
    viewer = 'viewer'
class JobStatus(str, Enum):
    queued = 'queued'
    running = 'running'
    completed = 'completed'
    failed = 'failed'
class PlanStatus(str, Enum):
    draft = 'draft'
    confirmed = 'confirmed'
    pending_reschedule = 'pending_reschedule'
    cancelled = 'cancelled'
