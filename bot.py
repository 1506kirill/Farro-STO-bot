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

PHONES_TEXT = '(067) 398-42-92    (050) 857-20-10    (073) 264-62-04'

# Шляхи до фото фасадiв (завантажуються локально при деплої)
PHOTO_BODY_PATH = '/app/photo_body.jpg'
PHOTO_STO_PATH  = '/app/photo_sto.jpg'

# file_id кешуються пiсля першого завантаження
_photo_cache = {}

CONTACTS = {
    'sto': {
        'name':    'СТО Farro',
        'address': 'вул. Богдана Хмельницького 4а (лiвий берег)',
        'maps':    'https://maps.app.goo.gl/yzXq7rwV2sB9SkRj9',
        'hours':   'ПН-ПТ 09:00-18:00',
    },
    'body': {
        'name':    'Кузовний сервiс Farro',
        'address': 'вул. Павла Чубинського 2а',
        'maps':    'https://maps.app.goo.gl/xe7u4vD1tvSg6buy6',
        'hours':   'ПН-ПТ 09:00-18:00',
    },
}

SERVICES = {
    'sto': [
        {
            'id':   'gbo',
            'name': 'ГБО — газове обладнання',
            'text': (
                'Встановлення та обслуговування ГБО\n\n'
                'Встановлення ГБО на 4 цилiндри — вiд 19 600 грн\n'
                'Встановлення ГБО на 6 цилiндрiв — вiд 30 500 грн\n'
                'Планове ТО ГБО — вiд 650 грн\n'
                'Комп\'ютерна дiагностика — 400 грн\n'
                'Сертифiкацiя ГБО (вписання в техпаспорт) — 3 000 грн\n\n'
                'У нас завжди все в наявностi. Найбiльший склад ГБО в областi.\n\n'
                'Детальнiше: https://farro.ua/install/'
            ),
        },
        {
            'id':   'cond',
            'name': 'Автокондицiонери',
            'text': (
                'Дiагностика та заправка кондицiонерiв\n\n'
                'Пiдключення та дiагностика — 400 грн\n'
                '1 гр фреону — 1,8 грн\n'
                '1 гр компресорного масла — 10 грн\n\n'
                'Також виконуємо:\n'
                'Ремонт трубок кондицiонера\n'
                'Пошук та усунення витоку фреону\n'
                'Промивка системи кондицiонування\n\n'
                'Важливо: точна кiлькiсть фреону визначається лише пiсля '
                'вiдкачування та зважування — по телефону це неможливо розрахувати.\n\n'
                'Детальнiше: https://farro.ua/kondicionery/'
            ),
        },
        {
            'id':   'engine',
            'name': 'Двигуни',
            'text': (
                'Дiагностика та ремонт двигунiв\n\n'
                'Замiна моторного масла — 400 грн\n'
                'Комп\'ютерна дiагностика — 400 грн\n'
                'Замiна ГРМ — вiд 3 500 грн\n'
                'Регулювання зазорiв клапанiв — вiд 1 500 грн\n'
                'Дiагностика ендоскопом — вiд 1 500 грн\n'
                'Замiр компресiї в цилiндрах — вiд 1 200 грн\n\n'
                'Детальнiше: https://farro.ua/kondicionery/'
            ),
        },
        {
            'id':   'wheel',
            'name': 'Розвал-сходження 3D',
            'text': (
                'Точне регулювання кутiв колiс на 3D стендi\n\n'
                'Одна вiсь — вiд 600 грн\n'
                'Двi осi — 1 000 грн\n\n'
                'Детальнiше: https://farro.ua/razval-shozhdenie/'
            ),
        },
        {
            'id':   'cool',
            'name': 'Промивка системи охолодження',
            'text': (
                'Промивка та замiна антифризу\n\n'
                'Замiна антифризу — вiд 600 грн\n'
                'Пошук витоку антифризу — 700 грн\n'
                'Промивка радiатора пiчки — вiд 1 700 грн\n'
                'Промивка всiєї системи охолодження — вiд 4 000 грн\n\n'
                'Детальнiше: https://farro.ua/promyvka-ohlazhdeniya/'
            ),
        },
        {
            'id':   'lights',
            'name': 'Ремонт фар та бамперiв',
            'text': (
                'Полiрування та ремонт фар i бамперiв\n\n'
                'Полiрування однiєї фари — 1 500 грн\n'
                'Пайка середньої трiщини — 1 000 грн\n'
                'Вiдновлення вiдсутнього вуха фари — вiд 1 000 грн\n\n'
                'Детальнiше: https://farro.ua/remont-far-i-bamperov/'
            ),
        },
        {
            'id':   'suspension',
            'name': 'Ремонт ходової',
            'text': (
                'Дiагностика та ремонт ходової частини\n\n'
                'Дiагностика ходової — 300 грн\n'
                'Замiна переднiх колодок — 600 грн\n'
                'Замiна одного амортизатора або пружини — 1 200 грн\n'
                'Замiна ступицi — 700 грн\n'
                'Зняття одного важеля — вiд 500 грн\n'
                'Замiна одного сайлентблока — вiд 350 грн\n'
                'Замiна шарової опори — вiд 350 грн\n\n'
                'Детальнiше: https://farro.ua/remont-hodovoj/'
            ),
        },
        {
            'id':   'exhaust',
            'name': 'Вихлопнi системи',
            'text': (
                'Дiагностика та ремонт системи вихлопу\n\n'
                'Дiагностика вихлопної системи — 200 грн\n'
                'Замiна гофри — вiд 1 200 грн\n\n'
                'Детальнiше: https://farro.ua/remont-vyhlopnoj/'
            ),
        },
        {
            'id':   'diag',
            'name': 'Дiагностика перед купiвлею авто',
            'text': (
                'Комплексна перевiрка авто перед покупкою\n\n'
                'Дiагностика ходової — 300 грн\n'
                'Дiагностика ЛКП — 700 грн\n'
                'Дiагностика ендоскопом — вiд 1 500 грн\n'
                'Дiагностика кондицiонера — 700 грн\n'
                'Комп\'ютерна дiагностика — 400 грн\n'
                'Дiагностика ГБО — 400 грн'
            ),
        },
    ],
    'body': [
        {
            'id':   'riht',
            'name': 'Рихтування авто',
            'text': (
                'Вiдновлення геометрiї кузова\n\n'
                'Замiна порога — вiд 3 000 грн\n'
                'Замiна полотна даху — вiд 20 000 грн\n'
                'Витяжка лонжерона — вiд 10 000 грн\n'
                'Рихтування порога — вiд 2 000 грн\n'
                'Замiна лобового скла — 3 000 грн\n\n'
                'Детальнiше: https://farro.ua/rihtovka-avto/'
            ),
        },
        {
            'id':   'paint',
            'name': 'Покраска авто',
            'text': (
                'Професiйна покраска з пiдбором кольору\n\n'
                'Покраска однiєї деталi — 4 500 грн + матерiали\n'
                'Покраска однiєї деталi трьохшаровою фарбою — 6 000 грн + матерiали\n'
                'Повне перефарбування авто — вiд 70 000 грн + матерiали\n\n'
                'Важливо: кiлькiсть та вартiсть матерiалiв розраховує лише маляр '
                'пiсля огляду авто — по телефону визначити неможливо.\n\n'
                'Детальнiше: https://farro.ua/pokraska-avto/'
            ),
        },
        {
            'id':   'pdr',
            'name': 'Видалення вм\'ятин PDR',
            'text': (
                'Видалення вм\'ятин без покраски\n\n'
                'Невелика вм\'ятина — вiд 600 грн\n'
                'Середня вм\'ятина — вiд 1 000 грн\n'
                'Пошкодження вiд граду — вiд 3 000 грн\n\n'
                'PDR зберiгає оригiнальне лакофарбове покриття. '
                'Пiдходить для вм\'ятин без пошкодження фарби.\n\n'
                'Детальнiше: https://farro.ua/rihtovka-avto/'
            ),
        },
    ],
}

