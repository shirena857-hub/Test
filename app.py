#!/usr/bin/env python3
"""
Social Media Downloader Bot – Render Worker Edition (No Port, Silent Logs)
Author: @UnknownGuy9876
Channel: https://t.me/+zGWXoEQXRo02YmRl
"""

import os
import sys
import logging
import time
import sqlite3
import threading
import subprocess
import schedule
import mimetypes
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# Rich console (optional, but we keep it for local run)
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
    level=logging.WARNING  # Only WARNING and above
)
# Mute noisy libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("yt_dlp").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)
console = Console()

# ============ CONFIGURATION (Environment variables) ============
class Config:
    TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN', '8642055013:AAGFs4ti8RVhOZ8RP2Ta8xrXzSsT6b4dwsY')
    
    # ADMIN_IDS as comma-separated string, e.g. "6804172454,123456789"
    admin_ids_str = os.getenv('ADMIN_IDS', '6804172454')
    ADMIN_IDS = [int(x.strip()) for x in admin_ids_str.split(',') if x.strip()]
    
    CHANNEL_LINK = os.getenv('CHANNEL_LINK', 'https://t.me/shihab_ff_66bot')
    BOT_USERNAME = os.getenv('BOT_USERNAME', '@File_store69xx_bot')
    
    # Storage limits
    MAX_STORAGE_MB = 1000
    AUTO_CLEANUP_HOURS = 1
    MAX_FILE_SIZE_MB = 100
    MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
    
    # User limits
    MAX_DOWNLOADS_PER_DAY = 100
    RATE_LIMIT_PER_HOUR = 20
    
    # Paths – use /app/data if disk mounted, else local
    if os.path.exists('/app/data'):
        DOWNLOAD_DIR = '/app/data/downloads'
        DB_PATH = '/app/data/downloads.db'
    else:
        DOWNLOAD_DIR = 'downloads'
        DB_PATH = 'downloads.db'
    
    TEMP_DIR = 'temp'
    
    # yt-dlp base options
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
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
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

# ============ STORAGE MANAGER (unchanged) ============
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
    
    def log_download(self, user_id: int, user_name: str, platform: str, 
                    url: str, filename: str, file_path: str) -> int:
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
    
    def mark_as_sent(self, download_id: int):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE downloads 
            SET status = 'sent', sent_time = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (download_id,))
        conn.commit()
        conn.close()
    
    def cleanup_old_files(self, hours_old: int = None):
        if hours_old is None:
            hours_old = Config.AUTO_CLEANUP_HOURS
        cutoff_time = datetime.now() - timedelta(hours=hours_old)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, file_path FROM downloads 
            WHERE download_time < ? AND deleted = 0
        ''', (cutoff_time,))
        deleted_count = 0
        for file_id, file_path in cursor.fetchall():
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                cursor.execute('UPDATE downloads SET deleted = 1 WHERE id = ?', (file_id,))
                deleted_count += 1
            except:
                pass
        conn.commit()
        conn.close()
        self.clean_empty_dirs()
        if deleted_count > 0:
            console.print(f"[cyan]🧹 Cleaned {deleted_count} old files[/cyan]")
        return deleted_count
    
    def clean_empty_dirs(self):
        for dirpath, dirnames, filenames in os.walk(self.download_dir, topdown=False):
            for dirname in dirnames:
                full_path = os.path.join(dirpath, dirname)
                try:
                    if not os.listdir(full_path):
                        os.rmdir(full_path)
                except:
                    pass
    
    def get_user_stats(self, user_id: int) -> Dict:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT total_downloads, downloads_today, joined_date
            FROM user_stats 
            WHERE user_id = ?
        ''', (user_id,))
        result = cursor.fetchone()
        conn.close()
        if result:
            total_downloads, downloads_today, joined_date = result
        else:
            total_downloads = downloads_today = 0
            joined_date = datetime.now()
        return {
            'total_downloads': total_downloads,
            'downloads_today': downloads_today,
            'max_per_day': Config.MAX_DOWNLOADS_PER_DAY,
            'joined_date': joined_date,
            'remaining_today': max(0, Config.MAX_DOWNLOADS_PER_DAY - downloads_today)
        }
    
    def can_user_download(self, user_id: int) -> tuple[bool, str]:
        stats = self.get_user_stats(user_id)
        if stats['downloads_today'] >= Config.MAX_DOWNLOADS_PER_DAY:
            return False, f"You've reached your daily limit ({Config.MAX_DOWNLOADS_PER_DAY} downloads). Try again tomorrow!"
        return True, ""
    
    def start_cleanup_scheduler(self):
        def cleanup_job():
            self.cleanup_old_files()
        schedule.every(30).minutes.do(cleanup_job)
        def run_scheduler():
            while True:
                schedule.run_pending()
                time.sleep(60)
        scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        scheduler_thread.start()

