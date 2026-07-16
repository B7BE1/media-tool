from flask import Flask, request, jsonify, render_template, send_from_directory
import os
import re

app = Flask(__name__)

DOWNLOAD_FOLDER = 'downloads'
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

@app.route('/')
def index():
    return render_template('index.html')

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
    from pytubefix import YouTube
    from pytubefix.cli import on_progress

    yt = YouTube(url, on_progress_callback=on_progress,
                 use_oauth=False, allow_oauth_cache=False)

    if format_type == 'mp3':
        stream = yt.streams.filter(only_audio=True).order_by('bitrate').desc().first()
    else:
        target_res = int(quality) if quality else 1080
        stream = yt.streams.filter(
            type='video', progressive=False, file_extension='mp4'
        ).order_by('resolution').desc()

        best = None
        for s in stream:
            h = int(s.resolution.replace('p', ''))
            if h <= target_res:
                best = s
                break
        if not best:
            best = stream.last()
        stream = best

    if not stream:
        raise Exception("لم يتم العثور على الجودة المطلوبة")

    safe_title = re.sub(r'[<>:"/\\|?*]', '', yt.title)[:100]
    ext = 'mp3' if format_type == 'mp3' else 'mp4'
    out_path = os.path.join(DOWNLOAD_FOLDER, f"{safe_title}.{ext}")

    stream.download(output_path=DOWNLOAD_FOLDER, filename=f"{safe_title}.{ext}")

    if format_type == 'mp3':
        import subprocess
        mp4_path = out_path.replace('.mp3', '.mp4')
        webm_path = out_path.replace('.mp3', '.webm')
        src = None
        if os.path.exists(mp4_path):
            src = mp4_path
        elif os.path.exists(webm_path):
            src = webm_path
        if src and src != out_path:
            subprocess.run([
                'ffmpeg', '-y', '-i', src, '-vn',
                '-acodec', 'libmp3lame', '-b:a', '192k', out_path
            ], capture_output=True)
            os.remove(src)

    return out_path


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


@app.route('/downloads/<filename>')
def download_file(filename):
    return send_from_directory(DOWNLOAD_FOLDER, filename, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)
