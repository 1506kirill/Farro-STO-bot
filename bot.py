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
        'name':    'Ð¡Ð¢Ð Farro',
        'address': 'Ð²ÑÐ». ÐÐ¾Ð³Ð´Ð°Ð½Ð° Ð¥Ð¼ÐµÐ»ÑÐ½Ð¸ÑÑÐºÐ¾Ð³Ð¾ 4Ð° (Ð»iÐ²Ð¸Ð¹ Ð±ÐµÑÐµÐ³)',
        'note':    '',
        'maps':    'https://maps.app.goo.gl/yzXq7rwV2sB9SkRj9',
        'hours':   'ÐÐ-ÐÐ¢ 09:00-18:00',
    },
    'body': {
        'name':    'ÐÑÐ·Ð¾Ð²Ð½Ð¸Ð¹ ÑÐµÑÐ²iÑ Farro',
        'address': 'Ð²ÑÐ». ÐÐ°Ð²Ð»Ð° Ð§ÑÐ±Ð¸Ð½ÑÑÐºÐ¾Ð³Ð¾ 2Ð°',
        'note':    '(Ð²ÐµÑÑ Ð²ÑÐ». Ð Ð¾Ð±Ð¾ÑÐ°)',
        'maps':    'https://maps.app.goo.gl/xe7u4vD1tvSg6buy6',
        'hours':   'ÐÐ-ÐÐ¢ 09:00-18:00',
    },
}

PHOTO_BODY = '/app/photo_body.jpg'
PHOTO_STO  = '/app/photo_sto.jpg'
_photo_cache: Dict[str, str] = {}

