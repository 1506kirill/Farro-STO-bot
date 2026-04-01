import os, re, json, logging
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional
import gspread
import anthropic
from google.oauth2.service_account import Credentials
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    Application, MessageHandler, CommandHandler,
    CallbackQueryHandler, filters, ContextTypes,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

KYIV_TZ        = ZoneInfo('Europe/Kyiv')
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '')
SPREADSHEET_ID = os.environ.get('SPREADSHEET_ID', '')
GOOGLE_CREDS   = os.environ.get('GOOGLE_CREDS', '')
STO_NAME       = os.environ.get('STO_NAME', 'Farro')
OWNER_ID       = int(os.environ.get('OWNER_ID', '0'))
MASTER_IDS     = [int(x.strip()) for x in os.environ.get('MASTER_IDS','').split(',') if x.strip()]
CLAUDE_API_KEY = os.environ.get('CLAUDE_API_KEY')

STAFF_IDS     = list(set(MASTER_IDS + ([OWNER_ID] if OWNER_ID else [])))
claude_client = anthropic.Anthropic(api_key=CLAUDE_API_KEY) if CLAUDE_API_KEY else None

PHONES = '(067) 398-42-92\n(050) 857-20-10\n(073) 264-62-04'

CONTACTS = {
    'sto': {
        'name':    'СТО Farro',
        'address': 'вул. Богдана Хмельницького 4а (лiвий берег)',
        'note':    '',
        'maps':    'https://maps.app.goo.gl/yzXq7rwV2sB9SkRj9',
        'hours':   'ПН-ПТ 09:00-18:00',
    },
    'body': {
        'name':    'Кузовний сервiс Farro',
        'address': 'вул. Павла Чубинського 2а',
        'note':    '(верх вул. Робоча)',
        'maps':    'https://maps.app.goo.gl/xe7u4vD1tvSg6buy6',
        'hours':   'ПН-ПТ 09:00-18:00',
    },
}

PHOTO_BODY = '/app/photo_body.jpg'
PHOTO_STO  = '/app/photo_sto.jpg'

PHOTO_SERVICES = {
    'cond':   '/app/images/Cold.jpg',
    'exh':    '/app/images/Gofra.jpg',
    'susp':   '/app/images/hodovka.jpg',
    'gbo':    '/app/images/Montag.jpg',
    'engine': '/app/images/Motor.jpg',
    'paint':  '/app/images/Paint.jpg',
    'lights': '/app/images/Plastic.jpg',
    'riht':   '/app/images/Riht.jpg',
    'pdr':    '/app/images/PDR.png',
    'cool':   '/app/images/Pechka.png',
    'wheel':  '/app/images/Razval.png',
}

_photo_cache: Dict[str, str] = {}

