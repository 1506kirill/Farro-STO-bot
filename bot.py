import os, re, json, logging
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional
import gspread
import anthropic
from google.oauth2.service_account import Credentials
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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

# 26 машин автопарку (короткi ID)
FLEET_CARS = {
    '0418': 'АЕ0418ОР', '2993': 'АЕ2993РI', '7935': 'AE7935PI',
    '3021': 'КА3021ЕО', '9489': 'КА9489ЕР', '7121': 'АЕ7121ТА',
    '8204': 'АЕ8204ТВ', '2548': 'AE2548TB', '9245': 'АЕ9245ТО',
    '0736': 'AE0736PK', '4715': 'AE4715TH', '6514': 'АЕ6514ТС',
    '4895': 'KA4895HE', '6843': 'KA6843HB', '5308': 'АЕ5308ТЕ',
    '1875': 'BI1875HO', '0665': 'KA0665IH', '0349': 'KA0349HO',
    '9854': 'BC9854PM', '8391': 'АЕ8391ТМ', '4553': 'AE4553XB',
    '8730': 'KA8730IX', '5725': 'AE5725OO', '6584': 'СА6584КА',
    '3531': 'AI3531PH', '1457': 'AI1457MM',
}

# Словник розпiзнавання назв авто з опечатками
CAR_NAMES = {
    # Toyota
    'камри':    'Toyota Camry',   'кемри':  'Toyota Camry',
    'камрi':    'Toyota Camry',   'camry':  'Toyota Camry',
    'прадо':    'Toyota Land Cruiser Prado',
    'прадiк':   'Toyota Land Cruiser Prado',
    'прадик':   'Toyota Land Cruiser Prado',
    'prado':    'Toyota Land Cruiser Prado',
    'rav4':     'Toyota RAV4',    'рав4':   'Toyota RAV4',
    'рав':      'Toyota RAV4',    'рафiк':  'Toyota RAV4',
    'крузак':   'Toyota Land Cruiser',
    'крузер':   'Toyota Land Cruiser',
    'хайлендер':'Toyota Highlander',
    'корола':   'Toyota Corolla', 'corolla':'Toyota Corolla',
    'авенсiс':  'Toyota Avensis',
    'версо':    'Toyota Verso',
    'ярис':     'Toyota Yaris',
    # Skoda
    'октавiя':  'Skoda Octavia',  'octavia':'Skoda Octavia',
    'октавия':  'Skoda Octavia',
    'суперб':   'Skoda Superb',   'superb': 'Skoda Superb',
    'рапiд':    'Skoda Rapid',    'rapid':  'Skoda Rapid',
    'кодiак':   'Skoda Kodiaq',   'kodiaq': 'Skoda Kodiaq',
    'карок':    'Skoda Karoq',    'karoq':  'Skoda Karoq',
    'фабiя':    'Skoda Fabia',    'fabia':  'Skoda Fabia',
    # Volkswagen
    'пассат':   'Volkswagen Passat',
    'тiгуан':   'Volkswagen Tiguan',
    'гольф':    'Volkswagen Golf',
    'джетта':   'Volkswagen Jetta',
    'поло':     'Volkswagen Polo',
    'туарег':   'Volkswagen Touareg',
    # BMW
    'бмв':      'BMW',            'bmw':    'BMW',
    'бумер':    'BMW',            'бумба':  'BMW',
    # Mercedes
    'мерс':     'Mercedes-Benz',  'мерседес':'Mercedes-Benz',
    'mercedes': 'Mercedes-Benz',
    'гелик':    'Mercedes-Benz G-Class',
    'гелiкоптер':'Mercedes-Benz G-Class',
    # Audi
    'аудi':     'Audi',           'audi':   'Audi',
    'ауди':     'Audi',
    # Hyundai
    'хундай':   'Hyundai',        'hyundai':'Hyundai',
    'хундаi':   'Hyundai',
    'туксон':   'Hyundai Tucson', 'tucson': 'Hyundai Tucson',
    'солярiс':  'Hyundai Solaris',
    'акцент':   'Hyundai Accent',
    'санта фе': 'Hyundai Santa Fe',
    # Kia
    'спортаж':  'Kia Sportage',   'sportage':'Kia Sportage',
    'сорento':  'Kia Sorento',    'sorento':'Kia Sorento',
    'сiд':      'Kia Ceed',       'сid':    'Kia Ceed',
    'рiо':      'Kia Rio',        'rio':    'Kia Rio',
    # Renault
    'дастер':   'Renault Duster', 'duster': 'Renault Duster',
    'логан':    'Renault Logan',  'logan':  'Renault Logan',
    'каптур':   'Renault Captur',
    'сандеро':  'Renault Sandero',
    'мегане':   'Renault Megane',
    # Ford
    'фокус':    'Ford Focus',     'focus':  'Ford Focus',
    'фьюжн':    'Ford Fusion',    'fusion': 'Ford Fusion',
    'куга':     'Ford Kuga',      'kuga':   'Ford Kuga',
    'мустанг':  'Ford Mustang',
    # Opel
    'астра':    'Opel Astra',     'astra':  'Opel Astra',
    'вектра':   'Opel Vectra',
    'зафiра':   'Opel Zafira',
    'iнсiгнiя': 'Opel Insignia',
    # Chevrolet
    'авео':     'Chevrolet Aveo', 'aveo':   'Chevrolet Aveo',
    'круз':     'Chevrolet Cruze','cruze':  'Chevrolet Cruze',
    'каптiва':  'Chevrolet Captiva',
    # Mitsubishi
    'аутлендер':'Mitsubishi Outlander',
    'паджеро':  'Mitsubishi Pajero',
    'лансер':   'Mitsubishi Lancer',
    # Nissan
    'кашкай':   'Nissan Qashqai', 'qashqai':'Nissan Qashqai',
    'кашкаi':   'Nissan Qashqai',
    'тiiда':    'Nissan Tiida',
    'альмера':  'Nissan Almera',
    'патфайндер':'Nissan Pathfinder',
    # Mazda
    'мазда':    'Mazda',          'mazda':  'Mazda',
    # Honda
    'хонда':    'Honda',          'honda':  'Honda',
    'цивiк':    'Honda Civic',    'civic':  'Honda Civic',
    'аккорд':   'Honda Accord',   'accord': 'Honda Accord',
    'crv':      'Honda CR-V',     'срв':    'Honda CR-V',
    # Lada / ВАЗ
    'жигулi':   'ВАЗ', 'жигули': 'ВАЗ',
    'нива':     'Lada Niva',
    'калiна':   'Lada Kalina',
    'гранта':   'Lada Granta',
    'веста':    'Lada Vesta',
    # Daewoo
    'ланос':    'Daewoo Lanos',   'lanos':  'Daewoo Lanos',
    'сенс':     'Daewoo Sens',
    'нексiя':   'Daewoo Nexia',
}