SERVICES = {
    'sto': [
        {'id':'gbo',    'name':'ÐÐÐ â Ð³Ð°Ð·Ð¾Ð²Ðµ Ð¾Ð±Ð»Ð°Ð´Ð½Ð°Ð½Ð½Ñ',
         'text':'ÐÑÑÐ°Ð½Ð¾Ð²Ð»ÐµÐ½Ð½Ñ ÑÐ° Ð¾Ð±ÑÐ»ÑÐ³Ð¾Ð²ÑÐ²Ð°Ð½Ð½Ñ ÐÐÐ\n\nÐÑÑÐ°Ð½Ð¾Ð²Ð»ÐµÐ½Ð½Ñ ÐÐÐ Ð½Ð° 4 ÑÐ¸Ð»iÐ½Ð´ÑÐ¸ â Ð²iÐ´ 19 600 Ð³ÑÐ½\nÐÑÑÐ°Ð½Ð¾Ð²Ð»ÐµÐ½Ð½Ñ ÐÐÐ Ð½Ð° 6 ÑÐ¸Ð»iÐ½Ð´ÑiÐ² â Ð²iÐ´ 30 500 Ð³ÑÐ½\nÐÐ»Ð°Ð½Ð¾Ð²Ðµ Ð¢Ð ÐÐÐ â Ð²iÐ´ 650 Ð³ÑÐ½\nÐÐ¾Ð¼Ð¿\'ÑÑÐµÑÐ½Ð° Ð´iÐ°Ð³Ð½Ð¾ÑÑÐ¸ÐºÐ° â 400 Ð³ÑÐ½\nÐ¡ÐµÑÑÐ¸ÑiÐºÐ°ÑiÑ ÐÐÐ â 3 000 Ð³ÑÐ½\n\nÐÐ°Ð¹Ð±iÐ»ÑÑÐ¸Ð¹ ÑÐºÐ»Ð°Ð´ ÐÐÐ Ð² Ð¾Ð±Ð»Ð°ÑÑi.\n\nhttps://farro.ua/install/'},
        {'id':'cond',   'name':'ÐÐ²ÑÐ¾ÐºÐ¾Ð½Ð´Ð¸ÑiÐ¾Ð½ÐµÑÐ¸',
         'text':'ÐiÐ°Ð³Ð½Ð¾ÑÑÐ¸ÐºÐ° ÑÐ° ÑÐµÐ¼Ð¾Ð½Ñ ÐºÐ¾Ð½Ð´Ð¸ÑiÐ¾Ð½ÐµÑiÐ²\n\nÐiÐ°Ð³Ð½Ð¾ÑÑÐ¸ÐºÐ° ÑÐ° Ð¿iÐ´ÐºÐ»ÑÑÐµÐ½Ð½Ñ â 400 Ð³ÑÐ½\n1 Ð³Ñ ÑÑÐµÐ¾Ð½Ñ â 1,8 Ð³ÑÐ½\n1 Ð³Ñ ÐºÐ¾Ð¼Ð¿ÑÐµÑÐ¾ÑÐ½Ð¾Ð³Ð¾ Ð¼Ð°ÑÐ»Ð° â 10 Ð³ÑÐ½\n\nÐ¢Ð°ÐºÐ¾Ð¶:\nÐ ÐµÐ¼Ð¾Ð½Ñ ÑÑÑÐ±Ð¾Ðº ÐºÐ¾Ð½Ð´Ð¸ÑiÐ¾Ð½ÐµÑÐ°\nÐÐ¾ÑÑÐº Ð²Ð¸ÑÐ¾ÐºÑ ÑÑÐµÐ¾Ð½Ñ\nÐÑÐ¾Ð¼Ð¸Ð²ÐºÐ° ÑÐ¸ÑÑÐµÐ¼Ð¸ ÐºÐ¾Ð½Ð´Ð¸ÑiÐ¾Ð½ÑÐ²Ð°Ð½Ð½Ñ\n\nÐÐ°Ð¶Ð»Ð¸Ð²Ð¾: ÑÐ¾ÑÐ½Ð° ÐºiÐ»ÑÐºiÑÑÑ ÑÑÐµÐ¾Ð½Ñ Ð²Ð¸Ð·Ð½Ð°ÑÐ°ÑÑÑÑÑ Ð»Ð¸ÑÐµ Ð¿iÑÐ»Ñ Ð²iÐ´ÐºÐ°ÑÑÐ²Ð°Ð½Ð½Ñ ÑÐ° Ð·Ð²Ð°Ð¶ÑÐ²Ð°Ð½Ð½Ñ.\n\nhttps://farro.ua/kondicionery/'},
        {'id':'engine', 'name':'ÐÐ²Ð¸Ð³ÑÐ½Ð¸',
         'text':'ÐiÐ°Ð³Ð½Ð¾ÑÑÐ¸ÐºÐ° ÑÐ° ÑÐµÐ¼Ð¾Ð½Ñ Ð´Ð²Ð¸Ð³ÑÐ½iÐ²\n\nÐÐ°Ð¼iÐ½Ð° Ð¼Ð¾ÑÐ¾ÑÐ½Ð¾Ð³Ð¾ Ð¼Ð°ÑÐ»Ð° â 400 Ð³ÑÐ½\nÐÐ¾Ð¼Ð¿\'ÑÑÐµÑÐ½Ð° Ð´iÐ°Ð³Ð½Ð¾ÑÑÐ¸ÐºÐ° â 400 Ð³ÑÐ½\nÐÐ°Ð¼iÐ½Ð° ÐÐ Ð â Ð²iÐ´ 3 500 Ð³ÑÐ½\nÐ ÐµÐ³ÑÐ»ÑÐ²Ð°Ð½Ð½Ñ ÐºÐ»Ð°Ð¿Ð°Ð½iÐ² â Ð²iÐ´ 1 500 Ð³ÑÐ½\nÐiÐ°Ð³Ð½Ð¾ÑÑÐ¸ÐºÐ° ÐµÐ½Ð´Ð¾ÑÐºÐ¾Ð¿Ð¾Ð¼ â Ð²iÐ´ 1 500 Ð³ÑÐ½\nÐÐ°Ð¼iÑ ÐºÐ¾Ð¼Ð¿ÑÐµÑiÑ â Ð²iÐ´ 1 200 Ð³ÑÐ½\n\nhttps://farro.ua/kondicionery/'},
        {'id':'wheel',  'name':'Ð Ð¾Ð·Ð²Ð°Ð»-ÑÑÐ¾Ð´Ð¶ÐµÐ½Ð½Ñ 3D',
         'text':'Ð¢Ð¾ÑÐ½Ðµ ÑÐµÐ³ÑÐ»ÑÐ²Ð°Ð½Ð½Ñ ÐºÑÑiÐ² Ð²ÑÑÐ°Ð½Ð¾Ð²Ð»ÐµÐ½Ð½Ñ ÐºÐ¾Ð»iÑ\n\nÐÐ´Ð½Ð° Ð²iÑÑ â Ð²iÐ´ 600 Ð³ÑÐ½\nÐÐ²i Ð¾Ñi â 1 000 Ð³ÑÐ½\n\nhttps://farro.ua/razval-shozhdenie/'},
        {'id':'cool',   'name':'ÐÑÐ¾Ð¼Ð¸Ð²ÐºÐ° ÑÐ¸ÑÑÐµÐ¼Ð¸ Ð¾ÑÐ¾Ð»Ð¾Ð´Ð¶ÐµÐ½Ð½Ñ',
         'text':'ÐÑÐ¾Ð¼Ð¸Ð²ÐºÐ° ÑÐ° Ð·Ð°Ð¼iÐ½Ð° Ð°Ð½ÑÐ¸ÑÑÐ¸Ð·Ñ\n\nÐÐ°Ð¼iÐ½Ð° Ð°Ð½ÑÐ¸ÑÑÐ¸Ð·Ñ â Ð²iÐ´ 600 Ð³ÑÐ½\nÐÐ¾ÑÑÐº Ð²Ð¸ÑÐ¾ÐºÑ Ð°Ð½ÑÐ¸ÑÑÐ¸Ð·Ñ â 700 Ð³ÑÐ½\nÐÑÐ¾Ð¼Ð¸Ð²ÐºÐ° ÑÐ°Ð´iÐ°ÑÐ¾ÑÐ° Ð¿iÑÐºÐ¸ â Ð²iÐ´ 1 700 Ð³ÑÐ½\nÐÑÐ¾Ð¼Ð¸Ð²ÐºÐ° Ð²ÑiÑÑ ÑÐ¸ÑÑÐµÐ¼Ð¸ â Ð²iÐ´ 4 000 Ð³ÑÐ½\n\nhttps://farro.ua/promyvka-ohlazhdeniya/'},
        {'id':'lights', 'name':'Ð ÐµÐ¼Ð¾Ð½Ñ ÑÐ°Ñ ÑÐ° Ð±Ð°Ð¼Ð¿ÐµÑiÐ²',
         'text':'Ð ÐµÐ¼Ð¾Ð½Ñ ÑÐ° Ð¿Ð¾Ð»iÑÑÐ²Ð°Ð½Ð½Ñ ÑÐ°Ñ i Ð±Ð°Ð¼Ð¿ÐµÑiÐ²\n\nÐÐ¾Ð»iÑÑÐ²Ð°Ð½Ð½Ñ ÑÐ°ÑÐ¸ â 1 500 Ð³ÑÐ½\nÐÐ°Ð¹ÐºÐ° ÑÑiÑÐ¸Ð½Ð¸ â 1 000 Ð³ÑÐ½\nÐiÐ´Ð½Ð¾Ð²Ð»ÐµÐ½Ð½Ñ Ð²ÑÑÐ° ÑÐ°ÑÐ¸ â Ð²iÐ´ 1 000 Ð³ÑÐ½\n\nhttps://farro.ua/remont-far-i-bamperov/'},
        {'id':'susp',   'name':'Ð ÐµÐ¼Ð¾Ð½Ñ ÑÐ¾Ð´Ð¾Ð²Ð¾Ñ',
         'text':'ÐiÐ°Ð³Ð½Ð¾ÑÑÐ¸ÐºÐ° ÑÐ° ÑÐµÐ¼Ð¾Ð½Ñ ÑÐ¾Ð´Ð¾Ð²Ð¾Ñ\n\nÐiÐ°Ð³Ð½Ð¾ÑÑÐ¸ÐºÐ° â 300 Ð³ÑÐ½\nÐÐ°Ð¼iÐ½Ð° Ð¿ÐµÑÐµÐ´Ð½iÑ ÐºÐ¾Ð»Ð¾Ð´Ð¾Ðº â 600 Ð³ÑÐ½\nÐÐ°Ð¼iÐ½Ð° Ð°Ð¼Ð¾ÑÑÐ¸Ð·Ð°ÑÐ¾ÑÐ° Ð°Ð±Ð¾ Ð¿ÑÑÐ¶Ð¸Ð½Ð¸ â 1 200 Ð³ÑÐ½\nÐÐ°Ð¼iÐ½Ð° ÑÑÑÐ¿Ð¸Ñi â 700 Ð³ÑÐ½\nÐÐ½ÑÑÑÑ Ð²Ð°Ð¶ÐµÐ»Ñ â Ð²iÐ´ 500 Ð³ÑÐ½\nÐÐ°Ð¼iÐ½Ð° ÑÐ°Ð¹Ð»ÐµÐ½ÑÐ±Ð»Ð¾ÐºÐ° â Ð²iÐ´ 350 Ð³ÑÐ½\nÐÐ°Ð¼iÐ½Ð° ÑÐ°ÑÐ¾Ð²Ð¾Ñ Ð¾Ð¿Ð¾ÑÐ¸ â Ð²iÐ´ 350 Ð³ÑÐ½\n\nhttps://farro.ua/remont-hodovoj/'},
        {'id':'exh',    'name':'ÐÐ¸ÑÐ»Ð¾Ð¿Ð½i ÑÐ¸ÑÑÐµÐ¼Ð¸',
         'text':'Ð ÐµÐ¼Ð¾Ð½Ñ ÑÐ¸ÑÑÐµÐ¼Ð¸ Ð²Ð¸ÑÐ»Ð¾Ð¿Ñ\n\nÐiÐ°Ð³Ð½Ð¾ÑÑÐ¸ÐºÐ° â 200 Ð³ÑÐ½\nÐÐ°Ð¼iÐ½Ð° Ð³Ð¾ÑÑÐ¸ â Ð²iÐ´ 1 200 Ð³ÑÐ½\n\nhttps://farro.ua/remont-vyhlopnoj/'},
        {'id':'diag',   'name':'ÐiÐ°Ð³Ð½Ð¾ÑÑÐ¸ÐºÐ° Ð¿ÐµÑÐµÐ´ ÐºÑÐ¿iÐ²Ð»ÐµÑ Ð°Ð²ÑÐ¾',
         'text':'ÐÐ¾Ð¼Ð¿Ð»ÐµÐºÑÐ½Ð° Ð¿ÐµÑÐµÐ²iÑÐºÐ° Ð°Ð²ÑÐ¾ Ð¿ÐµÑÐµÐ´ Ð¿Ð¾ÐºÑÐ¿ÐºÐ¾Ñ\n\nÐiÐ°Ð³Ð½Ð¾ÑÑÐ¸ÐºÐ° ÑÐ¾Ð´Ð¾Ð²Ð¾Ñ â 300 Ð³ÑÐ½\nÐiÐ°Ð³Ð½Ð¾ÑÑÐ¸ÐºÐ° ÐÐÐ â 700 Ð³ÑÐ½\nÐiÐ°Ð³Ð½Ð¾ÑÑÐ¸ÐºÐ° ÐµÐ½Ð´Ð¾ÑÐºÐ¾Ð¿Ð¾Ð¼ â Ð²iÐ´ 1 500 Ð³ÑÐ½\nÐiÐ°Ð³Ð½Ð¾ÑÑÐ¸ÐºÐ° ÐºÐ¾Ð½Ð´Ð¸ÑiÐ¾Ð½ÐµÑÐ° â 700 Ð³ÑÐ½\nÐÐ¾Ð¼Ð¿\'ÑÑÐµÑÐ½Ð° Ð´iÐ°Ð³Ð½Ð¾ÑÑÐ¸ÐºÐ° â 400 Ð³ÑÐ½\nÐiÐ°Ð³Ð½Ð¾ÑÑÐ¸ÐºÐ° ÐÐÐ â 400 Ð³ÑÐ½'},
    ],
    'body': [
        {'id':'riht',  'name':'Ð Ð¸ÑÑÑÐ²Ð°Ð½Ð½Ñ Ð°Ð²ÑÐ¾',
         'text':'ÐiÐ´Ð½Ð¾Ð²Ð»ÐµÐ½Ð½Ñ Ð³ÐµÐ¾Ð¼ÐµÑÑiÑ ÐºÑÐ·Ð¾Ð²Ð°\n\nÐÐ°Ð¼iÐ½Ð° Ð¿Ð¾ÑÐ¾Ð³Ð° â Ð²iÐ´ 3 000 Ð³ÑÐ½\nÐÐ°Ð¼iÐ½Ð° Ð¿Ð¾Ð»Ð¾ÑÐ½Ð° Ð´Ð°ÑÑ â Ð²iÐ´ 20 000 Ð³ÑÐ½\nÐÐ¸ÑÑÐ¶ÐºÐ° Ð»Ð¾Ð½Ð¶ÐµÑÐ¾Ð½Ð° â Ð²iÐ´ 10 000 Ð³ÑÐ½\nÐ Ð¸ÑÑÑÐ²Ð°Ð½Ð½Ñ Ð¿Ð¾ÑÐ¾Ð³Ð° â Ð²iÐ´ 2 000 Ð³ÑÐ½\nÐÐ°Ð¼iÐ½Ð° Ð»Ð¾Ð±Ð¾Ð²Ð¾Ð³Ð¾ ÑÐºÐ»Ð° â 3 000 Ð³ÑÐ½\n\nhttps://farro.ua/rihtovka-avto/'},
        {'id':'paint', 'name':'ÐÐ¾ÐºÑÐ°ÑÐºÐ° Ð°Ð²ÑÐ¾',
         'text':'ÐÑÐ¾ÑÐµÑiÐ¹Ð½Ðµ ÑÐ°ÑÐ±ÑÐ²Ð°Ð½Ð½Ñ Ð· Ð¿iÐ´Ð±Ð¾ÑÐ¾Ð¼ ÐºÐ¾Ð»ÑÐ¾ÑÑ\n\nÐÐ¾ÐºÑÐ°ÑÐºÐ° Ð¾Ð´Ð½iÑÑ Ð´ÐµÑÐ°Ð»i â 4 500 Ð³ÑÐ½ + Ð¼Ð°ÑÐµÑiÐ°Ð»Ð¸\nÐÐ¾ÐºÑÐ°ÑÐºÐ° Ð´ÐµÑÐ°Ð»i ÑÑÑÐ¾ÑÑÐ°ÑÐ¾Ð²Ð¾Ñ ÑÐ°ÑÐ±Ð¾Ñ â 6 000 Ð³ÑÐ½ + Ð¼Ð°ÑÐµÑiÐ°Ð»Ð¸\nÐÐ¾Ð²Ð½Ðµ Ð¿ÐµÑÐµÑÐ°ÑÐ±ÑÐ²Ð°Ð½Ð½Ñ Ð°Ð²ÑÐ¾ â Ð²iÐ´ 70 000 Ð³ÑÐ½ + Ð¼Ð°ÑÐµÑiÐ°Ð»Ð¸\n\nÐÐ°Ð¶Ð»Ð¸Ð²Ð¾: Ð²Ð°ÑÑiÑÑÑ Ð¼Ð°ÑÐµÑiÐ°Ð»iÐ² ÑÐ¾Ð·ÑÐ°ÑÐ¾Ð²ÑÑ Ð¼Ð°Ð»ÑÑ Ð¿iÑÐ»Ñ Ð¾Ð³Ð»ÑÐ´Ñ Ð°Ð²ÑÐ¾.\n\nhttps://farro.ua/pokraska-avto/'},
        {'id':'pdr',   'name':'ÐÐ¸Ð´Ð°Ð»ÐµÐ½Ð½Ñ Ð²Ð¼\'ÑÑÐ¸Ð½ PDR',
         'text':'ÐÐ¸Ð´Ð°Ð»ÐµÐ½Ð½Ñ Ð²Ð¼\'ÑÑÐ¸Ð½ Ð±ÐµÐ· Ð¿Ð¾ÐºÑÐ°ÑÐºÐ¸\n\nÐÐµÐ²ÐµÐ»Ð¸ÐºÐ° Ð²Ð¼\'ÑÑÐ¸Ð½Ð° â Ð²iÐ´ 600 Ð³ÑÐ½\nÐ¡ÐµÑÐµÐ´Ð½Ñ Ð²Ð¼\'ÑÑÐ¸Ð½Ð° â Ð²iÐ´ 1 000 Ð³ÑÐ½\nÐÐ¾ÑÐºÐ¾Ð´Ð¶ÐµÐ½Ð½Ñ Ð²iÐ´ Ð³ÑÐ°Ð´Ñ â Ð²iÐ´ 3 000 Ð³ÑÐ½\n\nPDR Ð·Ð±ÐµÑiÐ³Ð°Ñ Ð¾ÑÐ¸Ð³iÐ½Ð°Ð»ÑÐ½Ðµ Ð»Ð°ÐºÐ¾ÑÐ°ÑÐ±Ð¾Ð²Ðµ Ð¿Ð¾ÐºÑÐ¸ÑÑÑ.\n\nhttps://farro.ua/rihtovka-avto/'},
    ],
}