# ============ DOWNLOAD MANAGER (minimal changes) ============
class DownloadManager:
    def __init__(self):
        self.user_sessions: Dict[int, Dict] = {}
        self.test_youtube_connection()
    
    def test_youtube_connection(self):
        console.print("[cyan]Testing YouTube connection...[/cyan]")
        test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        try:
            test_opts = Config.YDL_OPTIONS.copy()
            test_opts['quiet'] = True
            test_opts['extract_flat'] = True
            with YoutubeDL(test_opts) as ydl:
                info = ydl.extract_info(test_url, download=False)
                if info:
                    console.print("[green]✓ YouTube connection successful![/green]")
                else:
                    console.print("[yellow]⚠ YouTube test failed (no info)[/yellow]")
        except Exception as e:
            console.print(f"[red]✗ YouTube test failed: {str(e)[:100]}[/red]")
    
    def detect_platform(self, url: str) -> str:
        url_lower = url.lower()
        if 'youtube.com' in url_lower or 'youtu.be' in url_lower:
            return 'YouTube'
        elif 'instagram.com' in url_lower:
            return 'Instagram'
        elif 'tiktok.com' in url_lower:
            return 'TikTok'
        elif 'twitter.com' in url_lower or 'x.com' in url_lower:
            return 'Twitter/X'
        elif 'facebook.com' in url_lower or 'fb.watch' in url_lower:
            return 'Facebook'
        elif 'reddit.com' in url_lower:
            return 'Reddit'
        elif 'pinterest.com' in url_lower or 'pin.it' in url_lower:
            return 'Pinterest'
        else:
            return 'Unknown'
    
    def get_format_keyboard(self, platform: str) -> InlineKeyboardMarkup:
        buttons = [
            [
                InlineKeyboardButton("🎬 Best Quality", callback_data="format_best"),
                InlineKeyboardButton("🎵 Audio Only", callback_data="format_audio")
            ],
            [
                InlineKeyboardButton("📱 Medium (720p)", callback_data="format_medium"),
                InlineKeyboardButton("💾 Small (480p)", callback_data="format_small")
            ]
        ]
        if platform == "Pinterest":
            buttons.insert(0, [InlineKeyboardButton("🖼️ Download as Image", callback_data="format_image")])
        buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
        return InlineKeyboardMarkup(buttons)
    
    def get_format_string(self, format_choice: str, platform: str) -> str:
        if platform == "YouTube" and format_choice == "format_best":
            return "bv*[height<=1080]+ba/b[height<=1080] / bv*+ba/b"
        elif platform == "Facebook":
            if format_choice == "format_best":
                return "best"
            elif format_choice == "format_medium":
                return "best[height<=720]"
            elif format_choice == "format_small":
                return "best[height<=480]"
        elif platform == "Pinterest" and format_choice == "format_image":
            return "best"
        
        # Default mapping
        format_map = {
            "format_best": "bv*+ba/b",
            "format_audio": "ba/b",
            "format_medium": "best[height<=720]",
            "format_small": "best[height<=480]",
        }
        return format_map.get(format_choice, "best")
    
    def get_ydl_options(self, format_choice: str, platform: str) -> Dict:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"%(title)s_{timestamp}.%(ext)s"
        output_path = os.path.join(storage_manager.download_dir, filename)
        
        ydl_opts = Config.YDL_OPTIONS.copy()
        ydl_opts['outtmpl'] = output_path
        ydl_opts['format'] = self.get_format_string(format_choice, platform)
        
        if platform == "YouTube":
            ydl_opts['extractor_args'] = {
                'youtube': {
                    'player_client': ['android', 'web'],
                    'player_skip': ['configs', 'webpage'],
                }
            }
        elif platform == "Instagram":
            ydl_opts['extractor_args'] = {'instagram': {'post': 'single'}}
        elif platform == "Facebook":
            ydl_opts['cookiefile'] = 'cookies.txt'
        
        if format_choice == "format_audio":
            ydl_opts['format'] = 'ba/b'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
            ydl_opts['postprocessors'] = [pp for pp in ydl_opts.get('postprocessors', []) if pp.get('key') != 'FFmpegVideoConvertor']
        
        return ydl_opts
    
    async def handle_tiktok_download(self, query, context, url, format_choice, user_id, user_name, platform):
        methods = [
            {'name': 'Method 1', 'opts': {'extractor_args': {'tiktok': {'app_version': '29.7.4'}}}},
            {'name': 'Method 2', 'opts': {'extractor_args': {'tiktok': {'web_client': 'web'}}}},
            {'name': 'Method 3', 'opts': {'extractor_args': {'tiktok': {'api_hostname': 'api19-normal-c-useast1a.tiktokv.com'}}}},
            {'name': 'Method 4', 'opts': {'force_generic_extractor': True}},
        ]
        
        for method in methods:
            try:
                await query.edit_message_text(
                    f"⏬ <b>Downloading from TikTok...</b>\n🔄 {method['name']}",
                    parse_mode='HTML'
                )
                ydl_opts = self.get_ydl_options(format_choice, platform)
                ydl_opts.update(method['opts'])
                ydl_opts['progress_hooks'] = [self.progress_hook]
                
                with YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    await send_downloaded_file(query, context, info, url, user_id, user_name, platform, ydl)
                return
            except Exception as e:
                console.print(f"[yellow]{method['name']} failed: {str(e)[:100]}[/yellow]")
                continue
        raise Exception("All TikTok methods failed.")
    
    async def handle_pinterest_download(self, query, context, url, format_choice, user_id, user_name, platform):
        try:
            # Quick test to see if it's an image
            test_opts = Config.YDL_OPTIONS.copy()
            test_opts['quiet'] = True
            test_opts['extract_flat'] = True
            with YoutubeDL(test_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                is_image = not info.get('formats') or len(info.get('formats', [])) <= 1
                
                if is_image or format_choice == "format_image":
                    await query.edit_message_text("⏬ <b>Downloading image from Pinterest...</b>", parse_mode='HTML')
                    ydl_opts = self.get_ydl_options("format_best", platform)
                    ydl_opts['format'] = 'best'
                else:
                    await query.edit_message_text("⏬ <b>Downloading video from Pinterest...</b>", parse_mode='HTML')
                    ydl_opts = self.get_ydl_options(format_choice, platform)
                
                ydl_opts['progress_hooks'] = [self.progress_hook]
                with YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    await send_downloaded_file(query, context, info, url, user_id, user_name, platform, ydl)
        except Exception as e:
            # Fallback to generic
            try:
                ydl_opts = self.get_ydl_options(format_choice, platform)
                ydl_opts['force_generic_extractor'] = True
                ydl_opts['progress_hooks'] = [self.progress_hook]
                with YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    await send_downloaded_file(query, context, info, url, user_id, user_name, platform, ydl)
            except Exception as e2:
                raise Exception(f"Pinterest download failed: {str(e2)}")
    
    def progress_hook(self, d):
        if d['status'] == 'finished':
            console.print("\n[green]✓ Download completed[/green]")
    
    def compress_video(self, input_path: str, output_path: str, target_size: int = Config.MAX_FILE_SIZE_BYTES) -> Optional[str]:
        try:
            subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        except:
            return None
        
        probe = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', input_path],
            capture_output=True, text=True
        )
        try:
            duration = float(probe.stdout.strip())
        except:
            return None
        
        target_bitrate = (target_size * 8) / duration * 0.9
        target_bitrate = int(max(target_bitrate, 100000))
        
        cmd = [
            'ffmpeg', '-i', input_path,
            '-b:v', str(target_bitrate),
            '-maxrate', str(int(target_bitrate*1.2)),
            '-bufsize', str(int(target_bitrate*2)),
            '-c:v', 'libx264',
            '-preset', 'medium',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-y', output_path
        ]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode == 0 and os.path.exists(output_path):
            return output_path
        return None