SERVICES = {
    'sto': [
        {'id':'gbo',    'name':'⛽ ГБО — газове обладнання',
         'text':'Встановлення та обслуговування ГБО\n\nВстановлення ГБО на 4 цилiндри — вiд 19 600 грн\nВстановлення ГБО на 6 цилiндрiв — вiд 30 500 грн\nПланове ТО ГБО — вiд 650 грн\nКомп\'ютерна дiагностика — 400 грн\nСертифiкацiя ГБО — 3 000 грн\n\nНайбiльший склад ГБО в областi.\n\nhttps://farro.ua/install/'},
        {'id':'cond',   'name':'❄️ Автокондицiонери',
         'text':'Дiагностика та ремонт кондицiонерiв\n\nДiагностика та пiдключення — 400 грн\n1 гр фреону — 1,8 грн\n1 гр компресорного масла — 10 грн\n\nТакож:\nРемонт трубок кондицiонера\nПошук витоку фреону\nПромивка системи кондицiонування\n\nВажливо: точна кiлькiсть фреону визначається лише пiсля вiдкачування та зважування.\n\nhttps://farro.ua/kondicionery/'},
        {'id':'engine', 'name':'🛠 Двигуни',
         'text':'Дiагностика та ремонт двигунiв\n\nЗамiна моторного масла — 400 грн\nКомп\'ютерна дiагностика — 400 грн\nЗамiна ГРМ — вiд 3 500 грн\nРегулювання клапанiв — вiд 1 500 грн\nДiагностика ендоскопом — вiд 1 500 грн\nЗамiр компресiї — вiд 1 200 грн\n\nhttps://farro.ua/kondicionery/'},
        {'id':'wheel',  'name':'🎯 Розвал-сходження 3D',
         'text':'Точне регулювання кутiв встановлення колiс\n\nОдна вiсь — вiд 600 грн\nДвi осi — 1 000 грн\n\nhttps://farro.ua/razval-shozhdenie/'},
        {'id':'cool',   'name':'🌡 Промивка системи охолодження',
         'text':'Промивка та замiна антифризу\n\nЗамiна антифризу — вiд 600 грн\nПошук витоку антифризу — 700 грн\nПромивка радiатора пiчки — вiд 1 700 грн\nПромивка всiєї системи — вiд 4 000 грн\n\nhttps://farro.ua/promyvka-ohlazhdeniya/'},
        {'id':'lights', 'name':'💡 Ремонт фар та бамперiв',
         'text':'Ремонт та полiрування фар i бамперiв\n\nПолiрування фари — 1 500 грн\nПайка трiщини — 1 000 грн\nВiдновлення вуха фари — вiд 1 000 грн\n\nhttps://farro.ua/remont-far-i-bamperov/'},
        {'id':'susp',   'name':'🚙 Ремонт ходової',
         'text':'Дiагностика та ремонт ходової\n\nДiагностика — 300 грн\nЗамiна переднiх колодок — 600 грн\nЗамiна амортизатора або пружини — 1 200 грн\nЗамiна ступицi — 700 грн\nЗняття важеля — вiд 500 грн\nЗамiна сайлентблока — вiд 350 грн\nЗамiна шарової опори — вiд 350 грн\n\nhttps://farro.ua/remont-hodovoj/'},
        {'id':'exh',    'name':'💨 Вихлопнi системи',
         'text':'Ремонт системи вихлопу\n\nДiагностика — 200 грн\nЗамiна гофри — вiд 1 200 грн\n\nhttps://farro.ua/remont-vyhlopnoj/'},
        {'id':'diag',   'name':'🔎 Дiагностика перед купiвлею авто',
         'text':'Комплексна перевiрка авто перед покупкою\n\nДiагностика ходової — 300 грн\nДiагностика ЛКП — 700 грн\nДiагностика ендоскопом — вiд 1 500 грн\nДiагностика кондицiонера — 700 грн\nКомп\'ютерна дiагностика — 400 грн\nДiагностика ГБО — 400 грн'},
    ],
    'body': [
        {'id':'riht',  'name':'🔨 Рихтування авто',
         'text':'Вiдновлення геометрiї кузова\n\nЗамiна порога — вiд 3 000 грн\nЗамiна полотна даху — вiд 20 000 грн\nВитяжка лонжерона — вiд 10 000 грн\nРихтування порога — вiд 2 000 грн\nЗамiна лобового скла — 3 000 грн\n\nhttps://farro.ua/rihtovka-avto/'},
        {'id':'paint', 'name':'🎨 Покраска авто',
         'text':'Професiйне фарбування з пiдбором кольору\n\nПокраска однiєї деталi — 4 500 грн + матерiали\nПокраска деталi трьохшаровою фарбою — 6 000 грн + матерiали\nПовне перефарбування авто — вiд 70 000 грн + матерiали\n\nВажливо: вартiсть матерiалiв розраховує маляр пiсля огляду авто.\n\nhttps://farro.ua/pokraska-avto/'},
        {'id':'pdr',   'name':'Видалення вм\'ятин PDR',
         'text':'Видалення вм\'ятин без покраски\n\nНевелика вм\'ятина — вiд 600 грн\nСередня вм\'ятина — вiд 1 000 грн\nПошкодження вiд граду — вiд 3 000 грн\n\nPDR зберiгає оригiнальне лакофарбове покриття.\n\nhttps://farro.ua/rihtovka-avto/'},
    ],
}

FLEET_CARS = {
    '0418':'АЕ0418ОР','2993':'АЕ2993РI','7935':'AE7935PI','3021':'КА3021ЕО',
    '9489':'КА9489ЕР','7121':'АЕ7121ТА','8204':'АЕ8204ТВ','2548':'AE2548TB',
    '9245':'АЕ9245ТО','0736':'AE0736PK','4715':'AE4715TH','6514':'АЕ6514ТС',
    '4895':'KA4895HE','6843':'KA6843HB','5308':'АЕ5308ТЕ','1875':'BI1875HO',
    '0665':'KA0665IH','0349':'KA0349HO','9854':'BC9854PM','8391':'АЕ8391ТМ',
    '4553':'AE4553XB','8730':'KA8730IX','5725':'AE5725OO','6584':'СА6584КА',
    '3531':'AI3531PH','1457':'AI1457MM',
}

