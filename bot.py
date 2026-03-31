import os, re, json, logging
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional
import gspread
import anthropic
from google.oauth2.service_account import Credentials
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
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

# Контакти СТО
PHONES = [
    ('(067) 398-42-92', '+380673984292'),
    ('(050) 857-20-10', '+380508572010'),
    ('(073) 264-62-04', '+380732646204'),
]

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

# Послуги з детальним описом
SERVICES = {
    'sto': [
        {
            'id':    'gbo',
            'name':  'ГБО (газове обладнання)',
            'icon':  '',
            'desc':  ('Встановлення та обслуговування газобалонного обладнання (ГБО).\n\n'
                      'Що входить:\n'
                      'Встановлення ГБО 4-го та 5-го поколiння\n'
                      'Налаштування та калiбрування\n'
                      'Технiчне обслуговування системи\n'
                      'Замiна фiльтрiв та редуктора\n\n'
                      'Орiєнтовна вартiсть:\n'
                      'Встановлення ГБО 4-го поколiння — вiд 8 000 грн\n'
                      'Встановлення ГБО 5-го поколiння — вiд 12 000 грн\n'
                      'ТО системи ГБО — вiд 800 грн\n\n'
                      'Детальнiше: https://farro.ua/install/'),
        },
        {
            'id':    'cond',
            'name':  'Автокондицiонери',
            'icon':  '',
            'desc':  ('Дiагностика, заправка та ремонт системи кондицiонування.\n\n'
                      'Що входить:\n'
                      'Дiагностика системи кондицiонування\n'
                      'Заправка фреоном\n'
                      'Замiна компресора, конденсатора, радiатора\n'
                      'Замiна салонного фiльтра\n'
                      'Антибактерiальна обробка\n\n'
                      'Орiєнтовна вартiсть:\n'
                      'Дiагностика — вiд 200 грн\n'
                      'Заправка фреоном — вiд 500 грн\n'
                      'Ремонт — вiд 800 грн\n\n'
                      'Детальнiше: https://farro.ua/kondicionery/'),
        },
        {
            'id':    'engine',
            'name':  'Двигуни',
            'icon':  '',
            'desc':  ('Дiагностика та ремонт двигунiв будь-якої складностi.\n\n'
                      'Що входить:\n'
                      'Комп\'ютерна дiагностика\n'
                      'Замiна масла та фiльтрiв\n'
                      'Ремонт ГРМ\n'
                      'Капiтальний ремонт двигуна\n'
                      'Промивка системи охолодження\n\n'
                      'Орiєнтовна вартiсть:\n'
                      'Дiагностика — вiд 300 грн\n'
                      'Замiна масла — вiд 300 грн\n'
                      'Ремонт ГРМ — вiд 1 500 грн\n\n'
                      'Детальнiше: https://farro.ua/kondicionery/'),
        },
        {
            'id':    'wheel',
            'name':  'Розвал-сходження 3D',
            'icon':  '',
            'desc':  ('Точне регулювання кутiв встановлення колiс на 3D стендi.\n\n'
                      'Що входить:\n'
                      'Перевiрка та регулювання кутiв коренебальних коренiв\n'
                      'Перевiрка рульового керування\n'
                      'Дiагностика пiдвiски\n\n'
                      'Орiєнтовна вартiсть:\n'
                      'Розвал-сходження 3D — 800 грн\n'
                      'З урахуванням регулювання — вiд 1 000 грн\n\n'
                      'Детальнiше: https://farro.ua/razval-shozhdenie/'),
        },
        {
            'id':    'cool',
            'name':  'Промивка системи охолодження',
            'icon':  '',
            'desc':  ('Промивка та замiна антифризу системи охолодження двигуна.\n\n'
                      'Що входить:\n'
                      'Промивка системи спецiальним засобом\n'
                      'Замiна антифризу\n'
                      'Перевiрка термостата\n'
                      'Перевiрка герметичностi системи\n\n'
                      'Орiєнтовна вартiсть:\n'
                      'Промивка + антифриз — вiд 600 грн\n\n'
                      'Детальнiше: https://farro.ua/promyvka-ohlazhdeniya/'),
        },
        {
            'id':    'lights',
            'name':  'Ремонт фар та бамперiв',
            'icon':  '',
            'desc':  ('Полiрування, ремонт та замiна фар i бамперiв.\n\n'
                      'Що входить:\n'
                      'Полiрування та вiдновлення прозоростi фар\n'
                      'Замiна лiнз та свiтлодiодiв\n'
                      'Ремонт та фарбування бамперiв\n'
                      'Замiна пiдсилювача бампера\n\n'
                      'Орiєнтовна вартiсть:\n'
                      'Полiрування фар — вiд 300 грн/шт\n'
                      'Ремонт бампера — вiд 500 грн\n\n'
                      'Детальнiше: https://farro.ua/remont-far-i-bamperov/'),
        },
        {
            'id':    'suspension',
            'name':  'Ремонт ходової',
            'icon':  '',
            'desc':  ('Дiагностика та ремонт ходової частини автомобiля.\n\n'
                      'Що входить:\n'
                      'Дiагностика пiдвiски на пiдйомнику\n'
                      'Замiна амортизаторiв\n'
                      'Замiна кульових опор, сайлентблокiв\n'
                      'Замiна рульових наконечникiв i тяг\n'
                      'Замiна гальмiвних колодок та дискiв\n\n'
                      'Орiєнтовна вартiсть:\n'
                      'Дiагностика — безкоштовно при ремонтi\n'
                      'Замiна амортизаторiв — вiд 400 грн/шт\n'
                      'Замiна кульових — вiд 300 грн/шт\n\n'
                      'Детальнiше: https://farro.ua/remont-hodovoj/'),
        },
        {
            'id':    'exhaust',
            'name':  'Вихлопнi системи',
            'icon':  '',
            'desc':  ('Дiагностика та ремонт системи вихлопу.\n\n'
                      'Що входить:\n'
                      'Дiагностика герметичностi системи\n'
                      'Замiна глушника, резонатора\n'
                      'Замiна каталiзатора\n'
                      'Зварювальнi роботи на системi вихлопу\n\n'
                      'Орiєнтовна вартiсть:\n'
                      'Замiна глушника — вiд 800 грн\n'
                      'Зварювання — вiд 400 грн\n\n'
                      'Детальнiше: https://farro.ua/remont-vyhlopnoj/'),
        },
        {
            'id':    'other_sto',
            'name':  'Iнше',
            'icon':  '',
            'desc':  'Маєте iнше питання? Напишiть нам — розберемось!',
        },
    ],
    'body': [
        {
            'id':    'riht',
            'name':  'Рихтування авто',
            'icon':  '',
            'desc':  ('Вiдновлення геометрiї кузова пiсля ДТП або механiчних пошкоджень.\n\n'
                      'Що входить:\n'
                      'Дiагностика пошкоджень\n'
                      'Рихтування на стапелi\n'
                      'Вiдновлення геометрiї кузова\n'
                      'Пiдготовка пiд фарбування\n\n'
                      'Орiєнтовна вартiсть:\n'
                      'Рихтування крила — вiд 500 грн\n'
                      'Рихтування дверей — вiд 700 грн\n'
                      'Рихтування капота — вiд 800 грн\n'
                      'Складнi деформацiї — за оцiнкою\n\n'
                      'Детальнiше: https://farro.ua/rihtovka-avto/'),
        },
        {
            'id':    'paint',
            'name':  'Покраска авто',
            'icon':  '',
            'desc':  ('Професiйна покраска автомобiля з пiдбором кольору.\n\n'
                      'Що входить:\n'
                      'Пiдбiр кольору по коду\n'
                      'Пiдготовка поверхнi\n'
                      'Нанесення ґрунту\n'
                      'Покраска з полiруванням\n'
                      'Захисне лакове покриття\n\n'
                      'Орiєнтовна вартiсть:\n'
                      'Покраска елемента — вiд 1 500 грн\n'
                      'Повна покраска авто — вiд 15 000 грн\n'
                      'Локальне фарбування — вiд 600 грн\n\n'
                      'Детальнiше: https://farro.ua/pokraska-avto/'),
        },
        {
            'id':    'pdr',
            'name':  'Видалення вм\'ятин PDR',
            'icon':  '',
            'desc':  ('Видалення вм\'ятин без покраски методом PDR (Paintless Dent Repair).\n\n'
                      'Що входить:\n'
                      'Дiагностика пошкоджень\n'
                      'Видалення вм\'ятин без покраски\n'
                      'Пiдходить для вм\'ятин без пошкодження лакофарбового покриття\n\n'
                      'Переваги PDR:\n'
                      'Зберiгається оригiнальне покриття\n'
                      'Швидко — вiд 1 години\n'
                      'Значно дешевше фарбування\n\n'
                      'Орiєнтовна вартiсть:\n'
                      'Невелика вм\'ятина — вiд 600 грн\n'
                      'Середня вм\'ятина — вiд 1 000 грн\n'
                      'Пошкодження вiд градю — вiд 3 000 грн\n\n'
                      'Детальнiше: https://farro.ua/rihtovka-avto/'),
        },
    ],
}

