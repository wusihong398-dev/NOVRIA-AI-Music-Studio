"""Offline lyric drafting helpers used by desktop and the mobile API.

The generator deliberately produces an editable draft.  It does not copy or
search existing songs, which keeps it useful without pretending to be a lyric
database or a song-download service.
"""

from __future__ import annotations

from itertools import cycle


MANDARIN = {
    "images": ["晚风", "灯火", "远方", "旧相片", "清晨", "雨巷"],
    "verbs": ["抱紧", "记得", "走过", "听见", "留下", "等待"],
    "endings": ["我们终会到达", "答案仍在心上", "这一次不再彷徨", "明天依然有光"],
}

CANTONESE = {
    "images": ["夜风", "街灯", "远方", "旧相", "晨光", "细雨"],
    "verbs": ["抱紧", "记得", "行过", "听见", "留低", "等待"],
    "endings": ["我哋终会到达", "答案依然喺心上", "这一次唔再彷徨", "听日依然有光"],
}

ENGLISH = {
    "images": ["night wind", "city lights", "distant road", "old photograph", "morning sun", "summer rain"],
    "verbs": ["hold", "remember", "follow", "hear", "carry", "wait for"],
    "endings": ["we will find our way", "the answer lives inside", "this time we will not hide", "tomorrow brings the light"],
}


def generate_lyrics(theme: str, language: str = "普通话", style: str = "流行", mood: str = "温暖", variants: int = 1) -> list[dict]:
    theme = (theme or "追寻梦想").strip()[:80]
    cantonese = language in {"粤语", "广东话", "Cantonese"}
    english = language in {"英语", "English", "en"}
    bank = ENGLISH if english else (CANTONESE if cantonese else MANDARIN)
    results = []
    for index in range(max(1, min(int(variants), 3))):
        images = cycle(bank["images"][index:] + bank["images"][:index])
        verbs = cycle(bank["verbs"][index:] + bank["verbs"][:index])
        endings = cycle(bank["endings"][index:] + bank["endings"][:index])
        if english:
            lines = [
                "[Verse 1]",
                f"The {next(images)} brings me back to {theme}",
                f"I {next(verbs)} every moment we survived",
                f"Through the {next(images)} I can see it clearly",
                next(endings).capitalize(),
                "", "[Pre-Chorus]",
                "Even when the road is turning wild",
                "I will let the rhythm be my guide",
                "", "[Chorus]",
                f"For {theme}, I will sing it one more time",
                f"In the {next(images)}, we keep the hope alive",
                next(endings).capitalize(),
                "We will write the ending side by side",
                "", "[Bridge]",
                "No more shadows, no more asking why",
                "I can hear your echo by my side",
                "", "[Chorus]",
                f"For {theme}, I will sing it one more time",
                next(endings).capitalize(),
            ]
        else:
            lines = [
            "[Verse 1]",
            f"{next(images)}轻轻讲起{theme}" if cantonese else f"{next(images)}轻轻说起{theme}",
            f"我{next(verbs)}每一段时光",
            f"{next(images)}将沉默慢慢点亮",
            next(endings),
            "",
            "[Pre-Chorus]",
            "若果路上仍有风浪" if cantonese else "如果路上还有风浪",
            "就让心跳带我朝着方向",
            "",
            "[Chorus]",
            f"为了{theme}，我愿意再唱",
            f"{next(images)}之中仍紧握着希望",
            next(endings),
            "一起把未完的故事写上",
            "",
            "[Bridge]",
            "这一刻不用再猜想",
            "你的回声就在我身旁",
            "",
            "[Chorus]",
            f"为了{theme}，我愿意再唱",
            next(endings),
            ]
        results.append({
            "title": f"{theme} · 方案 {index + 1}",
            "language": "英语" if english else ("粤语" if cantonese else "普通话"),
            "style": style,
            "mood": mood,
            "lyrics": "\n".join(lines),
            "notice": "AI 初稿，粤语发音与押韵建议由母语使用者复核。" if cantonese else "AI 初稿，请结合旋律修订音节与押韵。",
        })
    return results


def lyrics_to_lrc(text: str, bpm: float = 72.0) -> str:
    seconds = 0.0
    step = max(2.0, 240.0 / max(40.0, min(float(bpm), 240.0)))
    rows = ["[ar:橘味儿音乐 AI 初稿]", "[by:Juweier Music v3.5.0]"]
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("["):
            continue
        minute = int(seconds // 60)
        second = seconds - minute * 60
        rows.append(f"[{minute:02d}:{second:05.2f}]{line}")
        seconds += step
    return "\n".join(rows) + "\n"
