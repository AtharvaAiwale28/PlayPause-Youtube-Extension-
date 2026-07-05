"""
Lecture + Background Song Sync
--------------------------------
Runs a tiny local web server so the YouTube IFrame API works correctly
(YouTube rejects the player when opened directly as a file:// page).

How to use:
1. Run this script:  python lecture_song_sync.py
2. Your browser will open automatically to the app.
3. Paste your lecture's YouTube link and click Load.
4. Paste a song's YouTube link and click Load.
5. Pause the lecture -> the song plays in the background.
   Resume the lecture -> the song pauses.
"""

import http.server
import socketserver
import webbrowser
import threading

PORT = 8000

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Lecture + Background Song</title>
<style>
  :root {
    --bg: #14171c;
    --panel: #1c2028;
    --panel-border: #2a2f3a;
    --text: #e8e9ec;
    --muted: #8a90a0;
    --accent: #5b8def;
    --good: #4ec98b;
  }

  * { box-sizing: border-box; }

  body {
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    min-height: 100vh;
  }

  header {
    padding: 18px 28px;
    border-bottom: 1px solid var(--panel-border);
  }

  header h1 {
    font-size: 18px;
    font-weight: 600;
    margin: 0;
  }

  header p {
    margin: 2px 0 0;
    font-size: 13px;
    color: var(--muted);
  }

  main {
    max-width: 1000px;
    margin: 0 auto;
    padding: 22px;
  }

  .load-row {
    display: flex;
    gap: 8px;
    margin-bottom: 14px;
  }

  .load-row input {
    flex: 1;
    background: #10131a;
    border: 1px solid var(--panel-border);
    color: var(--text);
    padding: 10px 12px;
    border-radius: 8px;
    font-size: 14px;
  }
  .load-row input:focus { outline: 1px solid var(--muted); }

  .load-row button {
    background: #2a2f3a;
    color: var(--text);
    border: 1px solid var(--panel-border);
    padding: 10px 16px;
    border-radius: 8px;
    cursor: pointer;
    font-size: 14px;
  }
  .load-row button:hover { background: #333949; }

  .video-frame-wrap {
    position: relative;
    width: 100%;
    aspect-ratio: 16 / 9;
    background: #000;
    border-radius: 10px;
    overflow: hidden;
    margin-bottom: 8px;
  }

  .video-frame-wrap iframe {
    width: 100%;
    height: 100%;
    border: 0;
  }

  .empty-state {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--muted);
    font-size: 14px;
    text-align: center;
    padding: 20px;
  }

  .status {
    font-size: 12px;
    color: var(--muted);
    min-height: 16px;
    margin-bottom: 24px;
  }
  .status.playing { color: var(--good); }

  .song-bar {
    border-top: 1px solid var(--panel-border);
    padding-top: 18px;
  }

  .song-bar label {
    display: block;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted);
    margin-bottom: 8px;
  }

  .song-status {
    font-size: 12px;
    color: var(--muted);
  }
  .song-status.playing { color: var(--good); }

  /* Song player is never shown visually — audio only, in the background */
  #songHost {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    opacity: 0;
    pointer-events: none;
  }

  footer {
    max-width: 1000px;
    margin: 0 auto;
    padding: 4px 22px 28px;
    font-size: 12px;
    color: var(--muted);
    line-height: 1.6;
  }
</style>
</head>
<body>

<header>
  <h1>Lecture + Background Song</h1>
  <p>Pause the lecture and the song fades in. Resume the lecture and the song pauses.</p>
</header>

<main>
  <div class="load-row">
    <input id="inputLecture" type="text" placeholder="Paste the lecture's YouTube link">
    <button id="loadLecture">Load</button>
  </div>
  <div class="video-frame-wrap" id="frameWrapLecture">
    <div class="empty-state">Paste your lecture video link above and click Load.</div>
  </div>
  <div class="status" id="statusLecture"></div>

  <div class="song-bar">
    <label>Background song</label>
    <div class="load-row">
      <input id="inputSong" type="text" placeholder="Paste the song's YouTube link">
      <button id="loadSong">Load</button>
    </div>
    <div class="song-status" id="statusSong">No song loaded yet.</div>
  </div>
</main>

<div id="songHost"></div>

