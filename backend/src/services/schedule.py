"""检修日历编排：试排不占工位，确认统一占用，改期整案换位，封闭先受理者决定。"""
import time
from datetime import date, timedelta
from fastapi import HTTPException
from sqlalchemy import select, func, update
from src.models import Station, Vehicle, BayClosure, MaintenancePlan, PlanSlot, ScheduleConfig, Job

ACTIVE = ('confirmed', 'pending_reschedule')
WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日']

def today():
    return date.today()

def get_config(db):
    cfg = db.scalar(select(ScheduleConfig).order_by(ScheduleConfig.id))
    if not cfg:
        cfg = ScheduleConfig(min_attendance=90)
        db.add(cfg)
        db.flush()
    return cfg

def approved_job_for(db, model):
    for j in db.scalars(select(Job).where(Job.approved == True, Job.status == 'completed').order_by(Job.id.desc())):
        if str((j.params or {}).get('model')) == str(model):
            return j
    return None

def approved_km_of(job):
    for m in (job.result or {}).get('metrics', []):
        if m.get('label') == '目标可靠度里程':
            try:
                return float(m.get('value'))
            except (TypeError, ValueError):
                return None
    return None

def due_info(vehicle, job):
    approved_km = approved_km_of(job)
    if approved_km is None or vehicle.daily_km <= 0:
        return None
    remaining = approved_km - vehicle.current_km
    days_left = int(remaining // vehicle.daily_km)
    return {'approved_km': approved_km, 'remaining_km': round(remaining, 1), 'days_left': days_left,
            'due_date': today() + timedelta(days=days_left)}

def plan_dates(start, days):
    return [start + timedelta(days=i) for i in range(days)]

def _lock(db, model, row_id):
    # 可移植行级写锁：空更新在 PostgreSQL 锁行，在 SQLite 串行化写事务
    db.execute(update(model).where(model.id == row_id).values(id=row_id))

def lock_scope(db, vehicle_id=None, station_ids=(), plan_id=None):
    # 固定加锁顺序：车辆 → 站点 → 方案，避免并发死锁
    if vehicle_id:
        _lock(db, Vehicle, vehicle_id)
    for sid in sorted(set(station_ids)):
        _lock(db, Station, sid)
    if plan_id:
        _lock(db, MaintenancePlan, plan_id)

def closures_on(db, station_id, dates):
    out = {}
    if not dates:
        return out
    rows = db.scalars(select(BayClosure).where(BayClosure.station_id == station_id, BayClosure.active == True, BayClosure.date.in_(dates)))
    for r in rows:
        out[r.date] = out.get(r.date, 0) + r.bays
    return out

def occupancy_on(db, station_id, dates, exclude_plan=None):
    # 已确认与待重排方案的保留占用都计入工位占用，阻止新案挤占
    if not dates:
        return {}
    q = (select(PlanSlot.date, func.count()).join(MaintenancePlan, MaintenancePlan.id == PlanSlot.plan_id)
         .where(PlanSlot.station_id == station_id, PlanSlot.date.in_(dates), MaintenancePlan.status.in_(ACTIVE))
         .group_by(PlanSlot.date))
    if exclude_plan:
        q = q.where(PlanSlot.plan_id != exclude_plan)
    return dict(db.execute(q).all())

def busy_on(db, dates, exclude_plan=None):
    # 出勤口径：仅已确认方案的车辆当日停修；待重排车辆回到出车池
    out = {}
    if not dates:
        return out
    q = (select(PlanSlot.date, PlanSlot.vehicle_id).join(MaintenancePlan, MaintenancePlan.id == PlanSlot.plan_id)
         .where(PlanSlot.date.in_(dates), MaintenancePlan.status == 'confirmed'))
    if exclude_plan:
        q = q.where(PlanSlot.plan_id != exclude_plan)
    for d, v in db.execute(q).all():
        out.setdefault(d, set()).add(v)
    return out

def evaluate(db, vehicle, station, start, days, due_date=None, exclude_plan=None):
    conflicts = []
    dates = plan_dates(start, days)
    if start < today():
        conflicts.append({'type': 'past', 'date': start.isoformat(), 'message': f'开始日期 {start.isoformat()} 早于今天'})
    if due_date is not None and dates[-1] > due_date:
        conflicts.append({'type': 'overdue', 'date': dates[-1].isoformat(), 'due_date': due_date.isoformat(),
                          'message': f'完工日 {dates[-1].isoformat()} 晚于批准里程到期日 {due_date.isoformat()}，整案逾期'})
    closed = closures_on(db, station.id, dates)
    used = occupancy_on(db, station.id, dates, exclude_plan)
    for d in dates:
        cap = station.bays - closed.get(d, 0)
        if used.get(d, 0) + 1 > cap:
            conflicts.append({'type': 'capacity', 'date': d.isoformat(), 'station': station.name,
                              'message': f'{station.name} {d.isoformat()} 工位不足：可用 {max(cap, 0)}，已占 {used.get(d, 0)}'})
    q = (select(MaintenancePlan).join(PlanSlot, PlanSlot.plan_id == MaintenancePlan.id)
         .where(MaintenancePlan.vehicle_id == vehicle.id, MaintenancePlan.status.in_(ACTIVE), PlanSlot.date.in_(dates)).distinct())
    if exclude_plan:
        q = q.where(MaintenancePlan.id != exclude_plan)
    for p in db.scalars(q):
        conflicts.append({'type': 'overlap', 'date': '', 'plan_id': p.id,
                          'message': f'与该车既有停修方案 #{p.id} 日期重叠，同车不能重叠停修'})
    cfg = get_config(db)
    total = db.scalar(select(func.count()).select_from(Vehicle)) or 0
    busy = busy_on(db, dates, exclude_plan)
    for d in dates:
        attendance = total - len(busy.get(d, set()) | {vehicle.id})
        if attendance < cfg.min_attendance:
            conflicts.append({'type': 'attendance', 'date': d.isoformat(), 'attendance': attendance, 'floor': cfg.min_attendance,
                              'message': f'{d.isoformat()} 出勤 {attendance} 低于每日下限 {cfg.min_attendance}'})
    return {'dates': [d.isoformat() for d in dates], 'conflicts': conflicts}

def create_draft(db, data, user):
    vehicle = db.get(Vehicle, data.vehicle_id)
    if not vehicle:
        raise HTTPException(404, '车辆不存在')
    station = db.get(Station, data.station_id)
    if not station:
        raise HTTPException(404, '检修站不存在')
    if data.start_date < today():
        raise HTTPException(422, '开始日期不能早于今天')
    pending = db.scalar(select(MaintenancePlan).where(MaintenancePlan.vehicle_id == vehicle.id, MaintenancePlan.status == 'pending_reschedule'))
    if pending:
        raise HTTPException(409, f'该车存在待重排方案 #{pending.id}，未解决前不能另立新案挤占')
    job = approved_job_for(db, vehicle.model)
    if not job:
        raise HTTPException(409, f'型号 {vehicle.model} 尚无已批准里程，请先在结果复核中批准对应分析')
    due = due_info(vehicle, job)
    if due is None:
        raise HTTPException(409, '已批准结果缺少目标可靠度里程，无法编排日期')
    plan = MaintenancePlan(vehicle_id=vehicle.id, station_id=station.id, job_id=job.id, start_date=data.start_date,
                           days=data.days, due_date=due['due_date'], approved_km=due['approved_km'], status='draft',
                           created_by=user.id, created_at=time.time())
    db.add(plan)
    db.flush()
    return plan

def confirm(db, plan, user):
    lock_scope(db, plan.vehicle_id, [plan.station_id], plan.id)
    db.refresh(plan)
    if plan.status == 'confirmed':
        return plan  # 重试不重复排单
    if plan.status != 'draft':
        raise HTTPException(409, '仅试排方案可确认；待重排方案请改期')
    vehicle = db.get(Vehicle, plan.vehicle_id)
    station = db.get(Station, plan.station_id)
    ev = evaluate(db, vehicle, station, plan.start_date, plan.days, plan.due_date)
    if ev['conflicts']:
        raise HTTPException(409, '整案不可确认：' + '；'.join(sorted({c['message'] for c in ev['conflicts']})))
    for d in plan_dates(plan.start_date, plan.days):
        db.add(PlanSlot(plan_id=plan.id, station_id=plan.station_id, vehicle_id=plan.vehicle_id, date=d))
    plan.status = 'confirmed'
    plan.confirmed_at = time.time()
    db.flush()
    return plan

def reschedule(db, plan, data, user):
    station = db.get(Station, data.station_id)
    if not station:
        raise HTTPException(404, '检修站不存在')
    if data.start_date < today():
        raise HTTPException(422, '开始日期不能早于今天')
    key = (data.key or '').strip()
    lock_scope(db, plan.vehicle_id, [plan.station_id, station.id], plan.id)
    db.refresh(plan)
    if plan.status not in ACTIVE:
        raise HTTPException(409, '仅已确认或待重排方案可改期')
    if key and plan.reschedule_key == key:
        return plan  # 同一改期请求已应用，重试直接返回
    vehicle = db.get(Vehicle, plan.vehicle_id)
    ev = evaluate(db, vehicle, station, data.start_date, plan.days, plan.due_date, exclude_plan=plan.id)
    if ev['conflicts']:
        raise HTTPException(409, '新日期不可用，已保留原占用：' + '；'.join(sorted({c['message'] for c in ev['conflicts']})))
    for slot in db.scalars(select(PlanSlot).where(PlanSlot.plan_id == plan.id)):
        db.delete(slot)
    for d in plan_dates(data.start_date, plan.days):
        db.add(PlanSlot(plan_id=plan.id, station_id=station.id, vehicle_id=plan.vehicle_id, date=d))
    plan.station_id = station.id
    plan.start_date = data.start_date
    plan.status = 'confirmed'
    plan.confirmed_at = time.time()
    plan.reschedule_key = key or f'auto-{plan.id}-{int(time.time() * 1000)}'
    db.flush()
    return plan

def cancel(db, plan, user):
    lock_scope(db, plan.vehicle_id, [plan.station_id], plan.id)
    db.refresh(plan)
    if plan.status == 'cancelled':
        return plan
    for slot in db.scalars(select(PlanSlot).where(PlanSlot.plan_id == plan.id)):
        db.delete(slot)
    plan.status = 'cancelled'
    db.flush()
    return plan

def close_bays(db, data, user):
    station = db.get(Station, data.station_id)
    if not station:
        raise HTTPException(404, '检修站不存在')
    if data.date < today():
        raise HTTPException(422, '封闭日期不能早于今天')
    lock_scope(db, station_ids=[station.id])
    already = closures_on(db, station.id, [data.date]).get(data.date, 0)
    if already + data.bays > station.bays:
        raise HTTPException(409, f'{station.name} {data.date.isoformat()} 已封闭 {already}/{station.bays} 工位，本次封闭超出总数')
    closure = BayClosure(station_id=station.id, date=data.date, bays=data.bays, reason=data.reason, active=True,
                         displaced=[], created_by=user.id, created_at=time.time())
    db.add(closure)
    db.flush()
    capacity = station.bays - (already + data.bays)
    rows = db.execute(select(PlanSlot, MaintenancePlan).join(MaintenancePlan, MaintenancePlan.id == PlanSlot.plan_id)
                      .where(PlanSlot.station_id == station.id, PlanSlot.date == data.date, MaintenancePlan.status.in_(ACTIVE))
                      .order_by(MaintenancePlan.confirmed_at.asc().nulls_first(), MaintenancePlan.id.asc())).all()
    overflow = len(rows) - capacity
    displaced = []
    if overflow > 0:
        for slot, p in rows[-overflow:]:  # 先受理者保留，最新确认的让位
            db.delete(slot)
            if p.status == 'confirmed':
                p.status = 'pending_reschedule'
                displaced.append(p.id)
    closure.displaced = displaced
    db.flush()
    return closure

def reopen(db, closure, user):
    lock_scope(db, station_ids=[closure.station_id])
    closure.active = False
    db.flush()
    return closure

def calendar(db, start, days):
    days = min(max(int(days), 1), 31)
    dates = plan_dates(start, days)
    stations = db.scalars(select(Station).order_by(Station.id)).all()
    total = db.scalar(select(func.count()).select_from(Vehicle)) or 0
    cfg = get_config(db)
    occ = {}
    clo = {}
    if dates:
        q = (select(PlanSlot.station_id, PlanSlot.date, func.count()).join(MaintenancePlan, MaintenancePlan.id == PlanSlot.plan_id)
             .where(PlanSlot.date.in_(dates), MaintenancePlan.status.in_(ACTIVE)).group_by(PlanSlot.station_id, PlanSlot.date))
        occ = {(sid, d): n for sid, d, n in db.execute(q).all()}
        for c in db.scalars(select(BayClosure).where(BayClosure.active == True, BayClosure.date.in_(dates))):
            clo[(c.station_id, c.date)] = clo.get((c.station_id, c.date), 0) + c.bays
    busy = busy_on(db, dates)
    rows = []
    for d in dates:
        per = [{'station_id': s.id, 'name': s.name, 'bays': s.bays, 'closed': clo.get((s.id, d), 0),
                'occupied': occ.get((s.id, d), 0), 'free': s.bays - clo.get((s.id, d), 0) - occ.get((s.id, d), 0)} for s in stations]
        down = len(busy.get(d, set()))
        rows.append({'date': d.isoformat(), 'weekday': '周' + WEEKDAYS[d.weekday()], 'stations': per,
                     'fleet': {'total': total, 'down': down, 'attendance': total - down, 'floor': cfg.min_attendance,
                               'ok': total - down >= cfg.min_attendance}})
    return {'start': dates[0].isoformat() if dates else start.isoformat(), 'days': rows, 'min_attendance': cfg.min_attendance}

def plan_view(db, p):
    vehicle = db.get(Vehicle, p.vehicle_id)
    station = db.get(Station, p.station_id)
    slots = sorted(s.date for s in db.scalars(select(PlanSlot).where(PlanSlot.plan_id == p.id)))
    conflicts = []
    if p.status == 'draft':
        conflicts = evaluate(db, vehicle, station, p.start_date, p.days, p.due_date)['conflicts']
    return {'id': p.id, 'vehicle_id': p.vehicle_id, 'fleet_no': vehicle.fleet_no if vehicle else '?', 'model': vehicle.model if vehicle else '?',
            'station_id': p.station_id, 'station': station.name if station else '?', 'job_id': p.job_id,
            'start_date': p.start_date.isoformat(), 'days': p.days, 'due_date': p.due_date.isoformat(), 'approved_km': p.approved_km,
            'status': p.status, 'slots': [d.isoformat() for d in slots], 'conflicts': conflicts,
            'created_at': p.created_at, 'confirmed_at': p.confirmed_at}