CAR_NAMES = {
    'камри':'Toyota Camry','кемрi':'Toyota Camry','прадо':'Toyota Land Cruiser Prado',
    'прадiк':'Toyota Land Cruiser Prado','рав4':'Toyota RAV4','крузак':'Toyota Land Cruiser',
    'октавiя':'Skoda Octavia','октавия':'Skoda Octavia','фабiя':'Skoda Fabia',
    'пассат':'Volkswagen Passat','тiгуан':'Volkswagen Tiguan','гольф':'Volkswagen Golf',
    'бмв':'BMW','бумер':'BMW','мерс':'Mercedes-Benz','гелик':'Mercedes-Benz G-Class',
    'аудi':'Audi','хундай':'Hyundai','туксон':'Hyundai Tucson','спортаж':'Kia Sportage',
    'дастер':'Renault Duster','фокус':'Ford Focus','кашкай':'Nissan Qashqai',
    'рог':'Nissan Rogue','лiф':'Nissan Leaf','мазда':'Mazda','хонда':'Honda',
    'форестер':'Subaru Forester','лексус':'Lexus','кайен':'Porsche Cayenne',
    'рейндж':'Range Rover','теслa':'Tesla','tesla':'Tesla','ланос':'Daewoo Lanos',
}

def normalize_car(text):
    if not text or text == '-': return ''
    t = text.lower().strip()
    if t in CAR_NAMES: return CAR_NAMES[t]
    for k, v in CAR_NAMES.items():
        if k in t: return v
    digits = re.sub(r'[^0-9]', '', t)
    if digits in FLEET_CARS: return FLEET_CARS[digits]
    return text.strip().title()


def normalize_ua_phone(text):
    raw = (text or '').strip()
    digits = re.sub(r'\D', '', raw)

    if digits.startswith('380') and len(digits) == 12:
        return '+' + digits

    if digits.startswith('0') and len(digits) == 10:
        return '+38' + digits

    return None

def is_menu_btn(text):
    t = text.lower()
    return any(k in t for k in ['послуги','контакт','моє авто','мое авто','написати','менеджер','записат'])

def open_sheet():
    d = json.loads(GOOGLE_CREDS)
    scopes = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
    return gspread.authorize(Credentials.from_service_account_info(d, scopes=scopes)).open_by_key(SPREADSHEET_ID)

def get_ws(name):
    sp = open_sheet()
    for ws in sp.worksheets():
        if ws.title.lower() == name.lower(): return ws
    return sp.sheet1

def now_str(): return datetime.now(KYIV_TZ).strftime('%d.%m.%y %H:%M')
def today_str(): return datetime.now(KYIV_TZ).strftime('%d.%m.%y')
def is_staff(uid): return uid in STAFF_IDS

def polish(raw):
    if not claude_client: return raw
    try:
        r = claude_client.messages.create(
            model='claude-haiku-4-5-20251001', max_tokens=200,
            messages=[{'role':'user','content':(
                'Менеджер автосервiсу Farro написав клiєнту: ' + raw +
                '. Перепиши однiєю вiдповiддю українською. Коротко, ввiчливо, без смайлiв.'
            )}])
        return r.content[0].text.strip() or raw
    except Exception as e:
        logger.error('polish: %s', e)
        return raw

def get_client(tg_id):
    for row in get_ws('Клиенты').get_all_values()[1:]:
        if str(row[0]).strip() == str(tg_id):
            return {'tg_id':row[0],'name':row[1] if len(row)>1 else '',
                    'phone':row[2] if len(row)>2 else '','car':row[3] if len(row)>3 else '',
                    'model':row[4] if len(row)>4 else '',
                    'ins_end':row[6] if len(row)>6 else '',
                    'oil_odo':row[7] if len(row)>7 else '','oil_date':row[8] if len(row)>8 else '',
                    'grm_odo':row[9] if len(row)>9 else '','grm_date':row[10] if len(row)>10 else ''}
    return None

def save_client(tg_id, data):
    ws  = get_ws('Клиенты')
    row = [str(tg_id), data.get('name',''), data.get('phone',''),
           data.get('car',''), data.get('model',''), today_str(),
           data.get('ins_end',''), data.get('oil_odo',''), data.get('oil_date',''),
           data.get('grm_odo',''), data.get('grm_date','')]
    rows = ws.get_all_values()
    for i, r in enumerate(rows[1:], start=2):
        if str(r[0]).strip() == str(tg_id):
            ws.update('A{}:K{}'.format(i,i), [row]); return
    ws.append_row(row)

def get_all_clients():
    return [{'tg_id':r[0],'name':r[1] if len(r)>1 else '','car':r[3] if len(r)>3 else ''}
            for r in get_ws('Клиенты').get_all_values()[1:] if r and r[0]]

def gen_rid():
    rows = get_ws('Заказы').get_all_values()
    return 'REQ-{:04d}'.format(len([r for r in rows[1:] if r and r[0]]) + 1)

