#!/usr/bin/env python3
"""
Social Media Downloader Bot - ULTIMATE FIXED VERSION
Author: @UnknownGuy9876
Channel: https://t.me/+zGWXoEQXRo02YmRl
"""

import os
import sys
import json
import logging
import time
import sqlite3
import threading
import subprocess
import schedule
import mimetypes
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# Rich for console output
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Telegram Bot
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# Downloader
from yt_dlp import YoutubeDL

# Initialize
console = Console()
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============ CONFIGURATION ============
class Config:
    TELEGRAM_TOKEN = "8215271981:AAEIn1H03uk5LkPQc_XjARWuBGLhCtcrrew"
    ADMIN_IDS = [6804172454]
    CHANNEL_LINK = "https://t.me/shihab_ff_66bot"
    BOT_USERNAME = "@shihab_ff_log_bot"
    
    # Storage limits
    MAX_STORAGE_MB = 1000
    AUTO_CLEANUP_HOURS = 1
    MAX_FILE_SIZE_MB = 50
    MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
    
    # User limits
    MAX_DOWNLOADS_PER_DAY = 100
    RATE_LIMIT_PER_HOUR = 30
    
    # Paths
    DOWNLOAD_DIR = "downloads"
    TEMP_DIR = "temp"
    DB_PATH = "downloads.db"
    
    # yt-dlp settings
    YDL_OPTIONS = {
        'quiet': True,
        'no_warnings': False,
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
            'Accept-Language': 'en-US,en;q=0.5',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        },
        'retries': 10,
        'fragment_retries': 10,
        'skip_unavailable_fragments': True,
        'retry_sleep_functions': {
            'http': lambda n: 3,
            'fragment': lambda n: 3,
            'file_access': lambda n: 3,
        },
        'socket_timeout': 30,
        'extract_timeout': 180,
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

