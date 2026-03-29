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

# Все сотрудники = мастера + владелец
STAFF_IDS = list(set(MASTER_IDS + ([OWNER_ID] if OWNER_ID else [])))

CLAUDE_API_KEY = os.environ.get('CLAUDE_API_KEY')
claude_client  = anthropic.Anthropic(api_key=CLAUDE_API_KEY) if CLAUDE_API_KEY else None

# Два СТО
STO_INFO = {
    'sto': {
        'name':     'СТО Farro',
        'address':  'вул. Богдана Хмельницького 4а (лівий берег)',
        'maps':     'https://maps.app.goo.gl/yzXq7rwV2sB9SkRj9',
        'hours':    'ПН-ПТ 09:00-18:00',
        'services': [
            'ГБО',
            'Розвал-сходження 3D',
            'Автокондиціонери',
            'Ремонт ходової',
            'Зварювальні роботи',
            'Двигуни',
            'Пайка пластику',
            'Інше',
        ],
    },
    'body': {
        'name':     'Кузовний сервіс Farro',
        'address':  'вул. Павла Чубинського 2а',
        'maps':     'https://maps.app.goo.gl/xe7u4vD1tvSg6buy6',
        'hours':    'ПН-ПТ 09:00-18:00',
        'services': [
            'Рихтування авто',
            'Покраска авто',
            'Видалення вм\'ятин без покраски (PDR)',
            'Інше',
        ],
    },
}

# Маршрутизація заявок: всі мастери поки = OWNER_ID
# Пізніше можна налаштувати окремі ID для кожної послуги
SERVICE_ROUTING: Dict[str, List[int]] = {
    'ГБО':                             STAFF_IDS,
    'Розвал-сходження 3D':             STAFF_IDS,
    'Автокондиціонери':                STAFF_IDS,
    'Ремонт ходової':                  STAFF_IDS,
    'Зварювальні роботи':              STAFF_IDS,
    'Двигуни':                         STAFF_IDS,
    'Пайка пластику':                  STAFF_IDS,
    'Рихтування авто':                 STAFF_IDS,
    'Покраска авто':                   STAFF_IDS,
    'Видалення вм\'ятин без покраски (PDR)': STAFF_IDS,
    'Інше':                            STAFF_IDS,
}

def polish_master_reply(raw_text: str) -> str:
    logger.info('polish_master_reply called. claude_client={}'.format(claude_client is not None))
    if not claude_client:
        logger.warning('claude_client is None - CLAUDE_API_KEY not set or empty')
        return raw_text
    try:
        prompt = (
            'Ти ввічливий менеджер автосервісу Farro. '
            'Майстер написав відповідь клієнту: ' + raw_text + '. '
            'Перепиши українською мовою красиво, ввічливо, зрозуміло, без помилок. '
            'Збережи зміст. Тільки готовий текст без пояснень.'
        )
        resp = claude_client.messages.create(
            model='claude-sonnet-4-20250514',
            max_tokens=300,
            messages=[{'role': 'user', 'content': prompt}]
        )
        result = resp.content[0].text.strip()
        logger.info('polish result: {}'.format(result[:50]))
        return result if result else raw_text
    except Exception as e:
        logger.error('polish_master_reply error: {}'.format(e))
        return raw_text


def get_routing(service: str) -> List[int]:
    ids = SERVICE_ROUTING.get(service, STAFF_IDS)
    if OWNER_ID and OWNER_ID not in ids:
        ids = ids + [OWNER_ID]
    return list(set(ids))


# ── Google Sheets ─────────────────────────────────────────────

def open_sheet():
    d = json.loads(GOOGLE_CREDS)
    scopes = ['https://spreadsheets.google.com/feeds',
              'https://www.googleapis.com/auth/drive']
    creds = Credentials.from_service_account_info(d, scopes=scopes)
    return gspread.authorize(creds).open_by_key(SPREADSHEET_ID)

