#!/usr/bin/env python3
"""
Ultimate Social Media Downloader Bot – Railway/Render Ready
Author: @shihab_ff_857
"""

import os
import logging
import time
import sqlite3
import threading
import subprocess
import mimetypes
from datetime import datetime, timedelta
from typing import Dict, Optional
from http.server import HTTPServer, BaseHTTPRequestHandler

# Rich console (local development এ কাজ করবে, প্রোডাকশনে ঐচ্ছিক)
from rich.console import Console
from rich.panel import Panel

# Telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# yt-dlp
from yt_dlp import YoutubeDL

# ============ LOGGING SETUP – SILENT MODE ============
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.WARNING
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("yt_dlp").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)
console = Console()

# ============ CONFIGURATION (Environment variables) ============
class Config:
    TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN', 'YOUR_BOT_TOKEN')
    admin_ids_str = os.getenv('ADMIN_IDS', '6804172454')
    ADMIN_IDS = [int(x.strip()) for x in admin_ids_str.split(',') if x.strip()]
    CHANNEL_LINK = os.getenv('CHANNEL_LINK', 'https://t.me/shihab_ff_66bot')
    BOT_USERNAME = os.getenv('BOT_USERNAME', '@File_store69xx_bot')
    
    MAX_STORAGE_MB = 1000
    AUTO_CLEANUP_HOURS = 1
    MAX_FILE_SIZE_MB = 50
    MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
    
    MAX_DOWNLOADS_PER_DAY = 100
    RATE_LIMIT_PER_HOUR = 30
    
    # Persistent storage (if /app/data exists, use it)
    if os.path.exists('/app/data'):
        DOWNLOAD_DIR = '/app/data/downloads'
        DB_PATH = '/app/data/downloads.db'
    else:
        DOWNLOAD_DIR = 'downloads'
        DB_PATH = 'downloads.db'
    
    TEMP_DIR = 'temp'
    
    YDL_OPTIONS = {
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': False,
        'no_color': True,
        'cookiefile': 'cookies.txt',
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web'],
                'player_skip': ['configs', 'webpage'],
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        },
        'retries': 10,
        'fragment_retries': 10,
        'skip_unavailable_fragments': True,
        'socket_timeout': 30,
        'merge_output_format': 'mp4',
        'postprocessors': [{
            'key': 'FFmpegVideoConvertor',
            'preferedformat': 'mp4',
        }],
    }

