import os, json
from dotenv import load_dotenv
load_dotenv()
from datetime import date
from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import desc
from database import Base, engine, get_db, SessionLocal
from .models import User, Task, News, AuctionLot, Bid, DutyReport
from .security import hash_password, check_password, make_token, get_user, roles

app = FastAPI(title="ЭРЭЛ")
Base.metadata.create_all(engine)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

def seed():
    db=SessionLocal()
    email=os.getenv("ADMIN_EMAIL","admin@erel.local").lower()
    if not db.query(User).filter_by(email=email).first():
        db.add(User(name="Администратор",email=email,password_hash=hash_password(os.getenv("ADMIN_PASSWORD","ChangeThis123!")),role="admin"))
        db.commit()
    db.close()
seed()

@app.get("/")
def index(): return FileResponse("app/static/index.html")

class Register(BaseModel):
    name:str=Field(min_length=2,max_length=100)
    email:str
    password:str=Field(min_length=8,max_length=72)
    role:str="student"
    class_name:str=""
    invite_code:str=""
class Login(BaseModel):
    email:str
    password:str
class TaskData(BaseModel):
    title:str
    description:str=""
    reward:int=Field(ge=0,le=100000)
class NewsData(BaseModel):
    title:str
    body:str
class LotData(BaseModel):
    title:str
    description:str=""
    start_price:int=Field(ge=1)
    buy_now_price:int|None=None
class BidData(BaseModel):
    amount:int=Field(ge=1)
class DutyData(BaseModel):
    class_name:str
    report_date:str
    criteria:dict[str,bool]

def public_user(u):
    return {"id":u.id,"name":u.name,"email":u.email,"role":u.role,"class_name":u.class_name,"coins":u.coins}
def token_response(u): return {"access_token":make_token(u),"token_type":"bearer","user":public_user(u)}

@app.post("/api/register")
def register(x:Register,db:Session=Depends(get_db)):
    email=x.email.strip().lower()
    if "@" not in email: raise HTTPException(400,"Некорректная почта")
    if db.query(User).filter_by(email=email).first(): raise HTTPException(409,"Эта почта уже зарегистрирована")
    if x.role not in ("student","teacher","staff"): raise HTTPException(400,"Недопустимая роль")
    if x.role in ("teacher","staff") and x.invite_code != os.getenv("STAFF_INVITE_CODE","change-this-code"):
        raise HTTPException(403,"Неверный код приглашения")
    if x.role=="student" and not x.class_name.strip(): raise HTTPException(400,"Укажите класс")
    u=User(name=x.name.strip(),email=email,password_hash=hash_password(x.password),role=x.role,class_name=x.class_name.strip())
    db.add(u);db.commit();db.refresh(u);return token_response(u)

@app.post("/api/login")
def login(x:Login,db:Session=Depends(get_db)):
    u=db.query(User).filter_by(email=x.email.strip().lower()).first()
    if not u or not check_password(x.password,u.password_hash): raise HTTPException(401,"Неверная почта или пароль")
    return token_response(u)
@app.get("/api/me")
def me(u:User=Depends(get_user)): return public_user(u)

@app.get("/api/tasks")
def tasks(db:Session=Depends(get_db),u:User=Depends(get_user)):
    return [{"id":t.id,"title":t.title,"description":t.description,"reward":t.reward,"status":t.status,"student_id":t.student_id} for t in db.query(Task).order_by(desc(Task.created_at)).all()]
@app.post("/api/tasks")
def new_task(x:TaskData,db:Session=Depends(get_db),u:User=Depends(roles("teacher","staff","admin"))):
    t=Task(title=x.title,description=x.description,reward=x.reward,created_by=u.id);db.add(t);db.commit();return {"ok":True}
@app.post("/api/tasks/{tid}/take")
def take(tid:int,db:Session=Depends(get_db),u:User=Depends(roles("student"))):
    t=db.get(Task,tid)
    if not t or t.status!="open": raise HTTPException(400,"Поручение уже недоступно")
    t.student_id=u.id;t.status="taken";db.commit();return {"ok":True}
@app.post("/api/tasks/{tid}/submit")
def submit(tid:int,db:Session=Depends(get_db),u:User=Depends(roles("student"))):
    t=db.get(Task,tid)
    if not t or t.student_id!=u.id or t.status!="taken": raise HTTPException(400,"Нельзя отправить это поручение")
    t.status="review";db.commit();return {"ok":True}
@app.post("/api/tasks/{tid}/approve")
def approve(tid:int,db:Session=Depends(get_db),u:User=Depends(roles("teacher","staff","admin"))):
    t=db.get(Task,tid)
    if not t or t.status!="review": raise HTTPException(400,"Поручение не ожидает проверки")
    db.get(User,t.student_id).coins+=t.reward;t.status="done";db.commit();return {"ok":True}