FLEET_CARS = {
    '0418':'ÐÐ0418ÐÐ ','2993':'ÐÐ2993Ð I','7935':'AE7935PI','3021':'ÐÐ3021ÐÐ',
    '9489':'ÐÐ9489ÐÐ ','7121':'ÐÐ7121Ð¢Ð','8204':'ÐÐ8204Ð¢Ð','2548':'AE2548TB',
    '9245':'ÐÐ9245Ð¢Ð','0736':'AE0736PK','4715':'AE4715TH','6514':'ÐÐ6514Ð¢Ð¡',
    '4895':'KA4895HE','6843':'KA6843HB','5308':'ÐÐ5308Ð¢Ð','1875':'BI1875HO',
    '0665':'KA0665IH','0349':'KA0349HO','9854':'BC9854PM','8391':'ÐÐ8391Ð¢Ð',
    '4553':'AE4553XB','8730':'KA8730IX','5725':'AE5725OO','6584':'Ð¡Ð6584ÐÐ',
    '3531':'AI3531PH','1457':'AI1457MM',
}

CAR_NAMES = {
    'ÐºÐ°Ð¼ÑÐ¸':'Toyota Camry','ÐºÐµÐ¼Ñi':'Toyota Camry','Ð¿ÑÐ°Ð´Ð¾':'Toyota Land Cruiser Prado',
    'Ð¿ÑÐ°Ð´iÐº':'Toyota Land Cruiser Prado','ÑÐ°Ð²4':'Toyota RAV4','ÐºÑÑÐ·Ð°Ðº':'Toyota Land Cruiser',
    'Ð¾ÐºÑÐ°Ð²iÑ':'Skoda Octavia','Ð¾ÐºÑÐ°Ð²Ð¸Ñ':'Skoda Octavia','ÑÐ°Ð±iÑ':'Skoda Fabia',
    'Ð¿Ð°ÑÑÐ°Ñ':'Volkswagen Passat','ÑiÐ³ÑÐ°Ð½':'Volkswagen Tiguan','Ð³Ð¾Ð»ÑÑ':'Volkswagen Golf',
    'Ð±Ð¼Ð²':'BMW','Ð±ÑÐ¼ÐµÑ':'BMW','Ð¼ÐµÑÑ':'Mercedes-Benz','Ð³ÐµÐ»Ð¸Ðº':'Mercedes-Benz G-Class',
    'Ð°ÑÐ´i':'Audi','ÑÑÐ½Ð´Ð°Ð¹':'Hyundai','ÑÑÐºÑÐ¾Ð½':'Hyundai Tucson','ÑÐ¿Ð¾ÑÑÐ°Ð¶':'Kia Sportage',
    'Ð´Ð°ÑÑÐµÑ':'Renault Duster','ÑÐ¾ÐºÑÑ':'Ford Focus','ÐºÐ°ÑÐºÐ°Ð¹':'Nissan Qashqai',
    'ÑÐ¾Ð³':'Nissan Rogue','Ð»iÑ':'Nissan Leaf','Ð¼Ð°Ð·Ð´Ð°':'Mazda','ÑÐ¾Ð½Ð´Ð°':'Honda',
    'ÑÐ¾ÑÐµÑÑÐµÑ':'Subaru Forester','Ð»ÐµÐºÑÑÑ':'Lexus','ÐºÐ°Ð¹ÐµÐ½':'Porsche Cayenne',
    'ÑÐµÐ¹Ð½Ð´Ð¶':'Range Rover','ÑÐµÑÐ»a':'Tesla','tesla':'Tesla','Ð»Ð°Ð½Ð¾Ñ':'Daewoo Lanos',
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

def is_menu_btn(text):
    t = text.lower()
    return any(k in t for k in ['Ð¿Ð¾ÑÐ»ÑÐ³Ð¸','ÐºÐ¾Ð½ÑÐ°ÐºÑ','Ð¼Ð¾Ñ Ð°Ð²ÑÐ¾','Ð¼Ð¾Ðµ Ð°Ð²ÑÐ¾','Ð½Ð°Ð¿Ð¸ÑÐ°ÑÐ¸','Ð¼ÐµÐ½ÐµÐ´Ð¶ÐµÑ','Ð·Ð°Ð¿Ð¸ÑÐ°Ñ'])

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
                'ÐÐµÐ½ÐµÐ´Ð¶ÐµÑ Ð°Ð²ÑÐ¾ÑÐµÑÐ²iÑÑ Farro Ð½Ð°Ð¿Ð¸ÑÐ°Ð² ÐºÐ»iÑÐ½ÑÑ: ' + raw +
                '. ÐÐµÑÐµÐ¿Ð¸ÑÐ¸ Ð¾Ð´Ð½iÑÑ Ð²iÐ´Ð¿Ð¾Ð²iÐ´Ð´Ñ ÑÐºÑÐ°ÑÐ½ÑÑÐºÐ¾Ñ. ÐÐ¾ÑÐ¾ÑÐºÐ¾, Ð²Ð²iÑÐ»Ð¸Ð²Ð¾, Ð±ÐµÐ· ÑÐ¼Ð°Ð¹Ð»iÐ².'
            )}])
        return r.content[0].text.strip() or raw
    except Exception as e:
        logger.error('polish: %s', e)
        return raw