FLEET_CARS = {
    '0418':'АЕ0418ОР','2993':'АЕ2993РI','7935':'AE7935PI',
    '3021':'КА3021ЕО','9489':'КА9489ЕР','7121':'АЕ7121ТА',
    '8204':'АЕ8204ТВ','2548':'AE2548TB','9245':'АЕ9245ТО',
    '0736':'AE0736PK','4715':'AE4715TH','6514':'АЕ6514ТС',
    '4895':'KA4895HE','6843':'KA6843HB','5308':'АЕ5308ТЕ',
    '1875':'BI1875HO','0665':'KA0665IH','0349':'KA0349HO',
    '9854':'BC9854PM','8391':'АЕ8391ТМ','4553':'AE4553XB',
    '8730':'KA8730IX','5725':'AE5725OO','6584':'СА6584КА',
    '3531':'AI3531PH','1457':'AI1457MM',
}

CAR_NAMES = {
    'камри':'Toyota Camry','кемрi':'Toyota Camry','прадо':'Toyota Land Cruiser Prado',
    'прадiк':'Toyota Land Cruiser Prado','рав4':'Toyota RAV4','крузак':'Toyota Land Cruiser',
    'октавiя':'Skoda Octavia','октавия':'Skoda Octavia','фабiя':'Skoda Fabia',
    'пассат':'Volkswagen Passat','тiгуан':'Volkswagen Tiguan','гольф':'Volkswagen Golf',
    'бмв':'BMW','бумер':'BMW','мерс':'Mercedes-Benz','гелик':'Mercedes-Benz G-Class',
    'аудi':'Audi','хундай':'Hyundai','туксон':'Hyundai Tucson','спортаж':'Kia Sportage',
    'дастер':'Renault Duster','фокус':'Ford Focus','астра':'Opel Astra',
    'кашкай':'Nissan Qashqai','рог':'Nissan Rogue','джук':'Nissan Juke',
    'лiф':'Nissan Leaf','мазда':'Mazda','хонда':'Honda','форестер':'Subaru Forester',
    'лексус':'Lexus','кайен':'Porsche Cayenne','рейндж':'Range Rover',
    'вольво':'Volvo','теслa':'Tesla','tesla':'Tesla','ланос':'Daewoo Lanos',
    'сенс':'Daewoo Sens','нива':'Lada Niva','уаз':'UAZ',
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

def open_sheet():
    d = json.loads(GOOGLE_CREDS)
    scopes = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_info(d, scopes=scopes)
    return gspread.authorize(creds).open_by_key(SPREADSHEET_ID)

def get_ws(name):
    sp = open_sheet()
    for ws in sp.worksheets():
        if ws.title.lower() == name.lower(): return ws
    return sp.sheet1

def now_str(): return datetime.now(KYIV_TZ).strftime('%d.%m.%y %H:%M')
def today_str(): return datetime.now(KYIV_TZ).strftime('%d.%m.%y')
def is_staff(uid): return uid in STAFF_IDS

def polish_reply(raw):
    if not claude_client: return raw
    try:
        resp = claude_client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=200,
            messages=[{'role': 'user', 'content': (
                'Ти менеджер автосервiсу Farro. '
                'Майстер написав: ' + raw + '. '
                'Перепиши однiм варiантом украiнською мовою. '
                'Вiдповiдь коротка, ввiчлива, стримана, без смайлiв. '
                'Тiльки готовий текст.'
            )}])
        return resp.content[0].text.strip() or raw
    except Exception as e:
        logger.error('polish: %s', e)
        return raw