@app.get("/api/news")
def news(db:Session=Depends(get_db),u:User=Depends(get_user)):
    return [{"id":n.id,"title":n.title,"body":n.body,"created_at":n.created_at.isoformat()} for n in db.query(News).order_by(desc(News.created_at)).all()]
@app.post("/api/news")
def add_news(x:NewsData,db:Session=Depends(get_db),u:User=Depends(roles("teacher","staff","admin"))):
    db.add(News(title=x.title,body=x.body,author_id=u.id));db.commit();return {"ok":True}

@app.get("/api/auction")
def auction(db:Session=Depends(get_db),u:User=Depends(get_user)):
    return [{"id":l.id,"title":l.title,"description":l.description,"current_bid":l.current_bid,"buy_now_price":l.buy_now_price,"status":l.status,"seller_id":l.seller_id} for l in db.query(AuctionLot).order_by(desc(AuctionLot.created_at)).all()]
@app.post("/api/auction")
def lot(x:LotData,db:Session=Depends(get_db),u:User=Depends(roles("student"))):
    if x.buy_now_price and x.buy_now_price<x.start_price: raise HTTPException(400,"Цена выкупа ниже начальной")
    db.add(AuctionLot(title=x.title,description=x.description,start_price=x.start_price,current_bid=x.start_price,buy_now_price=x.buy_now_price,seller_id=u.id));db.commit();return {"ok":True}
@app.post("/api/auction/{lid}/bid")
def bid(lid:int,x:BidData,db:Session=Depends(get_db),u:User=Depends(roles("student"))):
    l=db.get(AuctionLot,lid)
    if not l or l.status!="open" or l.seller_id==u.id: raise HTTPException(400,"Лот недоступен")
    if x.amount<=l.current_bid: raise HTTPException(400,"Ставка должна быть выше текущей")
    if x.amount>u.coins: raise HTTPException(400,"Недостаточно Мификов")
    if l.highest_bidder_id: db.get(User,l.highest_bidder_id).coins+=l.current_bid
    u.coins-=x.amount;l.current_bid=x.amount;l.highest_bidder_id=u.id
    db.add(Bid(lot_id=lid,bidder_id=u.id,amount=x.amount));db.commit();return {"ok":True}
@app.post("/api/auction/{lid}/buy")
def buy(lid:int,db:Session=Depends(get_db),u:User=Depends(roles("student"))):
    l=db.get(AuctionLot,lid)
    if not l or l.status!="open" or not l.buy_now_price or l.seller_id==u.id: raise HTTPException(400,"Выкуп недоступен")
    if u.coins<l.buy_now_price: raise HTTPException(400,"Недостаточно Мификов")
    if l.highest_bidder_id: db.get(User,l.highest_bidder_id).coins+=l.current_bid
    u.coins-=l.buy_now_price;db.get(User,l.seller_id).coins+=l.buy_now_price
    l.current_bid=l.buy_now_price;l.highest_bidder_id=u.id;l.status="sold";db.commit();return {"ok":True}

CRITERIA=["Мусор выброшен","Стулья подняты","Пол чистый","Доска вымыта","Подоконники чистые","Парты расставлены","Корзина не переполнена"]
CLASSES=[f"{n} класс" for n in range(5,10)]+[f"{n} {d}" for n in (10,11) for d in ("ИНЖ","ГУМ","ПТХ","ТЕХ","БХ","ФМ")]
@app.get("/api/duty")
def duty(db:Session=Depends(get_db),u:User=Depends(get_user)):
    return [{"class_name":r.class_name,"date":r.report_date,"criteria":json.loads(r.criteria_json)} for r in db.query(DutyReport).all()]
@app.post("/api/duty")
def save_duty(x:DutyData,db:Session=Depends(get_db),u:User=Depends(roles("staff","admin"))):
    if x.class_name not in CLASSES: raise HTTPException(400,"Неизвестный класс")
    try: date.fromisoformat(x.report_date)
    except ValueError: raise HTTPException(400,"Неверная дата")
    if set(x.criteria)-set(CRITERIA): raise HTTPException(400,"Неизвестный критерий")
    r=db.query(DutyReport).filter_by(class_name=x.class_name,report_date=x.report_date).first()
    if r: r.criteria_json=json.dumps(x.criteria,ensure_ascii=False);r.worker_id=u.id
    else: db.add(DutyReport(class_name=x.class_name,report_date=x.report_date,criteria_json=json.dumps(x.criteria,ensure_ascii=False),worker_id=u.id))
    db.commit();return {"ok":True}
@app.get("/api/duty/rating")
def rating(db:Session=Depends(get_db),u:User=Depends(get_user)):
    totals={}
    for r in db.query(DutyReport).all():
        vals=list(json.loads(r.criteria_json).values())
        if vals:
            a=totals.setdefault(r.class_name,[0,0]);a[0]+=sum(vals);a[1]+=len(vals)
    return sorted([{"class_name":k,"percent":round(v[0]/v[1]*100)} for k,v in totals.items()],key=lambda x:-x["percent"])