# ============ GLOBAL INSTANCES ============
storage_manager = StorageManager()
download_manager = DownloadManager()

# ============ TELEGRAM HANDLERS (unchanged but HTML parse_mode) ============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome_text = f"""
👋 <b>Welcome {user.first_name}!</b>

🎬 <b>Ultimate Social Media Downloader Bot</b>
Download from 15+ platforms in highest quality!

<b>Supported Platforms:</b>
• YouTube (1080p HD)
• Instagram (Reels/Posts)
• TikTok (No Watermark)
• Twitter/X (Videos)
• Facebook (Videos)
• Reddit (Videos)
• Pinterest (Images & Videos)
• And many more!

<b>How to use:</b>
1. Send any social media link
2. Choose quality option
3. Get your media!

<b>Commands:</b>
/start - Show this message
/stats - Your statistics
/help - Help & instructions

<b>Bot by:</b> {Config.BOT_USERNAME}
<b>Channel:</b> {Config.CHANNEL_LINK}
    """
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("📢 Join Channel", url=Config.CHANNEL_LINK)
    ]])
    await update.message.reply_text(
        welcome_text,
        reply_markup=keyboard,
        parse_mode='HTML',
        disable_web_page_preview=True
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
📚 <b>How to Download:</b>

1. Copy any social media link
2. Send it to this bot
3. Choose quality option
4. Wait for download
5. Receive your media!

<b>Tips:</b>
• If file >50MB, bot tries to compress
• For YouTube 1080p, use cookies.txt
• Pinterest images auto-detected

<b>Need help?</b> Contact @shihab_ff_857
    """
    await update.message.reply_text(help_text, parse_mode='HTML')

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    stats = storage_manager.get_user_stats(user.id)
    text = f"""
📊 <b>Your Statistics</b>

👤 User: <code>{user.username or user.first_name}</code>
🆔 ID: <code>{user.id}</code>

<b>Download Stats:</b>
📥 Today: <code>{stats['downloads_today']}/{stats['max_per_day']}</code>
📈 Total: <code>{stats['total_downloads']}</code>

<b>Remaining:</b> <code>{stats['remaining_today']}</code> downloads
    """
    await update.message.reply_text(text, parse_mode='HTML')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    url = update.message.text.strip()
    
    if not url.startswith(('http://', 'https://', 'www.')):
        await update.message.reply_text(
            "❌ Please send a valid URL starting with http:// or https://",
            parse_mode='HTML'
        )
        return
    
    can_download, reason = storage_manager.can_user_download(user.id)
    if not can_download:
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
    
    keyboard = download_manager.get_format_keyboard(platform)
    quality_text = (
        "🎬 <b>Select Quality:</b>\n"
        "• Best Quality: Highest available\n"
        "• Audio Only: Extract MP3\n"
        "• Medium: 720p (if available)\n"
        "• Small: 480p (if available)"
    )
    if platform == "Pinterest":
        quality_text = "🖼️ <b>Pinterest detected!</b>\nChoose image or video quality:"
    
    await update.message.reply_text(quality_text, reply_markup=keyboard, parse_mode='HTML')

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data
    
    if data == "cancel":
        await query.edit_message_text("❌ Download cancelled.")
        download_manager.user_sessions.pop(user_id, None)
        return
    
    session = download_manager.user_sessions.get(user_id)
    if not session:
        await query.edit_message_text("❌ Session expired. Please send the link again.")
        return
    
    url = session['url']
    platform = session['platform']
    user_name = session['user_name']
    
    await query.edit_message_text(f"⏬ <b>Downloading from {platform}...</b>\n⏳ Please wait...", parse_mode='HTML')
    
    try:
        if platform == "TikTok":
            await download_manager.handle_tiktok_download(query, context, url, data, user_id, user_name, platform)
        elif platform == "YouTube":
            await handle_youtube_download(query, context, url, data, user_id, user_name, platform)
        elif platform == "Pinterest":
            await download_manager.handle_pinterest_download(query, context, url, data, user_id, user_name, platform)
        else:
            ydl_opts = download_manager.get_yl_options(data, platform)
            ydl_opts['progress_hooks'] = [download_manager.progress_hook]
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                await send_downloaded_file(query, context, info, url, user_id, user_name, platform, ydl)
    except Exception as e:
        await show_error_message(query, str(e), platform, url)
    finally:
        download_manager.user_sessions.pop(user_id, None)