STO_INFO = {
    'sto':  {'name': CONTACTS['sto']['name'],  'services': SERVICES['sto']},
    'body': {'name': CONTACTS['body']['name'], 'services': SERVICES['body']},
}

# 26 машин автопарку
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
    'камри':'Toyota Camry','кемрi':'Toyota Camry','кемри':'Toyota Camry',
    'прадо':'Toyota Land Cruiser Prado','прадiк':'Toyota Land Cruiser Prado',
    'rav4':'Toyota RAV4','рав4':'Toyota RAV4','рав':'Toyota RAV4',
    'крузак':'Toyota Land Cruiser','хайлендер':'Toyota Highlander',
    'корола':'Toyota Corolla','ярис':'Toyota Yaris','хайс':'Toyota HiAce',
    'октавiя':'Skoda Octavia','октавия':'Skoda Octavia','суперб':'Skoda Superb',
    'фабiя':'Skoda Fabia','кодiак':'Skoda Kodiaq','карок':'Skoda Karoq',
    'пассат':'Volkswagen Passat','тiгуан':'Volkswagen Tiguan','гольф':'Volkswagen Golf',
    'поло':'Volkswagen Polo','туарег':'Volkswagen Touareg',
    'транспортер':'Volkswagen Transporter','шаран':'Volkswagen Sharan',
    'бмв':'BMW','bmw':'BMW','бумер':'BMW','трiйка':'BMW 3 Series',
    'пятiрка':'BMW 5 Series','iкс5':'BMW X5','x5':'BMW X5','iкс3':'BMW X3',
    'мерс':'Mercedes-Benz','мерседес':'Mercedes-Benz','гелик':'Mercedes-Benz G-Class',
    'вiто':'Mercedes-Benz Vito','спрiнтер':'Mercedes-Benz Sprinter',
    'аудi':'Audi','audi':'Audi','а4':'Audi A4','а6':'Audi A6','ку7':'Audi Q7',
    'хундай':'Hyundai','туксон':'Hyundai Tucson','елантра':'Hyundai Elantra',
    'спортаж':'Kia Sportage','сiд':'Kia Ceed','рiо':'Kia Rio','оптима':'Kia Optima',
    'дастер':'Renault Duster','логан':'Renault Logan','каптур':'Renault Captur',
    'фокус':'Ford Focus','куга':'Ford Kuga','транзит':'Ford Transit',
    'астра':'Opel Astra','авео':'Chevrolet Aveo','круз':'Chevrolet Cruze',
    'аутлендер':'Mitsubishi Outlander','паджеро':'Mitsubishi Pajero',
    'кашкай':'Nissan Qashqai','рог':'Nissan Rogue','джук':'Nissan Juke',
    'iкстрейл':'Nissan X-Trail','лiф':'Nissan Leaf',
    'мазда':'Mazda','cx5':'Mazda CX-5','хонда':'Honda','civic':'Honda Civic',
    'accord':'Honda Accord','crv':'Honda CR-V',
    'форестер':'Subaru Forester','iмпреза':'Subaru Impreza','аутбек':'Subaru Outback',
    'лексус':'Lexus','rx':'Lexus RX','кайен':'Porsche Cayenne',
    'рейндж':'Range Rover','дефендер':'Land Rover Defender',
    'вольво':'Volvo','пежо':'Peugeot','сiтроен':'Citroen',
    'ланос':'Daewoo Lanos','сенс':'Daewoo Sens','нива':'Lada Niva',
    'теслa':'Tesla','tesla':'Tesla','уаз':'UAZ','буханка':'UAZ-452',
    'джилi':'Geely','черi':'Chery','чероки':'Jeep Cherokee',
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