def save_req(tg_id, name, phone, car, sto_key, service, wish):
    rid = gen_rid()
    get_ws('Заказы').append_row([rid,now_str(),str(tg_id),name,phone,car,
                                   CONTACTS[sto_key]['name'],service,wish,'new',''])
    return rid

def get_orders(tg_id):
    return [{'id':r[0],'date':r[1],'service':r[7] if len(r)>7 else '',
             'status':r[9] if len(r)>9 else ''}
            for r in get_ws('Заказы').get_all_values()[1:]
            if len(r)>2 and str(r[2]).strip()==str(tg_id)][-10:]

def status_lbl(s):
    return {'new':'Нова','confirmed':'Пiдтверджено','in_work':'В роботi',
            'ready':'Готово','issued':'Видано'}.get(s,s)

async def send_photo(bot, chat_id, path, caption='', reply_markup=None):
    if path in _photo_cache:
        await bot.send_photo(
            chat_id=chat_id,
            photo=_photo_cache[path],
            caption=caption,
            reply_markup=reply_markup
        )
        return
    try:
        with open(path,'rb') as f:
            msg = await bot.send_photo(
                chat_id=chat_id,
                photo=f,
                caption=caption,
                reply_markup=reply_markup
            )
        _photo_cache[path] = msg.photo[-1].file_id
    except Exception as e:
        logger.error('photo %s: %s', path, e)
        if caption:
            await bot.send_message(chat_id=chat_id, text=caption, reply_markup=reply_markup)

async def replace_or_send_text(q, ctx, text, reply_markup=None):
    try:
        if getattr(q.message, 'photo', None):
            try:
                await q.message.delete()
            except Exception:
                pass
            await ctx.bot.send_message(
                chat_id=q.message.chat_id,
                text=text,
                reply_markup=reply_markup
            )
        else:
            await q.edit_message_text(text, reply_markup=reply_markup)
    except Exception as e:
        logger.error('replace_or_send_text: %s', e)
        await ctx.bot.send_message(
            chat_id=q.message.chat_id,
            text=text,
            reply_markup=reply_markup
        )

async def to_client(bot, cid, text):
    await bot.send_message(chat_id=int(cid), text=text)

async def to_staff(bot, msg, client_id=None):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(
        '↩️ Вiдповiсти', callback_data='reply_{}'.format(client_id))]]) if client_id else None
    for uid in STAFF_IDS:
        try: await bot.send_message(chat_id=uid, text=msg, reply_markup=kb)
        except Exception as e: logger.error('staff %s: %s', uid, e)

def addr(sto_key):
    c = CONTACTS[sto_key]
    note = ' {}'.format(c['note']) if c.get('note') else ''
    return c['address'] + note

# ── Keyboards ────────────────────────────────────────────────

def kb_new():
    return ReplyKeyboardMarkup([
        ['🛠 Послуги та цiни', '📍 Контакти'],
        ['💬 Написати менеджеру'],
    ], resize_keyboard=True, is_persistent=True)

def kb_reg():
    return ReplyKeyboardMarkup([
        ['🛠 Послуги та цiни', '📍 Контакти'],
        ['🚗 Моє авто', '💬 Написати менеджеру'],
    ], resize_keyboard=True, is_persistent=True)

def kb_staff():
    return ReplyKeyboardMarkup([
        ['📥 Новi заявки', '📋 Всi активнi'],
        ['✅ Авто готове', '👥 Клiєнти'],
    ], resize_keyboard=True, is_persistent=True)

def ckb(uid): return kb_reg() if get_client(uid) else kb_new()

def kb_sto(prefix='menu'):
    c_b = CONTACTS['body']
    c_s = CONTACTS['sto']
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            '🚗 Кузовний сервiс ({})'.format(c_b['address']),
            callback_data='{}_body'.format(prefix))],
        [InlineKeyboardButton(
            '🔧 СТО ({})'.format(c_s['address']),
            callback_data='{}_sto'.format(prefix))],
    ])

def kb_write():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('🚗 Кузовний сервiс (Чубинського)', callback_data='write_body')],
        [InlineKeyboardButton('🔧 СТО (Хмельницького)',           callback_data='write_sto')],
    ])

def kb_svcs(sto_key):
    c = CONTACTS[sto_key]
    btns = [
        [InlineKeyboardButton('🧭 Навiгатор', url=c['maps'])],
    ]
    for svc in SERVICES[sto_key]:
        btns.append([InlineKeyboardButton(svc['name'], callback_data='svc_{}_{}'.format(sto_key, svc['id']))])
    btns.append([InlineKeyboardButton('💬 Написати менеджеру', callback_data='ask_{}'.format(sto_key))])
    return InlineKeyboardMarkup(btns)