def get_ws(name: str):
    sp = open_sheet()
    for ws in sp.worksheets():
        if ws.title.lower() == name.lower():
            return ws
    return sp.sheet1

def now_str() -> str:
    return datetime.now(KYIV_TZ).strftime('%d.%m.%y %H:%M')

def today_str() -> str:
    return datetime.now(KYIV_TZ).strftime('%d.%m.%y')

def parse_num(v) -> Optional[int]:
    s = re.sub(r'[^\d]', '', str(v or ''))
    try: return int(s) if s else None
    except: return None

def is_staff(uid: int) -> bool:
    return uid in STAFF_IDS


# ── Клієнти ──────────────────────────────────────────────────
# Колонки: A=TgID, B=Ім'я, C=Телефон, D=Номер авто, E=Марка, F=Дата реєстрації

def get_client(tg_id: int) -> Optional[Dict]:
    ws = get_ws('Клиенты')
    for row in ws.get_all_values()[1:]:
        if str(row[0]).strip() == str(tg_id):
            return {
                'tg_id': row[0],
                'name':  row[1] if len(row) > 1 else '',
                'phone': row[2] if len(row) > 2 else '',
                'car':   row[3] if len(row) > 3 else '',
                'model': row[4] if len(row) > 4 else '',
            }
    return None

def save_client(tg_id: int, name: str, phone: str, car: str, model: str):
    ws   = get_ws('Клиенты')
    rows = ws.get_all_values()
    for i, row in enumerate(rows[1:], start=2):
        if str(row[0]).strip() == str(tg_id):
            ws.update('B{}:F{}'.format(i,i), [[name, phone, car.upper(), model, today_str()]])
            return
    ws.append_row([str(tg_id), name, phone, car.upper(), model, today_str()])

def find_client_by_car(car: str) -> Optional[Dict]:
    ws = get_ws('Клиенты')
    cc = car.upper().replace(' ', '')
    for row in ws.get_all_values()[1:]:
        if len(row) > 3 and cc in str(row[3]).upper().replace(' ', ''):
            return {'tg_id': row[0], 'name': row[1], 'car': row[3]}
    return None


# ── Заявки ───────────────────────────────────────────────────
# Колонки: A=ID, B=Дата, C=TgID клієнта, D=Ім'я, E=Авто,
#          F=СТО, G=Послуга, H=Побажання, I=Статус, J=Майстер

def gen_request_id() -> str:
    rows = get_ws('Заказы').get_all_values()
    num  = len([r for r in rows[1:] if r and r[0]]) + 1
    return 'REQ-{:04d}'.format(num)

def save_request(tg_id: int, client_name: str, car: str,
                 sto_key: str, service: str, wish: str) -> str:
    rid = gen_request_id()
    get_ws('Заказы').append_row([
        rid, now_str(), str(tg_id), client_name,
        car, STO_INFO[sto_key]['name'], service, wish, 'new', ''
    ])
    return rid

def get_requests_by_client(tg_id: int) -> List[Dict]:
    result = []
    for row in get_ws('Заказы').get_all_values()[1:]:
        if len(row) > 2 and str(row[2]).strip() == str(tg_id):
            result.append({
                'id':      row[0], 'date': row[1],
                'sto':     row[5] if len(row) > 5 else '',
                'service': row[6] if len(row) > 6 else '',
                'wish':    row[7] if len(row) > 7 else '',
                'status':  row[8] if len(row) > 8 else '',
            })
    return result[-5:]

def get_orders_by_car(car: str) -> List[Dict]:
    cc = car.upper().replace(' ', '')
    result = []
    for row in get_ws('Заказы').get_all_values()[1:]:
        if len(row) > 4 and cc in str(row[4]).upper().replace(' ', ''):
            result.append({
                'id':      row[0], 'date': row[1],
                'service': row[6] if len(row) > 6 else '',
                'status':  row[8] if len(row) > 8 else '',
            })
    return result[-5:]


# ── Клавіатури ───────────────────────────────────────────────