# ============ DOWNLOAD MANAGER ============
class DownloadManager:
    def __init__(self):
        self.user_sessions: Dict[int, Dict] = {}
        self.platforms = [
            "YouTube", "Instagram", "TikTok", "Twitter/X",
            "Facebook", "Reddit", "Pinterest", "LinkedIn",
            "Vimeo", "Dailymotion", "SoundCloud", "Twitch",
            "Snapchat", "Likee", "Bilibili"
        ]
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
            console.print("[yellow]You may need to add cookies.txt file[/yellow]")
    
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
        """Get appropriate format string for each platform"""
        # Base formats
        format_map = {
            "format_best": "bv*+ba/b",  # Best video + audio
            "format_audio": "ba/b",      # Best audio only
            "format_medium": "best[height<=720]",  # Max 720p
            "format_small": "best[height<=480]",   # Max 480p
        }
        
        # Platform-specific adjustments
        if platform == "YouTube" and format_choice == "format_best":
            return "bv*[height<=1080]+ba/b[height<=1080] / bv*+ba/b"  # Prefer 1080p for YouTube
        elif platform == "Facebook":
            # Facebook often needs simple 'best' format
            if format_choice == "format_best":
                return "best"
            elif format_choice == "format_medium":
                return "best[height<=720]"
            elif format_choice == "format_small":
                return "best[height<=480]"
        elif platform == "Pinterest":
            if format_choice == "format_image":
                return "best"  # For images, just get best quality
            elif format_choice == "format_best":
                return "bv*+ba/b"  # For videos
            elif format_choice == "format_audio":
                return "ba/b"
        
        return format_map.get(format_choice, "best")
    
    def get_ydl_options(self, format_choice: str, platform: str) -> Dict:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"%(title)s_{timestamp}.%(ext)s"
        output_path = os.path.join(storage_manager.download_dir, filename)
        
        ydl_opts = Config.YDL_OPTIONS.copy()
        ydl_opts['outtmpl'] = output_path
        ydl_opts['format'] = self.get_format_string(format_choice, platform)
        
        # Platform-specific extractor args
        if platform == "YouTube":
            ydl_opts['extractor_args'] = {
                'youtube': {
                    'player_client': ['android', 'web'],
                    'player_skip': ['configs', 'webpage'],
                }
            }
        elif platform == "Instagram":
            ydl_opts['extractor_args'] = {'instagram': {'post': 'single'}}
        elif platform == "TikTok":
            # Handled separately
            pass
        elif platform == "Facebook":
            # Facebook often needs cookies or specific headers
            ydl_opts['cookiefile'] = 'cookies.txt'  # Try with cookies if available
        
        # Audio extraction
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
            {'name': 'Method 1 (Default)', 'opts': {'extractor_args': {'tiktok': {'app_version': '29.7.4'}}}},
            {'name': 'Method 2 (Web client)', 'opts': {'extractor_args': {'tiktok': {'web_client': 'web'}}}},
            {'name': 'Method 3 (No watermark)', 'opts': {'extractor_args': {'tiktok': {'api_hostname': 'api19-normal-c-useast1a.tiktokv.com'}}}},
            {'name': 'Method 4 (Generic)', 'opts': {'force_generic_extractor': True}},
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
                
                console.print(f"[cyan]Trying {method['name']}[/cyan]")
                with YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    await send_downloaded_file(query, context, info, url, user_id, user_name, platform, ydl)
                return
            except Exception as e:
                console.print(f"[yellow]{method['name']} failed: {str(e)[:100]}[/yellow]")
                continue
        raise Exception("All TikTok download methods failed. The platform may be blocking automated requests.")
    
    async def handle_pinterest_download(self, query, context, url, format_choice, user_id, user_name, platform):
        """Special handler for Pinterest to handle both images and videos"""
        try:
            # First, try to extract info without downloading to check if it's image or video
            test_opts = Config.YDL_OPTIONS.copy()
            test_opts['quiet'] = True
            test_opts['extract_flat'] = True
            
            with YoutubeDL(test_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                # Check if it's an image (no formats or only single format)
                is_image = False
                if 'formats' not in info or len(info.get('formats', [])) == 0:
                    is_image = True
                elif len(info.get('formats', [])) == 1 and info['formats'][0].get('vcodec') == 'none':
                    is_image = True
                
                if is_image or format_choice == "format_image":
                    # Download as image
                    await query.edit_message_text(
                        f"⏬ <b>Downloading image from Pinterest...</b>",
                        parse_mode='HTML'
                    )
                    ydl_opts = self.get_ydl_options("format_best", platform)
                    ydl_opts['format'] = 'best'  # Force best quality image
                else:
                    # Download as video
                    await query.edit_message_text(
                        f"⏬ <b>Downloading video from Pinterest...</b>",
                        parse_mode='HTML'
                    )
                    ydl_opts = self.get_ydl_options(format_choice, platform)
                
                ydl_opts['progress_hooks'] = [self.progress_hook]
                
                with YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    await send_downloaded_file(query, context, info, url, user_id, user_name, platform, ydl)
                    
        except Exception as e:
            # If extraction fails, try direct download with generic extractor
            try:
                await query.edit_message_text(
                    f"⏬ <b>Trying alternative method for Pinterest...</b>",
                    parse_mode='HTML'
                )
                ydl_opts = self.get_ydl_options(format_choice, platform)
                ydl_opts['force_generic_extractor'] = True
                ydl_opts['progress_hooks'] = [self.progress_hook]
                
                with YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    await send_downloaded_file(query, context, info, url, user_id, user_name, platform, ydl)
            except Exception as e2:
                raise Exception(f"Pinterest download failed: {str(e2)}")
    
    def progress_hook(self, d):
        if d['status'] == 'downloading':
            percent = d.get('_percent_str', '0%').strip()
            speed = d.get('_speed_str', 'N/A').strip()
            console.print(f"[cyan]Progress: {percent} | Speed: {speed}[/cyan]", end="\r")
        elif d['status'] == 'finished':
            console.print("\n[green]✓ Download completed[/green]")
    
    def compress_video(self, input_path: str, output_path: str, target_size: int = Config.MAX_FILE_SIZE_BYTES) -> Optional[str]:
        """Compress video using ffmpeg to fit under target_size."""
        try:
            subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        except:
            console.print("[red]ffmpeg not found, cannot compress[/red]")
            return None
        
        probe = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', input_path],
            capture_output=True, text=True
        )
        try:
            duration = float(probe.stdout.strip())
        except:
            console.print("[red]Could not determine video duration[/red]")
            return None
        
        target_bitrate = (target_size * 8) / duration * 0.9
        target_bitrate = int(max(target_bitrate, 100000))
        
        console.print(f"[cyan]Compressing: target bitrate {target_bitrate/1000:.0f} kbps[/cyan]")
        
        cmd = [
            'ffmpeg', '-i', input_path,
            '-b:v', str(target_bitrate),
            '-maxrate', str(int(target_bitrate*1.2)),
            '-bufsize', str(int(target_bitrate*2)),
            '-c:v', 'libx264',
            '-preset', 'medium',
            '-crf', '23',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-y', output_path
        ]
        
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode == 0 and os.path.exists(output_path):
            compressed_size = os.path.getsize(output_path)
            console.print(f"[green]Compressed to {compressed_size/1024/1024:.1f}MB[/green]")
            return output_path
        else:
            console.print(f"[red]Compression failed: {result.stderr.decode()[:200]}[/red]")
            return None