def kb_svc_detail(sto_key):
    c = CONTACTS[sto_key]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('💬 Написати менеджеру', callback_data='ask_{}'.format(sto_key))],
        [InlineKeyboardButton('🧭 Навiгатор', url=c['maps'])],
        [InlineKeyboardButton('⬅️ Назад до списку', callback_data='menu_{}'.format(sto_key))],
    ])

def kb_contact_body():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('🧭 Навiгатор: Кузовний сервiс', url=CONTACTS['body']['maps'])],
    ])

def kb_contact_sto():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('🧭 Навiгатор: СТО', url=CONTACTS['sto']['maps'])],
    ])

def kb_skip():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('⏭ Пропустити', callback_data='skip')],
        [InlineKeyboardButton('✅ Завершити', callback_data='finish_mycar')],
    ])

def kb_mycar_update():
    return InlineKeyboardMarkup([[InlineKeyboardButton('🔄 Оновити данi авто', callback_data='start_mycar')]])

MYCAR_FIELDS  = ['name','phone','car','ins_end','oil_odo','oil_date','grm_odo','grm_date']
MYCAR_PROMPTS = {
    'name':     'Ваше iм\'я',
    'phone':    'Номер телефону',
    'car':      'Марка та модель авто',
    'ins_end':  'Дата закiнчення страховки (наприклад 31.12.26)',
    'oil_odo':  'Одометр при останнiй замiнi масла (км)',
    'oil_date': 'Дата останньої замiни масла',
    'grm_odo':  'Одометр при останнiй замiнi ГРМ (км)',
    'grm_date': 'Дата останньої замiни ГРМ',
}

REG_FIELDS  = ['phone','name','car']
REG_PROMPTS = {
    'phone': 'Ваш номер телефону (обов\'язково):',
    'name':  'Як вас звати? (необов\'язково)',
    'car':   'Марка та модель авто (необов\'язково)',
}

# ── Handlers ─────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    name = update.effective_user.first_name or 'Клiєнт'
    ctx.user_data.clear()
    if is_staff(uid):
        await update.message.reply_text('Привiт, {}! ID: {}'.format(name,uid), reply_markup=kb_staff()); return
    client = get_client(uid)
    if client and client.get('phone'):
        txt = 'З поверненням, {}!\n\nОберiть пункт меню або напишiть нам.'.format(client.get('name',''))
        await update.message.reply_text(txt, reply_markup=kb_reg())
    else:
        txt = ('Вiтаємо в Farro!\n\n'
               'Скористайтеся однiєю з кнопок нижче або натиснiть кнопку нижче, '
               'щоб написати менеджеру.')
        await update.message.reply_text(txt, reply_markup=kb_new())

