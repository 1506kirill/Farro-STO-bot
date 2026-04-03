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
    if not raw:
        return raw
    raw_clean = raw.strip()
    short_map = {
        'да': 'Так.',
        'так': 'Так.',
        'ок': 'Добре.',
        'ok': 'Добре.',
        '+': 'Так.',
        'yes': 'Так.',
        'угу': 'Так.',
    }
    if raw_clean.lower() in short_map:
        return short_map[raw_clean.lower()]
    if not claude_client:
        return raw
    try:
        r = claude_client.messages.create(
            model='claude-haiku-4-5-20251001', max_tokens=200,
            messages=[{'role':'user','content':(
                'Менеджер автосервiсу Farro написав клiєнту: ' + raw +
                '. Переклади це однiєю готовою вiдповiддю українською мовою. '
                'Збережи змiст максимально точно, не змiнюй сенс, '
                'але зроби текст трохи природнiшим, ввiчливим i виразним. '
                'Поверни тiльки фiнальну вiдповiдь для клiєнта без коментарiв, пояснень, варiантiв, службових фраз чи примiток. '
                'Без смайлiв, без зайвого офiцiозу, без зайвих подробиць.'
            )}])
        result = r.content[0].text.strip() if r.content else ''
        banned = ['розширений варiант', 'варiант', 'пояснен', 'внутрiшн', 'службов']
        if not result or any(b in result.lower() for b in banned):
            return raw
        return result
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
                    'grm_odo':row[9] if len(row)>9 else '','grm_date':row[10] if len(row)>10 else '',
                    'current_odo':row[11] if len(row)>11 else ''}
    return None

def save_client(tg_id, data):
    ws  = get_ws('Клиенты')
    row = [str(tg_id), data.get('name',''), data.get('phone',''),
           data.get('car',''), data.get('model',''), today_str(),
           data.get('ins_end',''), data.get('oil_odo',''), data.get('oil_date',''),
           data.get('grm_odo',''), data.get('grm_date',''), data.get('current_odo','')]
    rows = ws.get_all_values()
    for i, r in enumerate(rows[1:], start=2):
        if str(r[0]).strip() == str(tg_id):
            ws.update('A{}:L{}'.format(i,i), [row]); return
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

async def forward_media_to_staff(bot, source_chat_id, message_id, header, client_id=None):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(
        '↩️ Вiдповiсти', callback_data='reply_{}'.format(client_id))]]) if client_id else None
    for uid in STAFF_IDS:
        try:
            await bot.send_message(chat_id=uid, text=header, reply_markup=kb)
            await bot.forward_message(chat_id=uid, from_chat_id=source_chat_id, message_id=message_id)
        except Exception as e:
            logger.error('staff media %s: %s', uid, e)

async def forward_media_to_client(bot, client_id, message):
    chat_id = int(client_id)

    if message.photo:
        media = message.photo[-1].file_id
        caption = message.caption or None
        await bot.send_photo(chat_id=chat_id, photo=media, caption=caption)
        return

    if message.video:
        await bot.send_video(
            chat_id=chat_id,
            video=message.video.file_id,
            caption=message.caption or None
        )
        return

    if message.voice:
        await bot.send_voice(
            chat_id=chat_id,
            voice=message.voice.file_id,
            caption=message.caption or None
        )
        return

    if message.document:
        await bot.send_document(
            chat_id=chat_id,
            document=message.document.file_id,
            caption=message.caption or None
        )
        return

    await bot.forward_message(chat_id=chat_id, from_chat_id=message.chat_id, message_id=message.message_id)

def addr(sto_key):
    c = CONTACTS[sto_key]
    note = ' {}'.format(c['note']) if c.get('note') else ''
    return c['address'] + note

# ── Keyboards ────────────────────────────────────────────────

def kb_new():
    return ReplyKeyboardMarkup([
        ['🛠 Послуги та цiни', '🚗 Моє авто'],
        ['💬 Написати менеджеру', '📞 Замовити дзвiнок'],
    ], resize_keyboard=True, is_persistent=True)

def kb_reg():
    return ReplyKeyboardMarkup([
        ['🛠 Послуги та цiни', '🚗 Моє авто'],
        ['💬 Написати менеджеру', '📞 Замовити дзвiнок'],
    ], resize_keyboard=True, is_persistent=True)

def get_unread_count(ctx, uid):
    try:
        return len(ctx.bot_data.get('unread', {}).get(uid, []))
    except:
        return 0