def get_client(tg_id):
    for row in get_ws('ÐÐ»Ð¸ÐµÐ½ÑÑ').get_all_values()[1:]:
        if str(row[0]).strip() == str(tg_id):
            return {'tg_id':row[0],'name':row[1] if len(row)>1 else '',
                    'phone':row[2] if len(row)>2 else '','car':row[3] if len(row)>3 else '',
                    'model':row[4] if len(row)>4 else '',
                    'ins_end':row[6] if len(row)>6 else '',
                    'oil_odo':row[7] if len(row)>7 else '','oil_date':row[8] if len(row)>8 else '',
                    'grm_odo':row[9] if len(row)>9 else '','grm_date':row[10] if len(row)>10 else ''}
    return None

def save_client(tg_id, data):
    ws  = get_ws('ÐÐ»Ð¸ÐµÐ½ÑÑ')
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
            for r in get_ws('ÐÐ»Ð¸ÐµÐ½ÑÑ').get_all_values()[1:] if r and r[0]]

def gen_rid():
    rows = get_ws('ÐÐ°ÐºÐ°Ð·Ñ').get_all_values()
    return 'REQ-{:04d}'.format(len([r for r in rows[1:] if r and r[0]]) + 1)

def save_req(tg_id, name, phone, car, sto_key, service, wish):
    rid = gen_rid()
    get_ws('ÐÐ°ÐºÐ°Ð·Ñ').append_row([rid,now_str(),str(tg_id),name,phone,car,
                                   CONTACTS[sto_key]['name'],service,wish,'new',''])
    return rid

def get_orders(tg_id):
    return [{'id':r[0],'date':r[1],'service':r[7] if len(r)>7 else '',
             'status':r[9] if len(r)>9 else ''}
            for r in get_ws('ÐÐ°ÐºÐ°Ð·Ñ').get_all_values()[1:]
            if len(r)>2 and str(r[2]).strip()==str(tg_id)][-10:]

def status_lbl(s):
    return {'new':'ÐÐ¾Ð²Ð°','confirmed':'ÐiÐ´ÑÐ²ÐµÑÐ´Ð¶ÐµÐ½Ð¾','in_work':'Ð ÑÐ¾Ð±Ð¾Ñi',
            'ready':'ÐÐ¾ÑÐ¾Ð²Ð¾','issued':'ÐÐ¸Ð´Ð°Ð½Ð¾'}.get(s,s)

async def send_photo(bot, chat_id, path, caption=''):
    if path in _photo_cache:
        await bot.send_photo(chat_id=chat_id, photo=_photo_cache[path], caption=caption); return
    try:
        with open(path,'rb') as f:
            msg = await bot.send_photo(chat_id=chat_id, photo=f, caption=caption)
        _photo_cache[path] = msg.photo[-1].file_id
    except Exception as e:
        logger.error('photo %s: %s', path, e)

async def to_client(bot, cid, text):
    await bot.send_message(chat_id=int(cid), text=text)

async def to_staff(bot, msg, client_id=None):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(
        'ÐiÐ´Ð¿Ð¾Ð²iÑÑÐ¸', callback_data='reply_{}'.format(client_id))]]) if client_id else None
    for uid in STAFF_IDS:
        try: await bot.send_message(chat_id=uid, text=msg, reply_markup=kb)
        except Exception as e: logger.error('staff %s: %s', uid, e)

def addr(sto_key):
    c = CONTACTS[sto_key]
    note = ' {}'.format(c['note']) if c.get('note') else ''
    return c['address'] + note

# ââ Keyboards ââââââââââââââââââââââââââââââââââââââââââââââââ

def kb_new():
    return ReplyKeyboardMarkup([
        ['ÐÐ¾ÑÐ»ÑÐ³Ð¸ ÑÐ° ÑiÐ½Ð¸', 'ÐÐ¾Ð½ÑÐ°ÐºÑÐ¸'],
        ['ÐÐ°Ð¿Ð¸ÑÐ°ÑÐ¸ Ð¼ÐµÐ½ÐµÐ´Ð¶ÐµÑÑ'],
    ], resize_keyboard=True, is_persistent=True)

def kb_reg():
    return ReplyKeyboardMarkup([
        ['ÐÐ¾ÑÐ»ÑÐ³Ð¸ ÑÐ° ÑiÐ½Ð¸', 'ÐÐ¾Ð½ÑÐ°ÐºÑÐ¸'],
        ['ÐÐ¾Ñ Ð°Ð²ÑÐ¾', 'ÐÐ°Ð¿Ð¸ÑÐ°ÑÐ¸ Ð¼ÐµÐ½ÐµÐ´Ð¶ÐµÑÑ'],
    ], resize_keyboard=True, is_persistent=True)

def kb_staff():
    return ReplyKeyboardMarkup([
        ['ÐÐ¾Ð²i Ð·Ð°ÑÐ²ÐºÐ¸', 'ÐÑi Ð°ÐºÑÐ¸Ð²Ð½i'],
        ['ÐÐ²ÑÐ¾ Ð³Ð¾ÑÐ¾Ð²Ðµ', 'ÐÐ»iÑÐ½ÑÐ¸'],
    ], resize_keyboard=True, is_persistent=True)

def ckb(uid): return kb_reg() if get_client(uid) else kb_new()