def normalize_car_name(text: str) -> str:
    t = text.lower().strip()
    # Спочатку точний збiг
    if t in CAR_NAMES:
        return CAR_NAMES[t]
    # Пошук по частинi слова
    for key, val in CAR_NAMES.items():
        if key in t or t in key:
            return val
    # Якщо це короткий ID автопарку
    digits = re.sub(r'[^0-9]', '', t)
    if digits in FLEET_CARS:
        return FLEET_CARS[digits]
    # Повертаємо як є з першою великою
    return text.strip().title()


def resolve_fleet_car(text: str) -> str:
    digits = re.sub(r'[^0-9]', '', text)
    if digits in FLEET_CARS:
        return FLEET_CARS[digits]
    return text.upper()


STO_INFO = {
    'sto': {
        'name':     'СТО Farro',
        'address':  'вул. Богдана Хмельницького 4а (лівий берег)',
        'maps':     'https://maps.app.goo.gl/yzXq7rwV2sB9SkRj9',
        'hours':    'ПН-ПТ 09:00-18:00',
        'services': ['ГБО','Розвал-сходження 3D','Автокондиціонери',
                     'Ремонт ходової','Зварювальні роботи','Двигуни','Пайка пластику','Інше'],
    },
    'body': {
        'name':     'Кузовний сервіс Farro',
        'address':  'вул. Павла Чубинського 2а',
        'maps':     'https://maps.app.goo.gl/xe7u4vD1tvSg6buy6',
        'hours':    'ПН-ПТ 09:00-18:00',
        'services': ['Рихтування авто','Покраска авто','Видалення вмятин без покраски (PDR)','Інше'],
    },
}