async def handle_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    text = (update.message.text or '').strip()
    ud   = ctx.user_data
    tlo  = text.lower()

    # Якщо кнопка меню — скидаємо всi активнi процеси
    if is_menu_btn(text) and not is_staff(uid):
        if 'reg_step' in ud or 'mycar_step' in ud:
            ud.clear()

    # ── Реєстрацiя ────────────────────────────────────────────
    if ud.get('reg_step'):
        step = ud['reg_step']
        data = ud.setdefault('reg_data',{})

        if step == 'phone':
            if text in ('-','Пропустити'):
                await update.message.reply_text(
                    "Номер телефону пропустити не можна. Вiн потрiбен, щоб менеджер мiг з вами зв'язатися."
                ); return
            phone = normalize_ua_phone(text)
            if not phone:
                await update.message.reply_text(
                    "Будь ласка, введiть коректний український номер телефону у форматi +380XXXXXXXXX або 0XXXXXXXXX."
                ); return
            data[step] = phone
        else:
            if text not in ('-','Пропустити'):
                data[step] = normalize_car(text) if step=='car' else text

        idx = REG_FIELDS.index(step)
        if idx+1 < len(REG_FIELDS):
            nxt = REG_FIELDS[idx+1]
            ud['reg_step'] = nxt
            if nxt == 'phone':
                await update.message.reply_text(REG_PROMPTS[nxt]); return
            await update.message.reply_text(REG_PROMPTS[nxt], reply_markup=kb_skip()); return
        save_client(uid, data)
        sto_key = ud.get('reg_sto','sto')
        ud.clear(); ud['write_sto'] = sto_key
        await update.message.reply_text('Дякуємо! Тепер можете написати ваше повiдомлення.', reply_markup=ckb(uid)); return

    # ── Заповнення профiлю авто ────────────────────────────────
    if ud.get('mycar_step'):
        step = ud['mycar_step']
        data = ud.setdefault('mycar_data',{})
        if text not in ('-','Пропустити'):
            data[step] = normalize_car(text) if step=='car' else text
        idx = MYCAR_FIELDS.index(step)
        if idx+1 < len(MYCAR_FIELDS):
            nxt = MYCAR_FIELDS[idx+1]
            ud['mycar_step'] = nxt
            await update.message.reply_text('{} (необов\'язково):'.format(MYCAR_PROMPTS[nxt]),
                                            reply_markup=kb_skip()); return
        client = get_client(uid) or {}
        client.update({k:v for k,v in data.items() if v})
        save_client(uid, client)
        ud.clear()
        await update.message.reply_text('Данi збережено!', reply_markup=kb_reg()); return

    # ── Вiдповiдь менеджера клiєнту ───────────────────────────
    if ud.get('reply_to'):
        cid = ud.pop('reply_to')
        polished = polish(text)
        try: await to_client(ctx.bot, cid, polished)
        except Exception as e: logger.error('reply: %s', e)
        return

    # ── Менеджер: команди ─────────────────────────────────────
    if is_staff(uid):
        if 'новi' in tlo or 'заявки' in tlo:
            ws    = get_ws('Заказы')
            new_r = [r for r in ws.get_all_values()[1:] if len(r)>9 and r[9]=='new']
            if not new_r:
                await update.message.reply_text('Нових заявок немає.', reply_markup=kb_staff()); return
            lines = ['Новi заявки: {}'.format(len(new_r))]
            for r in new_r:
                lines.append('{} | {} | {} | {}'.format(r[0],r[3],r[7],r[1]))
            await update.message.reply_text('\n'.join(lines), reply_markup=kb_staff()); return

        if 'активн' in tlo or 'всi' in tlo:
            ws     = get_ws('Заказы')
            active = [r for r in ws.get_all_values()[1:] if len(r)>9 and r[9] not in ('issued','')]
            if not active:
                await update.message.reply_text('Активних немає.', reply_markup=kb_staff()); return
            lines = ['Активнi: {}'.format(len(active))]
            for r in active:
                lines.append('{} | {} | {}'.format(r[0],r[3],r[7]))
            await update.message.reply_text('\n'.join(lines), reply_markup=kb_staff()); return

        if 'готове' in tlo or 'готово' in tlo:
            ws     = get_ws('Заказы')
            active = [r for r in ws.get_all_values()[1:] if len(r)>9 and r[9] not in ('issued','')]
            if not active:
                await update.message.reply_text('Активних немає.', reply_markup=kb_staff()); return
            btns = [[InlineKeyboardButton(
                '{} — {}'.format(r[0],r[3]), callback_data='ready_{}'.format(r[0]))]
                for r in active[:10]]
            btns.append([InlineKeyboardButton('Скасувати', callback_data='cancel')])
            await update.message.reply_text('Оберiть:', reply_markup=InlineKeyboardMarkup(btns)); return

        if 'клiєнти' in tlo or 'клієнти' in tlo:
            clients = get_all_clients()
            if not clients:
                await update.message.reply_text('Клiєнтiв немає.', reply_markup=kb_staff()); return
            btns = [[InlineKeyboardButton(
                '{} {}'.format(c['name'],'({})'.format(c['car']) if c['car'] else '').strip(),
                callback_data='wc_{}'.format(c['tg_id']))] for c in clients[:15]]
            btns.append([InlineKeyboardButton('Скасувати', callback_data='cancel')])
            await update.message.reply_text('Оберiть клiєнта:', reply_markup=InlineKeyboardMarkup(btns)); return

        await update.message.reply_text('Оберiть дiю:', reply_markup=kb_staff()); return

    # ── Клiєнт: кнопки меню ───────────────────────────────────
    if 'послуги' in tlo or 'цiни' in tlo:
        await update.message.reply_text('Оберiть сервiс:', reply_markup=kb_sto()); return

    if 'контакт' in tlo:
        c_s = CONTACTS['sto']
        c_b = CONTACTS['body']

        await send_photo(
            ctx.bot,
            uid,
            PHOTO_BODY,
            caption='Кузовний сервiс Farro\n{} {}\nГрафiк: {}'.format(
                c_b['address'], c_b['note'], c_b['hours']
            ),
            reply_markup=kb_contact_body()
        )

        await send_photo(
            ctx.bot,
            uid,
            PHOTO_STO,
            caption='СТО Farro\n{}\nГрафiк: {}'.format(
                c_s['address'], c_s['hours']
            ),
            reply_markup=kb_contact_sto()
        )

        await update.message.reply_text('Телефони:\n{}'.format(PHONES))
        return

    if 'моє авто' in tlo or 'мое авто' in tlo:
        client = get_client(uid)
        if not client:
            await update.message.reply_text('Для доступу до цього роздiлу потрiбно зареєструватись.',
                                            reply_markup=kb_new()); return
        lines = ['Ваш автомобiль']
        if client.get('name'):     lines.append('Iм\'я: {}'.format(client['name']))
        if client.get('phone'):    lines.append('Тел.: {}'.format(client['phone']))
        if client.get('car'):      lines.append('Авто: {}'.format(client['car']))
        if client.get('ins_end'):  lines.append('Страховка до: {}'.format(client['ins_end']))
        if client.get('oil_odo'):  lines.append('Масло: {} км ({})'.format(client['oil_odo'],client.get('oil_date','')))
        if client.get('grm_odo'):  lines.append('ГРМ: {} км ({})'.format(client['grm_odo'],client.get('grm_date','')))
        orders = get_orders(uid)
        if orders:
            lines.append('\nIсторiя замовлень:')
            for o in reversed(orders):
                lines.append('{} | {} | {}'.format(o['date'],o['service'],status_lbl(o['status'])))
        await update.message.reply_text('\n'.join(lines), reply_markup=kb_mycar_update()); return

    if 'написати' in tlo or 'менеджер' in tlo:
        await update.message.reply_text('Оберiть сервiс:', reply_markup=kb_write()); return

    if 'записат' in tlo:
        await update.message.reply_text('Оберiть сервiс для запису:', reply_markup=kb_sto()); return

    # ── Будь-яке повiдомлення → до менеджера ──────────────────
    client = get_client(uid)
    if not client:
        await update.message.reply_text(
            'Щоб написати менеджеру, спочатку натиснiть кнопку "💬 Написати менеджеру" нижче.',
            reply_markup=kb_new()
        ); return
    cname  = client['name']  if client else 'Новий клiєнт'
    phone  = client['phone'] if client else 'не вказано'
    car    = client['car']   if client else 'не вказано'
    sto    = ud.get('write_sto','')
    sto_s  = ' [{}]'.format(CONTACTS[sto]['name']) if sto in CONTACTS else ''
    fwd    = 'Клiєнт пише{}:\n{} | {} | {}\n\n{}'.format(sto_s,cname,phone,car,text)
    await to_staff(ctx.bot, fwd, client_id=uid)