<footer>
  Running this from a double-clicked file (file://) will trigger a YouTube "player configuration error."
  Serve it from a local server instead — open a terminal in this file's folder and run
  <code>python -m http.server 8000</code>, then visit <code>http://localhost:8000/study-sync-player.html</code> in your browser.
</footer>

<script>
  // ---------- Helpers ----------
  function extractVideoId(url) {
    if (!url) return null;
    url = url.trim();
    if (/^[a-zA-Z0-9_-]{11}$/.test(url)) return url;
    const patterns = [
      /(?:youtube\.com\/watch\?v=)([a-zA-Z0-9_-]{11})/,
      /(?:youtu\.be\/)([a-zA-Z0-9_-]{11})/,
      /(?:youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})/,
      /(?:youtube\.com\/shorts\/)([a-zA-Z0-9_-]{11})/
    ];
    for (const p of patterns) {
      const m = url.match(p);
      if (m) return m[1];
    }
    return null;
  }

  // ---------- YouTube IFrame API bootstrap ----------
  let ytApiReady = false;
  let pendingLoads = [];

  const tag = document.createElement('script');
  tag.src = "https://www.youtube.com/iframe_api";
  document.head.appendChild(tag);

  window.onYouTubeIframeAPIReady = function () {
    ytApiReady = true;
    pendingLoads.forEach(fn => fn());
    pendingLoads = [];
  };

  let playerLecture = null;
  let playerSong = null;

  function createPlayer(elementId, videoId, onReady, onStateChange) {
    return new YT.Player(elementId, {
      videoId: videoId,
      width: '100%',
      height: '100%',
      playerVars: { autoplay: 1, rel: 0, origin: window.location.origin },
      events: {
        onReady: onReady,
        onStateChange: onStateChange
      }
    });
  }

  function setStatus(id, text, playing) {
    const el = document.getElementById(id);
    el.textContent = text;
    el.classList.toggle('playing', !!playing);
  }

  // ---------- Sync logic ----------
  function handleLectureStateChange(event) {
    if (event.data === YT.PlayerState.PAUSED) {
      setStatus('statusLecture', 'Lecture paused', false);
      if (playerSong && typeof playerSong.getPlayerState === 'function') {
        if (playerSong.getPlayerState() !== YT.PlayerState.PLAYING) {
          playerSong.playVideo();
        }
      }
    } else if (event.data === YT.PlayerState.PLAYING) {
      setStatus('statusLecture', 'Lecture playing', true);
      if (playerSong && typeof playerSong.getPlayerState === 'function') {
        if (playerSong.getPlayerState() === YT.PlayerState.PLAYING) {
          playerSong.pauseVideo();
        }
      }
    }
  }

  function handleSongStateChange(event) {
    if (event.data === YT.PlayerState.PLAYING) {
      setStatus('statusSong', 'Playing in background', true);
    } else if (event.data === YT.PlayerState.PAUSED) {
      setStatus('statusSong', 'Paused', false);
    }
  }

  function loadLectureVideo(videoId) {
    document.getElementById('frameWrapLecture').innerHTML = '<div id="ytLecture"></div>';
    const build = () => {
      playerLecture = createPlayer('ytLecture', videoId,
        () => setStatus('statusLecture', 'Ready', false),
        handleLectureStateChange);
    };
    ytApiReady ? build() : pendingLoads.push(build);
  }

  function loadSongVideo(videoId) {
    document.getElementById('songHost').innerHTML = '<div id="ytSong"></div>';
    const build = () => {
      playerSong = createPlayer('ytSong', videoId,
        () => setStatus('statusSong', 'Loaded — will play when you pause the lecture', false),
        handleSongStateChange);
    };
    ytApiReady ? build() : pendingLoads.push(build);
  }

  // ---------- Wire up UI ----------
  document.getElementById('loadLecture').addEventListener('click', () => {
    const id = extractVideoId(document.getElementById('inputLecture').value);
    if (!id) { alert("That link doesn't look like a valid YouTube video URL."); return; }
    loadLectureVideo(id);
  });

  document.getElementById('loadSong').addEventListener('click', () => {
    const id = extractVideoId(document.getElementById('inputSong').value);
    if (!id) { alert("That link doesn't look like a valid YouTube video URL."); return; }
    loadSongVideo(id);
  });
</script>

</body>
</html>
"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(HTML_PAGE.encode("utf-8"))

    def log_message(self, format, *args):
        # Keep the console quiet
        pass


def start_server():
    with socketserver.TCPServer(("localhost", PORT), Handler) as httpd:
        print(f"Serving at http://localhost:{PORT}  (press Ctrl+C to stop)")
        httpd.serve_forever()


if __name__ == "__main__":
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    webbrowser.open(f"http://localhost:{PORT}")

    try:
        server_thread.join()
    except KeyboardInterrupt:
        print("\nStopped.")