# ============ STORAGE MANAGER ============
class StorageManager:
    def __init__(self):
        self.download_dir = Config.DOWNLOAD_DIR
        self.temp_dir = Config.TEMP_DIR
        self.db_path = Config.DB_PATH
        
        os.makedirs(self.download_dir, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)
        
        self.init_database()
        self.start_cleanup_scheduler()
        console.print("[green]✓ Storage Manager initialized[/green]")
    
    def init_database(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS downloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                user_name TEXT,
                platform TEXT,
                url TEXT,
                filename TEXT,
                file_path TEXT,
                file_size INTEGER,
                status TEXT DEFAULT 'pending',
                download_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sent_time TIMESTAMP,
                deleted BOOLEAN DEFAULT 0
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_stats (
                user_id INTEGER PRIMARY KEY,
                user_name TEXT,
                total_downloads INTEGER DEFAULT 0,
                downloads_today INTEGER DEFAULT 0,
                last_download_date DATE,
                joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()
    
    def log_download(self, user_id, user_name, platform, url, filename, file_path):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
        cursor.execute('''
            INSERT INTO downloads 
            (user_id, user_name, platform, url, filename, file_path, file_size, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'downloaded')
        ''', (user_id, user_name, platform, url, filename, file_path, file_size))
        download_id = cursor.lastrowid
        
        today = datetime.now().date()
        cursor.execute('''
            INSERT OR IGNORE INTO user_stats (user_id, user_name, joined_date)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        ''', (user_id, user_name))
        cursor.execute('''
            UPDATE user_stats 
            SET total_downloads = total_downloads + 1,
                downloads_today = CASE 
                    WHEN last_download_date = DATE(?) THEN downloads_today + 1 
                    ELSE 1 
                END,
                last_download_date = DATE(?)
            WHERE user_id = ?
        ''', (today, today, user_id))
        conn.commit()
        conn.close()
        return download_id
    
    def mark_as_sent(self, download_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE downloads 
            SET status = 'sent', sent_time = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (download_id,))
        conn.commit()
        conn.close()
    
    def cleanup_old_files(self, hours_old=None):
        if hours_old is None:
            hours_old = Config.AUTO_CLEANUP_HOURS
        cutoff = datetime.now() - timedelta(hours=hours_old)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, file_path FROM downloads 
            WHERE download_time < ? AND deleted = 0
        ''', (cutoff,))
        deleted = 0
        for fid, fpath in cursor.fetchall():
            try:
                if os.path.exists(fpath):
                    os.remove(fpath)
                cursor.execute('UPDATE downloads SET deleted = 1 WHERE id = ?', (fid,))
                deleted += 1
            except:
                pass
        conn.commit()
        conn.close()
        if deleted:
            console.print(f"[cyan]🧹 Cleaned {deleted} old files[/cyan]")
        return deleted
    
    def clean_empty_dirs(self):
        for root, dirs, files in os.walk(self.download_dir, topdown=False):
            for d in dirs:
                full = os.path.join(root, d)
                try:
                    if not os.listdir(full):
                        os.rmdir(full)
                except:
                    pass
    
    def get_user_stats(self, user_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT total_downloads, downloads_today, joined_date
            FROM user_stats WHERE user_id = ?
        ''', (user_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            total, today, joined = row
        else:
            total = today = 0
            joined = datetime.now()
        return {
            'total_downloads': total,
            'downloads_today': today,
            'max_per_day': Config.MAX_DOWNLOADS_PER_DAY,
            'joined_date': joined,
            'remaining_today': max(0, Config.MAX_DOWNLOADS_PER_DAY - today)
        }
    
    def can_user_download(self, user_id):
        stats = self.get_user_stats(user_id)
        if stats['downloads_today'] >= Config.MAX_DOWNLOADS_PER_DAY:
            return False, f"Daily limit ({Config.MAX_DOWNLOADS_PER_DAY}) reached. Try tomorrow."
        return True, ""
    
    def start_cleanup_scheduler(self):
        import schedule
        def job():
            self.cleanup_old_files()
        schedule.every(30).minutes.do(job)
        def runner():
            while True:
                schedule.run_pending()
                time.sleep(60)
        threading.Thread(target=runner, daemon=True).start()

# ============ DOWNLOAD MANAGER ============
class DownloadManager:
    def __init__(self):
        self.user_sessions: Dict[int, dict] = {}
    
    def detect_platform(self, url: str) -> str:
        url = url.lower()
        if 'youtube.com' in url or 'youtu.be' in url:
            return 'YouTube'
        if 'instagram.com' in url:
            return 'Instagram'
        if 'tiktok.com' in url:
            return 'TikTok'
        if 'twitter.com' in url or 'x.com' in url:
            return 'Twitter/X'
        if 'facebook.com' in url or 'fb.watch' in url:
            return 'Facebook'
        if 'reddit.com' in url:
            return 'Reddit'
        if 'pinterest.com' in url or 'pin.it' in url:
            return 'Pinterest'
        return 'Unknown'
    
    def get_format_keyboard(self, platform: str):
        buttons = [
            [InlineKeyboardButton("🎬 Best Quality", callback_data="format_best"),
             InlineKeyboardButton("🎵 Audio Only", callback_data="format_audio")],
            [InlineKeyboardButton("📱 Medium (720p)", callback_data="format_medium"),
             InlineKeyboardButton("💾 Small (480p)", callback_data="format_small")]
        ]
        if platform == "Pinterest":
            buttons.insert(0, [InlineKeyboardButton("🖼️ Download as Image", callback_data="format_image")])
        buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
        return InlineKeyboardMarkup(buttons)
    
    def get_format_string(self, choice: str, platform: str) -> str:
        if platform == "YouTube" and choice == "format_best":
            return "bv*[height<=1080]+ba/b[height<=1080] / bv*+ba/b"
        if platform == "Facebook":
            if choice == "format_best":
                return "best"
            if choice == "format_medium":
                return "best[height<=720]"
            if choice == "format_small":
                return "best[height<=480]"
        if platform == "Pinterest" and choice == "format_image":
            return "best"
        # Default mapping
        mapping = {
            "format_best": "bv*+ba/b",
            "format_audio": "ba/b",
            "format_medium": "best[height<=720]",
            "format_small": "best[height<=480]"
        }
        return mapping.get(choice, "best")
    
    def get_ydl_options(self, choice: str, platform: str) -> dict:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"%(title)s_{ts}.%(ext)s"
        outpath = os.path.join(storage_manager.download_dir, fname)
        opts = Config.YDL_OPTIONS.copy()
        opts['outtmpl'] = outpath
        opts['format'] = self.get_format_string(choice, platform)
        
        if platform == "YouTube":
            opts['extractor_args'] = {'youtube': {'player_client': ['android', 'web']}}
        elif platform == "Instagram":
            opts['extractor_args'] = {'instagram': {'post': 'single'}}
        elif platform == "Facebook":
            opts['cookiefile'] = 'cookies.txt'
        
        if choice == "format_audio":
            opts['format'] = 'ba/b'
            opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
            # remove video convertor
            opts['postprocessors'] = [p for p in opts.get('postprocessors', [])
                                      if p.get('key') != 'FFmpegVideoConvertor']
        return opts
    
    async def handle_tiktok(self, query, context, url, choice, user_id, user_name):
        methods = [
            {'name': 'Method 1', 'opts': {'extractor_args': {'tiktok': {'app_version': '29.7.4'}}}},
            {'name': 'Method 2', 'opts': {'extractor_args': {'tiktok': {'web_client': 'web'}}}},
            {'name': 'Method 3', 'opts': {'extractor_args': {'tiktok': {'api_hostname': 'api19-normal-c-useast1a.tiktokv.com'}}}},
            {'name': 'Method 4', 'opts': {'force_generic_extractor': True}},
        ]
        for m in methods:
            try:
                await query.edit_message_text(f"⏬ TikTok... 🔄 {m['name']}", parse_mode='HTML')
                opts = self.get_ydl_options(choice, 'TikTok')
                opts.update(m['opts'])
                opts['progress_hooks'] = [self.progress_hook]
                with YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    await send_downloaded_file(query, context, info, url, user_id, user_name, 'TikTok', ydl)
                return
            except Exception as e:
                console.print(f"[yellow]{m['name']} failed: {str(e)[:100]}[/yellow]")
                continue
        raise Exception("All TikTok methods failed.")
    
    async def handle_pinterest(self, query, context, url, choice, user_id, user_name):
        try:
            # test if it's image
            test_opts = Config.YDL_OPTIONS.copy()
            test_opts['quiet'] = True
            test_opts['extract_flat'] = True
            with YoutubeDL(test_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                is_image = not info.get('formats') or len(info.get('formats', [])) <= 1
                if is_image or choice == "format_image":
                    await query.edit_message_text("⏬ Downloading image from Pinterest...", parse_mode='HTML')
                    opts = self.get_ydl_options("format_best", 'Pinterest')
                    opts['format'] = 'best'
                else:
                    await query.edit_message_text("⏬ Downloading video from Pinterest...", parse_mode='HTML')
                    opts = self.get_ydl_options(choice, 'Pinterest')
                opts['progress_hooks'] = [self.progress_hook]
                with YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    await send_downloaded_file(query, context, info, url, user_id, user_name, 'Pinterest', ydl)
        except Exception as e:
            # fallback generic
            opts = self.get_ydl_options(choice, 'Pinterest')
            opts['force_generic_extractor'] = True
            opts['progress_hooks'] = [self.progress_hook]
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                await send_downloaded_file(query, context, info, url, user_id, user_name, 'Pinterest', ydl)
    
    async def handle_youtube(self, query, context, url, choice, user_id, user_name):
        methods = [
            {'name': 'Standard', 'opts': {}},
            {'name': '720p Fallback', 'opts': {'format': 'best[height<=720]'}},
            {'name': 'Audio Only', 'opts': {'format': 'ba', 'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}]}},
        ]
        for m in methods:
            try:
                await query.edit_message_text(f"⏬ YouTube... 🔄 {m['name']}", parse_mode='HTML')
                opts = self.get_ydl_options(choice, 'YouTube')
                opts.update(m['opts'])
                opts['progress_hooks'] = [self.progress_hook]
                with YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    await send_downloaded_file(query, context, info, url, user_id, user_name, 'YouTube', ydl)
                return
            except Exception as e:
                console.print(f"[yellow]{m['name']} failed: {str(e)[:100]}[/yellow]")
                continue
        raise Exception("All YouTube methods failed.")
    
    def progress_hook(self, d):
        if d['status'] == 'finished':
            console.print("\n[green]✓ Download completed[/green]")
    
    def compress_video(self, in_path, out_path, target_size=Config.MAX_FILE_SIZE_BYTES):
        try:
            subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        except:
            return None
        probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', in_path],
                               capture_output=True, text=True)
        try:
            dur = float(probe.stdout.strip())
        except:
            return None
        bitrate = (target_size * 8) / dur * 0.9
        bitrate = int(max(bitrate, 100000))
        cmd = [
            'ffmpeg', '-i', in_path,
            '-b:v', str(bitrate),
            '-maxrate', str(int(bitrate*1.2)),
            '-bufsize', str(int(bitrate*2)),
            '-c:v', 'libx264',
            '-preset', 'medium',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-y', out_path
        ]
        res = subprocess.run(cmd, capture_output=True)
        if res.returncode == 0 and os.path.exists(out_path):
            return out_path
        return None

# ============ GLOBAL INSTANCES ============
storage_manager = StorageManager()
download_manager = DownloadManager()

# ============ TELEGRAM HANDLERS ============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = f"""
👋 <b>Welcome {user.first_name}!</b>

🎬 <b>Ultimate Social Media Downloader Bot</b>
Download from 15+ platforms in highest quality!

<b>Supported:</b> YouTube, Instagram, TikTok, Twitter, Facebook, Reddit, Pinterest (images/videos), and more.

<b>How to use:</b>
1. Send any social media link
2. Choose quality
3. Get your media!

<b>Commands:</b>
/start - This message
/stats - Your statistics
/help - Instructions

<b>Bot by:</b> {Config.BOT_USERNAME}
<b>Channel:</b> {Config.CHANNEL_LINK}
    """
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📢 Join Channel", url=Config.CHANNEL_LINK)]])
    await update.message.reply_text(text, reply_markup=kb, parse_mode='HTML', disable_web_page_preview=True)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """
📚 <b>How to Download:</b>

1. Copy any social media link
2. Send it to this bot
3. Choose quality option
4. Wait for download (10-30 seconds)
5. Receive your video/audio/image!

<b>Tips:</b>
• If file >50MB, bot will try to compress (requires ffmpeg).
• For YouTube 1080p, add cookies.txt (see instructions).
• Pinterest images auto-detected.

<b>Need help?</b> Contact @shihab_ff_857
    """
    await update.message.reply_text(text, parse_mode='HTML')

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    s = storage_manager.get_user_stats(user.id)
    text = f"""
📊 <b>Your Statistics</b>

👤 User: <code>{user.username or user.first_name}</code>
🆔 ID: <code>{user.id}</code>

<b>Downloads:</b>
📥 Today: <code>{s['downloads_today']}/{s['max_per_day']}</code>
📈 Total: <code>{s['total_downloads']}</code>

<b>Remaining today:</b> <code>{s['remaining_today']}</code>
    """
    await update.message.reply_text(text, parse_mode='HTML')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    url = update.message.text.strip()
    
    if not url.startswith(('http://', 'https://', 'www.')):
        await update.message.reply_text("❌ Please send a valid URL starting with http:// or https://", parse_mode='HTML')
        return
    
    ok, reason = storage_manager.can_user_download(user.id)
    if not ok:
        await update.message.reply_text(f"⚠️ {reason}")
        return
    
    platform = download_manager.detect_platform(url)
    if platform == "Unknown":
        await update.message.reply_text("⚠️ <b>Platform not recognized</b>\nTrying anyway...", parse_mode='HTML')
    else:
        await update.message.reply_text(f"✅ <b>{platform}</b> link detected!", parse_mode='HTML')
    
    download_manager.user_sessions[user.id] = {
        'url': url,
        'platform': platform,
        'user_name': user.username or user.first_name,
    }
    
    kb = download_manager.get_format_keyboard(platform)
    msg = "🎬 <b>Select Quality:</b>\n• Best: Highest available\n• Audio: MP3\n• Medium: ~720p\n• Small: ~480p"
    if platform == "Pinterest":
        msg = "🖼️ <b>Pinterest detected!</b>\nChoose image or video quality:"
    await update.message.reply_text(msg, reply_markup=kb, parse_mode='HTML')

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data
    
    if data == "cancel":
        await query.edit_message_text("❌ Download cancelled.")
        download_manager.user_sessions.pop(user_id, None)
        return
    
    sess = download_manager.user_sessions.get(user_id)
    if not sess:
        await query.edit_message_text("❌ Session expired. Please send link again.")
        return
    
    url = sess['url']
    platform = sess['platform']
    user_name = sess['user_name']
    
    await query.edit_message_text(f"⏬ <b>Downloading from {platform}...</b>\n⏳ Please wait...", parse_mode='HTML')
    
    try:
        if platform == "TikTok":
            await download_manager.handle_tiktok(query, context, url, data, user_id, user_name)
        elif platform == "YouTube":
            await download_manager.handle_youtube(query, context, url, data, user_id, user_name)
        elif platform == "Pinterest":
            await download_manager.handle_pinterest(query, context, url, data, user_id, user_name)
        else:
            opts = download_manager.get_ydl_options(data, platform)
            opts['progress_hooks'] = [download_manager.progress_hook]
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                await send_downloaded_file(query, context, info, url, user_id, user_name, platform, ydl)
    except Exception as e:
        await show_error(query, str(e), platform, url)
    finally:
        download_manager.user_sessions.pop(user_id, None)

async def send_downloaded_file(query, context, info, url, user_id, user_name, platform, ydl):
    # Get file path
    if 'requested_downloads' in info and info['requested_downloads']:
        file_path = info['requested_downloads'][0].get('filepath')
    else:
        file_path = ydl.prepare_filename(info)
    
    # Handle different extensions
    if not os.path.exists(file_path):
        base = os.path.splitext(file_path)[0]
        for ext in ['.mp4', '.mkv', '.webm', '.mp3', '.m4a', '.jpg', '.jpeg', '.png']:
            test = base + ext
            if os.path.exists(test):
                file_path = test
                break
    
    if not os.path.exists(file_path):
        raise Exception("Downloaded file not found")
    
    file_size = os.path.getsize(file_path)
    title = info.get('title', 'Media')[:100]
    mime, _ = mimetypes.guess_type(file_path)
    is_image = mime and mime.startswith('image')
    is_audio = mime and mime.startswith('audio')
    is_video = mime and mime.startswith('video')
    
    # Compress large videos
    if is_video and file_size > Config.MAX_FILE_SIZE_BYTES:
        ffmpeg_ok = False
        try:
            subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
            ffmpeg_ok = True
        except:
            pass
        if not ffmpeg_ok:
            await query.edit_message_text(
                f"❌ File too large ({file_size//1024//1024}MB) and ffmpeg not installed. Please install ffmpeg or try lower quality.",
                parse_mode='HTML'
            )
            return
        await query.edit_message_text(f"📦 Size {file_size//1024//1024}MB > 50MB. 🔄 Compressing...", parse_mode='HTML')
        compressed = file_path + "_compressed.mp4"
        new_path = download_manager.compress_video(file_path, compressed)
        if new_path:
            os.remove(file_path)
            file_path = new_path
            file_size = os.path.getsize(file_path)
        else:
            await query.edit_message_text("❌ Compression failed. Try lower quality.", parse_mode='HTML')
            return
    
    # Log download
    download_id = storage_manager.log_download(user_id, user_name, platform, url, os.path.basename(file_path), file_path)
    
    await query.edit_message_text(
        f"✅ <b>Download Complete!</b>\n📹 {title}\n📏 Size: {file_size//1024//1024}MB\n📤 <b>Sending...</b>",
        parse_mode='HTML'
    )
    
    caption = f"✅ Downloaded from {platform}\n📹 {title}\n\n<b>Bot by:</b> {Config.BOT_USERNAME}\n<b>Channel:</b> {Config.CHANNEL_LINK}"
    
    try:
        with open(file_path, 'rb') as f:
            if is_audio or file_path.endswith(('.mp3', '.m4a')):
                await context.bot.send_audio(chat_id=query.message.chat_id, audio=f, caption=caption, parse_mode='HTML')
            elif is_image or file_path.endswith(('.jpg', '.jpeg', '.png')):
                await context.bot.send_photo(chat_id=query.message.chat_id, photo=f, caption=caption, parse_mode='HTML')
            else:
                await context.bot.send_video(chat_id=query.message.chat_id, video=f, caption=caption, supports_streaming=True, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Send error: {e}")
        await query.message.reply_text("❌ Failed to send file.")
        return
    
    storage_manager.mark_as_sent(download_id)
    try:
        os.remove(file_path)
    except:
        pass
    
    # Final success
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📢 Join Channel", url=Config.CHANNEL_LINK)]])
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=f"🎉 <b>Successfully Sent!</b>\n\n<b>Credits:</b>\nBot by {Config.BOT_USERNAME}\nJoin our channel: {Config.CHANNEL_LINK}\n\n✨ <b>Thank you!</b>",
        reply_markup=kb,
        parse_mode='HTML'
    )

async def show_error(query, error_msg, platform, url):
    # Clean common errors
    if "Sign in" in error_msg:
        error_msg = "YouTube requires authentication. Use cookies.txt or lower quality."
    elif "403" in error_msg and "TikTok" in error_msg:
        error_msg = "TikTok blocking requests. Try later or different video."
    elif "No video formats" in error_msg and "Pinterest" in error_msg:
        error_msg = "This Pinterest pin may be an image. Try 'Download as Image' option."
    elif "ffmpeg" in error_msg.lower():
        error_msg = "ffmpeg not installed. Use Dockerfile with ffmpeg."
    
    text = f"❌ <b>Download Failed</b>\n\n<b>Platform:</b> {platform}\n<b>Error:</b> <code>{error_msg[:200]}</code>\n\n<b>Solutions:</b>\n1. Try different quality\n2. Try another video\n3. Wait and retry\n\n<b>Need help?</b> Contact @shihab_ff_857"
    await query.edit_message_text(text, parse_mode='HTML')

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")

# ============ HEALTH SERVER (with auto-restart) ============
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_health_server():
    while True:
        try:
            port = int(os.environ.get('PORT', 8080))
            server = HTTPServer(('0.0.0.0', port), HealthHandler)
            console.print(f"[green]✓ Health server started on port {port}[/green]")
            server.serve_forever()
        except Exception as e:
            console.print(f"[red]✗ Health server error: {e}. Restarting in 5 seconds...[/red]")
            time.sleep(5)

# ============ MAIN ============
def main():
    # Start health server in background
    threading.Thread(target=run_health_server, daemon=True).start()
    console.print("[green]✓ Health server thread started[/green]")
    
    # Check ffmpeg
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        console.print("[green]✓ ffmpeg found[/green]")
    except:
        console.print("[yellow]⚠ ffmpeg not found – compression disabled[/yellow]")
    
    # Build bot application
    app = Application.builder().token(Config.TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_error_handler(error_handler)
    
    console.print("[green]✓ Bot is running. Press Ctrl+C to stop.[/green]")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Bot stopped by user.[/yellow]")
    except Exception as e:
        console.print(f"[red]Fatal error: {e}[/red]")