# ============ GLOBAL INSTANCES ============
storage_manager = StorageManager()
download_manager = DownloadManager()

# ============ TELEGRAM HANDLERS ============
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
        await update.message.reply_text(
            "⚠️ <b>Platform not recognized</b>\nTrying to download anyway...",
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text(
            f"✅ <b>{platform}</b> link detected!",
            parse_mode='HTML'
        )
    
    download_manager.user_sessions[user.id] = {
        'url': url,
        'platform': platform,
        'user_name': user.username or user.first_name,
        'chat_id': update.message.chat_id,
        'message_id': update.message.message_id
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
    
    await update.message.reply_text(
        quality_text,
        reply_markup=keyboard,
        parse_mode='HTML'
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    data = query.data
    
    if data == "cancel":
        await query.edit_message_text("❌ Download cancelled.")
        if user_id in download_manager.user_sessions:
            del download_manager.user_sessions[user_id]
        return
    
    if user_id not in download_manager.user_sessions:
        await query.edit_message_text("❌ Session expired. Please send the link again.")
        return
    
    session = download_manager.user_sessions[user_id]
    url = session['url']
    platform = session['platform']
    user_name = session['user_name']
    
    await query.edit_message_text(
        f"⏬ <b>Downloading from {platform}...</b>\n⏳ Please wait...",
        parse_mode='HTML'
    )
    
    try:
        if platform == "TikTok":
            await download_manager.handle_tiktok_download(query, context, url, data, user_id, user_name, platform)
        elif platform == "YouTube":
            await handle_youtube_download(query, context, url, data, user_id, user_name, platform)
        elif platform == "Pinterest":
            await download_manager.handle_pinterest_download(query, context, url, data, user_id, user_name, platform)
        else:
            ydl_opts = download_manager.get_ydl_options(data, platform)
            ydl_opts['progress_hooks'] = [download_manager.progress_hook]
            
            console.print(f"\n{'='*50}")
            console.print(f"[cyan]Starting download...[/cyan]")
            console.print(f"[yellow]Platform: {platform}[/yellow]")
            console.print(f"[yellow]URL: {url}[/yellow]")
            console.print(f"[yellow]Format: {ydl_opts['format']}[/yellow]")
            
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                await send_downloaded_file(query, context, info, url, user_id, user_name, platform, ydl)
    except Exception as e:
        error_msg = str(e)
        console.print(f"[red]Fatal error: {error_msg}[/red]")
        await show_error_message(query, error_msg, platform, url)
    finally:
        if user_id in download_manager.user_sessions:
            del download_manager.user_sessions[user_id]

async def handle_youtube_download(query, context, url, format_choice, user_id, user_name, platform):
    methods = [
        {'name': 'Standard', 'opts': {}},
        {'name': '720p Fallback', 'opts': {'format': 'best[height<=720]'}},
        {'name': 'Audio Only', 'opts': {'format': 'ba', 'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}]}},
    ]
    
    for method in methods:
        try:
            await query.edit_message_text(
                f"⏬ <b>Downloading from YouTube...</b>\n🔄 {method['name']}",
                parse_mode='HTML'
            )
            ydl_opts = download_manager.get_ydl_options(format_choice, platform)
            ydl_opts.update(method['opts'])
            ydl_opts['progress_hooks'] = [download_manager.progress_hook]
            
            console.print(f"[cyan]Trying {method['name']}[/cyan]")
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                await send_downloaded_file(query, context, info, url, user_id, user_name, platform, ydl)
            return
        except Exception as e:
            console.print(f"[yellow]{method['name']} failed: {str(e)[:100]}[/yellow]")
            continue
    
    raise Exception("All YouTube download methods failed.")

async def send_downloaded_file(query, context, info, url, user_id, user_name, platform, ydl):
    # Get file path
    if 'requested_downloads' in info and info['requested_downloads']:
        file_path = info['requested_downloads'][0].get('filepath')
    else:
        file_path = ydl.prepare_filename(info)
    
    # Handle different extensions
    if not os.path.exists(file_path):
        base_name = os.path.splitext(file_path)[0]
        for ext in ['.mp4', '.mkv', '.webm', '.mp3', '.m4a', '.jpg', '.jpeg', '.png', '.gif']:
            test_path = base_name + ext
            if os.path.exists(test_path):
                file_path = test_path
                break
    
    if not os.path.exists(file_path):
        raise Exception("Downloaded file not found")
    
    file_size = os.path.getsize(file_path)
    title = info.get('title', 'Media')[:100]
    
    # Determine file type
    mime_type, _ = mimetypes.guess_type(file_path)
    is_image = mime_type and mime_type.startswith('image')
    is_audio = mime_type and mime_type.startswith('audio')
    is_video = mime_type and mime_type.startswith('video')
    
    # For images, we don't compress
    if is_video and file_size > Config.MAX_FILE_SIZE_BYTES:
        # Check if ffmpeg is available
        ffmpeg_available = False
        try:
            subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
            ffmpeg_available = True
        except:
            ffmpeg_available = False
        
        if not ffmpeg_available:
            await query.edit_message_text(
                f"❌ File too large ({file_size//1024//1024}MB) and ffmpeg not installed.\n"
                f"Please install ffmpeg or try a lower quality.\n\n"
                f"<b>Termux:</b> pkg install ffmpeg\n"
                f"<b>Linux:</b> sudo apt install ffmpeg",
                parse_mode='HTML'
            )
            return
        
        await query.edit_message_text(
            f"📦 File size {file_size//1024//1024}MB > {Config.MAX_FILE_SIZE_MB}MB.\n"
            f"🔄 Compressing video... This may take a moment.",
            parse_mode='HTML'
        )
        
        compressed_path = file_path + "_compressed.mp4"
        new_path = download_manager.compress_video(file_path, compressed_path)
        
        if new_path and os.path.exists(new_path):
            os.remove(file_path)
            file_path = new_path
            file_size = os.path.getsize(file_path)
        else:
            await query.edit_message_text(
                f"❌ File too large ({file_size//1024//1024}MB) and compression failed.\n"
                f"Please try a lower quality option.",
                parse_mode='HTML'
            )
            return
    
    # Log download
    download_id = storage_manager.log_download(
        user_id=user_id,
        user_name=user_name,
        platform=platform,
        url=url,
        filename=os.path.basename(file_path),
        file_path=file_path
    )
    
    await query.edit_message_text(
        f"✅ <b>Download Complete!</b>\n"
        f"📹 {title}\n"
        f"📏 Size: <code>{file_size//1024//1024}MB</code>\n"
        f"📤 <b>Sending...</b>",
        parse_mode='HTML'
    )
    
    caption = (
        f"✅ Downloaded from {platform}\n"
        f"📹 {title}\n\n"
        f"<b>Bot by:</b> {Config.BOT_USERNAME}\n"
        f"<b>Channel:</b> {Config.CHANNEL_LINK}"
    )
    
    try:
        with open(file_path, 'rb') as f:
            if is_audio or file_path.endswith(('.mp3', '.m4a', '.ogg', '.wav')):
                await context.bot.send_audio(
                    chat_id=query.message.chat_id,
                    audio=f,
                    caption=caption,
                    parse_mode='HTML'
                )
            elif is_image or file_path.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                await context.bot.send_photo(
                    chat_id=query.message.chat_id,
                    photo=f,
                    caption=caption,
                    parse_mode='HTML'
                )
            else:
                await context.bot.send_video(
                    chat_id=query.message.chat_id,
                    video=f,
                    caption=caption,
                    supports_streaming=True,
                    parse_mode='HTML'
                )
    except FileNotFoundError:
        await query.message.reply_text("❌ File not found. Please try again.")
        return
    except Exception as e:
        logger.error(f"File send error: {e}")
        await query.message.reply_text("❌ Failed to send file. Please try again later.")
        return
    
    storage_manager.mark_as_sent(download_id)
    
    try:
        os.remove(file_path)
        console.print(f"[green]✓ File sent and deleted[/green]")
    except:
        pass
    
    success_text = (
        f"🎉 <b>Successfully Sent!</b>\n\n"
        f"<b>Credits:</b>\n"
        f"Bot by {Config.BOT_USERNAME}\n"
        f"Join our channel: {Config.CHANNEL_LINK}\n\n"
        f"✨ <b>Thank you for using our service!</b>"
    )
    
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("📢 Join Channel", url=Config.CHANNEL_LINK)
    ]])
    
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=success_text,
        reply_markup=keyboard,
        parse_mode='HTML',
        disable_web_page_preview=True
    )

async def show_error_message(query, error_msg, platform, url):
    # Clean error message
    if "Sign in" in error_msg:
        error_msg = "YouTube requires authentication. Add cookies.txt or try lower quality."
    elif "Requested format is not available" in error_msg:
        error_msg = "Format not available. Try a different quality."
    elif "Unavailable" in error_msg:
        error_msg = "Video unavailable (private/deleted/region-restricted)."
    elif "Private" in error_msg:
        error_msg = "This video is private."
    elif "too large" in error_msg:
        error_msg = f"File too large for Telegram. Try lower quality."
    elif "ffmpeg" in error_msg.lower() or "compression" in error_msg.lower():
        error_msg = "ffmpeg not installed. Install it:\nTermux: pkg install ffmpeg\nLinux: sudo apt install ffmpeg"
    elif "403" in error_msg and "TikTok" in error_msg:
        error_msg = "TikTok blocking requests. Try again later or different video."
    elif "No video formats" in error_msg and "Pinterest" in error_msg:
        error_msg = "This Pinterest pin might be an image. Try 'Download as Image' option."
    
    error_text = (
        f"❌ <b>Download Failed</b>\n\n"
        f"<b>Platform:</b> {platform}\n"
        f"<b>Error:</b> <code>{error_msg[:200]}</code>\n\n"
        f"<b>Solutions:</b>\n"
        f"1. Try different quality option\n"
        f"2. Try a different video/pin\n"
        f"3. Wait a few minutes and retry\n\n"
        f"<b>Need help?</b> Contact @shihab_ff_857"
    )
    
    await query.edit_message_text(error_text, parse_mode='HTML')

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}", exc_info=True)