def kb_staff(count=0):
    return ReplyKeyboardMarkup([
        ['🗂 Медiафайли', '📇 Контакти'],
        ['💬 Чати'],
    ], resize_keyboard=True, is_persistent=True)

def ckb(uid): return kb_reg() if get_client(uid) else kb_new()

def track_client_activity(ctx, uid, activity_type='text'):
    try:
        client = get_client(uid) or {}
        ctx.bot_data.setdefault('client_activity', {})[uid] = {
            'ts': datetime.now(KYIV_TZ),
            'type': activity_type,
            'name': client.get('name') or 'Клiєнт',
            'phone': client.get('phone') or 'не вказано',
            'car': client.get('car') or 'не вказано',
        }
    except Exception as e:
        logger.error('track_client_activity: %s', e)

def track_media_log(ctx, uid, media_type):
    try:
        client = get_client(uid) or {}
        logs = ctx.bot_data.setdefault('media_log', [])
        logs.append({
            'ts': datetime.now(KYIV_TZ),
            'uid': uid,
            'media_type': media_type,
            'name': client.get('name') or 'Клiєнт',
            'phone': client.get('phone') or 'не вказано',
            'car': client.get('car') or 'не вказано',
        })
        if len(logs) > 500:
            del logs[:-500]
    except Exception as e:
        logger.error('track_media_log: %s', e)

def detect_media_type(message):
    if getattr(message, 'photo', None):
        return 'Фото'
    if getattr(message, 'video', None):
        return 'Вiдео'
    if getattr(message, 'voice', None):
        return 'Голосове'
    if getattr(message, 'document', None):
        return 'Файл'
    return 'Медiа'

def kb_phone_request():
    return ReplyKeyboardMarkup([
        [KeyboardButton('📱 Подiлитися номером', request_contact=True)],
    ], resize_keyboard=True, one_time_keyboard=True, is_persistent=False)

def has_registered_phone(uid):
    client = get_client(uid)
    return bool(client and client.get('phone'))

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

def kb_call():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('🚗 Кузовний сервiс (Чубинського)', callback_data='call_body')],
        [InlineKeyboardButton('🔧 СТО (Хмельницького)',           callback_data='call_sto')],
    ])

def kb_svcs(sto_key):
    c = CONTACTS[sto_key]
    btns = [
        [InlineKeyboardButton('🧭 Прокласти маршрут', url=c['maps'])],
    ]
    for svc in SERVICES[sto_key]:
        btns.append([InlineKeyboardButton(svc['name'], callback_data='svc_{}_{}'.format(sto_key, svc['id']))])
    btns.append([InlineKeyboardButton('💬 Написати менеджеру', callback_data='ask_{}'.format(sto_key))])
    return InlineKeyboardMarkup(btns)

def kb_svc_detail(sto_key):
    c = CONTACTS[sto_key]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('💬 Написати менеджеру', callback_data='ask_{}'.format(sto_key))],
        [InlineKeyboardButton('🧭 Прокласти маршрут', url=c['maps'])],
        [InlineKeyboardButton('⬅️ Назад до списку', callback_data='menu_{}'.format(sto_key))],
    ])

def kb_contact_body():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('🧭 Прокласти маршрут: Кузовний сервiс', url=CONTACTS['body']['maps'])],
    ])

def kb_contact_sto():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('🧭 Прокласти маршрут: СТО', url=CONTACTS['sto']['maps'])],
    ])

def kb_skip():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('⏭ Пропустити', callback_data='skip')],
        [InlineKeyboardButton('✅ Завершити', callback_data='finish_mycar')],
    ])

def kb_mycar_update():
    return InlineKeyboardMarkup([[InlineKeyboardButton('🔄 Оновити данi авто', callback_data='start_mycar')]])