def get_client(tg_id):
    ws = get_ws('Клиенты')
    for row in ws.get_all_values()[1:]:
        if str(row[0]).strip() == str(tg_id):
            return {
                'tg_id':    row[0],
                'name':     row[1] if len(row)>1 else '',
                'phone':    row[2] if len(row)>2 else '',
                'car':      row[3] if len(row)>3 else '',
                'model':    row[4] if len(row)>4 else '',
                # F=5 - дата реєстрацiї (пропускаємо)
                'ins_end':  row[6] if len(row)>6 else '',
                'oil_odo':  row[7] if len(row)>7 else '',
                'oil_date': row[8] if len(row)>8 else '',
                'grm_odo':  row[9] if len(row)>9 else '',
                'grm_date': row[10] if len(row)>10 else '',
            }
    return None

def save_client(tg_id, data: dict):
    ws = get_ws('Клиенты')
    # A=tg_id, B=name, C=phone, D=car, E=model, F=reg_date,
    # G=ins_end, H=oil_odo, I=oil_date, J=grm_odo, K=grm_date
    row = [
        str(tg_id),
        data.get('name',''), data.get('phone',''),
        data.get('car',''), data.get('model',''),
        today_str(),  # F - дата реєстрацiї/оновлення
        data.get('ins_end',''), data.get('oil_odo',''), data.get('oil_date',''),
        data.get('grm_odo',''), data.get('grm_date',''),
    ]
    rows = ws.get_all_values()
    for i, r in enumerate(rows[1:], start=2):
        if str(r[0]).strip() == str(tg_id):
            ws.update('A{}:K{}'.format(i,i), [row])
            return
    ws.append_row(row)

def get_all_clients():
    ws = get_ws('Клиенты')
    return [{'tg_id':r[0],'name':r[1] if len(r)>1 else '','car':r[3] if len(r)>3 else ''}
            for r in ws.get_all_values()[1:] if r and r[0]]

def gen_request_id():
    rows = get_ws('Заказы').get_all_values()
    num  = len([r for r in rows[1:] if r and r[0]]) + 1
    return 'REQ-{:04d}'.format(num)

def save_request(tg_id, name, phone, car, sto_key, service, wish):
    rid = gen_request_id()
    get_ws('Заказы').append_row([
        rid, now_str(), str(tg_id), name, phone, car,
        CONTACTS[sto_key]['name'], service, wish, 'new', ''
    ])
    return rid

