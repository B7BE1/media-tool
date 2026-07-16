from flask import Flask, request, jsonify, render_template, send_from_directory
import os
import re

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024

DOWNLOAD_FOLDER = 'downloads'
SECRET_COOKIES = '/etc/secrets/cookies.txt'
LOCAL_COOKIES = 'cookies.txt'

def get_cookies_file():
    try:
        # Copy from read-only secret mount to writable location
        writable = LOCAL_COOKIES
        if os.path.exists(SECRET_COOKIES) and os.path.getsize(SECRET_COOKIES) > 50:
            import shutil
            shutil.copy2(SECRET_COOKIES, writable)
        if os.path.exists(writable) and os.path.getsize(writable) > 50:
            return writable
    except Exception:
        pass
    return None

if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

@app.route('/')
def index():
    has_cookies = get_cookies_file() is not None
    return render_template('index.html', has_cookies=has_cookies)

@app.route('/process', methods=['POST'])
def process():
    data = request.json
    url = data.get('url')
    format_type = data.get('format')
    quality = data.get('quality')

    try:
        is_youtube = re.search(r'(youtube\.com|youtu\.be)', url)

        if is_youtube:
            filename = download_youtube(url, format_type, quality)
        else:
            filename = download_other(url, format_type, quality)

        return jsonify({
            "status": "success",
            "filename": os.path.basename(filename),
            "download_url": f"/downloads/{os.path.basename(filename)}"
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


def download_youtube(url, format_type, quality):
    # Try yt-dlp with ios client (harder for YouTube to block)
    last_error = None
    for client in ['ios', 'android', 'web_embedded']:
        try:
            return _ytdlp_youtube(url, format_type, quality, client)
        except Exception as e:
            last_error = e
            continue
    raise Exception(str(last_error))


INVIDIOUS_INSTANCES = [
    'https://inv.nadeko.net',
    'https://invidious.nerdvpn.de',
    'https://invidious.f5.si',
    'https://inv.zoomerville.com',
]


def _invidious_youtube(url, format_type, quality):
    import urllib.request as ur
    import json as j

    vid_id = None
    for p in ['v=', 'youtu.be/']:
        idx = url.find(p)
        if idx != -1:
            vid_id = url[idx + len(p):].split('&')[0].split('/')[0].split('?')[0]
            break
    if not vid_id:
        raise Exception('Could not extract video ID')

    api_url = None
    video_data = None
    for instance in INVIDIOUS_INSTANCES:
        try:
            req = ur.Request(f'{instance}/api/v1/videos/{vid_id}')
            req.add_header('User-Agent', 'Mozilla/5.0')
            resp = ur.urlopen(req, timeout=10)
            video_data = j.loads(resp.read())
            api_url = instance
            break
        except Exception:
            continue

    if not video_data:
        raise Exception('All Invidious instances unreachable')

    title = video_data.get('title', 'video')
    safe_title = re.sub(r'[<>:\"/\\\\|?*]', '', title)[:100]

    if format_type == 'mp3':
        # Get best audio
        best = None
        best_br = 0
        for a in video_data.get('adaptiveFormats', []):
            if a.get('type', '').startswith('audio') and a.get('bitrate'):
                br = int(a['bitrate'].replace('k', '000'))
                if br > best_br:
                    best_br = br
                    best = a
        if not best:
            raise Exception('No audio stream available')

        temp_path = os.path.join(DOWNLOAD_FOLDER, f'{safe_title}_temp')
        ur.urlretrieve(best['url'], temp_path)

        out_path = os.path.join(DOWNLOAD_FOLDER, f'{safe_title}.mp3')
        import subprocess
        subprocess.run([
            'ffmpeg', '-y', '-i', temp_path, '-vn',
            '-acodec', 'libmp3lame', '-b:a', '192k', out_path
        ], capture_output=True)
        os.remove(temp_path)
        return out_path

    else:
        target_h = int(quality) if quality else 720

        # Get combined video+audio stream
        best = None
        for fmt in video_data.get('formatStreams', []):
            h = int(fmt.get('resolution', '0p').replace('p', ''))
            if h <= target_h:
                best = fmt
                break
        if not best:
            best = video_data.get('formatStreams', [{}])[0] if video_data.get('formatStreams') else None

        if not best:
            raise Exception('No video stream available')

        out_path = os.path.join(DOWNLOAD_FOLDER, f'{safe_title}.mp4')
        ur.urlretrieve(best['url'], out_path)
        return out_path


def _ytdlp_youtube(url, format_type, quality, player_client='ios'):
    import yt_dlp

    ydl_opts = {
        'outtmpl': f'{DOWNLOAD_FOLDER}/%(title)s.%(ext)s',
        'merge_output_format': 'mp4',
        'quiet': True,
        'no_warnings': True,
        'extractor_args': {'youtube': {'player_client': [player_client]}},
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        },
    }

    cookie_file = get_cookies_file()
    if cookie_file:
        ydl_opts['cookiefile'] = cookie_file

    if format_type == 'mp3':
        ydl_opts['format'] = 'bestaudio/best'
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
    else:
        ydl_opts['format'] = 'best'

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        if format_type == 'mp3':
            filename = filename.rsplit('.', 1)[0] + '.mp3'

    return filename


def download_other(url, format_type, quality):
    import yt_dlp

    ydl_opts = {
        'outtmpl': f'{DOWNLOAD_FOLDER}/%(title)s.%(ext)s',
        'merge_output_format': 'mp4',
        'quiet': True,
        'no_warnings': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        },
    }

    if format_type == 'mp3':
        ydl_opts['format'] = 'bestaudio/best'
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
    else:
        ydl_opts['format'] = 'bestvideo[height=2160][ext=webm]+bestaudio/best[height=2160]/best[ext=mp4]/best'

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        if format_type == 'mp3':
            filename = filename.rsplit('.', 1)[0] + '.mp3'

    return filename


@app.route('/upload-cookies', methods=['POST'])
def upload_cookies():
    if 'cookies' not in request.files:
        return jsonify({"status": "error", "message": "No file uploaded"}), 400

    file = request.files['cookies']
    if file.filename == '':
        return jsonify({"status": "error", "message": "No file selected"}), 400

    file.save(LOCAL_COOKIES)
    return jsonify({"status": "success", "message": "Cookies uploaded"})

@app.route('/status')
def status():
    cookie_file = get_cookies_file()
    return jsonify({
        "cookies": cookie_file is not None,
        "cookies_size": os.path.getsize(cookie_file) if cookie_file else 0,
        "cookies_path": cookie_file or 'none',
    })

@app.route('/downloads/<filename>')
def download_file(filename):
    return send_from_directory(DOWNLOAD_FOLDER, filename, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)
