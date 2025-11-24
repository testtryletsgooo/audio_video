import os
import uuid
import threading
import time
import subprocess
import re
from flask import Flask, render_template, request, jsonify, send_from_directory
from imageio_ffmpeg import get_ffmpeg_exe

app = Flask(__name__)

# Configuration
UPLOAD_FOLDER = 'uploads'
PROCESSED_FOLDER = 'processed'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROCESSED_FOLDER, exist_ok=True)

# Global dictionary to store job progress
jobs = {}

def get_duration(ffmpeg_exe, file_path):
    """
    Get the duration of the audio file in seconds using FFmpeg.
    """
    try:
        cmd = [ffmpeg_exe, '-i', file_path]
        # FFmpeg prints file info to stderr, not stdout
        result = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        # Look for "Duration: 00:00:00.00"
        match = re.search(r"Duration:\s*(\d{2}):(\d{2}):(\d{2})\.(\d{2})", result.stderr)
        if match:
            hours, minutes, seconds, centis = map(int, match.groups())
            return hours * 3600 + minutes * 60 + seconds + (centis / 100)
    except Exception as e:
        print(f"Error getting duration: {e}")
    return 0

def parse_time_to_seconds(time_str):
    """
    Converts '00:00:00.00' string to seconds.
    """
    try:
        h, m, s = time_str.split(':')
        return int(h) * 3600 + int(m) * 60 + float(s)
    except:
        return 0

def process_audio_files(job_id, file_paths, bg_image_path=None):
    ffmpeg_exe = get_ffmpeg_exe()
    
    processed_files = []
    total_files = len(file_paths)
    
    try:
        for index, file_path in enumerate(file_paths):
            filename = os.path.basename(file_path)
            jobs[job_id]['current_file'] = f"Converting {index + 1}/{total_files}: {filename}"
            jobs[job_id]['percent'] = 0
            
            output_filename = f"{os.path.splitext(filename)[0]}.mp4"
            output_path = os.path.join(PROCESSED_FOLDER, output_filename)
            
            # Get duration for progress calculation
            duration = get_duration(ffmpeg_exe, file_path)
            
            # Construct FFmpeg Command
            cmd = [ffmpeg_exe, '-y']

            if bg_image_path:
                # Use custom image loop
                # scale=1280:720 ensures consistent output size
                # setsar=1 prevents aspect ratio distortion flags
                cmd.extend([
                    '-loop', '1',
                    '-i', bg_image_path,
                    '-i', file_path,
                    '-vf', 'scale=1280:720,setsar=1'
                ])
            else:
                # Use default dark blue color
                cmd.extend([
                    '-f', 'lavfi', 
                    '-i', 'color=c=0x141E3C:s=1280x720:r=1',
                    '-i', file_path
                ])

            # Common encoding settings
            cmd.extend([
                '-c:v', 'libx264', 
                '-tune', 'stillimage',
                '-c:a', 'aac', 
                '-b:a', '192k',
                '-pix_fmt', 'yuv420p',
                '-shortest',  # Stop when audio stops
                output_path
            ])
            
            # Run FFmpeg and read progress from stderr
            process = subprocess.Popen(
                cmd,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                encoding='utf-8'
            )

            # Monitor progress
            while True:
                line = process.stderr.readline()
                if not line:
                    break
                
                # Parse "time=00:00:05.12" from log
                time_match = re.search(r"time=(\d{2}:\d{2}:\d{2}\.\d{2})", line)
                if time_match and duration > 0:
                    current_seconds = parse_time_to_seconds(time_match.group(1))
                    percent = int((current_seconds / duration) * 100)
                    jobs[job_id]['percent'] = percent
            
            process.wait()

            if process.returncode == 0:
                processed_files.append(output_filename)
            else:
                jobs[job_id]['errors'].append(f"Failed to convert {filename}")

            # Clean up input audio file
            try:
                os.remove(file_path)
            except:
                pass
        
        # Clean up background image if it was used and no longer needed (optional)
        # Keeping it simple: we generally leave the uploaded bg until server restart or explicit cleanup

        jobs[job_id]['status'] = 'completed'
        jobs[job_id]['percent'] = 100
        jobs[job_id]['current_file'] = "All tasks finished."
        jobs[job_id]['files_done'] = processed_files

    except Exception as e:
        print(f"Job failed: {e}")
        jobs[job_id]['status'] = 'failed'
        jobs[job_id]['errors'].append(str(e))

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_files():
    uploaded_files = request.files.getlist('audioFiles')
    bg_file = request.files.get('backgroundImage')

    if not uploaded_files or uploaded_files[0].filename == '':
        return jsonify({'error': 'No audio files selected'}), 400

    job_id = str(uuid.uuid4())
    saved_paths = []

    # Save Audio Files
    for file in uploaded_files:
        path = os.path.join(UPLOAD_FOLDER, file.filename)
        file.save(path)
        saved_paths.append(path)

    # Save Background Image (if exists)
    bg_path = None
    if bg_file and bg_file.filename != '':
        bg_path = os.path.join(UPLOAD_FOLDER, f"{job_id}_{bg_file.filename}")
        bg_file.save(bg_path)

    jobs[job_id] = {
        'status': 'processing',
        'percent': 0,
        'current_file': 'Initializing...',
        'files_done': [],
        'errors': []
    }

    # Pass bg_path to the processing thread
    thread = threading.Thread(target=process_audio_files, args=(job_id, saved_paths, bg_path))
    thread.daemon = True
    thread.start()

    return jsonify({'job_id': job_id})

@app.route('/status/<job_id>')
def job_status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    return jsonify(job)

@app.route('/download/<filename>')
def download_file(filename):
    return send_from_directory(PROCESSED_FOLDER, filename, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True, threaded=True, port=5000)