def main():
    banner = Panel.fit(
        f"[bold cyan]Ultimate Social Media Downloader Bot[/bold cyan]\n"
        f"[green]Author: {Config.BOT_USERNAME}[/green]\n"
        f"[yellow]Channel: {Config.CHANNEL_LINK}[/yellow]\n\n"
        f"[cyan]Features:[/cyan]\n"
        f"✅ YouTube 1080p\n"
        f"✅ TikTok 403 bypass\n"
        f"✅ Facebook fixed formats\n"
        f"✅ Pinterest images+videos\n"
        f"✅ Auto compression\n"
        f"✅ File type detection",
        title="🤖 Bot Status - READY",
        border_style="cyan"
    )
    
    console.print(banner)
    
    # Check for cookies.txt
    if os.path.exists('cookies.txt'):
        console.print("[green]✓ cookies.txt found[/green]")
    else:
        console.print("[yellow]⚠ No cookies.txt - YouTube may ask for sign-in[/yellow]")
        with open('cookies_instructions.txt', 'w') as f:
            f.write("""How to create cookies.txt for YouTube:

1. Install Chrome extension: "Get cookies.txt LOCALLY"
2. Go to YouTube.com and login
3. Click extension > Export
4. Save as "cookies.txt" in bot folder
5. Restart bot""")
        console.print("[green]✓ Created cookies_instructions.txt[/green]")
    
    # Check ffmpeg
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        console.print("[green]✓ ffmpeg found - compression enabled[/green]")
    except:
        console.print("[yellow]⚠ ffmpeg not found - install for compression[/yellow]")
        console.print("[cyan]Termux: pkg install ffmpeg[/cyan]")
        console.print("[cyan]Linux: sudo apt install ffmpeg[/cyan]")
    
    # Create application
    application = Application.builder().token(Config.TELEGRAM_TOKEN).build()
    
    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_error_handler(error_handler)
    
    console.print("[green]✓ Bot is now running! Press Ctrl+C to stop.[/green]")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Bot stopped by user.[/yellow]")
    except Exception as e:
        console.print(f"[red]Fatal error: {e}[/red]")