def resolve_car(text):
    if not text or text == '-': return ''
    digits = re.sub(r'[^0-9]', '', text)
    if digits in FLEET_CARS: return FLEET_CARS[digits]
    return text.upper()

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
    logger.info('polish_reply: %s', raw[:60])
    if not claude_client: return raw
    try:
        resp = claude_client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=400,
            messages=[{'role': 'user', 'content': (
                'Ти ввiчливий менеджер автосервiсу Farro. '
                'Майстер написав клiєнту: ' + raw + '. '
                'Перепиши украiнською мовою — красиво, ввiчливо, тепло. '
                'Збережи суть. Тiльки готовий текст.'
            )}])
        result = resp.content[0].text.strip()
        logger.info('polish result: %s', result[:80])
        return result if result else raw
    except Exception as e:
        logger.error('polish_reply: %s', e)
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
    ws = get_ws('Клиенты')
    rows = ws.get_all_values()
    for i, row in enumerate(rows[1:], start=2):
        if str(row[0]).strip() == str(tg_id):
            ws.update('B{}:F{}'.format(i,i), [[name,phone,car,model,today_str()]])
            return
    ws.append_row([str(tg_id),name,phone,car,model,today_str()])

def get_all_clients():
    ws = get_ws('Клиенты')
    return [{'tg_id':r[0],'name':r[1] if len(r)>1 else '','car':r[3] if len(r)>3 else ''}
            for r in ws.get_all_values()[1:] if r and r[0]]

def gen_request_id():
    rows = get_ws('Заказы').get_all_values()
    num  = len([r for r in rows[1:] if r and r[0]]) + 1
    return 'REQ-{:04d}'.format(num)