def kb_welcome():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('🔍 Дізнатися статус мого авто', callback_data='w_status')],
        [InlineKeyboardButton('📝 Записатися на послугу',      callback_data='w_new')],
    ])

def kb_main_client():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('📊 Статус мого авто',      callback_data='c_status')],
        [InlineKeyboardButton('📝 Записатися на послугу', callback_data='w_new')],
        [InlineKeyboardButton('📋 Мої заявки',            callback_data='c_requests')],
        [InlineKeyboardButton('💬 Написати майстру',      callback_data='c_contact')],
    ])

def kb_choose_sto():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('🔧 СТО (ГБО, Ходова, Кондиціонери...)',   callback_data='sto_sto')],
        [InlineKeyboardButton('🚗 Кузовний сервіс (Рихтування, Покраска, PDR)', callback_data='sto_body')],
    ])

def kb_services(sto_key: str):
    services = STO_INFO[sto_key]['services']
    buttons  = []
    for svc in services:
        buttons.append([InlineKeyboardButton(svc, callback_data='svc_{}_{}'.format(sto_key, svc[:30]))])
    return InlineKeyboardMarkup(buttons)

def kb_staff_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('📋 Нові заявки',              callback_data='s_new')],
        [InlineKeyboardButton('✅ Підтвердити запис',        callback_data='s_confirm')],
        [InlineKeyboardButton('🔧 Авто в роботі',           callback_data='s_inwork')],
        [InlineKeyboardButton('🏁 Авто готове',             callback_data='s_ready')],
        [InlineKeyboardButton('📊 Всі активні',             callback_data='s_all')],
    ])

def kb_cancel():
    return InlineKeyboardMarkup([[InlineKeyboardButton('❌ Скасувати', callback_data='cancel')]])


# ── Надсилання повідомлень ────────────────────────────────────

async def notify_staff(bot, service: str, message: str, client_id: int = None):
    recipients = get_routing(service)
    # Кнопка "Відповісти клієнту" якщо є client_id
    kb = None
    if client_id:
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                'Відповісти клієнту',
                callback_data='reply_{}'.format(client_id))
        ]])
    for uid in recipients:
        try:
            await bot.send_message(chat_id=uid, text=message, reply_markup=kb)
        except Exception as e:
            logger.error('notify_staff {}: {}'.format(uid, e))

async def notify_owner(bot, message: str):
    if OWNER_ID:
        try:
            await bot.send_message(chat_id=OWNER_ID, text=message)
        except Exception as e:
            logger.error('notify_owner: {}'.format(e))


# ── Handlers ─────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    name = update.effective_user.first_name or 'Клієнт'
    ctx.user_data.clear()

    if is_staff(uid):
        await update.message.reply_text(
            'Привіт, {}!\nID: {}\n\nПанель управління СТО Farro 🔥'.format(name, uid),
            reply_markup=kb_staff_main())
        return

    client = get_client(uid)
    if client:
        await update.message.reply_text(
            'З поверненням, {}! 👋\n\nЧим можу допомогти?'.format(client['name']),
            reply_markup=kb_main_client())
    else:
        await update.message.reply_text(
            'Вітаємо в СТО Farro 🔥\n\nВи вже здавали до нас авто?',
            reply_markup=kb_welcome())