def get_routing(service):
    return list(set(STAFF_IDS))

def open_sheet():
    d = json.loads(GOOGLE_CREDS)
    scopes = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_info(d, scopes=scopes)
    return gspread.authorize(creds).open_by_key(SPREADSHEET_ID)

def get_ws(name):
    sp = open_sheet()
    for ws in sp.worksheets():
        if ws.title.lower() == name.lower():
            return ws
    return sp.sheet1

def now_str():
    return datetime.now(KYIV_TZ).strftime('%d.%m.%y %H:%M')

def today_str():
    return datetime.now(KYIV_TZ).strftime('%d.%m.%y')

def parse_num(v):
    s = re.sub(r'[^0-9]', '', str(v or ''))
    try: return int(s) if s else None
    except: return None

def is_staff(uid):
    return uid in STAFF_IDS

def polish_reply(raw):
    logger.info('polish_reply called. has_claude={}'.format(claude_client is not None))
    if not claude_client:
        return raw
    try:
        prompt = ('Ти ввiчливий менеджер автосервiсу Farro. '
                  'Майстер написав вiдповiдь клiєнту: ' + raw + '. '
                  'Перепиши украiнською мовою красиво, ввiчливо, зрозумiло, без помилок. '
                  'Збережи змiст. Тiльки готовий текст без пояснень.')
        resp = claude_client.messages.create(
            model='claude-sonnet-4-20250514',
            max_tokens=300,
            messages=[{'role': 'user', 'content': prompt}])
        result = resp.content[0].text.strip()
        logger.info('polish result: {}'.format(result[:80]))
        return result if result else raw
    except Exception as e:
        logger.error('polish_reply error: {}'.format(e))
        return raw

def get_client(tg_id):
    ws = get_ws('Клиенты')
    for row in ws.get_all_values()[1:]:
        if str(row[0]).strip() == str(tg_id):
            return {'tg_id':row[0],'name':row[1] if len(row)>1 else '',
                    'phone':row[2] if len(row)>2 else '',
                    'car':row[3] if len(row)>3 else '',
                    'model':row[4] if len(row)>4 else ''}
    return None

def save_client(tg_id, name, phone, car, model):
    ws   = get_ws('Клиенты')
    rows = ws.get_all_values()
    for i, row in enumerate(rows[1:], start=2):
        if str(row[0]).strip() == str(tg_id):
            ws.update('B{}:F{}'.format(i,i), [[name,phone,car.upper(),model,today_str()]])
            return
    ws.append_row([str(tg_id),name,phone,car.upper(),model,today_str()])

def find_client_by_car(car):
    ws = get_ws('Клиенты')
    cc = car.upper().replace(' ','')
    for row in ws.get_all_values()[1:]:
        if len(row)>3 and cc in str(row[3]).upper().replace(' ',''):
            return {'tg_id':row[0],'name':row[1],'car':row[3]}
    return None

def get_all_clients():
    ws = get_ws('Клиенты')
    result = []
    for row in ws.get_all_values()[1:]:
        if row and row[0]:
            result.append({'tg_id':row[0],'name':row[1] if len(row)>1 else '',
                           'car':row[3] if len(row)>3 else ''})
    return result

def gen_request_id():
    rows = get_ws('Заказы').get_all_values()
    num  = len([r for r in rows[1:] if r and r[0]]) + 1
    return 'REQ-{:04d}'.format(num)

def save_request(tg_id, client_name, car, sto_key, service, wish):
    rid = gen_request_id()
    get_ws('Заказы').append_row([rid,now_str(),str(tg_id),client_name,
                                  car,STO_INFO[sto_key]['name'],service,wish,'new',''])
    return rid

def get_requests_by_client(tg_id):
    result = []
    for row in get_ws('Заказы').get_all_values()[1:]:
        if len(row)>2 and str(row[2]).strip() == str(tg_id):
            result.append({'id':row[0],'date':row[1],'sto':row[5] if len(row)>5 else '',
                           'service':row[6] if len(row)>6 else '','status':row[8] if len(row)>8 else ''})
    return result[-5:]