def get_orders_by_client(tg_id):
    result = []
    for row in get_ws('Заказы').get_all_values()[1:]:
        if len(row)>2 and str(row[2]).strip() == str(tg_id):
            result.append({
                'id': row[0], 'date': row[1],
                'service': row[7] if len(row)>7 else '',
                'status':  row[9] if len(row)>9 else '',
            })
    return result[-10:]

def status_icon(s):
    return {'new':'Нова','confirmed':'Пiдтверджено','in_work':'В роботi',
            'ready':'Готово','issued':'Видано'}.get(s, s)

# ── Клавiатури ────────────────────────────────────────────────

def kb_new_client():
    return ReplyKeyboardMarkup([
        ['Послуги та цiни', 'Контакти'],
        ['Написати менеджеру'],
    ], resize_keyboard=True, is_persistent=True)

def kb_registered_client():
    return ReplyKeyboardMarkup([
        ['Послуги та цiни', 'Контакти'],
        ['Моє авто', 'Написати менеджеру'],
    ], resize_keyboard=True, is_persistent=True)

def kb_staff():
    return ReplyKeyboardMarkup([
        ['Новi заявки', 'Всi активнi'],
        ['Авто готове', 'Клiєнти'],
    ], resize_keyboard=True)

def client_kb(uid):
    return kb_registered_client() if get_client(uid) else kb_new_client()

def kb_sto_choice(cb_prefix='menu'):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            'Кузовний сервiс (вул. Павла Чубинського 2а)',
            callback_data='{}_body'.format(cb_prefix))],
        [InlineKeyboardButton(
            'СТО (вул. Богдана Хмельницького 4а, лiвий берег)',
            callback_data='{}_sto'.format(cb_prefix))],
    ])

def kb_write_choice():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            'Кузовний сервiс (Чубинського)',
            callback_data='write_body')],
        [InlineKeyboardButton(
            'СТО (Хмельницького)',
            callback_data='write_sto')],
    ])

def kb_services(sto_key):
    btns = []
    for svc in SERVICES[sto_key]:
        btns.append([InlineKeyboardButton(svc['name'], callback_data='svc_{}_{}'.format(sto_key, svc['id']))])
    btns.append([InlineKeyboardButton('Написати менеджеру', callback_data='ask_manager_{}'.format(sto_key))])
    btns.append([InlineKeyboardButton('Назад', callback_data='back_services')])
    return InlineKeyboardMarkup(btns)

def kb_service_detail(sto_key, svc_id):
    c = CONTACTS[sto_key]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('Написати менеджеру', callback_data='ask_manager_{}'.format(sto_key))],
        [InlineKeyboardButton('Вiдкрити в навiгаторi', url=c['maps'])],
        [InlineKeyboardButton('Назад до списку', callback_data='menu_{}'.format(sto_key))],
    ])

def kb_contacts():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('Навiгатор: СТО (Хмельницького)', url=CONTACTS['sto']['maps'])],
        [InlineKeyboardButton('Навiгатор: Кузовний (Чубинського)', url=CONTACTS['body']['maps'])],
    ])

def kb_cancel():
    return InlineKeyboardMarkup([[InlineKeyboardButton('Скасувати', callback_data='cancel')]])

def kb_skip_or_cancel():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('Пропустити', callback_data='skip_field')],
        [InlineKeyboardButton('Скасувати', callback_data='cancel')],
    ])

def kb_reply_client(client_id):
    return InlineKeyboardMarkup([[InlineKeyboardButton(
        'Вiдповiсти клiєнту', callback_data='reply_{}'.format(client_id))]])

async def send_to_client(bot, client_id, text):
    await bot.send_message(chat_id=int(client_id), text=text)

async def send_photo_cached(bot, chat_id, path, caption=''):
    key = path
    if key in _photo_cache:
        await bot.send_photo(chat_id=chat_id, photo=_photo_cache[key], caption=caption)
        return
    try:
        with open(path, 'rb') as f:
            msg = await bot.send_photo(chat_id=chat_id, photo=f, caption=caption)
        _photo_cache[key] = msg.photo[-1].file_id
    except Exception as e:
        logger.error('send_photo %s: %s', path, e)

async def notify_staff(bot, message, client_id=None):
    kb = kb_reply_client(client_id) if client_id else None
    for uid in STAFF_IDS:
        try: await bot.send_message(chat_id=uid, text=message, reply_markup=kb)
        except Exception as e: logger.error('notify %s: %s', uid, e)

