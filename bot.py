import os, re, json, logging
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional

import gspread
from google.oauth2.service_account import Credentials
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
Application, MessageHandler, CommandHandler,
CallbackQueryHandler, filters, ContextTypes,
)

logging.basicConfig(level=logging.INFO, format=”%(asctime)s [%(levelname)s] %(message)s”)
logger = logging.getLogger(**name**)

KYIV_TZ        = ZoneInfo(“Europe/Kyiv”)
TELEGRAM_TOKEN = os.environ.get(“TELEGRAM_TOKEN”, “”)
SPREADSHEET_ID = os.environ.get(“SPREADSHEET_ID”, “”)
GOOGLE_CREDS   = os.environ.get(“GOOGLE_CREDS”, “”)
STO_NAME       = os.environ.get(“STO_NAME”, “Farro”)
OWNER_ID       = int(os.environ.get(“OWNER_ID”, “0”))
MASTER_IDS     = [int(x.strip()) for x in os.environ.get(“MASTER_IDS”,””).split(”,”) if x.strip()]

def open_sheet():
d = json.loads(GOOGLE_CREDS)
scopes = [“https://spreadsheets.google.com/feeds”,“https://www.googleapis.com/auth/drive”]
creds = Credentials.from_service_account_info(d, scopes=scopes)
return gspread.authorize(creds).open_by_key(SPREADSHEET_ID)

def get_ws(name: str):
sp = open_sheet()
for ws in sp.worksheets():
if ws.title.lower() == name.lower():
return ws
return sp.sheet1

def parse_num(v) -> Optional[int]:
s = re.sub(r”[^\d]”,””,str(v or “”))
try: return int(s) if s else None
except: return None

def today_str() -> str:
return datetime.now(KYIV_TZ).strftime(”%d.%m.%y”)

def now_str() -> str:
return datetime.now(KYIV_TZ).strftime(”%d.%m.%y %H:%M”)

def is_staff(uid: int) -> bool:
return uid in MASTER_IDS or uid == OWNER_ID

STATUSES = {
“new”:     “🆕 Принято”,
“in_work”: “🔧 В работе”,
“ready”:   “✅ Готово”,
“issued”:  “🚗 Выдано”,
}

def status_label(s: str) -> str:
return STATUSES.get(s, s)

# ── Клиенты ──────────────────────────────────────────────────

def get_client(tg_id: int) -> Optional[Dict]:
ws = get_ws(“Клиенты”)
for row in ws.get_all_values()[1:]:
if str(row[0]).strip() == str(tg_id):
return {“tg_id”:row[0],“name”:row[1] if len(row)>1 else “”,
“phone”:row[2] if len(row)>2 else “”,
“car”:row[3] if len(row)>3 else “”,
“model”:row[4] if len(row)>4 else “”}
return None

def find_client_by_car(car: str) -> Optional[Dict]:
ws = get_ws(“Клиенты”)
cc = car.upper().replace(” “,””)
for row in ws.get_all_values()[1:]:
if len(row)>3 and cc in str(row[3]).upper().replace(” “,””):
return {“tg_id”:row[0],“name”:row[1],“car”:row[3]}
return None

def register_client(tg_id, name, phone, car, model):
get_ws(“Клиенты”).append_row([str(tg_id),name,phone,car.upper(),model,today_str()])

# ── Заказы ───────────────────────────────────────────────────

def gen_order_id() -> str:
rows = get_ws(“Заказы”).get_all_values()
num  = len([r for r in rows[1:] if r and r[0]]) + 1
return f”ORD-{num:04d}”

def create_order(car, client_name, description, odo, master_name) -> str:
oid = gen_order_id()
get_ws(“Заказы”).append_row([oid,now_str(),car.upper(),client_name,description,“new”,master_name,odo,””,””])
return oid

def get_order(order_id: str) -> Optional[Dict]:
for row in get_ws(“Заказы”).get_all_values()[1:]:
if str(row[0]).strip() == order_id:
return {“id”:row[0],“date”:row[1] if len(row)>1 else “”,
“car”:row[2] if len(row)>2 else “”,
“client”:row[3] if len(row)>3 else “”,
“description”:row[4] if len(row)>4 else “”,
“status”:row[5] if len(row)>5 else “new”,
“master”:row[6] if len(row)>6 else “”,
“odo”:row[7] if len(row)>7 else “”,
“act_link”:row[8] if len(row)>8 else “”,
“ready_time”:row[9] if len(row)>9 else “”}
return None

def update_order_status(order_id, status, extra=””):
ws = get_ws(“Заказы”)
for i,row in enumerate(ws.get_all_values()[1:],start=2):
if str(row[0]).strip() == order_id:
ws.update(f”F{i}”,[[status]])
if status == “ready”: ws.update(f”J{i}”,[[now_str()]])
if extra: ws.update(f”I{i}”,[[extra]])
return

def get_active_orders() -> List[Dict]:
result = []
for row in get_ws(“Заказы”).get_all_values()[1:]:
if len(row)>5 and row[5] not in (“issued”,””):
result.append({“id”:row[0],“date”:row[1],“car”:row[2],
“client”:row[3],“description”:row[4],
“status”:row[5],“master”:row[6] if len(row)>6 else “”})
return result

def get_orders_by_car(car: str) -> List[Dict]:
cc = car.upper().replace(” “,””)
result = []
for row in get_ws(“Заказы”).get_all_values()[1:]:
if len(row)>2 and cc in str(row[2]).upper().replace(” “,””):
result.append({“id”:row[0],“date”:row[1],“car”:row[2],
“description”:row[4] if len(row)>4 else “”,
“status”:row[5] if len(row)>5 else “”,
“act_link”:row[8] if len(row)>8 else “”})
return result[-10:]

# ── История ТО ───────────────────────────────────────────────

def get_to_history(car: str) -> Optional[Dict]:
cc = car.upper().replace(” “,””)
for row in get_ws(“История_ТО”).get_all_values()[1:]:
if row and cc in str(row[0]).upper().replace(” “,””):
return {“car”:row[0],“oil_date”:row[1] if len(row)>1 else “”,
“oil_odo”:parse_num(row[2]) if len(row)>2 else None,
“grm_date”:row[3] if len(row)>3 else “”,
“grm_odo”:parse_num(row[4]) if len(row)>4 else None}
return None

def calc_oil(car, odo) -> str:
h = get_to_history(car)
if not h or not h[“oil_odo”]: return “Данных о замене масла нет. Обратитесь на СТО.”
rem = 10000-(odo-h[“oil_odo”])
if rem<=0: return f”❗ Масло просрочено на {abs(rem):,} км! Срочно на замену.”.replace(”,”,”.”)
if rem<=1000: return f”⚠️ До замены масла: {rem:,} км. Запишитесь на ТО.”.replace(”,”,”.”)
return f”✅ До замены масла: {rem:,} км (замена: {h[‘oil_date’]})”.replace(”,”,”.”)

def calc_grm(car, odo) -> str:
h = get_to_history(car)
if not h or not h[“grm_odo”]: return “Данных о замене ГРМ нет. Уточните у мастера.”
rem = 60000-(odo-h[“grm_odo”])
if rem<=0: return f”❗ ГРМ просрочен на {abs(rem):,} км!”.replace(”,”,”.”)
if rem<=2000: return f”⚠️ До замены ГРМ: {rem:,} км.”.replace(”,”,”.”)
return f”✅ До замены ГРМ: {rem:,} км (замена: {h[‘grm_date’]})”.replace(”,”,”.”)

# ── Клавиатуры ───────────────────────────────────────────────

def kb_client():
return InlineKeyboardMarkup([
[InlineKeyboardButton(“📊 Статус моего авто”,    callback_data=“c_status”)],
[InlineKeyboardButton(“🛢 Когда менять масло?”,  callback_data=“c_oil”)],
[InlineKeyboardButton(“📋 История работ”,        callback_data=“c_history”)],
[InlineKeyboardButton(“📩 Написать мастеру”,     callback_data=“c_contact”)],
])

def kb_master():
return InlineKeyboardMarkup([
[InlineKeyboardButton(“➕ Принять авто”,          callback_data=“m_new”)],
[InlineKeyboardButton(“📋 Активные заказы”,      callback_data=“m_orders”)],
[InlineKeyboardButton(“✅ Отметить готово”,       callback_data=“m_ready”)],
[InlineKeyboardButton(“📊 Заказы сегодня”,       callback_data=“m_today”)],
])

def kb_owner():
return InlineKeyboardMarkup([
[InlineKeyboardButton(“📋 Все активные заказы”,  callback_data=“m_orders”)],
[InlineKeyboardButton(“📊 Статистика”,           callback_data=“o_stats”)],
[InlineKeyboardButton(“🔧 Режим мастера”,        callback_data=“m_new”)],
])

def kb_cancel():
return InlineKeyboardMarkup([[InlineKeyboardButton(“❌ Отмена”, callback_data=“cancel”)]])

# ── Handlers ─────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
uid  = update.effective_user.id
name = update.effective_user.first_name or “Клиент”
ctx.user_data.clear()

```
if uid == OWNER_ID:
    await update.message.reply_text(
        f"👋 Привет, {name}! ID: {uid}\nРежим владельца — СТО {STO_NAME}.",
        reply_markup=kb_owner())
elif uid in MASTER_IDS:
    await update.message.reply_text(
        f"👋 Привет, {name}! ID: {uid}\nРежим мастера — СТО {STO_NAME}.",
        reply_markup=kb_master())
else:
    client = get_client(uid)
    if client and client["car"]:
        await update.message.reply_text(
            f"👋 Привет, {client['name']}!\nВаш автомобиль: {client['car']}\nЧем могу помочь?",
            reply_markup=kb_client())
    else:
        ctx.user_data["reg_step"] = "name"
        await update.message.reply_text(
            f"👋 Добро пожаловать в СТО {STO_NAME}!\nКак вас зовут?")
```

async def handle_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
uid  = update.effective_user.id
text = (update.message.text or “”).strip()
ud   = ctx.user_data

```
# Регистрация клиента
if ud.get("reg_step") == "name":
    ud["reg_name"] = text; ud["reg_step"] = "phone"
    await update.message.reply_text(f"Приятно, {text}! Ваш номер телефона?"); return
if ud.get("reg_step") == "phone":
    ud["reg_phone"] = text; ud["reg_step"] = "car"
    await update.message.reply_text("Номер вашего авто? (например АА1234ВВ)"); return
if ud.get("reg_step") == "car":
    ud["reg_car"] = text.upper(); ud["reg_step"] = "model"
    await update.message.reply_text("Марка и модель? (например Toyota Camry)"); return
if ud.get("reg_step") == "model":
    register_client(uid, ud["reg_name"], ud["reg_phone"], ud["reg_car"], text)
    car = ud["reg_car"]; ud.clear()
    await update.message.reply_text(
        f"✅ Вы зарегистрированы!\nАвто: {car}\nЧем могу помочь?",
        reply_markup=kb_client()); return

# Одометр для проверки масла
if ud.get("wait_odo"):
    car = ud.pop("wait_odo")
    odo = parse_num(text)
    if not odo:
        await update.message.reply_text("Введите пробег цифрами, например: 125000")
        ud["wait_odo"] = car; return
    await update.message.reply_text(
        f"🚗 {car}\n\n🛢 Масло:\n{calc_oil(car,odo)}\n\n⚙️ ГРМ:\n{calc_grm(car,odo)}",
        reply_markup=kb_client()); return

# Мастер: новый заказ
if ud.get("order_step"):
    step = ud["order_step"]
    if step == "car":
        ud["o_car"] = text.upper(); ud["order_step"] = "client"
        await update.message.reply_text("Имя клиента:"); return
    if step == "client":
        ud["o_client"] = text; ud["order_step"] = "desc"
        await update.message.reply_text("Описание работ:"); return
    if step == "desc":
        ud["o_desc"] = text; ud["order_step"] = "odo"
        await update.message.reply_text("Одометр (пробег):"); return
    if step == "odo":
        master = update.effective_user.first_name or "Мастер"
        oid    = create_order(ud["o_car"],ud["o_client"],ud["o_desc"],text,master)
        car = ud["o_car"]; client = ud["o_client"]; desc = ud["o_desc"]
        ud.clear()
        await update.message.reply_text(
            f"✅ Заказ создан!\n🔖 {oid}\n🚗 {car}\n👤 {client}\n📋 {desc}",
            reply_markup=kb_master()); return

# Мастер: готово по ID
if ud.get("wait_ready_id"):
    ud.pop("wait_ready_id")
    order = get_order(text.strip().upper())
    if not order:
        await update.message.reply_text("Заказ не найден. Проверьте номер."); return
    update_order_status(order["id"],"ready")
    await update.message.reply_text(
        f"✅ Заказ {order['id']} готов!\n🚗 {order['car']} — {order['client']}",
        reply_markup=kb_master())
    cl = find_client_by_car(order["car"])
    if cl and cl["tg_id"]:
        try:
            await ctx.bot.send_message(
                chat_id=int(cl["tg_id"]),
                text=f"✅ Ваш автомобиль {order['car']} готов!\n"
                     f"Работы: {order['description']}\n\n"
                     f"Ждём вас в СТО {STO_NAME}!")
        except Exception as e: logger.error(f"notify: {e}")
    return

# Клиент: сообщение мастеру
if ud.get("wait_msg"):
    ud.pop("wait_msg")
    cl = get_client(uid)
    cn = cl["name"] if cl else str(uid)
    cc = cl["car"]  if cl else "неизв."
    for mid in MASTER_IDS:
        try:
            await ctx.bot.send_message(chat_id=mid,
                text=f"📩 Сообщение от клиента:\n👤 {cn} | 🚗 {cc}\n\n{text}")
        except Exception as e: logger.error(f"fwd: {e}")
    await update.message.reply_text(
        "✅ Сообщение отправлено мастеру.", reply_markup=kb_client()); return

kb = kb_master() if is_staff(uid) else kb_client()
await update.message.reply_text("Выберите действие:", reply_markup=kb)
```

async def handle_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
q    = update.callback_query
uid  = q.from_user.id
data = q.data
await q.answer()
ud = ctx.user_data

```
if data == "cancel":
    ud.clear()
    kb = kb_master() if is_staff(uid) else kb_client()
    await q.edit_message_text("Отменено.", reply_markup=kb); return

# КЛИЕНТ
if data == "c_status":
    cl = get_client(uid)
    if not cl or not cl["car"]:
        await q.edit_message_text("Сначала зарегистрируйтесь — /start"); return
    orders = get_orders_by_car(cl["car"])
    active = [o for o in orders if o["status"] not in ("issued","")]
    if not active:
        await q.edit_message_text(
            f"🚗 {cl['car']}\n\nАктивных заказов нет.\nВсего работ в истории: {len(orders)}",
            reply_markup=kb_client()); return
    o = active[-1]
    txt = (f"🚗 {cl['car']}\n📊 {status_label(o['status'])}\n"
           f"🔖 {o['id']}\n📋 {o['description']}\n📅 {o['date']}")
    if o.get("act_link"): txt += f"\n📄 Акт: {o['act_link']}"
    await q.edit_message_text(txt, reply_markup=kb_client()); return

if data == "c_oil":
    cl = get_client(uid)
    if not cl or not cl["car"]:
        await q.edit_message_text("Сначала зарегистрируйтесь — /start"); return
    ud["wait_odo"] = cl["car"]
    await q.edit_message_text(
        f"🚗 {cl['car']}\nВведите текущий пробег (одометр) в км:",
        reply_markup=kb_cancel()); return

if data == "c_history":
    cl = get_client(uid)
    if not cl or not cl["car"]:
        await q.edit_message_text("Сначала зарегистрируйтесь — /start"); return
    orders = get_orders_by_car(cl["car"])
    if not orders:
        await q.edit_message_text("История работ пуста.", reply_markup=kb_client()); return
    lines = [f"📋 История — {cl['car']}\n"]
    for o in reversed(orders):
        ln = f"• {o['date']} — {o['description']}"
        if o.get("act_link"): ln += f" (акт)"
        lines.append(ln)
    await q.edit_message_text("\n".join(lines), reply_markup=kb_client()); return

if data == "c_contact":
    ud["wait_msg"] = True
    await q.edit_message_text(
        "📩 Напишите ваш вопрос — мастер ответит в ближайшее время:",
        reply_markup=kb_cancel()); return

# МАСТЕР
if data == "m_new":
    if not is_staff(uid):
        await q.edit_message_text("Нет доступа."); return
    ud["order_step"] = "car"
    await q.edit_message_text("➕ Новый заказ\n\nНомер авто клиента:", reply_markup=kb_cancel()); return

if data == "m_orders":
    if not is_staff(uid):
        await q.edit_message_text("Нет доступа."); return
    orders = get_active_orders()
    if not orders:
        await q.edit_message_text("Активных заказов нет.", reply_markup=kb_master()); return
    lines = [f"📋 Активные заказы: {len(orders)}\n"]
    for o in orders:
        lines.append(f"🔖 {o['id']} | 🚗 {o['car']} | {status_label(o['status'])}\n   👤 {o['client']}")
    await q.edit_message_text("\n".join(lines), reply_markup=kb_master()); return

if data == "m_ready":
    if not is_staff(uid):
        await q.edit_message_text("Нет доступа."); return
    ud["wait_ready_id"] = True
    await q.edit_message_text("Введите номер заказа (ORD-0001):", reply_markup=kb_cancel()); return

if data == "m_today":
    if not is_staff(uid):
        await q.edit_message_text("Нет доступа."); return
    orders  = get_active_orders()
    today   = today_str()
    torders = [o for o in orders if today in o.get("date","")]
    lines   = [f"📊 Сегодня {today}: {len(torders)} заказов\n"]
    for o in torders:
        lines.append(f"• {o['id']} | {o['car']} | {status_label(o['status'])}")
    await q.edit_message_text("\n".join(lines) or "Заказов сегодня нет.", reply_markup=kb_master()); return

# ВЛАДЕЛЕЦ
if data == "o_stats":
    if uid != OWNER_ID:
        await q.edit_message_text("Нет доступа."); return
    rows   = get_ws("Заказы").get_all_values()
    total  = len([r for r in rows[1:] if r and r[0]])
    active = len([r for r in rows[1:] if len(r)>5 and r[5] not in ("issued","")])
    issued = len([r for r in rows[1:] if len(r)>5 and r[5]=="issued"])
    await q.edit_message_text(
        f"📊 Статистика СТО {STO_NAME}\n\n"
        f"📋 Всего заказов: {total}\n🔧 Активных: {active}\n🚗 Выдано: {issued}",
        reply_markup=kb_owner()); return
```

def main():
app = Application.builder().token(TELEGRAM_TOKEN).build()
app.add_handler(CommandHandler(“start”, cmd_start))
app.add_handler(CommandHandler(“menu”,  lambda u,c: cmd_start(u,c)))
app.add_handler(CallbackQueryHandler(handle_cb))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
logger.info(f”СТО бот {STO_NAME} запущен!”)
app.run_polling(drop_pending_updates=True)

if **name** == “**main**”:
main()