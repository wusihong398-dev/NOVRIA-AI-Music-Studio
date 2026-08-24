from pathlib import Path
import re

path = Path('app/main.py')
text = path.read_text(encoding='utf-8')
text = re.sub(r'VERSION = "3\.5\.[0-9]+"', 'VERSION = "3.5.3"', text, count=1)

pattern = re.compile(
    r'class ServerArtifactCacheWorker\(QThread\):.*?\n\nclass LinkDownloadWorker\(QThread\):',
    re.S,
)
replacement = r'''_SERVER_ARTIFACT_CACHE_LOCKS = {}
_SERVER_ARTIFACT_CACHE_GUARD = threading.Lock()


class ServerArtifactCacheWorker(QThread):
    """Download published AI assets without duplicate .part writers."""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, client, artifacts, destination):
        super().__init__()
        self.client = client
        self.artifacts = dict(artifacts or {})
        self.destination = Path(destination)

    def _destination_lock(self):
        key = str(self.destination.resolve()).casefold()
        with _SERVER_ARTIFACT_CACHE_GUARD:
            lock = _SERVER_ARTIFACT_CACHE_LOCKS.get(key)
            if lock is None:
                lock = threading.Lock()
                _SERVER_ARTIFACT_CACHE_LOCKS[key] = lock
            return lock

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
        downloaded = {}
        try:
            self.destination.mkdir(parents=True, exist_ok=True)
            # Opening the same song from multiple UI actions used to create two
            # workers writing drums.wav.part at once (WinError 32). Serialize all
            # downloads for one song cache directory and clean stale .part files.
            with self._destination_lock():
                for key, url in self.artifacts.items():
                    name = names.get(key) or f"{safe_file_stem(key)}{suffixes.get(key,'')}"
                    target = self.destination / name
                    if target.is_file() and target.stat().st_size > 0:
                        downloaded[key] = str(target)
                        continue
                    part = target.with_suffix(target.suffix + '.part')
                    for attempt in range(12):
                        try:
                            if part.exists():
                                part.unlink()
                            self.client.download(str(url), target)
                            break
                        except PermissionError:
                            if attempt >= 11:
                                raise
                            time.sleep(0.25 + attempt * 0.1)
                        except OSError as exc:
                            if getattr(exc, 'winerror', None) != 32 or attempt >= 11:
                                raise
                            time.sleep(0.25 + attempt * 0.1)
                    if not target.is_file() or target.stat().st_size == 0:
                        raise RuntimeError(f"缓存成果失败：{name}")
                    downloaded[key] = str(target)
            self.done.emit(downloaded)
        except Exception as exc:
            self.failed.emit(str(exc))


class LinkDownloadWorker(QThread):'''
text, count = pattern.subn(replacement, text, count=1)
if count != 1:
    raise SystemExit('ServerArtifactCacheWorker patch target not found')

path.write_text(text, encoding='utf-8')
print('PATCH_WINDOWS_CACHE_V353_OK')