# ── Handlers ─────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    name = update.effective_user.first_name or 'Клiєнт'
    ctx.user_data.clear()

    if is_staff(uid):
        await update.message.reply_text(
            'Привiт, {}! ID: {}'.format(name, uid),
            reply_markup=kb_staff())
        return

    client = get_client(uid)
    if client and client['name']:
        text = ('З поверненням, {}!\n\n'
                'Оберiть пункт меню або просто напишiть нам.').format(client['name'])
        await update.message.reply_text(text, reply_markup=kb_registered_client())
    else:
        text = ('Вiтаємо в СТО Farro!\n\n'
                'Оберiть пункт меню нижче або напишiть ваше питання — '
                'менеджер вiдповiсть найближчим часом.')
        await update.message.reply_text(text, reply_markup=kb_new_client())

async def handle_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    text = (update.message.text or '').strip()
    ud   = ctx.user_data
    tlo  = text.lower()

    # ── Реєстрацiя через "Написати менеджеру" ─────────────────
    if ud.get('reg_step'):
        step = ud['reg_step']
        data = ud.setdefault('reg_data', {})

        if step == 'phone':
            if text != '-': data['phone'] = text
            ud['reg_step'] = 'name'
            await update.message.reply_text(
                'Як вас звати? (необов\'язково, можна пропустити)',
                reply_markup=kb_skip_or_cancel()); return

        if step == 'name':
            if text not in ('-', 'Пропустити'): data['name'] = text
            ud['reg_step'] = 'car'
            await update.message.reply_text(
                'Марка та модель вашого авто? (необов\'язково)',
                reply_markup=kb_skip_or_cancel()); return

        if step == 'car':
            if text not in ('-', 'Пропустити'): data['car'] = normalize_car(text)
            # Save client
            save_client(uid, data)
            sto_key = ud.get('reg_sto', 'sto')
            ud['reg_step'] = None
            ud['write_sto'] = sto_key
            c = CONTACTS[sto_key]
            msg = ('Дякуємо! Тепер просто напишiть ваше питання — '
                   'менеджер {} вiдповiсть найближчим часом.').format(c['name'])
            await update.message.reply_text(msg, reply_markup=client_kb(uid)); return

    # ── Заповнення профiлю авто (Моє авто) ────────────────────
    if ud.get('mycar_step'):
        step = ud['mycar_step']
        data = ud.setdefault('mycar_data', {})

        fields = ['name','phone','car','ins_end','oil_odo','oil_date','grm_odo','grm_date']
        prompts = {
            'name':     'Ваше iм\'я',
            'phone':    'Номер телефону',
            'car':      'Марка та модель авто',
            'ins_end':  'Дата закiнчення страховки (наприклад 31.12.26)',
            'oil_odo':  'Одометр при останнiй замiнi масла (км)',
            'oil_date': 'Дата останньої замiни масла (наприклад 15.03.26)',
            'grm_odo':  'Одометр при останнiй замiнi ГРМ (км)',
            'grm_date': 'Дата останньої замiни ГРМ (наприклад 10.01.25)',
        }

        if text not in ('-', 'Пропустити'):
            if step == 'car':
                data[step] = normalize_car(text)
            else:
                data[step] = text

        curr_idx = fields.index(step)
        if curr_idx + 1 < len(fields):
            next_field = fields[curr_idx + 1]
            ud['mycar_step'] = next_field
            await update.message.reply_text(
                '{} (необов\'язково):'.format(prompts[next_field]),
                reply_markup=kb_skip_or_cancel()); return
        else:
            # All done - merge with existing
            client = get_client(uid) or {}
            client.update({k:v for k,v in data.items() if v})
            save_client(uid, client)
            ud['mycar_step'] = None
            await update.message.reply_text(
                'Дякуємо! Данi збережено. Тепер у роздiлi "Моє авто" '
                'ви зможете вводити поточний одометр i система нагадає '
                'про замiну масла, ГРМ та страховку.',
                reply_markup=kb_registered_client()); return

    # ── Вiдповiдь менеджера клiєнту ───────────────────────────
    if ud.get('wait_reply_to'):
        client_id = ud.pop('wait_reply_to')
        polished  = polish_reply(text)
        try:
            await send_to_client(ctx.bot, client_id, polished)
        except Exception as e:
            logger.error('reply: %s', e)
        return

    # ── Reply keyboard — менеджер ─────────────────────────────
    if is_staff(uid):
        if 'новi' in tlo or 'заявки' in tlo:
            ws    = get_ws('Заказы')
            new_r = [r for r in ws.get_all_values()[1:] if len(r)>9 and r[9]=='new']
            if not new_r:
                await update.message.reply_text('Нових заявок немає.', reply_markup=kb_staff()); return
            lines = ['Новi заявки: {}'.format(len(new_r))]
            for r in new_r:
                lines.append('{} | {} | {} | {}'.format(r[0], r[3], r[7], r[1]))
            await update.message.reply_text('\n'.join(lines), reply_markup=kb_staff()); return

        if 'активн' in tlo or 'всi' in tlo:
            ws     = get_ws('Заказы')
            active = [r for r in ws.get_all_values()[1:] if len(r)>9 and r[9] not in ('issued','')]
            if not active:
                await update.message.reply_text('Активних заявок немає.', reply_markup=kb_staff()); return
            lines = ['Активнi: {}'.format(len(active))]
            for r in active:
                lines.append('{} | {} | {}'.format(r[0], r[3], r[7]))
            await update.message.reply_text('\n'.join(lines), reply_markup=kb_staff()); return

        if 'готове' in tlo or 'готово' in tlo:
            ws     = get_ws('Заказы')
            active = [r for r in ws.get_all_values()[1:] if len(r)>9 and r[9] not in ('issued','')]
            if not active:
                await update.message.reply_text('Активних заявок немає.', reply_markup=kb_staff()); return
            btns = []
            for r in active[:10]:
                btns.append([InlineKeyboardButton(
                    '{} — {} | {}'.format(r[0], r[3], r[7]),
                    callback_data='mark_ready_{}'.format(r[0]))])
            btns.append([InlineKeyboardButton('Скасувати', callback_data='cancel')])
            await update.message.reply_text('Оберiть готову заявку:', reply_markup=InlineKeyboardMarkup(btns)); return

        if 'клiєнти' in tlo or 'клієнти' in tlo:
            clients = get_all_clients()
            if not clients:
                await update.message.reply_text('Клiєнтiв немає.', reply_markup=kb_staff()); return
            btns = []
            for c in clients[:15]:
                label = '{} {}'.format(c['name'], '({})'.format(c['car']) if c['car'] else '')
                btns.append([InlineKeyboardButton(label.strip(), callback_data='wc_{}'.format(c['tg_id']))])
            btns.append([InlineKeyboardButton('Скасувати', callback_data='cancel')])
            await update.message.reply_text('Оберiть клiєнта:', reply_markup=InlineKeyboardMarkup(btns)); return

        await update.message.reply_text('Оберiть дiю:', reply_markup=kb_staff()); return

    # ── Reply keyboard — клiєнт ───────────────────────────────
    if 'послуги' in tlo or 'цiни' in tlo or 'цены' in tlo:
        ud.clear()
        await update.message.reply_text('Оберiть сервiс:', reply_markup=kb_sto_choice()); return

    if 'контакт' in tlo:
        c_sto  = CONTACTS['sto']
        client = get_client(uid)
        if not client:
            await update.message.reply_text(
                'Спочатку потрiбно зареєструватись. Напишiть нам або запишiться на послугу.',
                reply_markup=kb_new_client()); return

        lines = ['Ваш автомобiль']
        if client.get('name'):  lines.append('Iм\'я: {}'.format(client['name']))
        if client.get('phone'): lines.append('Тел.: {}'.format(client['phone']))
        if client.get('car'):   lines.append('Авто: {}'.format(client['car']))
        if client.get('ins_end'): lines.append('Страховка до: {}'.format(client['ins_end']))
        if client.get('oil_odo'): lines.append('Замiна масла: {} км ({})'.format(client['oil_odo'], client.get('oil_date','')))
        if client.get('grm_odo'): lines.append('Замiна ГРМ: {} км ({})'.format(client['grm_odo'], client.get('grm_date','')))

        orders = get_orders_by_client(uid)
        if orders:
            lines.append('\nIсторiя замовлень:')
            for o in reversed(orders):
                lines.append('{} | {} | {}'.format(o['date'], o['service'], status_icon(o['status'])))

        lines.append('\nОновити данi авто?')
        btns = InlineKeyboardMarkup([
            [InlineKeyboardButton('Оновити данi', callback_data='update_mycar')],
        ])
        await update.message.reply_text('\n'.join(lines), reply_markup=btns); return

    if 'написати' in tlo or 'менеджер' in tlo:
        ud.clear()
        await update.message.reply_text(
            'Оберiть, до якого сервiсу звертаєтесь:',
            reply_markup=kb_write_choice()); return

    if 'записат' in tlo:
        await update.message.reply_text('Оберiть сервiс для запису:', reply_markup=kb_sto_choice('menu')); return

    # ── Будь-яке iнше повiдомлення вiд клiєнта ───────────────
    client = get_client(uid)
    cname  = client['name'] if client else 'Новий клiєнт'
    phone  = client['phone'] if client else 'не вказано'
    car    = client['car']   if client else 'не вказано'
    sto    = ud.get('write_sto', 'обидва СТО')
    fwd    = 'Клiєнт пише ({}):\n{} | {} | {}\n\n{}'.format(sto, cname, phone, car, text)
    ctx.bot_data['last_client_{}'.format(uid)] = uid
    await notify_staff(ctx.bot, fwd, client_id=uid)
    # Показуємо меню клiєнту якщо його ще немає
    kb = client_kb(uid)
    await update.message.reply_text(
        'Менеджер вiдповiсть найближчим часом.',
        reply_markup=kb)