async def handle_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    text = (update.message.text or '').strip()
    ud   = ctx.user_data

    # ── Реєстрація ────────────────────────────────────────────
    if ud.get('reg_step') == 'name':
        ud['reg_name'] = text
        ud['reg_step'] = 'phone'
        await update.message.reply_text('Ваш номер телефону?')
        return

    if ud.get('reg_step') == 'phone':
        ud['reg_phone'] = text
        ud['reg_step']  = 'car'
        await update.message.reply_text('Номер вашого авто? (наприклад АА1234ВВ)\nЯкщо авто немає — напишіть прочерк -')
        return

    if ud.get('reg_step') == 'car':
        ud['reg_car']  = text.upper() if text != '-' else ''
        ud['reg_step'] = 'model'
        await update.message.reply_text('Марка і модель? (наприклад Toyota Camry)\nЯкщо не знаєте — напишіть прочерк -')
        return

    if ud.get('reg_step') == 'model':
        save_client(uid, ud['reg_name'], ud['reg_phone'], ud.get('reg_car',''), text if text != '-' else '')
        name = ud['reg_name']
        ud.clear()
        await update.message.reply_text(
            'Дякуємо, {}! Ви зареєстровані. 👍\n\nЧим можу допомогти?'.format(name),
            reply_markup=kb_main_client())
        return

    # ── Пошук авто для статусу ────────────────────────────────
    if ud.get('wait_car_status'):
        ud.pop('wait_car_status')
        orders = get_orders_by_car(text)
        if not orders:
            await update.message.reply_text(
                'Авто {} не знайдено в наших записах.\n\nХочете записатися на послугу?'.format(text.upper()),
                reply_markup=kb_main_client())
            return
        lines = ['📋 Статус авто {}:\n'.format(text.upper())]
        status_icons = {'new':'🆕','confirmed':'✅','in_work':'🔧','ready':'🏁','issued':'🚗'}
        for o in reversed(orders):
            icon = status_icons.get(o['status'], '📌')
            lines.append('{} {} | {} | {}'.format(icon, o['date'], o['service'], o['status']))
        await update.message.reply_text('\n'.join(lines), reply_markup=kb_main_client())
        return

    # ── Побажання клієнта при записі ─────────────────────────
    if ud.get('wait_wish'):
        sto_key = ud.get('selected_sto')
        service = ud.get('selected_service')
        wish    = text
        ud.pop('wait_wish', None)

        client  = get_client(uid)
        cname   = client['name'] if client else str(uid)
        car     = client['car']  if client else 'не вказано'

        rid = save_request(uid, cname, car, sto_key, service, wish)

        sto = STO_INFO[sto_key]
        msg = (
            '🔔 НОВА ЗАЯВКА {}\n\n'
            '👤 Клієнт: {}\n'
            '🚗 Авто: {}\n'
            '🏠 СТО: {}\n'
            '📍 {}\n'
            '🔧 Послуга: {}\n'
            '💬 Побажання: {}\n'
            '🕐 {}'
        ).format(rid, cname, car, sto['name'], sto['address'], service, wish, now_str())

        await notify_staff(ctx.bot, service, msg, client_id=uid)

        await update.message.reply_text(
            'Вашу заявку прийнято! ✅\n\n'
            '🔖 Номер заявки: {}\n'
            '🔧 Послуга: {}\n'
            '🏠 {}\n'
            '📍 {}\n'
            '🕐 {}\n\n'
            'Наш майстер звʼяжеться з вами найближчим часом для підтвердження.'.format(
                rid, service, sto['name'], sto['address'], sto['hours']),
            reply_markup=kb_main_client())
        return

    # ── Повідомлення майстру від клієнта ─────────────────────
    if ud.get('wait_client_msg'):
        ud.pop('wait_client_msg')
        client = get_client(uid)
        cname  = client['name'] if client else str(uid)
        car    = client['car']  if client else 'не вказано'

        fwd = '💬 Повідомлення від клієнта:\n👤 {} | 🚗 {}\n\n{}'.format(cname, car, text)
        kb_reply = InlineKeyboardMarkup([[InlineKeyboardButton('Відповісти клієнту', callback_data='reply_{}'.format(uid))]])
        for mid in STAFF_IDS:
            try: await ctx.bot.send_message(chat_id=mid, text=fwd, reply_markup=kb_reply)
            except Exception as e: logger.error('fwd: {}'.format(e))

        await update.message.reply_text(
            'Повідомлення надіслано майстру. ✅\nОчікуйте відповіді.',
            reply_markup=kb_main_client())
        return

    # ── Відповідь майстра клієнту ─────────────────────────────
    if ud.get('wait_reply_to'):
        client_id = ud.pop('wait_reply_to')
        try:
            await update.message.reply_text('Обробляю відповідь...')
            polished = polish_master_reply(text)
            await ctx.bot.send_message(chat_id=client_id,
                text='💬 Відповідь від майстра СТО Farro:\n\n' + polished)
            info = 'Відповідь надіслано. ✅\n\nВаш текст: ' + text + '\n\nНадіслано клієнту: ' + polished
            await update.message.reply_text(info, reply_markup=kb_staff_main())
        except Exception as e:
            await update.message.reply_text('Помилка: {}'.format(e), reply_markup=kb_staff_main())
        return
    if ud.get('wait_confirm_id'):
        rid = text.strip().upper()
        ud.pop('wait_confirm_id')
        ws   = get_ws('Заказы')
        rows = ws.get_all_values()
        found = False
        for i, row in enumerate(rows[1:], start=2):
            if str(row[0]).strip() == rid:
                ws.update('I{}'.format(i), [['confirmed']])
                client_id = str(row[2]).strip() if len(row) > 2 else None
                service   = row[6] if len(row) > 6 else ''
                found = True
                if client_id:
                    try:
                        await ctx.bot.send_message(
                            chat_id=int(client_id),
                            text='✅ Ваш запис підтверджено!\n\n'
                                 '🔖 Заявка: {}\n'
                                 '🔧 Послуга: {}\n\n'
                                 'Чекаємо вас! СТО Farro 🔥'.format(rid, service))
                    except Exception as e: logger.error('confirm notify: {}'.format(e))
                break
        if found:
            await update.message.reply_text('Запис {} підтверджено. Клієнта повідомлено. ✅'.format(rid),
                                            reply_markup=kb_staff_main())
        else:
            await update.message.reply_text('Заявку {} не знайдено.'.format(rid), reply_markup=kb_staff_main())
        return

    # ── За замовчуванням ──────────────────────────────────────
    if is_staff(uid):
        await update.message.reply_text('Оберіть дію:', reply_markup=kb_staff_main())
    else:
        await update.message.reply_text('Оберіть дію:', reply_markup=kb_main_client())