def kb_sto(prefix='menu'):
    c_b = CONTACTS['body']
    c_s = CONTACTS['sto']
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            'ÐÑÐ·Ð¾Ð²Ð½Ð¸Ð¹ ÑÐµÑÐ²iÑ ({})'.format(c_b['address']),
            callback_data='{}_body'.format(prefix))],
        [InlineKeyboardButton(
            'Ð¡Ð¢Ð ({})'.format(c_s['address']),
            callback_data='{}_sto'.format(prefix))],
    ])

def kb_write():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('ÐÑÐ·Ð¾Ð²Ð½Ð¸Ð¹ ÑÐµÑÐ²iÑ (Ð§ÑÐ±Ð¸Ð½ÑÑÐºÐ¾Ð³Ð¾)', callback_data='write_body')],
        [InlineKeyboardButton('Ð¡Ð¢Ð (Ð¥Ð¼ÐµÐ»ÑÐ½Ð¸ÑÑÐºÐ¾Ð³Ð¾)',           callback_data='write_sto')],
    ])

def kb_svcs(sto_key):
    c = CONTACTS[sto_key]
    btns = [
        [InlineKeyboardButton('ÐÐ°Ð²iÐ³Ð°ÑÐ¾Ñ', url=c['maps'])],
    ]
    for svc in SERVICES[sto_key]:
        btns.append([InlineKeyboardButton(svc['name'], callback_data='svc_{}_{}'.format(sto_key, svc['id']))])
    btns.append([InlineKeyboardButton('ÐÐ°Ð¿Ð¸ÑÐ°ÑÐ¸ Ð¼ÐµÐ½ÐµÐ´Ð¶ÐµÑÑ', callback_data='ask_{}'.format(sto_key))])
    return InlineKeyboardMarkup(btns)

def kb_svc_detail(sto_key):
    c = CONTACTS[sto_key]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('ÐÐ°Ð¿Ð¸ÑÐ°ÑÐ¸ Ð¼ÐµÐ½ÐµÐ´Ð¶ÐµÑÑ', callback_data='ask_{}'.format(sto_key))],
        [InlineKeyboardButton('ÐÐ°Ð²iÐ³Ð°ÑÐ¾Ñ', url=c['maps'])],
        [InlineKeyboardButton('ÐÐ°Ð·Ð°Ð´ Ð´Ð¾ ÑÐ¿Ð¸ÑÐºÑ', callback_data='menu_{}'.format(sto_key))],
    ])

def kb_contacts():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('ÐÐ°Ð²iÐ³Ð°ÑÐ¾Ñ: Ð¡Ð¢Ð', url=CONTACTS['sto']['maps'])],
        [InlineKeyboardButton('ÐÐ°Ð²iÐ³Ð°ÑÐ¾Ñ: ÐÑÐ·Ð¾Ð²Ð½Ð¸Ð¹ ÑÐµÑÐ²iÑ', url=CONTACTS['body']['maps'])],
    ])

def kb_skip():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('ÐÑÐ¾Ð¿ÑÑÑÐ¸ÑÐ¸', callback_data='skip')],
        [InlineKeyboardButton('ÐÐ°Ð²ÐµÑÑÐ¸ÑÐ¸', callback_data='finish_mycar')],
    ])

def kb_mycar_update():
    return InlineKeyboardMarkup([[InlineKeyboardButton('ÐÐ½Ð¾Ð²Ð¸ÑÐ¸ Ð´Ð°Ð½i Ð°Ð²ÑÐ¾', callback_data='start_mycar')]])

MYCAR_FIELDS  = ['name','phone','car','ins_end','oil_odo','oil_date','grm_odo','grm_date']
MYCAR_PROMPTS = {
    'name':     'ÐÐ°ÑÐµ iÐ¼\'Ñ',
    'phone':    'ÐÐ¾Ð¼ÐµÑ ÑÐµÐ»ÐµÑÐ¾Ð½Ñ',
    'car':      'ÐÐ°ÑÐºÐ° ÑÐ° Ð¼Ð¾Ð´ÐµÐ»Ñ Ð°Ð²ÑÐ¾',
    'ins_end':  'ÐÐ°ÑÐ° Ð·Ð°ÐºiÐ½ÑÐµÐ½Ð½Ñ ÑÑÑÐ°ÑÐ¾Ð²ÐºÐ¸ (Ð½Ð°Ð¿ÑÐ¸ÐºÐ»Ð°Ð´ 31.12.26)',
    'oil_odo':  'ÐÐ´Ð¾Ð¼ÐµÑÑ Ð¿ÑÐ¸ Ð¾ÑÑÐ°Ð½Ð½iÐ¹ Ð·Ð°Ð¼iÐ½i Ð¼Ð°ÑÐ»Ð° (ÐºÐ¼)',
    'oil_date': 'ÐÐ°ÑÐ° Ð¾ÑÑÐ°Ð½Ð½ÑÐ¾Ñ Ð·Ð°Ð¼iÐ½Ð¸ Ð¼Ð°ÑÐ»Ð°',
    'grm_odo':  'ÐÐ´Ð¾Ð¼ÐµÑÑ Ð¿ÑÐ¸ Ð¾ÑÑÐ°Ð½Ð½iÐ¹ Ð·Ð°Ð¼iÐ½i ÐÐ Ð (ÐºÐ¼)',
    'grm_date': 'ÐÐ°ÑÐ° Ð¾ÑÑÐ°Ð½Ð½ÑÐ¾Ñ Ð·Ð°Ð¼iÐ½Ð¸ ÐÐ Ð',
}

REG_FIELDS  = ['phone','name','car']
REG_PROMPTS = {
    'phone': 'ÐÐ°Ñ Ð½Ð¾Ð¼ÐµÑ ÑÐµÐ»ÐµÑÐ¾Ð½Ñ (Ð¾Ð±Ð¾Ð²\'ÑÐ·ÐºÐ¾Ð²Ð¾):',
    'name':  'Ð¯Ðº Ð²Ð°Ñ Ð·Ð²Ð°ÑÐ¸? (Ð½ÐµÐ¾Ð±Ð¾Ð²\'ÑÐ·ÐºÐ¾Ð²Ð¾)',
    'car':   'ÐÐ°ÑÐºÐ° ÑÐ° Ð¼Ð¾Ð´ÐµÐ»Ñ Ð°Ð²ÑÐ¾ (Ð½ÐµÐ¾Ð±Ð¾Ð²\'ÑÐ·ÐºÐ¾Ð²Ð¾)',
}

# ââ Handlers âââââââââââââââââââââââââââââââââââââââââââââââââ

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    name = update.effective_user.first_name or 'ÐÐ»iÑÐ½Ñ'
    ctx.user_data.clear()
    if is_staff(uid):
        await update.message.reply_text('ÐÑÐ¸Ð²iÑ, {}! ID: {}'.format(name,uid), reply_markup=kb_staff()); return
    client = get_client(uid)
    if client and client.get('phone'):
        txt = 'Ð Ð¿Ð¾Ð²ÐµÑÐ½ÐµÐ½Ð½ÑÐ¼, {}!\n\nÐÐ±ÐµÑiÑÑ Ð¿ÑÐ½ÐºÑ Ð¼ÐµÐ½Ñ Ð°Ð±Ð¾ Ð½Ð°Ð¿Ð¸ÑiÑÑ Ð½Ð°Ð¼.'.format(client.get('name',''))
        await update.message.reply_text(txt, reply_markup=kb_reg())
    else:
        txt = ('ÐiÑÐ°ÑÐ¼Ð¾ Ð² Farro!\n\n'
               'Ð¡ÐºÐ¾ÑÐ¸ÑÑÐ°Ð¹ÑÐµÑÑ Ð¾Ð´Ð½iÑÑ Ð· ÐºÐ½Ð¾Ð¿Ð¾Ðº Ð½Ð¸Ð¶ÑÐµ Ð°Ð±Ð¾ Ð½Ð°ÑÐ¸ÑÐ½iÑÑ ÐºÐ½Ð¾Ð¿ÐºÑ Ð½Ð¸Ð¶ÑÐµ, '
               'ÑÐ¾Ð± Ð½Ð°Ð¿Ð¸ÑÐ°ÑÐ¸ Ð¼ÐµÐ½ÐµÐ´Ð¶ÐµÑÑ.')
        await update.message.reply_text(txt, reply_markup=kb_new())