def get_orders_by_car(car):
    cc = car.upper().replace(' ','')
    result = []
    for row in get_ws('Заказы').get_all_values()[1:]:
        if len(row)>4 and cc in str(row[4]).upper().replace(' ',''):
            result.append({'id':row[0],'date':row[1],'service':row[6] if len(row)>6 else '',
                           'status':row[8] if len(row)>8 else ''})
    return result[-5:]

def kb_welcome():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('Дiзнатися статус мого авто', callback_data='w_status')],
        [InlineKeyboardButton('Записатися на послугу',      callback_data='w_new')],
    ])

def kb_main_client():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('Статус мого авто',      callback_data='c_status')],
        [InlineKeyboardButton('Записатися на послугу', callback_data='w_new')],
        [InlineKeyboardButton('Мої заявки',            callback_data='c_requests')],
        [InlineKeyboardButton('Написати майстру',      callback_data='c_contact')],
    ])

def kb_choose_sto():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('СТО (ГБО, Ходова, Кондицiонери...)', callback_data='sto_sto')],
        [InlineKeyboardButton('Кузовний сервiс (Рихтування, Покраска, PDR)', callback_data='sto_body')],
    ])

def kb_services(sto_key):
    services = STO_INFO[sto_key]['services']
    buttons  = []
    for svc in services:
        buttons.append([InlineKeyboardButton(svc, callback_data='svc_{}_{}'.format(sto_key, svc[:30]))])
    return InlineKeyboardMarkup(buttons)

def kb_staff_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('Новi заявки',         callback_data='s_new')],
        [InlineKeyboardButton('Пiдтвердити запис',   callback_data='s_confirm')],
        [InlineKeyboardButton('Авто готове',         callback_data='s_ready')],
        [InlineKeyboardButton('Всi активнi',         callback_data='s_all')],
        [InlineKeyboardButton('Написати клiєнту',    callback_data='s_write_client')],
    ])

def kb_write_templates():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('Нагадування про масло',  callback_data='tpl_oil')],
        [InlineKeyboardButton('Авто готове',            callback_data='tpl_ready')],
        [InlineKeyboardButton('Уточнення по цiнi',      callback_data='tpl_price')],
        [InlineKeyboardButton('Додатковi роботи',       callback_data='tpl_extra')],
        [InlineKeyboardButton('Свiй текст',             callback_data='tpl_custom')],
        [InlineKeyboardButton('Скасувати',              callback_data='cancel')],
    ])

def kb_cancel():
    return InlineKeyboardMarkup([[InlineKeyboardButton('Скасувати', callback_data='cancel')]])

async def notify_staff(bot, service, message, client_id=None):
    kb = None
    if client_id:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(
            'Вiдповiсти клiєнту', callback_data='reply_{}'.format(client_id))]])
    for uid in get_routing(service):
        try: await bot.send_message(chat_id=uid, text=message, reply_markup=kb)
        except Exception as e: logger.error('notify_staff {}: {}'.format(uid, e))

async def send_to_client(bot, client_id, text):
    msg = 'Повiдомлення вiд СТО Farro:\n\n' + text
    await bot.send_message(chat_id=int(client_id), text=msg)

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    name = update.effective_user.first_name or 'Клiєнт'
    ctx.user_data.clear()
    if is_staff(uid):
        await update.message.reply_text(
            'Привiт, {}! ID: {}\nПанель управлiння СТО Farro'.format(name, uid),
            reply_markup=kb_staff_main())
        return
    client = get_client(uid)
    if client:
        await update.message.reply_text(
            'З поверненням, {}! Чим можу допомогти?'.format(client['name']),
            reply_markup=kb_main_client())
    else:
        await update.message.reply_text(
            'Вiтаємо в СТО Farro!\nВи вже здавали до нас авто?',
            reply_markup=kb_welcome())

