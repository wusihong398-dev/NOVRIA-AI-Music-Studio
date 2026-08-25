from pathlib import Path
import re

path = Path('app/main.py')
text = path.read_text(encoding='utf-8-sig')
text = re.sub(r'VERSION = "3\.5\.[0-9]+"', 'VERSION = "3.5.10"', text, count=1)

pattern = re.compile(
    r"class ServerArtifactCacheWorker\(QThread\):.*?\n\nclass LinkDownloadWorker\(QThread\):",
    re.S,
)
replacement = r'''class ServerArtifactCacheWorker(QThread):
    """Download published AI assets concurrently and keep the UI responsive."""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, client, artifacts, destination):
        super().__init__()
        self.client = client
        self.artifacts = dict(artifacts or {})
        self.destination = Path(destination)

    def run(self):
        names = {
            "stem_vocals":"vocals.wav","stem_drums":"drums.wav","stem_bass":"bass.wav",
            "stem_guitar":"guitar.wav","stem_electric_guitar":"electric_guitar.wav",
            "stem_piano":"piano.wav","stem_other":"other.wav",
            "score_data":"score_data.json","lyrics_timeline":"lyrics_timeline.json",
            "musicxml":"lead_sheet.musicxml","electric_guitar_report":"guitar_second_stage.json",
        }
        suffixes = {
            "lead_sheet":".html","guitar_tab":".html","acoustic_guitar_tab":".html",
            "electric_guitar_tab":".html","bass_score":".html","drum_score":".html",
            "piano_score":".html","arrangement_midi":".mid",
        }
        self.destination.mkdir(parents=True, exist_ok=True)
        downloaded = {}
        downloaded_lock = threading.Lock()

        def fetch_one(item):
            key, url = item
            name = names.get(key) or f"{safe_file_stem(key)}{suffixes.get(key,'')}"
            target = self.destination / name
            # Finished files are persistent cache; never download them again.
            if target.is_file() and target.stat().st_size > 0:
                return key, str(target)
            last_error = None
            for attempt in range(3):
                try:
                    self.client.download(str(url), target)
                    if not target.is_file() or target.stat().st_size <= 0:
                        raise RuntimeError(f"{name} 下载结果为空")
                    return key, str(target)
                except Exception as exc:
                    last_error = exc
                    time.sleep(0.6 * (attempt + 1))
            raise RuntimeError(f"{name} 下载失败：{last_error}")

        try:
            # Seven WAV stems dominate transfer time. Parallel requests remove the
            # previous serial TTFB/wait chain while preserving per-file cache paths.
            max_workers = min(8, max(2, len(self.artifacts)))
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = [pool.submit(fetch_one, item) for item in self.artifacts.items()]
                for future in futures:
                    key, value = future.result()
                    with downloaded_lock:
                        downloaded[key] = value
            self.done.emit(downloaded)
        except Exception as exc:
            self.failed.emit(str(exc))


class LinkDownloadWorker(QThread):'''
text, n = pattern.subn(replacement, text, count=1)
if n != 1:
    raise SystemExit('ServerArtifactCacheWorker target missing')
if 'ThreadPoolExecutor(max_workers=max_workers)' not in text:
    raise SystemExit('parallel cache patch missing')
path.write_text(text, encoding='utf-8')
print('PATCH_WINDOWS_CACHE_V3510_OK')