MYCAR_FIELDS  = ['name','car','current_odo','ins_end','oil_odo','oil_date','grm_odo','grm_date']
MYCAR_PROMPTS = {
    'name':     'Ваше iм\'я',
    'phone':    'Номер телефону',
    'car':      'Марка та модель авто',
    'current_odo': 'Поточний одометр (км)',
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

def parse_int_digits(v):
    s = re.sub(r'\D', '', str(v or ''))
    return int(s) if s else None

def build_maintenance_reply(client, current_odo):
    oil_odo = parse_int_digits(client.get('oil_odo'))
    grm_odo = parse_int_digits(client.get('grm_odo'))

    parts = []
    if oil_odo:
        oil_left = 10000 - (current_odo - oil_odo)
        parts.append('До замiни масла залишилось: {} км'.format(oil_left))
    else:
        parts.append('Немає даних про останню замiну масла.')

    if grm_odo:
        grm_left = 50000 - (current_odo - grm_odo)
        parts.append('До замiни ГРМ залишилось: {} км'.format(grm_left))
    else:
        parts.append('Немає даних про останню замiну ГРМ.')

    return '\n'.join(parts)

def format_hours_text():
    return ('Графiк роботи:\n'
            'Кузовний сервiс — {}\n'
            'СТО — {}\n'
            'На вихiдних не працюємо.').format(CONTACTS['body']['hours'], CONTACTS['sto']['hours'])

def format_address_text():
    return ('Нашi адреси:\n'
            '🚗 Кузовний сервiс: {} {}\n'
            '🔧 СТО: {}').format(
                CONTACTS['body']['address'],
                CONTACTS['body']['note'],
                CONTACTS['sto']['address']
            )

def is_hours_question(tlo):
    keys = ['граф', 'до скiльки', 'до скольки', 'коли можна пiд', 'когда можно подъ',
            'на вихiдних', 'на выходных', 'в суботу', 'в субботу', 'завтра можна', 'завтра можно',
            'коли працюєте', 'когда работаете', 'режим роботи']
    return any(k in tlo for k in keys)

def is_address_question(tlo):
    keys = ['який адрес', 'какой адрес', 'куди пiд', 'куда подъ', 'де ви', 'где вы',
            'де знаход', 'где наход', 'як вас знайти', 'как вас найти']
    return any(k in tlo for k in keys)

# ── Handlers ─────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    name = update.effective_user.first_name or 'Клiєнт'
    ctx.user_data.clear()
    if is_staff(uid):
        await update.message.reply_text('Привiт, {}! ID: {}'.format(name,uid), reply_markup=kb_staff()); return
    client = get_client(uid)
    if client and client.get('phone'):
        txt = 'З поверненням, {}!\n\nОберiть одну з кнопок нижче або натиснiть "💬 Написати менеджеру".'.format(client.get('name',''))
        await update.message.reply_text(txt, reply_markup=kb_reg())
    else:
        ctx.user_data['reg_step'] = 'phone'
        ctx.user_data['reg_data'] = {}
        txt = ('Вiтаємо в Farro!\n\n'
               'Щоб розпочати дiалог з менеджером, спочатку подiлiться номером телефону кнопкою нижче '
               'або введiть його вручну у форматi +380XXXXXXXXX.')
        await update.message.reply_text(txt, reply_markup=kb_phone_request())

async def handle_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    text = (update.message.text or '').strip()
    ud   = ctx.user_data
    tlo  = text.lower()

    if (not is_staff(uid)) and (not has_registered_phone(uid)):
        allowed_steps = {'phone', 'choose_service', 'name', 'car'}
        if ud.get('reg_step') not in allowed_steps:
            ud['reg_step'] = 'phone'
            ud['reg_data'] = {}
            await update.message.reply_text(
                'Щоб розпочати дiалог з менеджером, спочатку подiлiться номером телефону кнопкою нижче.',
                reply_markup=kb_phone_request()
            )
            return

    # Якщо кнопка меню — скидаємо всi активнi процеси
    if is_menu_btn(text) and not is_staff(uid):
        if 'reg_step' in ud or 'mycar_step' in ud or 'awaiting_mycar_odo' in ud:
            ud.clear()

    # ── Реєстрацiя ────────────────────────────────────────────
    if ud.get('reg_step'):
        step = ud['reg_step']
        data = ud.setdefault('reg_data',{})

        if step == 'choose_service':
            await update.message.reply_text(
                'Будь ласка, оберiть кнопкою, куди хочете написати:',
                reply_markup=kb_write()
            ); return

        if step == 'phone':
            if text in ('-','Пропустити'):
                await update.message.reply_text(
                    "Номер телефону пропустити не можна. Вiн потрiбен, щоб менеджер мiг з вами зв'язатися.",
                    reply_markup=kb_phone_request()
                ); return
            phone = normalize_ua_phone(text)
            if not phone:
                await update.message.reply_text(
                    "Будь ласка, введiть коректний український номер телефону у форматi +380XXXXXXXXX або 0XXXXXXXXX, або натиснiть кнопку «📱 Подiлитися номером».",
                    reply_markup=kb_phone_request()
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
                await update.message.reply_text(REG_PROMPTS[nxt], reply_markup=kb_phone_request()); return
            await update.message.reply_text(REG_PROMPTS[nxt], reply_markup=kb_skip()); return
        # Пiсля телефону, iменi та авто клiєнт завершив мiнi-реєстрацiю
        save_client(uid, data)
        sto_key = ud.get('reg_sto')
        ud.clear()
        if sto_key:
            ud['write_sto'] = sto_key
            await update.message.reply_text('Дякуємо! Тепер можете написати ваше повiдомлення.', reply_markup=ckb(uid)); return
        await update.message.reply_text('Данi збережено.', reply_markup=ckb(uid)); return

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
        if 'всi клiєнти' in tlo or 'всі клієнти' in tlo:
            recent = []
            cutoff = datetime.now(KYIV_TZ).timestamp() - 7 * 24 * 3600
            for client_uid, item in ctx.bot_data.get('client_activity', {}).items():
                ts = item.get('ts')
                if ts and ts.timestamp() >= cutoff:
                    recent.append((client_uid, item))
            recent.sort(key=lambda x: x[1]['ts'], reverse=True)

            if not recent:
                await update.message.reply_text('За останнi 7 днiв клiєнтiв з активнiстю немає.', reply_markup=kb_staff()); return

            lines = ['Клiєнти за останнi 7 днiв:']
            for client_uid, item in recent:
                lines.append('{} | {} | {} | {}'.format(
                    item['ts'].strftime('%d.%m.%y %H:%M'),
                    item.get('name') or 'Клiєнт',
                    item.get('phone') or 'не вказано',
                    item.get('car') or 'не вказано'
                ))
            await update.message.reply_text('\n'.join(lines[:50]), reply_markup=kb_staff()); return

        if 'медiафайли' in tlo or 'медіафайли' in tlo:
            rows = get_recent_media_sheet()
            if not rows:
                await update.message.reply_text('Медiафайлiв поки немає.', reply_markup=kb_staff()); return

            await update.message.reply_text('Медiафайли за 7 днiв:', reply_markup=kb_staff())

            for r in rows[-20:]:
                file_id = r[3] if len(r) > 3 else ''
                media_type = (r[1] if len(r) > 1 else '').lower()
                caption = send_logged_media_caption(r)
                try:
                    if file_id:
                        if 'фото' in media_type:
                            await ctx.bot.send_photo(chat_id=uid, photo=file_id, caption=caption)
                        elif 'вiдео' in media_type or 'відео' in media_type:
                            await ctx.bot.send_video(chat_id=uid, video=file_id, caption=caption)
                        elif 'голос' in media_type:
                            await ctx.bot.send_voice(chat_id=uid, voice=file_id, caption=caption)
                        elif 'файл' in media_type:
                            await ctx.bot.send_document(chat_id=uid, document=file_id, caption=caption)
                        else:
                            await update.message.reply_text(caption)
                    else:
                        await update.message.reply_text(caption)
                except Exception as e:
                    logger.error('send logged media: %s', e)
                    await update.message.reply_text(caption)
            return

        if 'всi клiєнти' in tlo:
            rows = get_recent_clients_sheet()
            lines = ['Клiєнти за 7 днiв:']
            for r in rows[-50:]:
                lines.append(f"{r[1]} | {r[0]}")
            await update.message.reply_text('\n'.join(lines), reply_markup=kb_staff()); return

        if 'медiафайли' in tlo:
            rows = get_recent_media_sheet()
            lines = ['Медiафайли за 7 днiв:']
            for r in rows[-50:]:
                lines.append(f"{r[2]} | {r[1]} | {r[0]}")
            await update.message.reply_text('\n'.join(lines), reply_markup=kb_staff()); return

        await update.message.reply_text('Оберiть дiю:', reply_markup=kb_staff()); return

    # ── Клiєнт: кнопки меню ───────────────────────────────────
    if is_hours_question(tlo):
        await update.message.reply_text(format_hours_text(), reply_markup=ckb(uid)); return

    if is_address_question(tlo):
        await update.message.reply_text(format_address_text(), reply_markup=ckb(uid)); return

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
        ud['awaiting_mycar_odo'] = True
        lines = ['Ваш автомобiль']
        if client.get('name'):     lines.append('Iм\'я: {}'.format(client['name']))
        if client.get('phone'):    lines.append('Тел.: {}'.format(client['phone']))
        if client.get('car'):      lines.append('Авто: {}'.format(client['car']))
        if client.get('current_odo'): lines.append('Поточний одометр: {} км'.format(client['current_odo']))
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
        await update.message.reply_text('Оберiть, куди хочете написати:', reply_markup=kb_write()); return

    if 'замовити дзв' in tlo or 'замовити звон' in tlo:
        await update.message.reply_text('Оберiть, вiд якого сервiсу потрiбен дзвiнок:', reply_markup=kb_call()); return

    if ud.get('awaiting_mycar_odo'):
        client = get_client(uid)
        odo = parse_int_digits(text)
        if odo:
            client = client or {}
            client['current_odo'] = str(odo)
            save_client(uid, client)
            ud.pop('awaiting_mycar_odo', None)
            await update.message.reply_text(build_maintenance_reply(client, odo), reply_markup=kb_reg()); return
        else:
            await update.message.reply_text('Введiть поточнi показники одометра цифрами.'); return

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
    track_client_activity(ctx, uid, 'text')
    log_client_activity_sheet(uid)
    log_chat(uid, 'client', text)
    await to_staff(ctx.bot, fwd, client_id=uid)

async def handle_media(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    msg = update.message
    ud = ctx.user_data

    if is_staff(uid):
        if ud.get('reply_to'):
            cid = ud.pop('reply_to')
            try:
                await forward_media_to_client(ctx.bot, cid, msg)
            except Exception as e:
                logger.error('forward media to client: %s', e)
                await msg.reply_text('Не вдалося переслати медiафайл клiєнту.', reply_markup=kb_staff())
            return
        await msg.reply_text('Оберiть клiєнта i натиснiть «↩️ Вiдповiсти», перш нiж надсилати медiафайли.', reply_markup=kb_staff())
        return

    if not has_registered_phone(uid):
        ud['reg_step'] = 'phone'
        ud['reg_data'] = ud.get('reg_data', {})
        await msg.reply_text(
            'Щоб розпочати дiалог з менеджером, спочатку подiлiться номером телефону кнопкою нижче.',
            reply_markup=kb_phone_request()
        )
        return

    client = get_client(uid)
    if not client:
        await msg.reply_text(
            'Щоб написати менеджеру, спочатку натиснiть кнопку "💬 Написати менеджеру" нижче.',
            reply_markup=kb_new()
        )
        return

    cname = client.get('name') or 'Клiєнт'
    phone = client.get('phone') or 'не вказано'
    car = client.get('car') or 'не вказано'
    sto = ud.get('write_sto', '')
    sto_s = ' [{}]'.format(CONTACTS[sto]['name']) if sto in CONTACTS else ''
    header = 'Клiєнт надiслав медiафайл{}:\n{} | {} | {}'.format(sto_s, cname, phone, car)

    media_type = detect_media_type(msg)
    track_client_activity(ctx, uid, media_type)
    track_media_log(ctx, uid, media_type)
    log_media_sheet(uid, msg, detect_media_type(msg))
    await forward_media_to_staff(ctx.bot, msg.chat_id, msg.message_id, header, client_id=uid)

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
                    await q.message.reply_text(REG_PROMPTS[nxt], reply_markup=kb_phone_request()); return
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

        photo_path = PHOTO_BODY if sto_key == 'body' else PHOTO_STO

        try:
            if getattr(q.message, 'photo', None) or getattr(q.message, 'text', None):
                await q.message.delete()
        except Exception as e:
            logger.error('delete menu msg: %s', e)

        await send_photo(
            ctx.bot,
            q.message.chat_id,
            photo_path,
            caption=msg,
            reply_markup=kb_svcs(sto_key)
        ); return

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

    if data.startswith('call_'):
        sto_key = data[5:]
        c = CONTACTS.get(sto_key, CONTACTS['sto'])
        client = get_client(uid) or {}
        cname = client.get('name') or 'Клiєнт'
        phone = client.get('phone') or 'не вказано'
        car = client.get('car') or 'не вказано'
        msg = 'Запит на дзвiнок [{}]:\n{} | {} | {}'.format(c['name'], cname, phone, car)
        await to_staff(ctx.bot, msg, client_id=uid)
        await replace_or_send_text(
            q, ctx,
            'Ваш запит вiдправлено. Очiкуйте, будь ласка.',
            reply_markup=None
        ); return

    if data.startswith('write_'):
        sto_key = data[6:]

        if (not is_staff(uid)) and (not has_registered_phone(uid)):
            ud['reg_sto']  = sto_key
            ud['reg_step'] = 'phone'
            ud['reg_data'] = ud.get('reg_data', {})
            await replace_or_send_text(
                q, ctx,
                'Щоб менеджер мiг вам вiдповiсти, спочатку надiшлiть номер телефону кнопкою нижче або введiть його вручну у форматi +380XXXXXXXXX.',
                reply_markup=kb_phone_request()
            ); return

        ud['write_sto'] = sto_key
        c = CONTACTS[sto_key]
        await replace_or_send_text(
            q, ctx,
            'Напишiть ваше питання — менеджер {} вiдповiсть.'.format(c['name'])
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


async def handle_contact(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    contact = update.message.contact
    ud = ctx.user_data

    if not contact:
        return

    if contact.user_id and contact.user_id != uid:
        await update.message.reply_text(
            'Будь ласка, надiшлiть саме свiй номер телефону.',
            reply_markup=kb_phone_request()
        )
        return

    if ud.get('reg_step') != 'phone':
        await update.message.reply_text('Дякуємо. Номер отримано.')
        return

    phone = normalize_ua_phone(contact.phone_number)
    if not phone:
        await update.message.reply_text(
            'Не вдалося розпiзнати номер. Надiшлiть коректний український номер телефону.',
            reply_markup=kb_phone_request()
        )
        return

    data = ud.setdefault('reg_data', {})
    data['phone'] = phone

    client = get_client(uid) or {}
    client.update({'phone': phone})
    save_client(uid, client)

    ud.clear()
    await update.message.reply_text(
        'Дякуємо! Номер телефону збережено. Тепер можете скористатися меню нижче.',
        reply_markup=ckb(uid)
    )



def log_client_activity_sheet(uid):
    try:
        ws = get_ws('Активность')
        ws.append_row([str(uid), now_str()])
    except Exception as e:
        logger.error('log_client_activity_sheet: %s', e)

def log_media_sheet(uid, message, media_type):
    try:
        ws = get_ws('Медиа')
        client = get_client(uid) or {}
        file_id = ''
        caption = message.caption or ''
        if getattr(message, 'photo', None):
            file_id = message.photo[-1].file_id
        elif getattr(message, 'video', None):
            file_id = message.video.file_id
        elif getattr(message, 'voice', None):
            file_id = message.voice.file_id
        elif getattr(message, 'document', None):
            file_id = message.document.file_id

        ws.append_row([
            str(uid),
            media_type,
            now_str(),
            file_id,
            client.get('name') or 'Клiєнт',
            client.get('phone') or 'не вказано',
            client.get('car') or 'не вказано',
            caption
        ])
    except Exception as e:
        logger.error('log_media_sheet: %s', e)

def send_logged_media_caption(row):
    dt = row[2] if len(row) > 2 else ''
    media_type = row[1] if len(row) > 1 else 'Медiа'
    name = row[4] if len(row) > 4 else 'Клiєнт'
    phone = row[5] if len(row) > 5 else 'не вказано'
    car = row[6] if len(row) > 6 else 'не вказано'
    return '{} | {}\n{} | {} | {}'.format(dt, media_type, name, phone, car)

def get_recent_clients_sheet():
    try:
        return get_ws('Активность').get_all_values()[1:]
    except:
        return []

def get_recent_media_sheet():
    try:
        return get_ws('Медиа').get_all_values()[1:]
    except:
        return []


def log_chat(uid, direction, text_msg):
    try:
        ws = get_ws('Чаты')
        ws.append_row([str(uid), direction, now_str(), text_msg])
    except Exception as e:
        logger.error('log_chat: %s', e)

def get_chat(uid):
    try:
        ws = get_ws('Чаты')
        rows = ws.get_all_values()[1:]
        return [r for r in rows if r[0] == str(uid)]
    except:
        return []

def main():

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler('start', cmd_start))
    app.add_handler(CommandHandler('menu',  cmd_start))
    app.add_handler(CommandHandler('help',  cmd_start))
    app.add_handler(CallbackQueryHandler(handle_cb))
    app.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    app.add_handler(MessageHandler((filters.PHOTO | filters.VIDEO | filters.VOICE | filters.Document.ALL), handle_media))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    logger.info('v7 start | claude=%s | staff=%s', bool(claude_client), STAFF_IDS)
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