async def handle_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    text = (update.message.text or '').strip()
    ud   = ctx.user_data
    tlo  = text.lower()

    # Ð¯ÐºÑÐ¾ ÐºÐ½Ð¾Ð¿ÐºÐ° Ð¼ÐµÐ½Ñ â ÑÐºÐ¸Ð´Ð°ÑÐ¼Ð¾ Ð²Ñi Ð°ÐºÑÐ¸Ð²Ð½i Ð¿ÑÐ¾ÑÐµÑÐ¸
    if is_menu_btn(text) and not is_staff(uid):
        if 'reg_step' in ud or 'mycar_step' in ud:
            ud.clear()

    # ââ Ð ÐµÑÑÑÑÐ°ÑiÑ ââââââââââââââââââââââââââââââââââââââââââââ
    if ud.get('reg_step'):
        step = ud['reg_step']
        data = ud.setdefault('reg_data',{})
        if step == 'phone' and text in ('-','ÐÑÐ¾Ð¿ÑÑÑÐ¸ÑÐ¸'):
            await update.message.reply_text(
                'ÐÐ¾Ð¼ÐµÑ ÑÐµÐ»ÐµÑÐ¾Ð½Ñ Ð¿ÑÐ¾Ð¿ÑÑÑÐ¸ÑÐ¸ Ð½Ðµ Ð¼Ð¾Ð¶Ð½Ð°. ÐiÐ½ Ð¿Ð¾ÑÑiÐ±ÐµÐ½, ÑÐ¾Ð± Ð¼ÐµÐ½ÐµÐ´Ð¶ÐµÑ Ð¼iÐ³ Ð· Ð²Ð°Ð¼Ð¸ Ð·Ð²\'ÑÐ·Ð°ÑÐ¸ÑÑ.'
            ); return
        if text not in ('-','ÐÑÐ¾Ð¿ÑÑÑÐ¸ÑÐ¸'):
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
        await update.message.reply_text('ÐÑÐºÑÑÐ¼Ð¾! Ð¢ÐµÐ¿ÐµÑ Ð¼Ð¾Ð¶ÐµÑÐµ Ð½Ð°Ð¿Ð¸ÑÐ°ÑÐ¸ Ð²Ð°ÑÐµ Ð¿Ð¾Ð²iÐ´Ð¾Ð¼Ð»ÐµÐ½Ð½Ñ.', reply_markup=ckb(uid)); return

    # ââ ÐÐ°Ð¿Ð¾Ð²Ð½ÐµÐ½Ð½Ñ Ð¿ÑÐ¾ÑiÐ»Ñ Ð°Ð²ÑÐ¾ ââââââââââââââââââââââââââââââââ
    if ud.get('mycar_step'):
        step = ud['mycar_step']
        data = ud.setdefault('mycar_data',{})
        if text not in ('-','ÐÑÐ¾Ð¿ÑÑÑÐ¸ÑÐ¸'):
            data[step] = normalize_car(text) if step=='car' else text
        idx = MYCAR_FIELDS.index(step)
        if idx+1 < len(MYCAR_FIELDS):
            nxt = MYCAR_FIELDS[idx+1]
            ud['mycar_step'] = nxt
            await update.message.reply_text('{} (Ð½ÐµÐ¾Ð±Ð¾Ð²\'ÑÐ·ÐºÐ¾Ð²Ð¾):'.format(MYCAR_PROMPTS[nxt]),
                                            reply_markup=kb_skip()); return
        client = get_client(uid) or {}
        client.update({k:v for k,v in data.items() if v})
        save_client(uid, client)
        ud.clear()
        await update.message.reply_text('ÐÐ°Ð½i Ð·Ð±ÐµÑÐµÐ¶ÐµÐ½Ð¾!', reply_markup=kb_reg()); return

    # ââ ÐiÐ´Ð¿Ð¾Ð²iÐ´Ñ Ð¼ÐµÐ½ÐµÐ´Ð¶ÐµÑÐ° ÐºÐ»iÑÐ½ÑÑ âââââââââââââââââââââââââââ
    if ud.get('reply_to'):
        cid = ud.pop('reply_to')
        polished = polish(text)
        try: await to_client(ctx.bot, cid, polished)
        except Exception as e: logger.error('reply: %s', e)
        return

    # ââ ÐÐµÐ½ÐµÐ´Ð¶ÐµÑ: ÐºÐ¾Ð¼Ð°Ð½Ð´Ð¸ âââââââââââââââââââââââââââââââââââââ
    if is_staff(uid):
        if 'Ð½Ð¾Ð²i' in tlo or 'Ð·Ð°ÑÐ²ÐºÐ¸' in tlo:
            ws    = get_ws('ÐÐ°ÐºÐ°Ð·Ñ')
            new_r = [r for r in ws.get_all_values()[1:] if len(r)>9 and r[9]=='new']
            if not new_r:
                await update.message.reply_text('ÐÐ¾Ð²Ð¸Ñ Ð·Ð°ÑÐ²Ð¾Ðº Ð½ÐµÐ¼Ð°Ñ.', reply_markup=kb_staff()); return
            lines = ['ÐÐ¾Ð²i Ð·Ð°ÑÐ²ÐºÐ¸: {}'.format(len(new_r))]
            for r in new_r:
                lines.append('{} | {} | {} | {}'.format(r[0],r[3],r[7],r[1]))
            await update.message.reply_text('\n'.join(lines), reply_markup=kb_staff()); return

        if 'Ð°ÐºÑÐ¸Ð²Ð½' in tlo or 'Ð²Ñi' in tlo:
            ws     = get_ws('ÐÐ°ÐºÐ°Ð·Ñ')
            active = [r for r in ws.get_all_values()[1:] if len(r)>9 and r[9] not in ('issued','')]
            if not active:
                await update.message.reply_text('ÐÐºÑÐ¸Ð²Ð½Ð¸Ñ Ð½ÐµÐ¼Ð°Ñ.', reply_markup=kb_staff()); return
            lines = ['ÐÐºÑÐ¸Ð²Ð½i: {}'.format(len(active))]
            for r in active:
                lines.append('{} | {} | {}'.format(r[0],r[3],r[7]))
            await update.message.reply_text('\n'.join(lines), reply_markup=kb_staff()); return

        if 'Ð³Ð¾ÑÐ¾Ð²Ðµ' in tlo or 'Ð³Ð¾ÑÐ¾Ð²Ð¾' in tlo:
            ws     = get_ws('ÐÐ°ÐºÐ°Ð·Ñ')
            active = [r for r in ws.get_all_values()[1:] if len(r)>9 and r[9] not in ('issued','')]
            if not active:
                await update.message.reply_text('ÐÐºÑÐ¸Ð²Ð½Ð¸Ñ Ð½ÐµÐ¼Ð°Ñ.', reply_markup=kb_staff()); return
            btns = [[InlineKeyboardButton(
                '{} â {}'.format(r[0],r[3]), callback_data='ready_{}'.format(r[0]))]
                for r in active[:10]]
            btns.append([InlineKeyboardButton('Ð¡ÐºÐ°ÑÑÐ²Ð°ÑÐ¸', callback_data='cancel')])
            await update.message.reply_text('ÐÐ±ÐµÑiÑÑ:', reply_markup=InlineKeyboardMarkup(btns)); return

        if 'ÐºÐ»iÑÐ½ÑÐ¸' in tlo or 'ÐºÐ»ÑÑÐ½ÑÐ¸' in tlo:
            clients = get_all_clients()
            if not clients:
                await update.message.reply_text('ÐÐ»iÑÐ½ÑiÐ² Ð½ÐµÐ¼Ð°Ñ.', reply_markup=kb_staff()); return
            btns = [[InlineKeyboardButton(
                '{} {}'.format(c['name'],'({})'.format(c['car']) if c['car'] else '').strip(),
                callback_data='wc_{}'.format(c['tg_id']))] for c in clients[:15]]
            btns.append([InlineKeyboardButton('Ð¡ÐºÐ°ÑÑÐ²Ð°ÑÐ¸', callback_data='cancel')])
            await update.message.reply_text('ÐÐ±ÐµÑiÑÑ ÐºÐ»iÑÐ½ÑÐ°:', reply_markup=InlineKeyboardMarkup(btns)); return

        await update.message.reply_text('ÐÐ±ÐµÑiÑÑ Ð´iÑ:', reply_markup=kb_staff()); return

    # ââ ÐÐ»iÑÐ½Ñ: ÐºÐ½Ð¾Ð¿ÐºÐ¸ Ð¼ÐµÐ½Ñ âââââââââââââââââââââââââââââââââââ
    if 'Ð¿Ð¾ÑÐ»ÑÐ³Ð¸' in tlo or 'ÑiÐ½Ð¸' in tlo:
        await update.message.reply_text('ÐÐ±ÐµÑiÑÑ ÑÐµÑÐ²iÑ:', reply_markup=kb_sto()); return

    if 'ÐºÐ¾Ð½ÑÐ°ÐºÑ' in tlo:
        c_s = CONTACTS['sto']
        c_b = CONTACTS['body']
        await send_photo(ctx.bot, uid, PHOTO_BODY,
            caption='ÐÑÐ·Ð¾Ð²Ð½Ð¸Ð¹ ÑÐµÑÐ²iÑ Farro\n{} {}\nÐÑÐ°ÑiÐº: {}'.format(
                c_b['address'], c_b['note'], c_b['hours']))
        await send_photo(ctx.bot, uid, PHOTO_STO,
            caption='Ð¡Ð¢Ð Farro\n{}\nÐÑÐ°ÑiÐº: {}'.format(c_s['address'], c_s['hours']))
        await update.message.reply_text(
            'Ð¢ÐµÐ»ÐµÑÐ¾Ð½Ð¸:\n{}'.format(PHONES), reply_markup=kb_contacts()); return

    if 'Ð¼Ð¾Ñ Ð°Ð²ÑÐ¾' in tlo or 'Ð¼Ð¾Ðµ Ð°Ð²ÑÐ¾' in tlo:
        client = get_client(uid)
        if not client:
            await update.message.reply_text('ÐÐ»Ñ Ð´Ð¾ÑÑÑÐ¿Ñ Ð´Ð¾ ÑÑÐ¾Ð³Ð¾ ÑÐ¾Ð·Ð´iÐ»Ñ Ð¿Ð¾ÑÑiÐ±Ð½Ð¾ Ð·Ð°ÑÐµÑÑÑÑÑÐ²Ð°ÑÐ¸ÑÑ.',
                                            reply_markup=kb_new()); return
        lines = ['ÐÐ°Ñ Ð°Ð²ÑÐ¾Ð¼Ð¾Ð±iÐ»Ñ']
        if client.get('name'):     lines.append('IÐ¼\'Ñ: {}'.format(client['name']))
        if client.get('phone'):    lines.append('Ð¢ÐµÐ».: {}'.format(client['phone']))
        if client.get('car'):      lines.append('ÐÐ²ÑÐ¾: {}'.format(client['car']))
        if client.get('ins_end'):  lines.append('Ð¡ÑÑÐ°ÑÐ¾Ð²ÐºÐ° Ð´Ð¾: {}'.format(client['ins_end']))
        if client.get('oil_odo'):  lines.append('ÐÐ°ÑÐ»Ð¾: {} ÐºÐ¼ ({})'.format(client['oil_odo'],client.get('oil_date','')))
        if client.get('grm_odo'):  lines.append('ÐÐ Ð: {} ÐºÐ¼ ({})'.format(client['grm_odo'],client.get('grm_date','')))
        orders = get_orders(uid)
        if orders:
            lines.append('\nIÑÑÐ¾ÑiÑ Ð·Ð°Ð¼Ð¾Ð²Ð»ÐµÐ½Ñ:')
            for o in reversed(orders):
                lines.append('{} | {} | {}'.format(o['date'],o['service'],status_lbl(o['status'])))
        await update.message.reply_text('\n'.join(lines), reply_markup=kb_mycar_update()); return

    if 'Ð½Ð°Ð¿Ð¸ÑÐ°ÑÐ¸' in tlo or 'Ð¼ÐµÐ½ÐµÐ´Ð¶ÐµÑ' in tlo:
        await update.message.reply_text('ÐÐ±ÐµÑiÑÑ ÑÐµÑÐ²iÑ:', reply_markup=kb_write()); return

    if 'Ð·Ð°Ð¿Ð¸ÑÐ°Ñ' in tlo:
        await update.message.reply_text('ÐÐ±ÐµÑiÑÑ ÑÐµÑÐ²iÑ Ð´Ð»Ñ Ð·Ð°Ð¿Ð¸ÑÑ:', reply_markup=kb_sto()); return

    # ââ ÐÑÐ´Ñ-ÑÐºÐµ Ð¿Ð¾Ð²iÐ´Ð¾Ð¼Ð»ÐµÐ½Ð½Ñ â Ð´Ð¾ Ð¼ÐµÐ½ÐµÐ´Ð¶ÐµÑÐ° ââââââââââââââââââ
    client = get_client(uid)
    if not client:
        await update.message.reply_text(
            'Ð©Ð¾Ð± Ð½Ð°Ð¿Ð¸ÑÐ°ÑÐ¸ Ð¼ÐµÐ½ÐµÐ´Ð¶ÐµÑÑ, ÑÐ¿Ð¾ÑÐ°ÑÐºÑ Ð½Ð°ÑÐ¸ÑÐ½iÑÑ ÐºÐ½Ð¾Ð¿ÐºÑ "ð¬ ÐÐ°Ð¿Ð¸ÑÐ°ÑÐ¸ Ð¼ÐµÐ½ÐµÐ´Ð¶ÐµÑÑ" Ð½Ð¸Ð¶ÑÐµ.',
            reply_markup=kb_new()
        ); return
    cname  = client['name']  if client else 'ÐÐ¾Ð²Ð¸Ð¹ ÐºÐ»iÑÐ½Ñ'
    phone  = client['phone'] if client else 'Ð½Ðµ Ð²ÐºÐ°Ð·Ð°Ð½Ð¾'
    car    = client['car']   if client else 'Ð½Ðµ Ð²ÐºÐ°Ð·Ð°Ð½Ð¾'
    sto    = ud.get('write_sto','')
    sto_s  = ' [{}]'.format(CONTACTS[sto]['name']) if sto in CONTACTS else ''
    fwd    = 'ÐÐ»iÑÐ½Ñ Ð¿Ð¸ÑÐµ{}:\n{} | {} | {}\n\n{}'.format(sto_s,cname,phone,car,text)
    await to_staff(ctx.bot, fwd, client_id=uid)

