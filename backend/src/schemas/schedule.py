from datetime import date
from pydantic import BaseModel, Field
class PlanInput(BaseModel):
    vehicle_id: int
    station_id: int
    start_date: date
    days: int = Field(ge=1, le=30)
class RescheduleInput(BaseModel):
    station_id: int
    start_date: date
    key: str = Field(default='', max_length=80)
class ClosureInput(BaseModel):
    station_id: int
    date: date
    bays: int = Field(ge=1, le=50)
    reason: str = Field(min_length=2, max_length=200)
class ConfigInput(BaseModel):
    min_attendance: int = Field(ge=0, le=100000)