async def handle_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    text = (update.message.text or '').strip()
    ud   = ctx.user_data

    # Реєстрацiя
    if ud.get('reg_step') == 'name':
        ud['reg_name'] = text; ud['reg_step'] = 'phone'
        await update.message.reply_text('Ваш номер телефону?'); return
    if ud.get('reg_step') == 'phone':
        ud['reg_phone'] = text; ud['reg_step'] = 'car'
        await update.message.reply_text('Номер вашого авто? (або - якщо немає)'); return
    if ud.get('reg_step') == 'car':
        car_val = resolve_fleet_car(text) if text != '-' else ''
        ud['reg_car'] = car_val; ud['reg_step'] = 'model'
        await update.message.reply_text('Марка i модель? (або -)'); return
    if ud.get('reg_step') == 'model':
        model = normalize_car_name(text) if text != '-' else ''
        save_client(uid, ud['reg_name'], ud['reg_phone'], ud.get('reg_car',''), model)
        name = ud['reg_name']; ud.clear()
        await update.message.reply_text('Дякуємо, {}! Зареєстрованi.'.format(name), reply_markup=kb_main_client()); return

    # Пошук авто для статусу
    if ud.get('wait_car_status'):
        ud.pop('wait_car_status')
        orders = get_orders_by_car(text)
        if not orders:
            await update.message.reply_text('Авто {} не знайдено.'.format(text.upper()), reply_markup=kb_main_client()); return
        icons = {'new':'Нова','confirmed':'Пiдтверджено','in_work':'В роботi','ready':'Готово','issued':'Видано'}
        lines = ['Статус авто {}:'.format(text.upper())]
        for o in reversed(orders):
            lines.append('{} | {} | {}'.format(o['date'], o['service'], icons.get(o['status'], o['status'])))
        await update.message.reply_text('\n'.join(lines), reply_markup=kb_main_client()); return

    # Побажання при записi
    if ud.get('wait_wish'):
        sto_key = ud.get('selected_sto')
        service = ud.get('selected_service')
        ud.pop('wait_wish', None)
        client  = get_client(uid)
        cname   = client['name'] if client else str(uid)
        car     = client['car']  if client else 'не вказано'
        rid     = save_request(uid, cname, car, sto_key, service, text)
        sto     = STO_INFO[sto_key]
        msg = ('НОВА ЗАЯВКА {}\n\nКлiєнт: {}\nАвто: {}\nСТО: {}\nАдреса: {}\n'
               'Послуга: {}\nПобажання: {}\nЧас: {}').format(
            rid, cname, car, sto['name'], sto['address'], service, text, now_str())
        await notify_staff(ctx.bot, service, msg, client_id=uid)
        await update.message.reply_text(
            'Заявку прийнято!\nНомер: {}\nПослуга: {}\n{}\n{}\n{}\n\nМайстер зв\'яжеться з вами найближчим часом.'.format(
                rid, service, sto['name'], sto['address'], sto['hours']),
            reply_markup=kb_main_client()); return

    # Повiдомлення вiд клiєнта майстру
    if ud.get('wait_client_msg'):
        ud.pop('wait_client_msg')
        client = get_client(uid)
        cname  = client['name'] if client else str(uid)
        car    = client['car']  if client else 'не вказано'
        fwd    = 'Повiдомлення вiд клiєнта:\n{} | {}\n\n{}'.format(cname, car, text)
        kb_r   = InlineKeyboardMarkup([[InlineKeyboardButton('Вiдповiсти клiєнту', callback_data='reply_{}'.format(uid))]])
        for mid in STAFF_IDS:
            try: await ctx.bot.send_message(chat_id=mid, text=fwd, reply_markup=kb_r)
            except Exception as e: logger.error('fwd: {}'.format(e))
        await update.message.reply_text('Повiдомлення надiслано майстру.', reply_markup=kb_main_client()); return

    # Вiдповiдь майстра клiєнту
    if ud.get('wait_reply_to'):
        client_id = ud.pop('wait_reply_to')
        await update.message.reply_text('Обробляю...')
        polished  = polish_reply(text)
        try:
            await send_to_client(ctx.bot, client_id, polished)
            await update.message.reply_text(
                'Надiслано клiєнту.\n\nВаш текст: ' + text + '\n\nНадiслано: ' + polished,
                reply_markup=kb_staff_main())
        except Exception as e:
            await update.message.reply_text('Помилка: {}'.format(e), reply_markup=kb_staff_main())
        return

    # Пiдтвердження запису
    if ud.get('wait_confirm_id'):
        rid = text.strip().upper(); ud.pop('wait_confirm_id')
        ws  = get_ws('Заказы')
        for i, row in enumerate(ws.get_all_values()[1:], start=2):
            if str(row[0]).strip() == rid:
                ws.update('I{}'.format(i), [['confirmed']])
                client_id = str(row[2]).strip() if len(row)>2 else None
                service   = row[6] if len(row)>6 else ''
                if client_id:
                    try:
                        await ctx.bot.send_message(chat_id=int(client_id),
                            text='Ваш запис пiдтверджено!\nЗаявка: {}\nПослуга: {}\nЧекаємо вас! СТО Farro'.format(rid, service))
                    except Exception as e: logger.error('confirm: {}'.format(e))
                await update.message.reply_text('Запис {} пiдтверджено.'.format(rid), reply_markup=kb_staff_main())
                return
        await update.message.reply_text('Заявку {} не знайдено.'.format(rid), reply_markup=kb_staff_main()); return

    # Свiй текст для клiєнта
    if ud.get('wait_custom_msg'):
        ud.pop('wait_custom_msg')
        client_id = ud.get('write_to_client_id')
        cname     = ud.get('write_to_name', '')
        await update.message.reply_text('Обробляю...')
        polished  = polish_reply(text)
        try:
            await send_to_client(ctx.bot, client_id, polished)
            await update.message.reply_text(
                'Надiслано клiєнту {}.\n\nВаш текст: '.format(cname) + text + '\n\nНадiслано: ' + polished,
                reply_markup=kb_staff_main())
        except Exception as e:
            await update.message.reply_text('Помилка: {}'.format(e), reply_markup=kb_staff_main())
        return

    kb = kb_staff_main() if is_staff(uid) else kb_main_client()
    await update.message.reply_text('Оберiть дiю:', reply_markup=kb)

