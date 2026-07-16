from flask import Flask, request, jsonify, render_template, send_from_directory
import yt_dlp
import os

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
    format_type = data.get('format') # mp4 أو mp3
    quality = data.get('quality')

    try:
        # إعدادات yt-dlp
        # إعدادات إجبارية لتحميل MP4 فقط
        ydl_opts = {
            'outtmpl': f'{DOWNLOAD_FOLDER}/%(title)s.%(ext)s',
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'merge_output_format': 'mp4', # السطر المهم لدمج الملفات بصيغة mp4
        }
        if format_type == 'mp3':
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        else:
            # المنطق الجديد: 
            # 1. إذا كان فيه 4K (2160p) يحمل webm (أعلى جودة).
            # 2. إذا ما كان فيه، يحمل أفضل جودة متاحة بصيغة mp4.
            ydl_opts['format'] = (
                f'bestvideo[height=2160][ext=webm]+bestaudio/best[height=2160]/best[ext=mp4]/best'
            )
            ydl_opts['merge_output_format'] = 'mp4'

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            # تحديث الامتداد في حال تحويل الصوت
            if format_type == 'mp3':
                filename = filename.rsplit('.', 1)[0] + '.mp3'

            # إرجاع رابط التحميل للواجهة
            return jsonify({
                "status": "success",
                "filename": os.path.basename(filename),
                "download_url": f"/downloads/{os.path.basename(filename)}"
            })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route('/downloads/<filename>')
def download_file(filename):
    return send_from_directory(DOWNLOAD_FOLDER, filename, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)