async def handle_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    uid  = q.from_user.id
    data = q.data
    await q.answer()
    ud   = ctx.user_data

    if data == 'cancel':
        ud.clear()
        await q.edit_message_text('Скасовано.'); return

    if data == 'skip_field':
        # Simulate empty input for current step
        update.callback_query.message.text = '-'
        fake = type('FakeUpdate', (), {
            'effective_user': update.effective_user,
            'message': type('Msg', (), {
                'text': '-', 'reply_text': update.callback_query.message.reply_text
            })()
        })()
        # Just advance step
        step = ud.get('reg_step') or ud.get('mycar_step')
        if ud.get('reg_step'):
            fields = ['phone','name','car']
            idx = fields.index(step) if step in fields else -1
        else:
            fields = ['name','phone','car','ins_end','oil_odo','oil_date','grm_odo','grm_date']
            idx = fields.index(step) if step in fields else -1

        if idx >= 0 and idx+1 < len(fields):
            next_f = fields[idx+1]
            if ud.get('reg_step'): ud['reg_step'] = next_f
            else: ud['mycar_step'] = next_f
            prompts = {
                'name':'Iм\'я','phone':'Номер телефону','car':'Марка та модель авто',
                'ins_end':'Дата страховки','oil_odo':'Одометр замiни масла',
                'oil_date':'Дата замiни масла','grm_odo':'Одометр замiни ГРМ',
                'grm_date':'Дата замiни ГРМ',
            }
            await q.message.reply_text(
                '{} (необов\'язково):'.format(prompts.get(next_f, next_f)),
                reply_markup=kb_skip_or_cancel())
        elif ud.get('reg_step'):
            save_client(uid, ud.get('reg_data',{}))
            sto_key = ud.get('reg_sto','sto')
            ud.clear()
            ud['write_sto'] = sto_key
            await q.message.reply_text(
                'Дякуємо! Напишiть ваше питання.',
                reply_markup=client_kb(uid))
        else:
            client = get_client(uid) or {}
            client.update({k:v for k,v in ud.get('mycar_data',{}).items() if v})
            save_client(uid, client)
            ud.clear()
            await q.message.reply_text('Данi збережено.', reply_markup=kb_registered_client())
        return

    if data == 'back_services':
        await q.edit_message_text('Оберiть сервiс:', reply_markup=kb_sto_choice()); return

    if data == 'update_mycar':
        ud['mycar_step'] = 'name'
        ud['mycar_data'] = {}
        await q.edit_message_text(
            'Заповнiть данi про ваш автомобiль.\n'
            'Всi поля необов\'язковi — можна пропустити.\n\n'
            'Iм\'я:',
            reply_markup=kb_skip_or_cancel()); return

    # Меню СТО
    if data.startswith('menu_'):
        sto_key = data[5:]
        if sto_key not in CONTACTS: return
        c = CONTACTS[sto_key]
        msg = ('{}\n\n'
               'Адреса: {}\n'
               'Графiк: {}\n'
               'Тел.: {}\n\n'
               'Оберiть послугу:').format(c['name'], c['address'], c['hours'], PHONES_TEXT)
        await q.edit_message_text(msg, reply_markup=kb_services(sto_key)); return

    # Деталi послуги
    if data.startswith('svc_'):
        parts   = data[4:].split('_', 1)
        sto_key = parts[0]
        svc_id  = parts[1] if len(parts)>1 else ''
        svc     = next((s for s in SERVICES[sto_key] if s['id']==svc_id), None)
        if not svc:
            await q.edit_message_text('Послугу не знайдено.'); return
        c   = CONTACTS[sto_key]
        msg = ('{}\n\n{}\n\n'
               'Адреса: {}\n'
               'Графiк: {}\n'
               'Тел.: {}').format(svc['name'], svc['text'], c['address'], c['hours'], PHONES_TEXT)
        # Telegram limit 4096
        if len(msg) > 4000:
            msg = msg[:3990] + '...'
        await q.edit_message_text(msg, reply_markup=kb_service_detail(sto_key, svc_id)); return

    # Запис на послугу
    if data.startswith('book_'):
        parts   = data[5:].split('_', 1)
        sto_key = parts[0]
        svc_id  = parts[1] if len(parts)>1 else ''
        svc     = next((s for s in SERVICES[sto_key] if s['id']==svc_id), None)
        svc_name= svc['name'] if svc else svc_id
        client  = get_client(uid)
        name    = client['name']  if client else ''
        phone   = client['phone'] if client else ''
        car     = client['car']   if client else ''
        rid     = save_request(uid, name, phone, car, sto_key, svc_name, 'запис через бота')
        c       = CONTACTS[sto_key]
        msg = ('{}\nКлiєнт: {} | {} | {}\nПослуга: {}\n{}').format(
            rid, name or str(uid), phone or 'тел. не вказано',
            car or 'авто не вказано', svc_name, now_str())
        await notify_staff(ctx.bot, 'НОВА ЗАЯВКА\n\n' + msg, client_id=uid)
        await q.edit_message_text(
            'Заявку прийнято!\nНомер: {}\nПослуга: {}\n{}\n{}\n\n'
            'Менеджер зв\'яжеться з вами найближчим часом.'.format(
                rid, svc_name, c['address'], c['hours'])); return

    # Запитати менеджера з послуги
    if data.startswith('ask_manager_'):
        sto_key = data[12:]
        ud['write_sto'] = sto_key
        c = CONTACTS.get(sto_key, CONTACTS['sto'])
        await q.edit_message_text(
            'Напишiть ваше питання — менеджер {} вiдповiсть найближчим часом.'.format(c['name'])); return

    # Написати менеджеру (вибiр СТО)
    if data.startswith('write_'):
        sto_key = data[6:]
        client  = get_client(uid)
        if not client or not client.get('phone'):
            ud['reg_sto']  = sto_key
            ud['reg_step'] = 'phone'
            ud['reg_data'] = {}
            await q.edit_message_text(
                'Будь ласка, вкажiть ваш номер телефону, '
                'щоб менеджер мiг з вами зв\'язатись:',
                reply_markup=kb_cancel()); return
        ud['write_sto'] = sto_key
        c = CONTACTS[sto_key]
        await q.edit_message_text(
            'Напишiть ваше питання — менеджер {} вiдповiсть найближчим часом.'.format(c['name'])); return

    # Вiдповiдь клiєнту
    if data.startswith('reply_'):
        client_id = int(data[6:])
        ud['wait_reply_to'] = client_id
        await q.edit_message_text(''); return

    # Позначити авто готовим
    if data.startswith('mark_ready_'):
        rid  = data[11:]
        ws   = get_ws('Заказы')
        for i, row in enumerate(ws.get_all_values()[1:], start=2):
            if str(row[0]).strip() == rid:
                ws.update('J{}'.format(i), [['ready']])
                cid      = str(row[2]).strip() if len(row)>2 else None
                car      = row[5] if len(row)>5 else ''
                service  = row[7] if len(row)>7 else ''
                sto_name = row[6] if len(row)>6 else ''
                if cid:
                    try:
                        await ctx.bot.send_message(
                            chat_id=int(cid),
                            text='Ваш автомобiль готовий до видачi.\n\nАвто: {}\nПослуга: {}\n{}\n\nЧекаємо вас.'.format(
                                car, service, sto_name))
                    except Exception as e: logger.error('ready: %s', e)
                await q.edit_message_text('Заявка {} — готова. Клiєнта повiдомлено.'.format(rid)); return
        await q.edit_message_text('Заявку не знайдено.'); return

    # Вибiр клiєнта для написання
    if data.startswith('wc_'):
        cid = data[3:]
        ws  = get_ws('Клиенты')
        cname = cid; car = ''
        for r in ws.get_all_values()[1:]:
            if str(r[0]).strip() == cid:
                cname = r[1] if len(r)>1 else cname
                car   = r[3] if len(r)>3 else ''
                break
        ud['wait_reply_to'] = int(cid)
        car_s = ' ({})'.format(car) if car else ''
        await q.edit_message_text('Клiєнт: {}{}. Напишiть повiдомлення:'.format(cname, car_s)); return

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler('start', cmd_start))
    app.add_handler(CommandHandler('menu',  cmd_start))
    app.add_handler(CommandHandler('help',  cmd_start))
    app.add_handler(CallbackQueryHandler(handle_cb))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    logger.info('СТО бот v6 запущен! CLAUDE=%s STAFF=%s', bool(claude_client), STAFF_IDS)
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