async def handle_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    uid  = q.from_user.id
    data = q.data
    await q.answer()
    ud   = ctx.user_data

    if data == 'cancel':
        ud.clear()
        kb = kb_staff_main() if is_staff(uid) else kb_main_client()
        await q.edit_message_text('Скасовано.', reply_markup=kb); return

    if data == 'w_status':
        ud['wait_car_status'] = True
        await q.edit_message_text('Введiть номер вашого авто:', reply_markup=kb_cancel()); return

    if data == 'w_new':
        client = get_client(uid)
        if not client:
            ud['reg_step'] = 'name'
            await q.edit_message_text('Для запису потрiбна реєстрацiя.\nЯк вас звати?', reply_markup=kb_cancel())
        else:
            await q.edit_message_text('Оберiть СТО:', reply_markup=kb_choose_sto())
        return

    if data.startswith('sto_'):
        sto_key = data[4:]
        if sto_key not in STO_INFO: return
        ud['selected_sto'] = sto_key
        sto = STO_INFO[sto_key]
        await q.edit_message_text(
            '{}\n{}\n{}\nОберiть послугу:'.format(sto['name'], sto['address'], sto['hours']),
            reply_markup=kb_services(sto_key)); return

    if data.startswith('svc_'):
        parts   = data[4:].split('_', 1)
        sto_key = parts[0]
        service = parts[1] if len(parts)>1 else 'Iнше'
        for svc in STO_INFO.get(sto_key,{}).get('services',[]):
            if svc[:30] == service: service = svc; break
        ud['selected_sto']     = sto_key
        ud['selected_service'] = service
        ud['wait_wish']        = True
        await q.edit_message_text(
            'Послуга: {}\n\nОпишiть проблему i зручний час для запису:'.format(service),
            reply_markup=kb_cancel()); return

    if data == 'c_status':
        client = get_client(uid)
        if not client:
            await q.edit_message_text('Спочатку зареєструйтесь — /start'); return
        if not client['car']:
            ud['wait_car_status'] = True
            await q.edit_message_text('Введiть номер авто:', reply_markup=kb_cancel()); return
        orders = get_orders_by_car(client['car'])
        if not orders:
            await q.edit_message_text('Активних заявок немає.', reply_markup=kb_main_client()); return
        icons = {'new':'Нова','confirmed':'Пiдтверджено','in_work':'В роботi','ready':'Готово','issued':'Видано'}
        lines = ['Статус авто {}:'.format(client['car'])]
        for o in reversed(orders):
            lines.append('{} | {} | {}'.format(o['date'], o['service'], icons.get(o['status'], o['status'])))
        await q.edit_message_text('\n'.join(lines), reply_markup=kb_main_client()); return

    if data == 'c_requests':
        reqs = get_requests_by_client(uid)
        if not reqs:
            await q.edit_message_text('Заявок не знайдено.', reply_markup=kb_main_client()); return
        icons = {'new':'Нова','confirmed':'Пiдтверджено','in_work':'В роботi','ready':'Готово','issued':'Видано'}
        lines = ['Вашi останнi заявки:']
        for r in reversed(reqs):
            lines.append('{} | {} | {}'.format(r['date'], r['service'], icons.get(r['status'], r['status'])))
        await q.edit_message_text('\n'.join(lines), reply_markup=kb_main_client()); return

    if data == 'c_contact':
        ud['wait_client_msg'] = True
        await q.edit_message_text('Напишiть питання — майстер вiдповiсть найближчим часом:', reply_markup=kb_cancel()); return

    if data.startswith('reply_'):
        client_id = int(data[6:])
        ud['wait_reply_to'] = client_id
        await q.edit_message_text('Напишiть вiдповiдь клiєнту. Бот вiдправить її вiд iменi СТО Farro:', reply_markup=kb_cancel()); return

    # Панель мастера
    if not is_staff(uid):
        await q.edit_message_text('Немає доступу.'); return

    if data == 's_new':
        ws    = get_ws('Заказы')
        rows  = ws.get_all_values()
        new_r = [r for r in rows[1:] if len(r)>8 and r[8]=='new']
        if not new_r:
            await q.edit_message_text('Нових заявок немає.', reply_markup=kb_staff_main()); return
        lines = ['Новi заявки: {}'.format(len(new_r))]
        for r in new_r:
            lines.append('{} | {} | {} | {}'.format(r[0], r[3], r[6], r[1]))
        await q.edit_message_text('\n'.join(lines), reply_markup=kb_staff_main()); return

    if data == 's_confirm':
        ud['wait_confirm_id'] = True
        await q.edit_message_text('Введiть номер заявки (REQ-0001):', reply_markup=kb_cancel()); return

    if data == 's_ready':
        ws     = get_ws('Заказы')
        rows   = ws.get_all_values()
        active = [r for r in rows[1:] if len(r)>8 and r[8] not in ('issued','')]
        if not active:
            await q.edit_message_text('Активних заявок немає.', reply_markup=kb_staff_main()); return
        buttons = []
        for r in active[:10]:
            buttons.append([InlineKeyboardButton(
                '{} — {} | {}'.format(r[0], r[3], r[6]),
                callback_data='mark_ready_{}'.format(r[0]))])
        buttons.append([InlineKeyboardButton('Скасувати', callback_data='cancel')])
        await q.edit_message_text('Оберiть готову заявку:', reply_markup=InlineKeyboardMarkup(buttons)); return

    if data.startswith('mark_ready_'):
        rid  = data[11:]
        ws   = get_ws('Заказы')
        for i, row in enumerate(ws.get_all_values()[1:], start=2):
            if str(row[0]).strip() == rid:
                ws.update('I{}'.format(i), [['ready']])
                client_id = str(row[2]).strip() if len(row)>2 else None
                car       = row[4] if len(row)>4 else ''
                service   = row[6] if len(row)>6 else ''
                sto_name  = row[5] if len(row)>5 else ''
                if client_id:
                    try:
                        await ctx.bot.send_message(chat_id=int(client_id),
                            text='Ваш автомобiль готовий!\nАвто: {}\nПослуга: {}\n{}\nЧекаємо вас! СТО Farro'.format(car, service, sto_name))
                    except Exception as e: logger.error('ready: {}'.format(e))
                await q.edit_message_text('Заявка {} готова. Клiєнта повiдомлено.'.format(rid), reply_markup=kb_staff_main())
                return
        await q.edit_message_text('Заявку не знайдено.', reply_markup=kb_staff_main()); return

    if data == 's_all':
        ws     = get_ws('Заказы')
        rows   = ws.get_all_values()
        active = [r for r in rows[1:] if len(r)>8 and r[8] not in ('issued','')]
        if not active:
            await q.edit_message_text('Активних заявок немає.', reply_markup=kb_staff_main()); return
        icons = {'new':'Нова','confirmed':'Пiдтверджено','in_work':'В роботi','ready':'Готово'}
        lines = ['Всi активнi: {}'.format(len(active))]
        for r in active:
            lines.append('{} | {} | {} | {}'.format(icons.get(r[8],''), r[0], r[3], r[6]))
        await q.edit_message_text('\n'.join(lines), reply_markup=kb_staff_main()); return

    if data == 's_write_client':
        clients = get_all_clients()
        if not clients:
            await q.edit_message_text('Клiєнтiв не знайдено.', reply_markup=kb_staff_main()); return
        buttons = []
        for c in clients[:15]:
            label = '{} — {}'.format(c['name'], c['car']) if c['car'] else c['name']
            buttons.append([InlineKeyboardButton(label, callback_data='wc_{}'.format(c['tg_id']))])
        buttons.append([InlineKeyboardButton('Скасувати', callback_data='cancel')])
        await q.edit_message_text('Оберiть клiєнта:', reply_markup=InlineKeyboardMarkup(buttons)); return

    if data.startswith('wc_'):
        client_tg_id = data[3:]
        ud['write_to_client_id'] = int(client_tg_id)
        ws   = get_ws('Клиенты')
        rows = ws.get_all_values()
        cname = client_tg_id; car = ''
        for r in rows[1:]:
            if str(r[0]).strip() == client_tg_id:
                cname = r[1] if len(r)>1 else cname
                car   = r[3] if len(r)>3 else ''
                break
        ud['write_to_name'] = cname
        ud['write_to_car']  = car
        car_str = ' ({})'.format(car) if car else ''
        await q.edit_message_text('Клiєнт: {}{}. Оберiть тип:'.format(cname, car_str),
                                  reply_markup=kb_write_templates()); return

    if data.startswith('tpl_'):
        tpl    = data[4:]
        cname  = ud.get('write_to_name', '')
        car    = ud.get('write_to_car', '')
        car_s  = ' ({})'.format(car) if car else ''
        cid    = ud.get('write_to_client_id')

        if tpl == 'custom':
            ud['wait_custom_msg'] = True
            await q.edit_message_text('Напишiть повiдомлення клiєнту {}{}:'.format(cname, car_s),
                                      reply_markup=kb_cancel()); return

        texts = {
            'oil':   'Нагадуємо, що для вашого авто{} наближається термiн замiни моторного масла. Рекомендуємо записатися на ТО. Чекаємо вас у СТО Farro!'.format(car_s),
            'ready': 'Ваш автомобiль{} готовий до видачi! Всi роботи виконано. Чекаємо вас у СТО Farro.'.format(car_s),
            'price': 'Доброго дня! Хотiли уточнити деталi щодо вартостi робiт по вашому авто{}. Будь ласка, напишiть нам.'.format(car_s),
            'extra': 'Пiд час огляду вашого авто{} ми виявили додатковi роботи якi рекомендуємо виконати. Напишiть нам — розкажемо детальнiше.'.format(car_s),
        }

        if tpl in texts and cid:
            try:
                await send_to_client(ctx.bot, cid, texts[tpl])
                await q.edit_message_text('Надiслано клiєнту {}!'.format(cname), reply_markup=kb_staff_main())
            except Exception as e:
                await q.edit_message_text('Помилка: {}'.format(e), reply_markup=kb_staff_main())
        return

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler('start', cmd_start))
    app.add_handler(CommandHandler('menu',  cmd_start))
    app.add_handler(CallbackQueryHandler(handle_cb))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    logger.info('СТО бот {} запущен!'.format(STO_NAME))
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