async def handle_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    uid  = q.from_user.id
    data = q.data
    await q.answer()
    ud = ctx.user_data

    if data == 'cancel':
        ud.clear()
        kb = kb_staff_main() if is_staff(uid) else kb_main_client()
        await q.edit_message_text('Скасовано.', reply_markup=kb)
        return

    # ── Вітальне меню ─────────────────────────────────────────
    if data == 'w_status':
        ud['wait_car_status'] = True
        await q.edit_message_text(
            'Введіть номер вашого авто (наприклад АА1234ВВ):',
            reply_markup=kb_cancel())
        return

    if data == 'w_new':
        client = get_client(uid)
        if not client:
            ud['reg_step'] = 'name'
            await q.edit_message_text(
                'Для запису потрібна реєстрація.\nЯк вас звати?',
                reply_markup=kb_cancel())
        else:
            await q.edit_message_text(
                'Оберіть СТО:',
                reply_markup=kb_choose_sto())
        return

    # ── Вибір СТО ─────────────────────────────────────────────
    if data.startswith('sto_'):
        sto_key = data[4:]
        if sto_key not in STO_INFO:
            await q.edit_message_text('Невідоме СТО.')
            return
        ud['selected_sto'] = sto_key
        sto = STO_INFO[sto_key]
        await q.edit_message_text(
            '{}\n📍 {}\n🗺 {}\n🕐 {}\n\nОберіть послугу:'.format(
                sto['name'], sto['address'], sto['maps'], sto['hours']),
            reply_markup=kb_services(sto_key))
        return

    # ── Вибір послуги ─────────────────────────────────────────
    if data.startswith('svc_'):
        parts   = data[4:].split('_', 1)
        sto_key = parts[0]
        service = parts[1] if len(parts) > 1 else 'Інше'

        # Знаходимо повну назву послуги
        for svc in STO_INFO.get(sto_key, {}).get('services', []):
            if svc[:30] == service:
                service = svc
                break

        ud['selected_sto']     = sto_key
        ud['selected_service'] = service
        ud['wait_wish']        = True
        await q.edit_message_text(
            'Послуга: {}\n\nОпишіть коротко що сталось або що потрібно зробити.\nТакож вкажіть зручний час для запису:'.format(service),
            reply_markup=kb_cancel())
        return

    # ── Клієнтське меню ───────────────────────────────────────
    if data == 'c_status':
        client = get_client(uid)
        if not client:
            await q.edit_message_text('Спочатку зареєструйтесь — /start')
            return
        if not client['car']:
            ud['wait_car_status'] = True
            await q.edit_message_text(
                'Введіть номер авто для перевірки:',
                reply_markup=kb_cancel())
            return
        orders = get_orders_by_car(client['car'])
        if not orders:
            await q.edit_message_text(
                'Активних заявок для {} не знайдено.'.format(client['car']),
                reply_markup=kb_main_client())
            return
        status_icons = {'new':'🆕','confirmed':'✅','in_work':'🔧','ready':'🏁','issued':'🚗'}
        lines = ['📋 Статус авто {}:\n'.format(client['car'])]
        for o in reversed(orders):
            icon = status_icons.get(o['status'], '📌')
            lines.append('{} {} | {}'.format(icon, o['date'], o['service']))
        await q.edit_message_text('\n'.join(lines), reply_markup=kb_main_client())
        return

    if data == 'c_requests':
        requests = get_requests_by_client(uid)
        if not requests:
            await q.edit_message_text('Заявок не знайдено.', reply_markup=kb_main_client())
            return
        lines = ['📋 Ваші останні заявки:\n']
        status_icons = {'new':'🆕','confirmed':'✅','in_work':'🔧','ready':'🏁','issued':'🚗'}
        for r in reversed(requests):
            icon = status_icons.get(r['status'], '📌')
            lines.append('{} {} | {} | {}'.format(icon, r['date'], r['service'], r['sto']))
        await q.edit_message_text('\n'.join(lines), reply_markup=kb_main_client())
        return

    if data == 'c_contact':
        ud['wait_client_msg'] = True
        await q.edit_message_text(
            'Напишіть ваше питання — майстер відповість найближчим часом:',
            reply_markup=kb_cancel())
        return

    # ── Панель мастера ────────────────────────────────────────
    if not is_staff(uid):
        await q.edit_message_text('Немає доступу.')
        return

    # ── Відповідь клієнту через бота ─────────────────────────
    if data.startswith('reply_'):
        client_id = int(data[6:])
        ud['wait_reply_to'] = client_id
        msg_txt = 'Напишіть відповідь клієнту. Клієнт отримає її від імені бота СТО Farro:'
        await q.edit_message_text(msg_txt, reply_markup=kb_cancel())
        return

    if data == 's_new':
        ws    = get_ws('Заказы')
        rows  = ws.get_all_values()
        new_r = [r for r in rows[1:] if len(r) > 8 and r[8] == 'new']
        if not new_r:
            await q.edit_message_text('Нових заявок немає.', reply_markup=kb_staff_main())
            return
        lines = ['🆕 Нові заявки: {}\n'.format(len(new_r))]
        for r in new_r:
            lines.append('🔖 {} | {} | {} | {}'.format(r[0], r[3], r[6], r[1]))
        await q.edit_message_text('\n'.join(lines), reply_markup=kb_staff_main())
        return

    if data == 's_confirm':
        ud['wait_confirm_id'] = True
        await q.edit_message_text(
            'Введіть номер заявки для підтвердження (наприклад REQ-0001):',
            reply_markup=kb_cancel())
        return

    if data == 's_inwork':
        ws   = get_ws('Заказы')
        rows = ws.get_all_values()
        active = [r for r in rows[1:] if len(r) > 8 and r[8] in ('confirmed', 'in_work')]
        if not active:
            await q.edit_message_text('Немає авто в роботі.', reply_markup=kb_staff_main())
            return
        lines = ['🔧 В роботі: {}\n'.format(len(active))]
        for r in active:
            lines.append('🔖 {} | {} | {}'.format(r[0], r[3], r[6]))
        # Кнопки для кожної заявки
        buttons = []
        for r in active:
            buttons.append([InlineKeyboardButton(
                'Готово: {} — {}'.format(r[0], r[3]),
                callback_data='ready_{}'.format(r[0]))])
        buttons.append([InlineKeyboardButton('⬅️ Назад', callback_data='s_all')])
        await q.edit_message_text('\n'.join(lines), reply_markup=InlineKeyboardMarkup(buttons))
        return

    if data == 's_ready':
        ws   = get_ws('Заказы')
        rows = ws.get_all_values()
        active = [r for r in rows[1:] if len(r) > 8 and r[8] in ('confirmed', 'in_work', 'new')]
        buttons = []
        for r in active[:10]:
            buttons.append([InlineKeyboardButton(
                '{} — {} | {}'.format(r[0], r[3], r[6]),
                callback_data='ready_{}'.format(r[0]))])
        buttons.append([InlineKeyboardButton('❌ Скасувати', callback_data='cancel')])
        await q.edit_message_text(
            'Оберіть заявку яка готова:',
            reply_markup=InlineKeyboardMarkup(buttons))
        return

    if data.startswith('ready_'):
        rid  = data[6:]
        ws   = get_ws('Заказы')
        rows = ws.get_all_values()
        for i, row in enumerate(rows[1:], start=2):
            if str(row[0]).strip() == rid:
                ws.update('I{}'.format(i), [['ready']])
                client_id = str(row[2]).strip() if len(row) > 2 else None
                cname     = row[3] if len(row) > 3 else ''
                car       = row[4] if len(row) > 4 else ''
                service   = row[6] if len(row) > 6 else ''
                sto_name  = row[5] if len(row) > 5 else ''
                if client_id:
                    try:
                        await ctx.bot.send_message(
                            chat_id=int(client_id),
                            text='🏁 Ваш автомобіль готовий!\n\n'
                                 '🚗 Авто: {}\n'
                                 '🔧 Послуга: {}\n'
                                 '🏠 {}\n\n'
                                 'Чекаємо вас! СТО Farro 🔥'.format(car, service, sto_name))
                    except Exception as e: logger.error('ready notify: {}'.format(e))
                await q.edit_message_text(
                    'Заявка {} відмічена як готова. ✅\nКлієнта {} повідомлено.'.format(rid, cname),
                    reply_markup=kb_staff_main())
                return
        await q.edit_message_text('Заявку не знайдено.', reply_markup=kb_staff_main())
        return

    if data == 's_all':
        ws    = get_ws('Заказы')
        rows  = ws.get_all_values()
        active = [r for r in rows[1:] if len(r) > 8 and r[8] not in ('issued', '')]
        if not active:
            await q.edit_message_text('Активних заявок немає.', reply_markup=kb_staff_main())
            return
        status_icons = {'new':'🆕','confirmed':'✅','in_work':'🔧','ready':'🏁'}
        lines = ['📋 Всі активні заявки: {}\n'.format(len(active))]
        for r in active:
            icon = status_icons.get(r[8], '📌')
            lines.append('{} {} | {} | {}'.format(icon, r[0], r[3], r[6]))
        await q.edit_message_text('\n'.join(lines), reply_markup=kb_staff_main())
        return


async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_staff(uid):
        await update.message.reply_text('Панель управління:', reply_markup=kb_staff_main())
    else:
        await update.message.reply_text('Меню:', reply_markup=kb_main_client())


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler('start', cmd_start))
    app.add_handler(CommandHandler('menu',  cmd_menu))
    app.add_handler(CallbackQueryHandler(handle_cb))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    logger.info('СТО бот {} запущен!'.format(STO_NAME))
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