def save_request(tg_id, client_name, car, sto_key, service, wish):
    rid = gen_request_id()
    get_ws('Заказы').append_row([rid,now_str(),str(tg_id),client_name,
                                  car,STO_INFO[sto_key]['name'],service,wish,'new',''])
    return rid

def get_orders_by_car(car):
    cc = car.upper().replace(' ','')
    result = []
    for row in get_ws('Заказы').get_all_values()[1:]:
        if len(row)>4 and cc in str(row[4]).upper().replace(' ',''):
            result.append({'id':row[0],'date':row[1],
                           'service':row[6] if len(row)>6 else '',
                           'status':row[8] if len(row)>8 else ''})
    return result[-5:]

def get_requests_by_client(tg_id):
    result = []
    for row in get_ws('Заказы').get_all_values()[1:]:
        if len(row)>2 and str(row[2]).strip() == str(tg_id):
            result.append({'id':row[0],'date':row[1],
                           'service':row[6] if len(row)>6 else '',
                           'status':row[8] if len(row)>8 else ''})
    return result[-5:]

# ── Клавiатури ────────────────────────────────────────────────

# Постiйне меню внизу для клiєнта (як мессенджер)
def reply_kb_client():
    return ReplyKeyboardMarkup([
        ['Послуги та цiни', 'Моє авто'],
        ['Мої заявки', 'Записатися на ремонт'],
    ], resize_keyboard=True, input_field_placeholder='Пишiть нам — ми вiдповiмо!')

# Постiйне меню внизу для менеджера
def reply_kb_staff():
    return ReplyKeyboardMarkup([
        ['Новi заявки', 'Всi активнi'],
        ['Авто готове', 'Клiєнти'],
    ], resize_keyboard=True, input_field_placeholder='Або просто вiдповiдайте клiєнту...')

# Iнлайн кнопки для детального вмiсту
def kb_sto_choice():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('Кузовний сервiс (вул. Павла Чубинського 2а)', callback_data='menu_body')],
        [InlineKeyboardButton('СТО (вул. Богдана Хмельницького 4а, лiвий берег)', callback_data='menu_sto')],
    ])

def kb_services_list(sto_key):
    c    = CONTACTS[sto_key]
    btns = []
    # Телефони як кнопки для дзвiнка
    for label, number in PHONES:
        btns.append([InlineKeyboardButton(
            'Зателефонувати ' + label, url='tel:' + number)])
    btns.append([InlineKeyboardButton(
        'Вiдкрити в навiгаторi', url=c['maps'])])
    for svc in SERVICES[sto_key]:
        btns.append([InlineKeyboardButton(
            svc['icon'] + ' ' + svc['name'],
            callback_data='svc_{}_{}'.format(sto_key, svc['id']))])
    btns.append([InlineKeyboardButton('Запитати менеджера', callback_data='ask_manager')])
    return InlineKeyboardMarkup(btns)

def kb_service_detail(sto_key, svc_id):
    c    = CONTACTS[sto_key]
    btns = [
        [InlineKeyboardButton('Записатися на цю послугу', callback_data='book_{}_{}'.format(sto_key, svc_id))],
        [InlineKeyboardButton('Запитати менеджера',        callback_data='ask_manager')],
    ]
    for label, number in PHONES:
        btns.append([InlineKeyboardButton(
            'Зателефонувати ' + label, url='tel:' + number)])
    btns.append([InlineKeyboardButton('Навiгатор', url=c['maps'])])
    btns.append([InlineKeyboardButton('Назад до списку', callback_data='menu_{}'.format(sto_key))])
    return InlineKeyboardMarkup(btns)

def kb_book_confirm(sto_key, svc_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('Пiдтвердити', callback_data='confirm_{}_{}'.format(sto_key, svc_id))],
        [InlineKeyboardButton('Скасувати', callback_data='cancel')],
    ])

def kb_cancel():
    return InlineKeyboardMarkup([[InlineKeyboardButton('Скасувати', callback_data='cancel')]])

def kb_reply_manager():
    return None  # Клiєнт просто пише в чат

def kb_reply_client(client_id):
    return InlineKeyboardMarkup([[InlineKeyboardButton(
        'Вiдповiсти клiєнту', callback_data='reply_{}'.format(client_id))]])

def kb_ready_list():
    ws     = get_ws('Заказы')
    active = [r for r in ws.get_all_values()[1:] if len(r)>8 and r[8] not in ('issued','')]
    if not active: return None
    btns = []
    for r in active[:10]:
        btns.append([InlineKeyboardButton(
            '{} — {} | {}'.format(r[0], r[3], r[6]),
            callback_data='mark_ready_{}'.format(r[0]))])
    btns.append([InlineKeyboardButton('Скасувати', callback_data='cancel')])
    return InlineKeyboardMarkup(btns)

