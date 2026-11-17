import time, json, random
from datetime import timedelta
from sqlalchemy import select, func
from src.config.database import Session
from migrations.initial import migrate
from src.models import User, Dataset, Job, Report, Delivery, Audit, Station, Vehicle, BayClosure, MaintenancePlan, ScheduleConfig
from src.services.business import metadata, seed_records, analyze
from src.services.reports import deliver
from src.services import schedule as sched
from src.schemas.schedule import PlanInput, ClosureInput
from src.utils.security import hash_password
from src.utils.serialization import checksum

def seed_fleet(db, admin):
    if not db.scalar(select(ScheduleConfig)):
        db.add(ScheduleConfig(min_attendance=90))
    for name, bays in [('东湖检修站', 3), ('临港检修站', 2), ('西坝检修站', 2)]:
        if not db.scalar(select(Station).where(Station.name == name)):
            db.add(Station(name=name, bays=bays, created_at=time.time()))
    db.flush()
    if not db.scalar(select(Vehicle)):
        rng = random.Random(20261117)
        thresholds = {}
        for model in ('AC-8', 'AC-12'):
            job = sched.approved_job_for(db, model)
            thresholds[model] = sched.approved_km_of(job) if job else 33000.0
        for i in range(96):
            model = 'AC-8' if i % 2 == 0 else 'AC-12'
            daily = round(rng.uniform(120, 260), 1)
            target = rng.choice([rng.uniform(-12, -1), rng.uniform(4, 30), rng.uniform(30, 90), rng.uniform(90, 200)])
            km = max(1000.0, round(thresholds[model] - daily * target, 1))
            db.add(Vehicle(fleet_no=f'鹭湾-{i+1:03}', model=model, current_km=km, daily_km=daily, created_at=time.time()))
        db.flush()

def seed_plans(db, admin):
    if db.scalar(select(MaintenancePlan)):
        return
    stations = {s.name: s for s in db.scalars(select(Station))}
    today = sched.today()
    ready = []
    for v in db.scalars(select(Vehicle)):
        job = sched.approved_job_for(db, v.model)
        due = sched.due_info(v, job) if job else None
        if due and due['days_left'] >= 8:
            ready.append((v, due['days_left']))
    ready.sort(key=lambda x: x[1])
    if len(ready) >= 2:
        first = sched.create_draft(db, PlanInput(vehicle_id=ready[0][0].id, station_id=stations['东湖检修站'].id,
                                                 start_date=today + timedelta(days=1), days=2), admin)
        sched.confirm(db, first, admin)
        sched.create_draft(db, PlanInput(vehicle_id=ready[1][0].id, station_id=stations['临港检修站'].id,
                                         start_date=today + timedelta(days=3), days=2), admin)
    if not db.scalar(select(BayClosure)) and stations:
        sched.close_bays(db, ClosureInput(station_id=stations['西坝检修站'].id, date=today + timedelta(days=6), bays=1,
                                          reason='吊装设备周检，临时封闭 1 个工位'), admin)

def seed():
    migrate()
    with Session() as db:
        for role,name in [('admin','林知 · 业务负责人'),('analyst','陈舟 · 分析员'),('viewer','周禾 · 观察员')]:
            email=role+'@demo.local'
            if not db.scalar(select(User).where(User.email==email)):
                db.add(User(email=email,name=name,role=role,password=hash_password('Demo123!')))
        db.flush()
        admin=db.scalar(select(User).where(User.role=='admin'))
        m=metadata()
        d=db.scalar(select(Dataset).where(Dataset.name==m['dataset_name']))
        if not d:
            rows=seed_records()
            d=Dataset(name=m['dataset_name'],source=m['short']+'-202611.csv',records=rows,checksum=checksum(rows),created_at=time.time())
            db.add(d); db.flush()
        if not db.scalar(select(Job).where(Job.name=='基线复核 · '+m['name'])):
            params={p['key']:p['default'] for p in m.get('parameters',[])}
            result=analyze(d.records,params)
            json.dumps(result,ensure_ascii=False,allow_nan=False)
            j=Job(name='基线复核 · '+m['name'],dataset_id=d.id,params=params,status='completed',result=result,created_by=admin.id,created_at=time.time()-3600,finished_at=time.time()-3595,approved=True)
            db.add(j);db.flush()
            r=Report(name='每日业务复核简报',job_id=j.id,destination='业务复核组 · 本地收件箱',interval_seconds=86400,next_run=time.time()+86400,enabled=True)
            db.add(r);db.flush();deliver(db,r)
            db.add(Audit(actor='seed',action='demo.baseline',detail={'dataset':d.id},at=time.time()))
        if not db.scalar(select(Job).where(Job.name=='基线复核 · AC-12 独立拟合')):
            params={'model':'AC-12','reliability':0.9}
            result=analyze(d.records,params)
            json.dumps(result,ensure_ascii=False,allow_nan=False)
            db.add(Job(name='基线复核 · AC-12 独立拟合',dataset_id=d.id,params=params,status='completed',result=result,created_by=admin.id,created_at=time.time()-3500,finished_at=time.time()-3495,approved=True))
            db.flush()
        seed_fleet(db, admin)
        seed_plans(db, admin)
        db.commit()
        counts={model.__tablename__:db.scalar(select(func.count()).select_from(model)) for model in [User,Dataset,Job,Report,Delivery,Audit,Station,Vehicle,MaintenancePlan]}
        print(json.dumps(counts,ensure_ascii=False))
        return counts
if __name__=='__main__':seed()
