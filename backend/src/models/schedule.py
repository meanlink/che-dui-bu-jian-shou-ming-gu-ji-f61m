from datetime import date
from sqlalchemy import String, JSON, Double, ForeignKey, Boolean, Integer, Date, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
class Station(Base):
    __tablename__ = 'stations'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    bays: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[float] = mapped_column(Double, default=0)
class Vehicle(Base):
    __tablename__ = 'vehicles'
    id: Mapped[int] = mapped_column(primary_key=True)
    fleet_no: Mapped[str] = mapped_column(String(40), unique=True)
    model: Mapped[str] = mapped_column(String(40))
    current_km: Mapped[float] = mapped_column(Double)
    daily_km: Mapped[float] = mapped_column(Double)
    created_at: Mapped[float] = mapped_column(Double, default=0)
class BayClosure(Base):
    __tablename__ = 'bay_closures'
    id: Mapped[int] = mapped_column(primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey('stations.id'))
    date: Mapped[date] = mapped_column(Date)
    bays: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(200), default='')
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    displaced: Mapped[list] = mapped_column(JSON, default=list)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[float] = mapped_column(Double)
class MaintenancePlan(Base):
    __tablename__ = 'maintenance_plans'
    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey('vehicles.id'))
    station_id: Mapped[int] = mapped_column(ForeignKey('stations.id'))
    job_id: Mapped[int] = mapped_column(ForeignKey('jobs.id'))
    start_date: Mapped[date] = mapped_column(Date)
    days: Mapped[int] = mapped_column(Integer)
    due_date: Mapped[date] = mapped_column(Date)
    approved_km: Mapped[float] = mapped_column(Double)
    status: Mapped[str] = mapped_column(String(20), default='draft')
    reschedule_key: Mapped[str] = mapped_column(String(80), default='')
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[float] = mapped_column(Double)
    confirmed_at: Mapped[float | None] = mapped_column(Double, nullable=True)
class PlanSlot(Base):
    __tablename__ = 'plan_slots'
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey('maintenance_plans.id'))
    station_id: Mapped[int] = mapped_column(ForeignKey('stations.id'))
    vehicle_id: Mapped[int] = mapped_column(ForeignKey('vehicles.id'))
    date: Mapped[date] = mapped_column(Date)
    __table_args__ = (UniqueConstraint('plan_id', 'date'),)
class ScheduleConfig(Base):
    __tablename__ = 'schedule_config'
    id: Mapped[int] = mapped_column(primary_key=True)
    min_attendance: Mapped[int] = mapped_column(Integer, default=90)