def kb_clients_list():
    clients = get_all_clients()
    if not clients: return None
    btns = []
    for c in clients[:15]:
        label = '{} {}'.format(c['name'], '({})'.format(c['car']) if c['car'] else '')
        btns.append([InlineKeyboardButton(label, callback_data='wc_{}'.format(c['tg_id']))])
    btns.append([InlineKeyboardButton('Скасувати', callback_data='cancel')])
    return InlineKeyboardMarkup(btns)

def kb_write_templates():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('Нагадування про масло',    callback_data='tpl_oil')],
        [InlineKeyboardButton('Авто готове до видачi',    callback_data='tpl_ready')],
        [InlineKeyboardButton('Уточнення по цiнi',        callback_data='tpl_price')],
        [InlineKeyboardButton('Знайшли доп. роботи',      callback_data='tpl_extra')],
        [InlineKeyboardButton('Свiй текст (через Claude)', callback_data='tpl_custom')],
        [InlineKeyboardButton('Скасувати',                callback_data='cancel')],
    ])

# ── Утилiти ───────────────────────────────────────────────────

def contact_block(sto_key):
    c = CONTACTS[sto_key]
    return ('{}\n'
            'Адреса: {}\n'
            'Карти: {}\n'
            'Тел.: {}\n'
            'Графiк: {}').format(c['name'], c['address'], c['maps'], c['phone'], c['hours'])

async def send_to_client(bot, client_id, text):
    await bot.send_message(
        chat_id=int(client_id),
        text='Повiдомлення вiд СТО Farro:\n\n' + text,
)

async def notify_staff(bot, message, client_id=None):
    kb = kb_reply_client(client_id) if client_id else None
    for uid in STAFF_IDS:
        try: await bot.send_message(chat_id=uid, text=message, reply_markup=kb)
        except Exception as e: logger.error('notify %s: %s', uid, e)

def status_icon(s):
    return {'new':'Нова','confirmed':'Пiдтверджено','in_work':'В роботi',
            'ready':'Готово','issued':'Видано'}.get(s, s)

# ── Основнi хендлери ─────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    name = update.effective_user.first_name or 'Клiєнт'
    ctx.user_data.clear()

    if is_staff(uid):
        await update.message.reply_text(
            'Привiт, {}! ID: {}\nПанель менеджера СТО Farro'.format(name, uid),
            reply_markup=reply_kb_staff())
        return

    client = get_client(uid)
    if client:
        greeting = 'З поверненням, {}! Оберiть пункт меню або просто напишiть нам.'.format(client['name'])
    else:
        greeting = 'Вiтаємо в СТО Farro! Оберiть пункт меню нижче або просто напишiть ваше питання.'
    await update.message.reply_text(greeting, reply_markup=reply_kb_client())