async def handle_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    uid  = q.from_user.id
    data = q.data
    await q.answer()
    ud   = ctx.user_data

    if data == 'cancel':
        ud.clear()
        await q.edit_message_text('Скасовано.'); return

    if data == 'skip':
        step = ud.get('mycar_step') or ud.get('reg_step')
        if ud.get('mycar_step') and step in MYCAR_FIELDS:
            idx = MYCAR_FIELDS.index(step)
            if idx+1 < len(MYCAR_FIELDS):
                nxt = MYCAR_FIELDS[idx+1]
                ud['mycar_step'] = nxt
                await q.message.reply_text('{} (необов\'язково):'.format(MYCAR_PROMPTS[nxt]),
                                           reply_markup=kb_skip()); return
            client = get_client(uid) or {}
            client.update({k:v for k,v in ud.get('mycar_data',{}).items() if v})
            save_client(uid, client)
            ud.clear()
            await q.message.reply_text('Данi збережено!', reply_markup=kb_reg()); return
        if ud.get('reg_step') and step in REG_FIELDS:
            if step == 'phone':
                await q.message.reply_text(
                    'Номер телефону пропустити не можна. Вiн потрiбен, щоб менеджер мiг з вами зв\'язатися.'
                ); return
            idx = REG_FIELDS.index(step)
            if idx+1 < len(REG_FIELDS):
                nxt = REG_FIELDS[idx+1]
                ud['reg_step'] = nxt
                if nxt == 'phone':
                    await q.message.reply_text(REG_PROMPTS[nxt]); return
                await q.message.reply_text(REG_PROMPTS[nxt], reply_markup=kb_skip()); return
            save_client(uid, ud.get('reg_data',{}))
            sto_key = ud.get('reg_sto','sto')
            ud.clear(); ud['write_sto'] = sto_key
            await q.message.reply_text('Дякуємо! Тепер можете написати ваше повiдомлення.', reply_markup=ckb(uid)); return
        return

    if data == 'finish_mycar':
        client = get_client(uid) or {}
        client.update({k:v for k,v in ud.get('mycar_data',{}).items() if v})
        save_client(uid, client)
        ud.clear()
        await q.message.reply_text('Данi збережено!', reply_markup=kb_reg()); return

    if data == 'start_mycar':
        ud['mycar_step'] = 'name'
        ud['mycar_data'] = {}
        await q.edit_message_text(
            'Заповнiть данi про ваш автомобiль.\nВсi поля необов\'язковi.\n\n'
            '{} (необов\'язково):'.format(MYCAR_PROMPTS['name']),
            reply_markup=kb_skip()); return

    if data.startswith('menu_'):
        sto_key = data[5:]
        if sto_key not in CONTACTS: return
        c = CONTACTS[sto_key]
        note = ' {}'.format(c['note']) if c.get('note') else ''
        msg = '{}\n\nАдреса: {}{}\nГрафiк: {}\nТел.:\n{}\n\nОберiть послугу:'.format(
            c['name'], c['address'], note, c['hours'], PHONES)
        await q.edit_message_text(msg, reply_markup=kb_svcs(sto_key)); return

    if data.startswith('svc_'):
        parts   = data[4:].split('_',1)
        sto_key = parts[0]
        svc_id  = parts[1] if len(parts)>1 else ''
        svc     = next((s for s in SERVICES[sto_key] if s['id']==svc_id), None)
        if not svc:
            await replace_or_send_text(q, ctx, 'Послугу не знайдено.'); return
        c    = CONTACTS[sto_key]
        note = ' {}'.format(c['note']) if c.get('note') else ''
        msg  = '{}\n\n{}\n\nАдреса: {}{}\nГрафiк: {}\nТел.:\n{}'.format(
            svc['name'], svc['text'], c['address'], note, c['hours'], PHONES)
        if len(msg)>1024: msg = msg[:1014]+'...'

        photo_path = PHOTO_SERVICES.get(svc_id)
        if photo_path:
            try:
                if getattr(q.message, 'photo', None) or getattr(q.message, 'text', None):
                    await q.message.delete()
            except Exception as e:
                logger.error('delete svc menu msg: %s', e)

            await send_photo(
                ctx.bot,
                q.message.chat_id,
                photo_path,
                caption=msg,
                reply_markup=kb_svc_detail(sto_key)
            )
        else:
            full_msg = '{}\n\n{}\n\nАдреса: {}{}\nГрафiк: {}\nТел.:\n{}'.format(
                svc['name'], svc['text'], c['address'], note, c['hours'], PHONES
            )
            if len(full_msg)>4000: full_msg = full_msg[:3990]+'...'
            await replace_or_send_text(q, ctx, full_msg, reply_markup=kb_svc_detail(sto_key))
        return

    if data.startswith('ask_'):
        sto_key = data[4:]
        ud['write_sto'] = sto_key
        c = CONTACTS.get(sto_key, CONTACTS['sto'])
        await replace_or_send_text(
            q, ctx,
            'Напишiть ваше питання — менеджер {} вiдповiсть.'.format(c['name'])
        ); return

    if data.startswith('write_'):
        sto_key = data[6:]
        ud['reg_sto']  = sto_key
        ud['reg_step'] = 'phone'
        ud['reg_data'] = {}
        await replace_or_send_text(
            q, ctx,
            'Щоб менеджер мiг вам вiдповiсти, спочатку вкажiть номер телефону:'
        ); return

    if data.startswith('reply_'):
        ud['reply_to'] = int(data[6:])
        await replace_or_send_text(q, ctx, ''); return

    if data.startswith('ready_'):
        rid  = data[6:]
        ws   = get_ws('Заказы')
        for i, row in enumerate(ws.get_all_values()[1:], start=2):
            if str(row[0]).strip() == rid:
                ws.update('J{}'.format(i),[['ready']])
                cid  = str(row[2]).strip() if len(row)>2 else None
                car  = row[5] if len(row)>5 else ''
                svc  = row[7] if len(row)>7 else ''
                name = row[6] if len(row)>6 else ''
                if cid:
                    try: await to_client(ctx.bot, cid,
                        'Ваш автомобiль готовий.\n\nАвто: {}\nПослуга: {}\n{}\n\nЧекаємо вас.'.format(car,svc,name))
                    except Exception as e: logger.error('ready: %s', e)
                await q.edit_message_text('Заявка {} — готова.'.format(rid)); return
        await q.edit_message_text('Не знайдено.'); return

    if data.startswith('wc_'):
        cid = data[3:]
        ws  = get_ws('Клиенты')
        cn = cid; car = ''
        for r in ws.get_all_values()[1:]:
            if str(r[0]).strip()==cid:
                cn = r[1] if len(r)>1 else cn
                car = r[3] if len(r)>3 else ''
                break
        ud['reply_to'] = int(cid)
        await q.edit_message_text('Клiєнт: {} {}. Напишiть повiдомлення:'.format(
            cn,'({})'.format(car) if car else '')); return

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler('start', cmd_start))
    app.add_handler(CommandHandler('menu',  cmd_start))
    app.add_handler(CommandHandler('help',  cmd_start))
    app.add_handler(CallbackQueryHandler(handle_cb))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    logger.info('v7 start | claude=%s | staff=%s', bool(claude_client), STAFF_IDS)
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