async def handle_youtube_download(query, context, url, format_choice, user_id, user_name, platform):
    methods = [
        {'name': 'Standard', 'opts': {}},
        {'name': '720p Fallback', 'opts': {'format': 'best[height<=720]'}},
        {'name': 'Audio Only', 'opts': {'format': 'ba', 'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}]}},
    ]
    for method in methods:
        try:
            await query.edit_message_text(f"⏬ <b>Downloading from YouTube...</b>\n🔄 {method['name']}", parse_mode='HTML')
            ydl_opts = download_manager.get_ydl_options(format_choice, platform)
            ydl_opts.update(method['opts'])
            ydl_opts['progress_hooks'] = [download_manager.progress_hook]
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                await send_downloaded_file(query, context, info, url, user_id, user_name, platform, ydl)
            return
        except Exception as e:
            console.print(f"[yellow]{method['name']} failed: {str(e)[:100]}[/yellow]")
            continue
    raise Exception("All YouTube methods failed.")

async def send_downloaded_file(query, context, info, url, user_id, user_name, platform, ydl):
    # Get file path
    if 'requested_downloads' in info and info['requested_downloads']:
        file_path = info['requested_downloads'][0].get('filepath')
    else:
        file_path = ydl.prepare_filename(info)
    
    # Handle extension variations
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
    
    # Compression for large videos
    if is_video and file_size > Config.MAX_FILE_SIZE_BYTES:
        # Check ffmpeg
        ffmpeg_ok = False
        try:
            subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
            ffmpeg_ok = True
        except:
            pass
        
        if not ffmpeg_ok:
            await query.edit_message_text(
                f"❌ File too large ({file_size//1024//1024}MB) and ffmpeg not installed.\n"
                f"Please install ffmpeg or try lower quality.\n"
                f"<b>Render users:</b> Use Dockerfile with ffmpeg.",
                parse_mode='HTML'
            )
            return
        
        await query.edit_message_text(
            f"📦 File size {file_size//1024//1024}MB > {Config.MAX_FILE_SIZE_MB}MB.\n"
            f"🔄 Compressing...",
            parse_mode='HTML'
        )
        compressed = file_path + "_compressed.mp4"
        new_path = download_manager.compress_video(file_path, compressed)
        if new_path:
            os.remove(file_path)
            file_path = new_path
            file_size = os.path.getsize(file_path)
        else:
            await query.edit_message_text(
                f"❌ Compression failed. Try lower quality.",
                parse_mode='HTML'
            )
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
    
    # Final success message
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("📢 Join Channel", url=Config.CHANNEL_LINK)
    ]])
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=f"🎉 <b>Successfully Sent!</b>\n\n<b>Credits:</b>\nBot by {Config.BOT_USERNAME}\nJoin our channel: {Config.CHANNEL_LINK}\n\n✨ <b>Thank you!</b>",
        reply_markup=keyboard,
        parse_mode='HTML'
    )