async def handle_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    text = (update.message.text or '').strip()
    ud   = ctx.user_data

    # ── Реєстрацiя ────────────────────────────────────────────
    if ud.get('reg_step') == 'name':
        ud['reg_name'] = text; ud['reg_step'] = 'phone'
        await update.message.reply_text('Ваш номер телефону?', reply_markup=reply_kb_client()); return
    if ud.get('reg_step') == 'phone':
        ud['reg_phone'] = text; ud['reg_step'] = 'car'
        await update.message.reply_text('Номер вашого авто? (або - якщо немає)', reply_markup=reply_kb_client()); return
    if ud.get('reg_step') == 'car':
        ud['reg_car'] = resolve_car(text); ud['reg_step'] = 'model'
        await update.message.reply_text('Марка i модель авто? (або -)', reply_markup=reply_kb_client()); return
    if ud.get('reg_step') == 'model':
        save_client(uid, ud['reg_name'], ud['reg_phone'], ud.get('reg_car',''), normalize_car(text))
        name = ud['reg_name']; ud.clear()
        await update.message.reply_text(
            'Дякуємо, {}! Ви зареєстрованi. Тепер просто пишiть нам!'.format(name),
            reply_markup=reply_kb_client()); return

    # ── Пошук авто для статусу ─────────────────────────────────
    if ud.get('wait_car_status'):
        ud.pop('wait_car_status')
        orders = get_orders_by_car(text)
        if not orders:
            await update.message.reply_text('Авто {} не знайдено в наших записах.'.format(text.upper()),
                                            reply_markup=reply_kb_client()); return
        lines = ['Статус авто {}:'.format(text.upper())]
        for o in reversed(orders):
            lines.append('{} | {} | {}'.format(o['date'], o['service'], status_icon(o['status'])))
        await update.message.reply_text('\n'.join(lines), reply_markup=reply_kb_client()); return

    # ── Побажання при записi ──────────────────────────────────
    if ud.get('wait_wish'):
        sto_key = ud.get('sel_sto')
        svc_id  = ud.get('sel_svc')
        ud.pop('wait_wish', None)
        svc     = next((s for s in SERVICES[sto_key] if s['id']==svc_id), None)
        svc_name= svc['name'] if svc else svc_id
        client  = get_client(uid)
        cname   = client['name'] if client else str(uid)
        car     = client['car']  if client else 'не вказано'
        c       = CONTACTS[sto_key]
        rid     = save_request(uid, cname, car, sto_key, svc_name, text)
        msg = ('НОВА ЗАЯВКА {}\n\nКлiєнт: {}\nАвто: {}\nСТО: {}\n'
               'Послуга: {}\nПобажання: {}\n{}').format(
            rid, cname, car, c['name'], svc_name, text, now_str())
        await notify_staff(ctx.bot, msg, client_id=uid)
        await update.message.reply_text(
            'Заявку прийнято! Номер: {}\nПослуга: {}\n{}\n{}\n\nМайстер зв\'яжеться найближчим часом.'.format(
                rid, svc_name, c['address'], c['hours']),
            reply_markup=reply_kb_client()); return

    # ── Вiдповiдь менеджера клiєнту ───────────────────────────
    if ud.get('wait_reply_to'):
        client_id = ud.pop('wait_reply_to')
        polished  = polish_reply(text)
        try:
            await send_to_client(ctx.bot, client_id, polished)

        except Exception as e:
            await update.message.reply_text('Помилка: {}'.format(e), reply_markup=reply_kb_staff())
        return


    if ud.get('wait_custom'):
        ud.pop('wait_custom')
        client_id = ud.get('write_to_id')
        cname     = ud.get('write_to_name','')
        polished  = polish_reply(text)
        try:
            await send_to_client(ctx.bot, client_id, polished)

        except Exception as e:
            await update.message.reply_text('Помилка: {}'.format(e), reply_markup=reply_kb_staff())
        return


    # ── Пiдтвердження запису ──────────────────────────────────
    if ud.get('wait_confirm'):
        rid = text.strip().upper(); ud.pop('wait_confirm')
        ws  = get_ws('Заказы')
        for i, row in enumerate(ws.get_all_values()[1:], start=2):
            if str(row[0]).strip() == rid:
                ws.update('I{}'.format(i), [['confirmed']])
                cid     = str(row[2]).strip() if len(row)>2 else None
                service = row[6] if len(row)>6 else ''
                if cid:
                    try:
                        await ctx.bot.send_message(
                            chat_id=int(cid),
                            text='Ваш запис пiдтверджено!\nЗаявка: {}\nПослуга: {}\nЧекаємо вас!'.format(rid, service),
                            )
                    except Exception as e: logger.error('confirm: %s', e)
                await update.message.reply_text('Запис {} пiдтверджено.'.format(rid), reply_markup=reply_kb_staff())
                return
        await update.message.reply_text('Заявку {} не знайдено.'.format(rid), reply_markup=reply_kb_staff()); return

    # ── Повiдомлення вiд клiєнта менеджеру ───────────────────
    if ud.get('wait_client_msg'):
        ud.pop('wait_client_msg')
        client = get_client(uid)
        cname  = client['name'] if client else 'Новий клiєнт'
        car    = client['car']  if client else 'не вказано'
        fwd    = 'Повiдомлення вiд клiєнта:\n{} | {}\n\n{}'.format(cname, car, text)
        await notify_staff(ctx.bot, fwd, client_id=uid)
        await update.message.reply_text('Повiдомлення надiслано менеджеру.', reply_markup=reply_kb_client()); return

    # ── Reply keyboard команди ────────────────────────────────
    text_lo = text.lower()

    if 'послуги' in text_lo or 'цiни' in text_lo or 'цены' in text_lo:
        await update.message.reply_text('Оберiть сервiс:', reply_markup=kb_sto_choice()); return

    if 'статус' in text_lo or 'авто' in text_lo or 'готово' in text_lo:
        client = get_client(uid)
        if client and client['car']:
            orders = get_orders_by_car(client['car'])
            if orders:
                lines = ['Статус авто {}:'.format(client['car'])]
                for o in reversed(orders):
                    lines.append('{} | {} | {}'.format(o['date'], o['service'], status_icon(o['status'])))
                await update.message.reply_text('\n'.join(lines), reply_markup=reply_kb_client()); return
        ud['wait_car_status'] = True
        await update.message.reply_text('Введiть номер авто:', reply_markup=reply_kb_client()); return

    if 'записат' in text_lo or 'запис' in text_lo:
        client = get_client(uid)
        if not client:
            ud['reg_step'] = 'name'
            await update.message.reply_text('Для запису потрiбна реєстрацiя. Як вас звати?',
                                            reply_markup=reply_kb_client())
        else:
            await update.message.reply_text('Оберiть сервiс для запису:', reply_markup=kb_sto_choice())
        return

    # Клiєнт згадав менеджера - просто пiдтверджуємо що чуємо
    if 'менеджер' in text_lo and not is_staff(uid):
        pass  # впаде далi на загальний обробник чату

    # ── Менеджер: команди ────────────────────────────────────
    if is_staff(uid):
        if 'новi' in text_lo or 'заявки' in text_lo:
            ws    = get_ws('Заказы')
            new_r = [r for r in ws.get_all_values()[1:] if len(r)>8 and r[8]=='new']
            if not new_r:
                await update.message.reply_text('Нових заявок немає.', reply_markup=reply_kb_staff()); return
            lines = ['Новi заявки: {}'.format(len(new_r))]
            for r in new_r:
                lines.append('{} | {} | {} | {}'.format(r[0], r[3], r[6], r[1]))
            await update.message.reply_text('\n'.join(lines), reply_markup=reply_kb_staff()); return

        if 'активн' in text_lo or 'всi' in text_lo:
            ws     = get_ws('Заказы')
            active = [r for r in ws.get_all_values()[1:] if len(r)>8 and r[8] not in ('issued','')]
            if not active:
                await update.message.reply_text('Активних заявок немає.', reply_markup=reply_kb_staff()); return
            lines = ['Активнi заявки: {}'.format(len(active))]
            for r in active:
                lines.append('{} {} | {} | {}'.format(status_icon(r[8]), r[0], r[3], r[6]))
            await update.message.reply_text('\n'.join(lines), reply_markup=reply_kb_staff()); return

        if 'готове' in text_lo or 'готово' in text_lo:
            kb = kb_ready_list()
            if not kb:
                await update.message.reply_text('Активних заявок немає.', reply_markup=reply_kb_staff()); return
            await update.message.reply_text('Оберiть готову заявку:', reply_markup=kb); return

        if 'клiєнти' in text_lo or 'клієнти' in text_lo or 'написати' in text_lo:
            kb = kb_clients_list()
            if not kb:
                await update.message.reply_text('Клiєнтiв не знайдено.', reply_markup=reply_kb_staff()); return
            await update.message.reply_text('Оберiть клiєнта:', reply_markup=kb); return

        # Менеджер написав текст без контексту
        # Нагадуємо: треба натиснути "Вiдповiсти" пiд повiдомленням клiєнта
        msg = 'Щоб вiдповiсти — натиснiть кнопку Вiдповiсти клiєнту пiд його повiдомленням. Або оберiть клiєнта через Клiєнти.'
        await update.message.reply_text(msg, reply_markup=reply_kb_staff())
        return

    # ── Будь-яке повiдомлення вiд клiєнта — це чат з менеджером ──
    client = get_client(uid)
    cname  = client['name'] if client else 'Новий клiєнт ({})'.format(uid)
    car    = client['car']  if client else 'не вказано'
    fwd    = 'Клiєнт пише:\n{} | {}\n\n{}'.format(cname, car, text)
    await notify_staff(ctx.bot, fwd, client_id=uid)