async def handle_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    uid  = q.from_user.id
    data = q.data
    await q.answer()
    ud   = ctx.user_data

    if data == 'cancel':
        ud.clear()
        await q.edit_message_text('Ð¡ÐºÐ°ÑÐ¾Ð²Ð°Ð½Ð¾.'); return

    if data == 'skip':
        step = ud.get('mycar_step') or ud.get('reg_step')
        if ud.get('mycar_step') and step in MYCAR_FIELDS:
            idx = MYCAR_FIELDS.index(step)
            if idx+1 < len(MYCAR_FIELDS):
                nxt = MYCAR_FIELDS[idx+1]
                ud['mycar_step'] = nxt
                await q.message.reply_text('{} (Ð½ÐµÐ¾Ð±Ð¾Ð²\'ÑÐ·ÐºÐ¾Ð²Ð¾):'.format(MYCAR_PROMPTS[nxt]),
                                           reply_markup=kb_skip()); return
            client = get_client(uid) or {}
            client.update({k:v for k,v in ud.get('mycar_data',{}).items() if v})
            save_client(uid, client)
            ud.clear()
            await q.message.reply_text('ÐÐ°Ð½i Ð·Ð±ÐµÑÐµÐ¶ÐµÐ½Ð¾!', reply_markup=kb_reg()); return
        if ud.get('reg_step') and step in REG_FIELDS:
            if step == 'phone':
                await q.message.reply_text(
                    'ÐÐ¾Ð¼ÐµÑ ÑÐµÐ»ÐµÑÐ¾Ð½Ñ Ð¿ÑÐ¾Ð¿ÑÑÑÐ¸ÑÐ¸ Ð½Ðµ Ð¼Ð¾Ð¶Ð½Ð°. ÐiÐ½ Ð¿Ð¾ÑÑiÐ±ÐµÐ½, ÑÐ¾Ð± Ð¼ÐµÐ½ÐµÐ´Ð¶ÐµÑ Ð¼iÐ³ Ð· Ð²Ð°Ð¼Ð¸ Ð·Ð²\'ÑÐ·Ð°ÑÐ¸ÑÑ.'
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
            await q.message.reply_text('ÐÑÐºÑÑÐ¼Ð¾! Ð¢ÐµÐ¿ÐµÑ Ð¼Ð¾Ð¶ÐµÑÐµ Ð½Ð°Ð¿Ð¸ÑÐ°ÑÐ¸ Ð²Ð°ÑÐµ Ð¿Ð¾Ð²iÐ´Ð¾Ð¼Ð»ÐµÐ½Ð½Ñ.', reply_markup=ckb(uid)); return
        return

    if data == 'finish_mycar':
        client = get_client(uid) or {}
        client.update({k:v for k,v in ud.get('mycar_data',{}).items() if v})
        save_client(uid, client)
        ud.clear()
        await q.message.reply_text('ÐÐ°Ð½i Ð·Ð±ÐµÑÐµÐ¶ÐµÐ½Ð¾!', reply_markup=kb_reg()); return

    if data == 'start_mycar':
        ud['mycar_step'] = 'name'
        ud['mycar_data'] = {}
        await q.edit_message_text(
            'ÐÐ°Ð¿Ð¾Ð²Ð½iÑÑ Ð´Ð°Ð½i Ð¿ÑÐ¾ Ð²Ð°Ñ Ð°Ð²ÑÐ¾Ð¼Ð¾Ð±iÐ»Ñ.\nÐÑi Ð¿Ð¾Ð»Ñ Ð½ÐµÐ¾Ð±Ð¾Ð²\'ÑÐ·ÐºÐ¾Ð²i.\n\n'
            '{} (Ð½ÐµÐ¾Ð±Ð¾Ð²\'ÑÐ·ÐºÐ¾Ð²Ð¾):'.format(MYCAR_PROMPTS['name']),
            reply_markup=kb_skip()); return

    if data.startswith('menu_'):
        sto_key = data[5:]
        if sto_key not in CONTACTS: return
        c = CONTACTS[sto_key]
        note = ' {}'.format(c['note']) if c.get('note') else ''
        msg = '{}\n\nÐÐ´ÑÐµÑÐ°: {}{}\nÐÑÐ°ÑiÐº: {}\nÐ¢ÐµÐ».:\n{}\n\nÐÐ±ÐµÑiÑÑ Ð¿Ð¾ÑÐ»ÑÐ³Ñ:'.format(
            c['name'], c['address'], note, c['hours'], PHONES)
        await q.edit_message_text(msg, reply_markup=kb_svcs(sto_key)); return

    if data.startswith('svc_'):
        parts   = data[4:].split('_',1)
        sto_key = parts[0]
        svc_id  = parts[1] if len(parts)>1 else ''
        svc     = next((s for s in SERVICES[sto_key] if s['id']==svc_id), None)
        if not svc:
            await q.edit_message_text('ÐÐ¾ÑÐ»ÑÐ³Ñ Ð½Ðµ Ð·Ð½Ð°Ð¹Ð´ÐµÐ½Ð¾.'); return
        c    = CONTACTS[sto_key]
        note = ' {}'.format(c['note']) if c.get('note') else ''
        msg  = '{}\n\n{}\n\nÐÐ´ÑÐµÑÐ°: {}{}\nÐÑÐ°ÑiÐº: {}\nÐ¢ÐµÐ».:\n{}'.format(
            svc['name'], svc['text'], c['address'], note, c['hours'], PHONES)
        if len(msg)>4000: msg = msg[:3990]+'...'
        await q.edit_message_text(msg, reply_markup=kb_svc_detail(sto_key)); return

    if data.startswith('ask_'):
        sto_key = data[4:]
        ud['write_sto'] = sto_key
        c = CONTACTS.get(sto_key, CONTACTS['sto'])
        await q.edit_message_text(
            'ÐÐ°Ð¿Ð¸ÑiÑÑ Ð²Ð°ÑÐµ Ð¿Ð¸ÑÐ°Ð½Ð½Ñ â Ð¼ÐµÐ½ÐµÐ´Ð¶ÐµÑ {} Ð²iÐ´Ð¿Ð¾Ð²iÑÑÑ.'.format(c['name'])); return

    if data.startswith('write_'):
        sto_key = data[6:]
        ud['reg_sto']  = sto_key
        ud['reg_step'] = 'phone'
        ud['reg_data'] = {}
        await q.edit_message_text(
            'Ð©Ð¾Ð± Ð¼ÐµÐ½ÐµÐ´Ð¶ÐµÑ Ð¼iÐ³ Ð²Ð°Ð¼ Ð²iÐ´Ð¿Ð¾Ð²iÑÑÐ¸, ÑÐ¿Ð¾ÑÐ°ÑÐºÑ Ð²ÐºÐ°Ð¶iÑÑ Ð½Ð¾Ð¼ÐµÑ ÑÐµÐ»ÐµÑÐ¾Ð½Ñ:'); return

    if data.startswith('reply_'):
        ud['reply_to'] = int(data[6:])
        await q.edit_message_text(''); return

    if data.startswith('ready_'):
        rid  = data[6:]
        ws   = get_ws('ÐÐ°ÐºÐ°Ð·Ñ')
        for i, row in enumerate(ws.get_all_values()[1:], start=2):
            if str(row[0]).strip() == rid:
                ws.update('J{}'.format(i),[['ready']])
                cid  = str(row[2]).strip() if len(row)>2 else None
                car  = row[5] if len(row)>5 else ''
                svc  = row[7] if len(row)>7 else ''
                name = row[6] if len(row)>6 else ''
                if cid:
                    try: await to_client(ctx.bot, cid,
                        'ÐÐ°Ñ Ð°Ð²ÑÐ¾Ð¼Ð¾Ð±iÐ»Ñ Ð³Ð¾ÑÐ¾Ð²Ð¸Ð¹.\n\nÐÐ²ÑÐ¾: {}\nÐÐ¾ÑÐ»ÑÐ³Ð°: {}\n{}\n\nÐ§ÐµÐºÐ°ÑÐ¼Ð¾ Ð²Ð°Ñ.'.format(car,svc,name))
                    except Exception as e: logger.error('ready: %s', e)
                await q.edit_message_text('ÐÐ°ÑÐ²ÐºÐ° {} â Ð³Ð¾ÑÐ¾Ð²Ð°.'.format(rid)); return
        await q.edit_message_text('ÐÐµ Ð·Ð½Ð°Ð¹Ð´ÐµÐ½Ð¾.'); return

    if data.startswith('wc_'):
        cid = data[3:]
        ws  = get_ws('ÐÐ»Ð¸ÐµÐ½ÑÑ')
        cn = cid; car = ''
        for r in ws.get_all_values()[1:]:
            if str(r[0]).strip()==cid:
                cn = r[1] if len(r)>1 else cn
                car = r[3] if len(r)>3 else ''
                break
        ud['reply_to'] = int(cid)
        await q.edit_message_text('ÐÐ»iÑÐ½Ñ: {} {}. ÐÐ°Ð¿Ð¸ÑiÑÑ Ð¿Ð¾Ð²iÐ´Ð¾Ð¼Ð»ÐµÐ½Ð½Ñ:'.format(
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