async def show_error_message(query, error_msg, platform, url):
    # Clean common errors
    if "Sign in" in error_msg:
        error_msg = "YouTube requires authentication. Use cookies.txt or lower quality."
    elif "403" in error_msg and "TikTok" in error_msg:
        error_msg = "TikTok blocking. Try later or different video."
    elif "No video formats" in error_msg and "Pinterest" in error_msg:
        error_msg = "This Pinterest pin may be an image. Try 'Download as Image'."
    elif "ffmpeg" in error_msg.lower():
        error_msg = "ffmpeg not installed. Use Dockerfile with ffmpeg."
    
    text = f"❌ <b>Download Failed</b>\n\n<b>Platform:</b> {platform}\n<b>Error:</b> <code>{error_msg[:200]}</code>\n\n<b>Solutions:</b>\n1. Try different quality\n2. Try another video\n3. Wait and retry\n\n<b>Need help?</b> Contact @shihab_ff_857"
    await query.edit_message_text(text, parse_mode='HTML')

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")

# ============ MAIN – NO PORT, ONLY WORKER ============
def main():
    # Print startup banner
    banner = Panel.fit(
        f"[bold cyan]Ultimate Social Media Downloader Bot[/bold cyan]\n"
        f"[green]Running as Render Worker – No Port Needed[/green]\n"
        f"[yellow]Log level: WARNING (minimal)[/yellow]",
        title="🤖 Bot Status",
        border_style="cyan"
    )
    console.print(banner)
    
    # Check ffmpeg
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        console.print("[green]✓ ffmpeg found[/green]")
    except:
        console.print("[yellow]⚠ ffmpeg not found – compression disabled[/yellow]")
    
    # Create application
    application = Application.builder().token(Config.TELEGRAM_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_error_handler(error_handler)
    
    # Start polling (this blocks)
    console.print("[green]✓ Bot is running. Press Ctrl+C to stop.[/green]")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Bot stopped by user.[/yellow]")
    except Exception as e:
        console.print(f"[red]Fatal error: {e}[/red]")