async def handle_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    uid  = q.from_user.id
    data = q.data
    await q.answer()
    ud   = ctx.user_data

    if data == 'cancel':
        ud.clear()
        await q.edit_message_text('Скасовано.'); return

    if data == 'ask_manager':
        ud['wait_client_msg'] = True
        await q.edit_message_text('Напишiть ваше питання — менеджер вiдповiсть найближчим часом:'); return

    # Меню СТО або кузовного
    if data.startswith('menu_'):
        sto_key = data[5:]
        c       = CONTACTS[sto_key]
        text    = ('{}\n\n'
                   'Адреса: {}\n'
                   'Карти/Навiгатор: {}\n'
                   'Телефон: {}\n'
                   'Графiк: {}\n\n'
                   'Оберiть послугу:').format(
            c['name'], c['address'], c['maps'], c['phone'], c['hours'])
        await q.edit_message_text(text, reply_markup=kb_services_list(sto_key)); return

    # Деталi послуги
    if data.startswith('svc_'):
        parts   = data[4:].split('_', 1)
        sto_key = parts[0]
        svc_id  = parts[1] if len(parts)>1 else ''
        svc     = next((s for s in SERVICES[sto_key] if s['id']==svc_id), None)
        if not svc:
            await q.edit_message_text('Послугу не знайдено.'); return
        c = CONTACTS[sto_key]
        text = ('{} {}\n\n{}\n\n'
                'Адреса: {}\n'
                'Карти: {}\n'
                'Тел.: {}\n'
                'Графiк: {}').format(
            svc['icon'], svc['name'], svc['desc'],
            c['address'], c['maps'], c['phone'], c['hours'])
        await q.edit_message_text(text, reply_markup=kb_service_detail(sto_key, svc_id)); return

    # Запис на конкретну послугу
    if data.startswith('book_'):
        parts   = data[5:].split('_', 1)
        sto_key = parts[0]
        svc_id  = parts[1] if len(parts)>1 else ''
        client  = get_client(uid)
        if not client:
            ud['reg_step']  = 'name'
            ud['after_reg_sto'] = sto_key
            ud['after_reg_svc'] = svc_id
            await q.edit_message_text('Для запису потрiбна реєстрацiя. Як вас звати?'); return
        ud['sel_sto']   = sto_key
        ud['sel_svc']   = svc_id
        ud['wait_wish'] = True
        svc = next((s for s in SERVICES[sto_key] if s['id']==svc_id), None)
        svc_name = svc['name'] if svc else svc_id
        await q.edit_message_text(
            'Послуга: {}\n\nОпишiть проблему i зручний час для запису:'.format(svc_name)); return

    # Вибiр СТО для запису через reply kb
    if data.startswith('sto_'):
        sto_key = data[4:]
        if sto_key not in STO_INFO: return
        ud['sel_sto'] = sto_key
        c = CONTACTS[sto_key]
        await q.edit_message_text(
            '{}\n{}\n{}\n\nОберiть послугу:'.format(c['name'], c['address'], c['hours']),
            reply_markup=kb_services_list(sto_key)); return

    # Вiдповiдь клiєнту — кнопка у повiдомленнi для менеджера
    if data.startswith('reply_'):
        client_id = int(data[6:])
        ud['wait_reply_to'] = client_id
        await q.edit_message_text('Пишiть:'); return

    # Готовнiсть авто
    if data.startswith('mark_ready_'):
        rid  = data[11:]
        ws   = get_ws('Заказы')
        for i, row in enumerate(ws.get_all_values()[1:], start=2):
            if str(row[0]).strip() == rid:
                ws.update('I{}'.format(i), [['ready']])
                cid      = str(row[2]).strip() if len(row)>2 else None
                car      = row[4] if len(row)>4 else ''
                service  = row[6] if len(row)>6 else ''
                sto_name = row[5] if len(row)>5 else ''
                if cid:
                    try:
                        await ctx.bot.send_message(
                            chat_id=int(cid),
                            text='Ваш автомобiль готовий!\nАвто: {}\nПослуга: {}\n{}\nЧекаємо вас!'.format(
                                car, service, sto_name),
                            )
                    except Exception as e: logger.error('ready: %s', e)
                await q.edit_message_text('Заявка {} вiдмiчена як готова. Клiєнта повiдомлено.'.format(rid)); return
        await q.edit_message_text('Заявку не знайдено.'); return

    # Вибiр клiєнта для написання
    if data.startswith('wc_'):
        cid  = data[3:]
        ws   = get_ws('Клиенты')
        cname = cid; car = ''
        for r in ws.get_all_values()[1:]:
            if str(r[0]).strip() == cid:
                cname = r[1] if len(r)>1 else cname
                car   = r[3] if len(r)>3 else ''
                break
        ud['write_to_id']   = int(cid)
        ud['write_to_name'] = cname
        ud['write_to_car']  = car
        car_s = ' ({})'.format(car) if car else ''
        await q.edit_message_text(
            'Клiєнт: {}{}. Оберiть тип:'.format(cname, car_s),
            reply_markup=kb_write_templates()); return

    # Шаблони
    if data.startswith('tpl_'):
        tpl   = data[4:]
        cname = ud.get('write_to_name','')
        car   = ud.get('write_to_car','')
        cid   = ud.get('write_to_id')
        car_s = ' ({})'.format(car) if car else ''

        if tpl == 'custom':
            ud['wait_custom'] = True
            await q.edit_message_text(
                'Напишiть текст для {} — Claude зробить його ввiчливiшим:'.format(cname)); return

        texts = {
            'oil':   'Нагадуємо — для вашого авто{} наближається час замiни олiї. Записуйтесь на ТО у СТО Farro!'.format(car_s),
            'ready': 'Ваш автомобiль{} готовий до видачi. Чекаємо вас!'.format(car_s),
            'price': 'Хотiли уточнити вартiсть робiт по вашому авто{}. Напишiть нам.'.format(car_s),
            'extra': 'Виявили додатковi роботи по вашому авто{}. Розкажемо детальнiше.'.format(car_s),
        }
        if tpl in texts and cid:
            try:
                await send_to_client(ctx.bot, cid, texts[tpl])
                await q.edit_message_text('OK', reply_markup=reply_kb_staff())
            except Exception as e:
                await q.edit_message_text('Помилка: {}'.format(e), reply_markup=reply_kb_staff())
        return

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler('start', cmd_start))
    app.add_handler(CommandHandler('menu',  cmd_start))
    app.add_handler(CallbackQueryHandler(handle_cb))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    logger.info('СТО бот %s v5 запущен!', STO_NAME)
    logger.info('CLAUDE: %s | STAFF: %s', bool(claude_client), STAFF_IDS)
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
