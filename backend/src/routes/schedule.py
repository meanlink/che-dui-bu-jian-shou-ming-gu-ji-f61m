from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from src.config.database import get_db
from src.models import Station, Vehicle, BayClosure, MaintenancePlan
from src.schemas.schedule import PlanInput, RescheduleInput, ClosureInput, ConfigInput
from src.middlewares.auth import current_user, can_write, admin_only
from src.services import schedule
from src.services.audit import record
router = APIRouter(prefix='/schedule')

def _plan_or_404(db, pid):
    plan = db.get(MaintenancePlan, pid)
    if not plan:
        raise HTTPException(404, '检修方案不存在')
    return plan

@router.get('/bootstrap')
def bootstrap(db=Depends(get_db), u=Depends(current_user)):
    stations = [{'id': s.id, 'name': s.name, 'bays': s.bays} for s in db.scalars(select(Station).order_by(Station.id))]
    vehicles = []
    for v in db.scalars(select(Vehicle).order_by(Vehicle.fleet_no)):
        job = schedule.approved_job_for(db, v.model)
        due = schedule.due_info(v, job) if job else None
        row = {'id': v.id, 'fleet_no': v.fleet_no, 'model': v.model, 'current_km': v.current_km, 'daily_km': v.daily_km, 'approved': bool(job)}
        if due:
            row.update({'approved_km': due['approved_km'], 'remaining_km': due['remaining_km'], 'days_left': due['days_left'], 'due_date': due['due_date'].isoformat()})
        vehicles.append(row)
    cfg = schedule.get_config(db)
    return {'stations': stations, 'vehicles': vehicles, 'config': {'min_attendance': cfg.min_attendance}, 'today': schedule.today().isoformat()}

@router.get('/calendar')
def cal(start: date | None = None, days: int = 14, db=Depends(get_db), u=Depends(current_user)):
    return schedule.calendar(db, start or schedule.today(), days)

@router.get('/plans')
def plans(db=Depends(get_db), u=Depends(current_user)):
    return [schedule.plan_view(db, p) for p in db.scalars(select(MaintenancePlan).order_by(MaintenancePlan.id.desc()))]

@router.post('/plans', status_code=201)
def create(data: PlanInput, db=Depends(get_db), u=Depends(can_write)):
    plan = schedule.create_draft(db, data, u)
    record(db, u.email, 'schedule.plan.create', {'id': plan.id, 'vehicle': plan.vehicle_id, 'start': plan.start_date.isoformat(), 'days': plan.days})
    db.commit()
    return schedule.plan_view(db, plan)

@router.post('/plans/{pid}/confirm')
def confirm(pid: int, db=Depends(get_db), u=Depends(can_write)):
    plan = schedule.confirm(db, _plan_or_404(db, pid), u)
    record(db, u.email, 'schedule.plan.confirm', {'id': pid})
    db.commit()
    return schedule.plan_view(db, plan)

@router.post('/plans/{pid}/reschedule')
def change(pid: int, data: RescheduleInput, db=Depends(get_db), u=Depends(can_write)):
    plan = schedule.reschedule(db, _plan_or_404(db, pid), data, u)
    record(db, u.email, 'schedule.plan.reschedule', {'id': pid, 'start': data.start_date.isoformat(), 'station': data.station_id})
    db.commit()
    return schedule.plan_view(db, plan)

@router.post('/plans/{pid}/cancel')
def cancel(pid: int, db=Depends(get_db), u=Depends(can_write)):
    plan = schedule.cancel(db, _plan_or_404(db, pid), u)
    record(db, u.email, 'schedule.plan.cancel', {'id': pid})
    db.commit()
    return schedule.plan_view(db, plan)

@router.get('/closures')
def closures(db=Depends(get_db), u=Depends(current_user)):
    out = []
    stations = {s.id: s.name for s in db.scalars(select(Station))}
    for c in db.scalars(select(BayClosure).order_by(BayClosure.id.desc()).limit(50)):
        out.append({'id': c.id, 'station_id': c.station_id, 'station': stations.get(c.station_id, '?'), 'date': c.date.isoformat(),
                    'bays': c.bays, 'reason': c.reason, 'active': c.active, 'displaced': c.displaced or [], 'created_at': c.created_at})
    return out

@router.post('/closures', status_code=201)
def close(data: ClosureInput, db=Depends(get_db), u=Depends(can_write)):
    closure = schedule.close_bays(db, data, u)
    record(db, u.email, 'schedule.closure.create', {'id': closure.id, 'station': closure.station_id, 'date': closure.date.isoformat(), 'bays': closure.bays, 'displaced': closure.displaced})
    db.commit()
    return {'id': closure.id, 'displaced': closure.displaced}

@router.post('/closures/{cid}/reopen')
def reopen(cid: int, db=Depends(get_db), u=Depends(can_write)):
    closure = db.get(BayClosure, cid)
    if not closure:
        raise HTTPException(404, '封闭记录不存在')
    schedule.reopen(db, closure, u)
    record(db, u.email, 'schedule.closure.reopen', {'id': cid})
    db.commit()
    return {'id': cid, 'active': closure.active}

@router.put('/config')
def config(data: ConfigInput, db=Depends(get_db), u=Depends(admin_only)):
    cfg = schedule.get_config(db)
    cfg.min_attendance = data.min_attendance
    record(db, u.email, 'schedule.config.update', {'min_attendance': data.min_attendance})
    db.commit()
    return {'min_attendance': cfg.min_attendance}
